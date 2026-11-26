"""Extraction par règles (regex) des caractéristiques d'une aptitude.

Volontairement déterministe et sans contexte d'unité : on lit le timing
(`condition`), le coût (sort/prière/ordre), le jet de déclenchement, les
prérequis, la cible et les effets chiffrés. Tout ce qui n'est pas reconnu reste
absent (jamais deviné) ; `pipeline.py` signale une aptitude sans effet reconnu
comme « à revoir » plutôt que de lui inventer une note.

Probabilités de déclenchement (hors contexte, sans relance ni bonus) :

* sort de valeur N : P(2D6 ≥ N), dissipation adverse ignorée ;
* prière de valeur N : P(D6 ≥ N), points rituels ignorés (sous-estime un peu) ;
* « Roll a dice. On a N+ » : (7 − N)/6 ; « Roll 2D6. On a N+ » : P(2D6 ≥ N) ;
* ordre, Blood Tithe, Fate : automatique (coût noté à part).

Découpé par famille de règles : `dice`, `timing`, `conditions`, `scope`,
`activation`, `stat_mods`, `qualitative`, `rolls`, `effects`, `targets` ;
ce module garde `extract()` et réexporte l'API publique.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

from ..models import BEARER_TARGET, Extraction, RawAbility
from ..perimeter import (
    AFTER_FRIENDLY_LOSS,
    ON_OWN_ATTACKS,
    RETALIATION,
    SHOT_BY_BEARER,
    charge_subjects,
    once_trigger_clause,
)
from ..resources import resource_usage
from .activation import OPPOSED_TEST_PROB, OPPOSED_TEST_PROBS, activation_of, p_prayer_banked  # noqa: F401
from .conditions import CHARGE_ENEMY, CHARGE_OURS, CONDITION_RULES, conditions_of, split_main_secondary  # noqa: F401
from .dice import dice_mean, p_2d6, p_d6  # noqa: F401
from .effects import effects_of
from .qualitative import QUALITATIVE_RULES  # noqa: F401
from .references import engine_factors, reference_effects
from .rolls import dice_count_of, rerolls_of  # noqa: F401
from .scope import scope_of
from .targets import (
    effect_friendly_target,  # noqa: F401
    excludes_self_of,
    friendly_target_of,
    unlock_prereqs_of,
)
from .timing import frequency_of, turn_of

#: v34 : « Once Per Battle » + « If …, … for the rest of the battle » : les conditions du « If » sont un
#: déclencheur à réussir une seule fois sur la partie (`perimeter.once_trigger_clause`).
ONCE_TRIGGER_PENALTY_FACTOR = 0.5
ONCE_TRIGGER_LABEL = "déclencheur unique (pénalités ÷ 2)"


#: Les dégâts directs gardent leur lecture (realized.direct_damage exclut tout prérequis inconnu).
_NO_SHOT_LABEL = {"mortal_damage", "slay"}
_SHOT_TEXT = re.compile(
    r"\bthis unit's shooting attacks?\b|\bshooting attacks? made by this unit\b|"
    r"\bSHOOT ability (?:for|used by) this unit\b|\bthis unit (?:used|uses) a SHOOT ability\b",
    re.I,
)
_SHOT_WEAPON = re.compile(r"\b(?:attacks made with|targeted by(?: all of)?) this unit's\b", re.I)
_ENEMY_AURA = re.compile(
    r"\benemy\b[^.:]{0,60}?\bwithin (\d+)\"\s*of this (?:unit|model)\b|"
    r"\bdeclared an? [^.:]{0,40}?\bfor (?:a|an|any)(?: visible)?(?: enemy)?(?: [A-Z]+)? (?:unit|units|HERO|MONSTER)\s+"
    r"within (\d+)\"\s*of this unit\b|"
    # cible amie OU ennemie (« Pick a visible unit within 12" of the caster », Aethershock)
    r"\b[Pp]ick (?:a|any|up to \d+)(?: visible)? units? within (\d+)\"\s*of (?:this unit|the caster|the chanter)\b",
)


_RETALIATION_TEXT = re.compile(
    r"\bcombat attacks? that targets? this unit\b|\bmodel in this unit is slain by a combat attack\b|"
    r"\binflicted by a combat attack is allocated to this unit\b|\bward roll for this unit for a damage point "
    r"inflicted by a combat attack\b",
    re.I,
)
_OWN_ATTACKS_TEXT = re.compile(
    r"\beach time (?:an attack made (?:by|with) this unit\b|this unit attacks with its\b)[^.]*?"
    r"\bscores? a (?:hit|critical hit|wound)",
    re.I,
)
#: v36 : soin déclenché par le combat du porteur (« slain by this unit's combat attacks », « Each time this unit uses a
#: FIGHT ability ») : il faut se battre — condition « au combat » (D = P(au combat) en couche 3).
_HEAL_BY_FIGHT = re.compile(
    r"\bby this unit's combat attacks\b|\b[Ee]ach time this unit uses a FIGHT ability\b|"
    r"\bthis unit (?:used|uses) a FIGHT ability\b"
)
#: v36 : … et après la destruction d'un type d'unité ennemie précis (« that enemy HERO was destroyed ») : condition
#: tenue par l'adversaire, listée en « bon cas » (réponse utilisateur) via `target_condition`.
_HEAL_AFTER_KILL_OF = re.compile(
    r"\benemy (?:non-)?((?:HERO|WIZARD|PRIEST|MONSTER)(?: or (?:HERO|WIZARD|PRIEST|MONSTER))?)\b[^.:]*?"
    r"\b(?:destroyed|slain)\b"
)
_HEAL_KINDS = ("heal", "return_models")
#: Condition en tête de l'effet, qui vaut pour toute la suite (« If this unit charged this turn, roll a dice.
#: On a 3+, this unit can move 2D6"… Inflict D3 mortal damage », Destructive Bulk).
_HEAD_CHARGED = re.compile(r"^\s*If this unit (?:has )?charged this (?:turn|phase)\b", re.I)
_HEAD_IN_COMBAT = re.compile(r"^\s*If this unit is in combat\b", re.I)
_IN_COMBAT_OR_CHARGED = re.compile(r"\bIf this unit is in combat or (?:has )?charged this (?:turn|phase)\b", re.I)


#: v42 : receveurs écrits dans l'en-tête d'une liste d'effets centrée sur la cible (Waaagh!).
_HEADER_RECEIVERS = re.compile(
    r"\bthe following effects apply to (?:all )?friendly ((?:non-)?[A-Z][A-Z'’ -]*?[A-Z])(?: units?)? "
    r"(?:while|that|wholly|within)\b"
)
#: v42 : l'effet suit la destruction d'une unité amie au tour précédent.
_AFTER_LOSS = re.compile(r"\b(?:was|were|has been|have been) destroyed (?:in|during) the previous turn\b")


def _add_requires(e, labels: list[str]):
    new = [lab for lab in labels if lab not in (e.requires or "").split(" | ")]
    return dataclasses.replace(e, requires=" | ".join(filter(None, [e.requires, *new]))) if new else e


def _heal_kill_condition(e, effect: str):
    """v36 : « élimine un HERO » sur un soin qui suit la destruction d'une unité ennemie d'un type précis, lu dans
    la phrase (ou l'option « - … ») qui porte ce soin."""
    for line in re.split(r"\n", effect):
        if not re.search(r"\b[Hh]eal\b|\b[Rr]eturn\b", line):
            continue
        m = _HEAL_AFTER_KILL_OF.search(line)
        if m and not m.group(0).startswith("enemy non-"):
            label = f"élimine un {m.group(1).replace(' or ', '/')}"
            if label not in (e.target_condition or ""):
                return dataclasses.replace(e, target_condition=" | ".join(filter(None, [e.target_condition, label])))
            return e
    return e


def declare_requires(declare: str, who: set[str]) -> list[str]:
    """Prérequis de charge écrits dans l'Annonce, qui valent pour la cible ennemie choisie (v35)."""
    out = (["a chargé"] if "nous" in who else []) + (["charge ennemie"] if "ennemi" in who else [])
    if re.search(r"\b(?:has|have|had|did) not charged?\b", declare, re.I):
        out.append("sans charge")
    return out


def shot_by_bearer(condition: str, text: str) -> bool:
    """Effet déclenché par les tirs du porteur (v35) : formule « this unit's shooting attacks », ou phase de
    tir et « attacks made with / targeted by this unit's <arme> » (Star-venom, Starstone Bolas)."""
    # v36 : aussi dans le déclencheur d'une réaction (« Reaction: You declared a SHOOT ability for this unit »)
    return bool(
        _SHOT_TEXT.search(f"{condition} {text}")
        or ("shooting phase" in condition.lower() and _SHOT_WEAPON.search(text))
    )


def enemy_aura_range(text: str) -> Optional[int]:
    """Rayon d'une aura ennemie écrite autour du porteur (« enemy units within 9" of this unit »), sinon None."""
    m = _ENEMY_AURA.search(text)
    return int(next(g for g in m.groups() if g)) if m else None


def extract(raw: RawAbility) -> tuple[Extraction, float]:
    """Extraction complète + pénalité de mise en place cumulée (utilisée par scoring)."""
    if not raw.effect.strip() and raw.declare.strip():
        # v30 : tout le texte rangé sous « Declare » (OVERDRIVE SWITCH) : c'est l'effet
        raw = dataclasses.replace(raw, declare="", effect=raw.declare)
    main, secondary = split_main_secondary(raw.effect)
    scope, rng, wholly = scope_of(raw.declare, raw.effect)
    enemy_target = scope in ("one_enemy", "enemy_aura", "all_enemies")
    conditions, penalty = conditions_of(f"{raw.condition} {raw.declare} {main}", enemy_target)
    if penalty and once_trigger_clause(main, raw.condition):
        # v34 : conditions à réussir UNE fois pour un effet qui dure toute la bataille (Oath of Supremacy) :
        # une seule réussite sur la partie suffit → pénalités de mise en place divisées par 2
        penalty *= ONCE_TRIGGER_PENALTY_FACTOR
        conditions = conditions + [ONCE_TRIGGER_LABEL]
    if secondary:
        # prérequis propres à un effet secondaire : notés, sans pénalité de mise en place
        conditions += [
            f"{c} (effet secondaire seulement)"
            for c in conditions_of(secondary, enemy_target)[0]
            if c not in conditions
        ]
    p, notes, variance = activation_of(raw, raw.effect)
    effects, target_kw, scales = effects_of(
        raw.declare, raw.effect, scope, passive=raw.condition.lower().startswith("passive"), condition=raw.condition
    )
    # condition de charge portée par l'Annonce (« Pick up to 3 friendly Verminus units that charged this
    # turn ») : elle vaut pour tous les effets amis, pas seulement pour la phrase qui les porte (v23)
    who = charge_subjects(raw.declare, enemy_target)
    if "nous" in who:
        effects = [
            e
            if e.side != "friendly" or "a chargé" in (e.requires or "")
            else dataclasses.replace(e, requires=" | ".join(filter(None, ["a chargé", e.requires])))
            for e in effects
        ]
    # v35 : idem pour les effets ENNEMIS (« If this unit charged this turn, pick an enemy unit in combat with
    # it… », Chilling Onslaught ; « Pick an enemy unit that charged this turn… », Dance of Death ; « If this
    # unit did not charge this turn, pick… », Deafening Drone) — la condition de l'Annonce vaut pour la cible
    effects = [
        e if e.side != "enemy" else _add_requires(e, declare_requires(raw.declare, who)) for e in effects
    ]
    # v35 : débuff déclenché par les tirs du porteur (Hurricane Winds, Deathly Barrage…) : la couche 3 lit
    # l'exposition sur la portée de ses armes de tir, pas « au contact » faute de portée écrite
    if shot_by_bearer(raw.condition, f"{raw.declare} {raw.effect}"):
        effects = [
            _add_requires(e, [SHOT_BY_BEARER]) if e.side == "enemy" and e.kind not in _NO_SHOT_LABEL else e
            for e in effects
        ]
    # v35 : riposte (BM à l'attaquant quand le porteur est frappé au combat) / BM sur ses propres attaques
    mortal_label = (
        RETALIATION
        if _RETALIATION_TEXT.search(raw.effect)
        else ON_OWN_ATTACKS
        if _OWN_ATTACKS_TEXT.search(raw.effect)
        else ""
    )
    if mortal_label:
        effects = [
            _add_requires(e, [mortal_label]) if e.kind == "mortal_damage" and e.side == "enemy" else e for e in effects
        ]
    if _HEAL_BY_FIGHT.search(raw.effect):
        effects = [_add_requires(e, ["au combat"]) if e.kind in _HEAL_KINDS else e for e in effects]
    effects = [_heal_kill_condition(e, raw.effect) if e.kind in _HEAL_KINDS else e for e in effects]
    # v35 : condition en tête de l'effet (« If this unit charged this turn, … ») : elle vaut pour tous ses effets
    head = (
        ["a chargé"]
        if _HEAD_CHARGED.search(raw.effect)
        else ["au combat"]
        # v36 : aussi en tête de l'Annonce (« If this unit is in combat, pick a visible enemy HERO… », Terminate
        # Their Command, Storm of Steel)
        if _HEAD_IN_COMBAT.search(raw.effect) or _HEAD_IN_COMBAT.search(raw.declare)
        else []
    )
    if _IN_COMBAT_OR_CHARGED.search(f"{raw.declare} {raw.effect}"):
        # v36 : « If this unit is in combat or charged this turn » (Windrider, Smoke Bombs) : deux alternatives,
        # et qui a chargé est au combat → « au combat » seul, pas « a chargé » ET « au combat »
        effects = [
            dataclasses.replace(
                e, requires=" | ".join(r for r in (e.requires or "").split(" | ") if r and r != "a chargé")
            )
            for e in effects
        ]
        head = ["au combat"]
    if head:
        # (un déclencheur unique v34 — Oath of the Marauder — porte déjà sa charge : ne pas la recompter)
        effects = [e if "déclencheur unique" in (e.requires or "") else _add_requires(e, head) for e in effects]
    if scope in ("self", "unknown") and rng is None:
        # v35 : aura ennemie sans portée lue (« Subtract 1 from charge rolls for enemy units within 9" of this
        # unit », réaction « for a unit within 12" of this unit ») : la portée sert l'exposition (couche 3)
        rng = enemy_aura_range(f"{raw.condition} {raw.declare} {raw.effect}")
    # cible amie par effet (v26) : une ligne d'option l'emporte ; ailleurs, seulement si l'aptitude n'en a pas
    ability_ft = friendly_target_of(raw.declare, raw.effect)
    effects = [
        dataclasses.replace(
            e,
            friendly_target=(
                e.friendly_target[7:]
                if e.friendly_target.startswith("option:")
                else e.friendly_target
                if e.friendly_target == BEARER_TARGET
                else ("" if ability_ft else e.friendly_target)
            ),
        )
        for e in effects
    ]
    effects = [e if e.friendly_target != ability_ft else dataclasses.replace(e, friendly_target="") for e in effects]
    # v42 : « Pick a friendly IRONJAWZ HERO to be the target … the following effects apply to friendly IRONJAWZ units
    # while they are wholly within 18" of the target: - … » : la cible est le centre de la bulle, les receveurs sont
    # ceux de l'en-tête (Waaagh! Ironjawz et Grunta : le moteur ne buffait que les héros, Darkjawz 2026-11-25)
    hdr = _HEADER_RECEIVERS.search(raw.effect)
    if hdr and ability_ft and hdr.group(1) != ability_ft:
        effects = [
            dataclasses.replace(e, friendly_target=hdr.group(1)) if e.side != "enemy" and not e.friendly_target else e
            for e in effects
        ]
    # v42 : « For each friendly SYLVANETH unit … that was destroyed in the previous turn, you can pick … » : l'effet
    # suit une perte amie, il n'est pas permanent (Memories of the Fallen, Zoko 2026-11-25)
    if _AFTER_LOSS.search(raw.declare):
        effects = [_add_requires(e, [AFTER_FRIENDLY_LOSS]) if e.side != "enemy" else e for e in effects]
    # v33 : effet réservé au porteur → nom(s) de sa charte, que la couche 3 résout comme un nom de charte ;
    # porté par une règle de faction (pas de nom de charte), on retombe sur la cible de l'aptitude
    bearer_names = " or ".join(dict.fromkeys(o.owner_name for o in raw.owners if o.owner_kind == "warscroll"))
    effects = [
        e if e.friendly_target != BEARER_TARGET else dataclasses.replace(e, friendly_target=bearer_names or "")
        for e in effects
    ]
    # v33 : cible ennemie à survoler (« an enemy unit that this unit passed across this phase », Bomb Racks)
    if re.search(r"\bpassed across\b", raw.declare):
        effects = [
            e
            if e.side != "enemy" or "a survolé la cible" in (e.requires or "")
            else dataclasses.replace(e, requires=" | ".join(filter(None, [e.requires, "a survolé la cible"])))
            for e in effects
        ]
    # v34 (B) : mécanique de faction dont la valeur est dans d'autres aptitudes (méta, statut, décor…),
    # résolue en seconde passe par `abilities.references` ; seulement si rien d'autre n'a été reconnu
    if all(e.kind == "warscroll_rule" for e in effects):
        effects = reference_effects(raw) or effects
    factor, factor_note, act, act_note = engine_factors(raw)
    usage, usage_note = resource_usage(raw)
    if usage is not None and usage < 1:
        factor *= usage
        factor_note = "; ".join(filter(None, [factor_note, usage_note]))
    if act != 1.0:
        p *= act
        notes = notes + [act_note]
    ex = Extraction(
        power_factor=factor,
        power_factor_note=factor_note,
        resource_usage=usage,
        frequency=frequency_of(raw.condition),
        turn=turn_of(raw.condition, raw.phase),
        scope=scope,
        range_inches=rng,
        wholly_within=wholly,
        activation_prob=round(p, 4),
        activation_notes=notes,
        conditions=conditions,
        effects=effects,
        variance=variance,  # type: ignore[arg-type]
        target_keywords=target_kw,
        scales_with_size=scales,
        unlock_prereqs=unlock_prereqs_of(raw.effect),
        # marquage : unités amies qui profitent de la cible désignée (« Hobgrot Slittaz », « NIGHTHAUNT »)
        excludes_self=scope in ("one_friendly", "friendly_aura", "army") and excludes_self_of(raw.declare, raw.effect),
        friendly_target=friendly_target_of(raw.declare, raw.effect)
        if scope in ("one_friendly", "friendly_aura", "army") or any(e.detail == "marquage" for e in effects)
        else "",
    )
    return ex, penalty

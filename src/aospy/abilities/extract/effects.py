"""Assemblage des effets d'une aptitude (`effects_of`) : annotation, sujet de chaque phrase."""

from __future__ import annotations

import dataclasses
import re

from ..models import BEARER_TARGET, Effect, Scope
from ..perimeter import perimeter_of, sentence_at
from .activation import _BINOMIAL, _GATE_D6
from .dice import dice_mean
from .qualitative import _HEAL_RE, _MORTAL_PER_ROLL, _MORTAL_RE, _MOVE_RE, _RETURN_RE, _WARD_RE, QUALITATIVE_RULES
from .rolls import _MAKE_MOVE_RE, dice_count_of, rerolls_of
from .stat_mods import _LOCAL_ENEMY, _LOCAL_FRIENDLY, _stat_mods
from .targets import effect_friendly_target, option_of

_OFFENSIVE_STATS = ("hit", "wound", "attacks", "rend", "damage")
#: effets qualitatifs qui portent sur des attaques (périmètre d'armes pertinent)
_WEAPON_KINDS = {"crit", "anti", "charge_bonus", "reroll", "no_crit", "no_weapon_abilities", "stat_set"}


def _annotate(
    e: Effect, sentence: str, text: str, passive: bool, enemy_target: bool = False, condition: str = ""
) -> Effect:
    """Ajoute le périmètre (armes, cible, prérequis, durée) lu dans la phrase source."""
    offensive = (e.kind == "stat_mod" and e.stat in _OFFENSIVE_STATS) or (
        e.kind in _WEAPON_KINDS and not (e.kind == "reroll" and e.stat not in ("hit", "wound", ""))
    )
    ft = effect_friendly_target(sentence, text) if e.side == "friendly" else ""
    return dataclasses.replace(
        e,
        friendly_target=e.friendly_target or ft,
        option_group=option_of(sentence, text),
        **perimeter_of(sentence, text, passive, offensive, e.kind, enemy_target, condition),
    )


#: « Roll 8 dice » / « Roll either 5 dice or … » : nombre de dés fixe d'un effet « for each N+ » (v33).
_FIXED_DICE = re.compile(r"\b[Rr]oll (?:either )?(\d+) dice\b(?! for each)")
#: Nombre de dés qui dépend du contexte (figurines de la cible, PV, ressource…).
_VARIABLE_DICE = re.compile(
    r"\b[Rr]oll (?:a number of dice|a dice for each|\d+ dice for each|a D6 for each)|\bmake a number of\b|"
    r"\broll of D6 for each\b",
    re.I,
)


def per_roll_mortals(effect: str, m: re.Match) -> tuple[float, str]:
    """(espérance, détail) d'un « For each N+, inflict K mortal damage » (analyseur v33).

    Nombre de dés fixe → espérance N × P(N+) × K ; nombre de dés selon le contexte → P(N+) × K par dé,
    détail « par dé » (la couche 3 relit le texte contre une cible type, `analysis/layers/mortals.py`)."""
    k = int(m.group(1))
    t = re.search(r"(\d)\+", m.group(0))
    p = (7 - int(t.group(1))) / 6 if t else 0.5
    before = effect[max(0, m.start() - 220) : m.start()]
    either = re.search(r"\b[Rr]oll either (\d+) dice\b", before)
    fixed = list(_FIXED_DICE.finditer(before))
    variable = list(_VARIABLE_DICE.finditer(before))
    if either:
        return round(int(either.group(1)) * p * k, 3), ""
    if fixed and (not variable or fixed[-1].start() > variable[-1].start()):
        return round(int(fixed[-1].group(1)) * p * k, 3), ""
    return round(p * k, 3), "par dé"


def equal_to_roll_mortals(effect: str, pos: int) -> tuple[float | None, str]:
    """(espérance, dé) d'un « inflict an amount of mortal damage equal to the roll » (analyseur v33).

    Le dé lancé (D3 ou D6) et son seuil (« On a 2+ ») sont lus juste avant. Un seuil de D6 déjà compté
    comme jet de déclenchement (`activation_of`) donne la moyenne sachant le seuil passé ; sinon
    l'espérance inclut le seuil (D3 sur 2+ : (2 + 3) / 3)."""
    if not re.match(r"[^.]{0,60}?\bequal to the (?:D3 |D6 |dice )?roll\b", effect[pos : pos + 90]):
        return None, ""
    before = effect[max(0, pos - 220) : pos]
    rolls = list(re.finditer(r"\b[Rr]oll (?:a |an )?(D3|D6|dice)\b", before))
    if not rolls:
        return None, ""
    r = rolls[-1]
    faces = 3 if r.group(1) == "D3" else 6
    gate = re.search(r"\b[Oo]n an? (\d)\+", before[r.end() :])
    n = int(gate.group(1)) if gate else 1
    outcomes = list(range(n, faces + 1))
    gated = faces == 6 and gate is not None and bool(_GATE_D6.search(effect)) and not _BINOMIAL.search(effect)
    die = f"D{faces}" + (f" sur {n}+" if n > 1 else "")
    return round(sum(outcomes) / (len(outcomes) if gated else faces), 3), die


#: Sujet de la proposition qui subit une restriction (v29) : « Enemy MONSTERS cannot… » = ennemi, « They cannot use
#: MOVE abilities » après une téléportation = contrepartie amie, « the target » suit la cible déclarée.
_SUBJ_ENEMY = re.compile(r"\b[Ee]nemy\b")
_SUBJ_TARGET = re.compile(r"\b(?:[Tt]he|[Tt]hat|[Ee]ach) target\b")
_SUBJ_SELF = re.compile(
    r"\b(?:[Tt]his (?:unit|model|terrain feature|MANIFESTATION)|[Yy]our general|"
    r"[Ff]riendly|[Tt]he Shrine Guardian|[Uu]nits in this Regiment)\b"
)
_SUBJ_PRONOUN = re.compile(r"\b(?:[Ii]t|[Tt]hey|[Tt]hat unit)\b")
#: v36 : cible ami OU ennemi au choix, re-désignée ennemie dans le paragraphe (« If the target is an enemy unit,
#: inflict X mortal damage on it », Gifts of Pain and Pleasure, Invocation of Nagash ; « If you picked an enemy
#: unit to be the target, … inflict D3 mortal damage on the target », Jolly Gutpipes) : dégâts à l'ennemi.
_ENEMY_REDESIGNATED = re.compile(r"\bIf (?:the target is an enemy\b|you picked an enemy\b)", re.I)
#: v36 : « cannot move or be removed from the battlefield by an ability that would allow it to be set up
#: again » (The Mirror's Depths, Awakening Slumbering Spirits), « Each time the target is removed from the
#: battlefield and set up again » (Jolly Gutpipes, déclencheur) : ni téléportation ni réserve.
_NOT_A_SETUP = re.compile(r"\bcannot\b[^.]*$|\b[Ee]ach time\b[^.]*\bis removed from the battlefield\b[^.]*$")
#: v36 : « Your opponent must remove the target from the battlefield and set it up again in combat with this
#: unit » (Shadow Lariat, DR AG 'EM OUT) : c'est l'ennemi qu'on déplace (débuff), pas une mobilité à nous.
_ENEMY_MOVED = re.compile(r"\b[Yy]our opponent must remove (?:the target|that unit|it)\b[^.]*$")


def _subject_side(full: str, pos: int, default_side: str) -> str:
    before = full[max(0, pos - 160) : pos]
    # v36 : « … and it cannot be removed » : un nouveau sujet pronom ouvre une proposition (The Mirror's Depths)
    clause = re.split(r"[.:;\n]|\bthen\b|, (?=[a-z])| and (?=(?:it|they) )", before)[-1]
    if _SUBJ_ENEMY.search(clause):
        return "enemy"
    if _SUBJ_TARGET.search(clause):
        return default_side
    if _SUBJ_SELF.search(clause):
        return "friendly"
    if _SUBJ_PRONOUN.search(clause):
        # pronom : antécédent dans la même phrase (« If the target is an enemy unit, it has STRIKE-LAST »),
        # sinon la cible déclarée (« - It cannot use RUN abilities » sous une cible ennemie)
        sentence = re.split(r"[.:\n]", before)[-1]
        if _SUBJ_ENEMY.search(sentence):
            return "enemy"
        if re.match(r"\s*(?:While|If) the target\b", sentence):
            # v36 : « While the target is gazing into eternity, it must end … no further from this unit … and it
            # cannot be removed » (The Mirror's Depths) : le pronom reprend la cible, pas « this unit »
            return default_side
        if re.search(r"\b(?:[Tt]his (?:unit|model)|[Ff]riendly)\b", sentence):
            return "friendly"
        # v36 : antécédent dans une phrase précédente de la même ligne d'option (« Mesmerise: Pick a visible
        # enemy unit within 12" of this unit. Until …, that unit cannot use commands », Gobbapalooza)
        line = full[full.rfind("\n", 0, pos) + 1 : pos]
        if re.search(r"\b[Pp]ick (?:a|an|one|up to \d+)(?: visible)? enemy\b", line):
            return "enemy"
        return default_side
    return ""


def effects_of(
    declare: str, effect: str, scope: Scope, passive: bool = False, condition: str = ""
) -> tuple[list[Effect], list[str], bool]:
    """Effets reconnus (avec leur périmètre), mots-clés ciblés (Anti-X), dépendance à l'effectif."""
    default_side = "enemy" if scope in ("one_enemy", "enemy_aura", "all_enemies") else "friendly"
    out: list[Effect] = []

    enemy_target = default_side == "enemy"

    def add(e: Effect, text: str, pos: int) -> None:
        out.append(_annotate(e, sentence_at(text, pos), text, passive, enemy_target, condition))

    local_side = default_side
    # cible déclarée explicitement amie (pas « amie ou ennemie au choix », scope inconnu)
    declared = "friendly" if scope in ("self", "one_friendly", "friendly_aura", "army") else ""
    for sentence in re.split(r"(?<=[.:])\s+|\n", effect):
        if _LOCAL_ENEMY.search(sentence):
            local_side = "enemy"
            if re.search(r"\b[Pp]ick\b|\bIf you picked\b|\bIf the target is\b", sentence):
                declared = ""  # re-désignation explicite : « the target » est désormais ennemie
        elif _LOCAL_FRIENDLY.search(sentence):
            local_side = "friendly"
        out.extend(
            _annotate(e, sentence, effect, passive, local_side == "enemy", condition)
            for e in _stat_mods(sentence, local_side, declared)
        )

    seen_mortal = False
    per_roll_spans: list[tuple[int, int]] = []
    for m in _MORTAL_PER_ROLL.finditer(effect):
        mean, det = per_roll_mortals(effect, m)
        add(Effect("mortal_damage", "", mean, "", "enemy", det), effect, m.start())
        per_roll_spans.append((m.start(), m.end()))
        seen_mortal = True
    friendly_declared = scope in ("one_friendly", "friendly_aura", "army")
    for m in _MORTAL_RE.finditer(effect):
        if any(a <= m.start() < b for a, b in per_roll_spans):
            continue  # v33 : déjà compté par « For each N+ » (doublon à 1 avant)
        expr = m.group(1) or ""
        if seen_mortal and not expr[:1].isdigit() and "D" not in expr:
            continue
        mean = dice_mean(expr.replace("+X", "+1")) if expr else None  # « D3+X » : X = 1 (v27)
        rolled, die = equal_to_roll_mortals(effect, m.end()) if mean is None else (None, "")
        after = effect[m.start() : m.end() + 40]
        # v33 : « On a 1, inflict D3 mortal damage on the target » quand la cible déclarée est amie (Foul
        # Elixirs) : contrepartie, sauf re-désignation d'une cible ennemie entre-temps
        target_us = (
            bool(re.search(r"mortal damage on (?:this unit|it|that friendly)", after))
            or (
                friendly_declared
                and bool(re.search(r"mortal damage on (?:the|each) target\b", after))
                and not re.search(r"\b[Pp]ick\b[^.]*\benemy\b", effect[: m.start()])
            )
        ) and not _ENEMY_REDESIGNATED.search(effect[effect.rfind("\n", 0, m.start()) + 1 : m.start()])
        value = mean if mean is not None else rolled
        add(
            Effect(
                "mortal_damage",
                "",
                value or 0.0,
                expr if "D" in expr else die,
                "friendly" if target_us else "enemy",
                "auto-infligé" if target_us else ("variable" if value is None else ""),
            ),
            effect,
            m.start(),
        )
    for m in re.finditer(r"[Aa]llocate (\d+|D\d) damage points? to (?:this unit|this MANIFESTATION|it)\b", effect):
        # v30 : dégâts que l'unité s'inflige (surchauffe, contrecoup) : contrepartie, poids nul
        add(
            Effect(
                "mortal_damage",
                "",
                dice_mean(m.group(1)) or 0.0,
                m.group(1) if "D" in m.group(1) else "",
                "friendly",
                "auto-infligé",
            ),
            effect,
            m.start(),
        )
    for m in re.finditer(
        r"[Aa]llocate (\d+|D\d(?:\+\d)?|a number of) damage points? to (?:the target|each target|"
        r"that enemy unit|each enemy unit|the enemy unit)\b",
        effect,
    ):
        expr = m.group(1)
        mean = dice_mean(expr) if expr != "a number of" else None
        # v35 : « Allocate 3 damage points to the target » quand la cible déclarée est AMIE (Offering of Blood,
        # Atrocious Ministrations) : un coût payé par notre unité, pas des dégâts à l'ennemi
        ours = (
            friendly_declared
            and m.group(0).endswith(("the target", "each target"))
            and not re.search(r"\b[Pp]ick\b[^.]*\benemy\b", effect[: m.start()])
        )
        add(
            Effect(
                "mortal_damage",
                "",
                mean or 0.0,
                expr if "D" in expr else "",
                "friendly" if ours else "enemy",
                "auto-infligé" if ours else ("variable" if mean is None else ""),
            ),
            effect,
            m.start(),
        )
    fragile = bool(re.search(r"unmodified save roll of 1[^.]*remove", effect))
    for m in _WARD_RE.finditer(effect):
        side = (
            "enemy"
            if re.search(r"target[^.]*enemy|enemy units have", effect) and default_side == "enemy"
            else "friendly"
        )
        # v33 : « … and this unit has WARD (4+) » dans une aptitude qui vise une autre unité amie (Royal
        # Retinue) : « this unit » est le porteur (terminologie GW), pas la cible désignée
        bearer = friendly_declared and bool(
            re.search(r"\bthis (?:unit|model) (?:has|have|gains?) $", effect[max(0, m.start() - 30) : m.start()])
        )
        add(
            Effect(
                "ward",
                "",
                int(m.group(1)),
                "",
                side,
                "fragile" if fragile else "",
                friendly_target=BEARER_TARGET if bearer and side == "friendly" else "",
            ),
            effect,
            m.start(),
        )
    for m in _HEAL_RE.finditer(effect):
        if re.search(r"\bwould $", effect[max(0, m.start() - 6) : m.start()]):
            continue  # v36 : « an ability that would heal 1 or more damage points » : déclencheur, pas un soin
        mean = dice_mean(m.group(1))
        add(Effect("heal", "", mean or 0.0, m.group(1) if "D" in m.group(1) else "", "friendly"), effect, m.start())
    for m in re.finditer(r"\b[Aa]dd (\d+) to the number of damage points healed", effect):
        # v36 : « add 1 to the number of damage points healed » (Polluting Aura) : +1 à chaque soin, côté ami
        add(Effect("heal", "", float(m.group(1)), "", "friendly", "bonus aux soins"), effect, m.start())
    for m in _RETURN_RE.finditer(effect):
        # v34 : retour nié ou hypothétique (« would heal or return … does not heal … or return ») = anti-soin
        if re.search(
            r"(?:would|does not|do not|cannot)(?: heal(?: any damage points)?)?(?: or)?\s*$",
            effect[max(0, m.start() - 45) : m.start()],
        ):
            continue
        expr = (m.group(1) or "").replace("up to ", "")
        mean = dice_mean(expr) if expr else None
        add(Effect("return_models", "", mean or 0.0, expr if "D" in expr else "", "friendly"), effect, m.start())
    for m in _MOVE_RE.finditer(effect):
        expr = m.group(1) or ""
        if re.search(r"cannot move|can move[^.]*but cannot", effect[m.start() - 10 : m.start() + 5]):
            continue
        mean = dice_mean(expr) if expr else None
        side = (
            "enemy"
            if re.search(r"the target can move|enemy", effect[max(0, m.start() - 40) : m.start()])
            and default_side == "enemy"
            else "friendly"
        )
        add(Effect("move", "", mean or 0.0, expr if "D" in expr else "", side), effect, m.start())

    for m in _MAKE_MOVE_RE.finditer(effect):  # v28 : « it can immediately make a D6" move »
        mean = dice_mean(m.group(1))
        add(Effect("move", "", mean or 0.0, m.group(1) if "D" in m.group(1) else "", "friendly"), effect, m.start())

    target_kw: list[str] = []
    full = f"{declare} {effect}"
    for e, pos in rerolls_of(full):
        add(e, full, pos)
    for e, pos in dice_count_of(full):
        add(e, full, pos)
    for pat, kind, stat in QUALITATIVE_RULES:
        for m in re.finditer(pat, full):
            if kind == "anti":
                target_kw.append(m.group(1).upper())
            if kind in ("strike_first", "strike_last") and re.search(
                r"\b(?:while|if) (?:they|it|this unit|the target|that unit) (?:has|have) $",
                full[max(0, m.start() - 40) : m.start()],
            ):
                continue  # v33 : « … while they have STRIKE-FIRST » (Rune of Fury) : condition, pas un gain
            if re.search(r"(?:casting|chanting) roll was \d+\+[^.]*$", full[max(0, m.start() - 160) : m.start()]):
                continue  # bonus sur un jet élevé (« If the chanting roll was 8+, in addition … ») : pas acquis
            if kind == "no_weapon_abilities" and re.search(
                r"The Companion weapon ability has no effect on", full[max(0, m.start() - 40) : m.end() + 5]
            ):
                continue  # contrainte sur nos propres unités (Monstrous Entourage), pas un débuff
            if kind == "stat_set" and re.search(
                r"(?:has|have) \d+ or more damage points|[Bb]attle [Dd]amaged",
                full[max(0, m.start() - 200) : m.start()],
            ):
                continue  # profil dégradé (v27) : une perte, déjà lue par battle_damaged
            if kind == "stat_set" and re.search(
                r"\b(?:[Ii]f|[Ww]hile|whose|[Uu]nless)\b[^.,:]*$", full[max(0, m.start() - 60) : m.start()]
            ):
                continue  # « If the target's Save characteristic is 3+ » : condition, pas un effet (v27)
            if kind == "warscroll_rule" and not passive and re.search(r"token", m.group(0)):
                continue  # v30 : jeton posé par une aptitude active (Bomb Rats…) : l'effet est ailleurs, à lire
            if (
                kind == "fly"
                and "FLY" not in m.group(0)
                and any(e.kind in ("move", "extra_move", "redeploy", "deep_strike") for e in out)
            ):
                continue  # « It can move through the combat ranges » : modalité du mouvement, pas un effet en plus
            if kind in ("redeploy", "deep_strike") and _NOT_A_SETUP.search(
                full[max(0, full.rfind(". ", 0, m.start()), full.rfind("\n", 0, m.start())) : m.start()]
            ):
                continue  # v36 : interdiction ou déclencheur, pas une mise en place
            side, detail_override = default_side, ""
            if kind in ("no_ward", "slay", "no_weapon_abilities", "no_crit", "no_buff"):
                side = "enemy"
                head = full[max(full.rfind(". ", 0, m.start()), full.rfind("\n", 0, m.start())) + 1 : m.start()]
                if kind == "no_buff" and friendly_declared and not re.search(r"\benemy\b", head) and re.search(
                    r"for the target\b", full[m.start() : m.end() + 40]
                ):
                    # v39 : « Wild-eyed Brutality: Ignore positive modifiers to save rolls for the target » sur une
                    # cible amie (Blood-drenched) : la contrepartie du buff, pas un débuff ennemi
                    side, detail_override = "friendly", "contrepartie"
                if kind == "slay" and re.search(
                    r"\bwould be automatically destroyed, it is not\b", full[max(0, m.start() - 120) : m.end() + 20]
                ):
                    side = "friendly"  # v35 : protection contre l'élimination (Avatar of Destruction)
                elif (
                    kind == "slay"
                    and friendly_declared
                    and re.search(r"\bfriendly\b", declare)
                    and not re.search(r"\benemy\b", declare)
                    and re.search(
                        r"\bmodels? in the (?:drained|target) unit\b", full[max(0, m.start() - 60) : m.start()]
                    )
                ):
                    # v36 : figurines amies sacrifiées (Father of Necromancy) : un coût
                    side, detail_override = "friendly", "auto-infligé"
                if kind == "no_ward" and re.match(r"(?:it|this unit)\b", full[m.end() : m.end() + 12]) and re.search(
                    r"\bthis unit has [^.]*\bbut $", full[max(0, m.start() - 80) : m.start()]
                ):
                    side = "friendly"  # v35 : « this unit has STRIKE-FIRST but ward rolls cannot be made for it »
            if kind in ("strike_last", "restriction", "lockout", "move_debuff", "untargetable"):
                side = _subject_side(full, m.start(), default_side) or (
                    "enemy" if re.search(r"target|enemy", full[max(0, m.start() - 80) : m.start()]) else "friendly"
                )
                if "has no effect" in m.group(0):
                    side = "enemy"  # v27 : on annule une capacité adverse
            if kind in ("taunt", "anti_heal", "strip_enhancement", "fury_debuff"):
                side = "enemy"
            if kind in (
                "strike_first",
                "run_and_charge",
                "run_and_shoot",
                "redeploy",
                "extra_fight",
                "fight_twice",
                "extra_shoot",
                "fly",
                "cp_gain",
                "crit",
                "shoot_in_combat",
                "charge_bonus",
                "summon",
                "anti_magic",
                "control",
                "pile_in",
                "damage_redirect",
                "anti",
                "extra_move",
                "deep_strike",
                "stat_set",
                "negate_attack",
                "keyword_gain",
                "damage_ignore",
                "resource",
                "extra_use",
                "battle_damaged",
                "free_retreat",
                "fixed_roll",
                "rally",
                "range_bonus",
                "ignore_debuff",
                "snipe",
                "profile_choice",
                "tactic_cards",
                "coherency",
                "warscroll_rule",
            ):
                side = "friendly"
            if kind == "control" and m.group(0).startswith("control score"):
                # v36 (grille contrôle) : « that enemy unit has a maximum control score of 1 », « Subtract … from the
                # target's control score » sur une cible ennemie : débuff ; « This unit has a maximum control score
                # of 1 » (Beast) : contrepartie sur sa propre unité
                head = full[max(full.rfind(". ", 0, m.start()), full.rfind("\n", 0, m.start())) + 1 : m.start()]
                # « Add … to this unit's control score » après une cible ennemie (Light A Pyre) : reste ami
                ours = re.search(r"\b(?:this unit's|its) $", head)
                if not ours and (default_side == "enemy" or re.search(r"\benemy\b", head)):
                    side = "enemy"
                elif re.search(r"\b(?:[Tt]his unit|[Ii]t) has a maximum $", head):
                    detail_override = "contrepartie"
            if kind == "redeploy" and _ENEMY_MOVED.search(full[max(0, m.start() - 40) : m.end()]):
                side = "enemy"  # v36 : l'adversaire déplace SA cible (Shadow Lariat) : débuff
            if kind not in _WEAPON_KINDS and any(e.kind == kind and e.stat == stat and e.side == side for e in out):
                break  # v28 : deux règles du même effet (ressource…) ne le doublent pas
            add(Effect(kind, stat, 0.0, "", side, detail_override or m.group(0)[:80]), full, m.start())
            if detail_override == "contrepartie":
                continue  # v36 : la contrepartie (« maximum control score of 1 ») ne cache pas l'option suivante
            break  # un même effet qualitatif compte une fois

    for kw in re.findall(r"\b(MONSTER|HERO|INFANTRY|CAVALRY|WIZARD|PRIEST|WAR MACHINE|MANIFESTATION)S?\b", declare):
        if re.search(r"enemy " + kw, declare):
            target_kw.append(kw)

    scales = bool(re.search(r"for each model in (?:this|that|the target) unit|number of models in", full, re.I))
    return out, sorted(set(target_kw)), scales

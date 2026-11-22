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

from ..models import BEARER_TARGET, Extraction, RawAbility
from ..perimeter import charge_subjects
from .activation import OPPOSED_TEST_PROB, OPPOSED_TEST_PROBS, activation_of, p_prayer_banked  # noqa: F401
from .conditions import CHARGE_ENEMY, CHARGE_OURS, CONDITION_RULES, conditions_of, split_main_secondary  # noqa: F401
from .dice import dice_mean, p_2d6, p_d6  # noqa: F401
from .effects import effects_of
from .qualitative import QUALITATIVE_RULES  # noqa: F401
from .rolls import dice_count_of, rerolls_of  # noqa: F401
from .scope import scope_of
from .targets import (
    effect_friendly_target,  # noqa: F401
    excludes_self_of,
    friendly_target_of,
    unlock_prereqs_of,
)
from .timing import frequency_of, turn_of


def extract(raw: RawAbility) -> tuple[Extraction, float]:
    """Extraction complète + pénalité de mise en place cumulée (utilisée par scoring)."""
    if not raw.effect.strip() and raw.declare.strip():
        # v30 : tout le texte rangé sous « Declare » (OVERDRIVE SWITCH) : c'est l'effet
        raw = dataclasses.replace(raw, declare="", effect=raw.declare)
    main, secondary = split_main_secondary(raw.effect)
    scope, rng, wholly = scope_of(raw.declare, raw.effect)
    enemy_target = scope in ("one_enemy", "enemy_aura", "all_enemies")
    conditions, penalty = conditions_of(f"{raw.condition} {raw.declare} {main}", enemy_target)
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
    if "nous" in charge_subjects(raw.declare, enemy_target):
        effects = [
            e
            if e.side != "friendly" or "a chargé" in (e.requires or "")
            else dataclasses.replace(e, requires=" | ".join(filter(None, ["a chargé", e.requires])))
            for e in effects
        ]
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
    ex = Extraction(
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

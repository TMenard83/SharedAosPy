"""Bonus génériques (delta de caractéristiques) applicables à une unité hors DB.

Pas de nouvelle couche de résolution dans `combat.py` : `expected_weapon_damage`/
`weapon_damage_moments`/`weapon_damage_distribution` lisent déjà `weapon.attacks/
hit/wound/rend/damage` et `defender.save/ward` directement, donc un bonus
générique (ex. règle d'armée « +1 pour toucher, +1 pour sauvegarder ») s'applique
en amont, en construisant une copie modifiée de l'`Unit`/ses `Weapon` via
`dataclasses.replace` — même mécanisme que `analysis/cost/features.py::_ranged_only`/
`_melee_only`. Aucun changement au moteur de combat lui-même.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

from ..domain.models import Unit

#: Seuil de jet le plus favorable possible sur 1d6 (un 2+ reste le plancher même
#: avec un bonus supplémentaire — même convention que `combat.py::_prob_x_plus`).
_BEST_ROLL = 2
#: Cible interne pour « aucun ward » (cf. `features.py::UnitFeatures.ward_num`).
_NO_WARD = 7


@dataclass(frozen=True)
class StatDelta:
    """Delta additif de caractéristiques, appliqué par `apply_bonus`.

    `hit`/`wound`/`save`/`ward` sont des bonus « + facile » (comme un modificateur
    de jet AoS : +1 rapproche du succès), pas des seuils bruts — un `StatDelta`
    entièrement à zéro est un no-op, ce qui permet de traiter un bonus libre et un
    bonus d'armée listé (cf. `Bonus`) par le même chemin de code.
    """

    hit: int = 0
    wound: int = 0
    rend: int = 0
    save: int = 0
    ward: int = 0
    damage: int = 0
    attacks: int = 0

    def __add__(self, other: "StatDelta") -> "StatDelta":
        return StatDelta(
            hit=self.hit + other.hit,
            wound=self.wound + other.wound,
            rend=self.rend + other.rend,
            save=self.save + other.save,
            ward=self.ward + other.ward,
            damage=self.damage + other.damage,
            attacks=self.attacks + other.attacks,
        )


#: `StatDelta` neutre, réutilisable comme valeur de départ pour `combine`.
NO_DELTA = StatDelta()


def combine(deltas: Iterable[StatDelta]) -> StatDelta:
    """Somme une collection de `StatDelta` (bonus d'armée cochés + bonus libre)."""
    total = NO_DELTA
    for d in deltas:
        total = total + d
    return total


def apply_bonus(unit: Unit, delta: StatDelta) -> Unit:
    """Retourne une copie de `unit` avec `delta` appliqué à chaque profil d'arme
    et aux caractéristiques défensives de l'unité. `weapon.name` n'est jamais
    modifié (le matching de `loadout.py::model_counts` est keyé dessus).
    """
    if delta == NO_DELTA:
        return unit

    weapons = [
        dataclasses.replace(
            w,
            hit=max(_BEST_ROLL, w.hit - delta.hit),
            wound=max(_BEST_ROLL, w.wound - delta.wound),
            rend=max(0, w.rend + delta.rend),
            damage=max(0, w.damage + delta.damage),
            attacks=max(0, w.attacks + delta.attacks),
        )
        for w in unit.weapons
    ]

    new_save = max(_BEST_ROLL, unit.save - delta.save)
    base_ward = unit.ward if unit.ward is not None else _NO_WARD
    new_ward_num = max(_BEST_ROLL, base_ward - delta.ward)
    new_ward = None if new_ward_num >= _NO_WARD else new_ward_num

    return dataclasses.replace(unit, weapons=weapons, save=new_save, ward=new_ward)


@dataclass(frozen=True)
class Bonus:
    """Un bonus d'armée nommé (ex. « Heure de Gloire »), cf. `bonus_simulator/army_rules.py`."""

    name: str
    description: str
    delta: StatDelta

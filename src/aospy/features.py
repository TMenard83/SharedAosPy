"""Vecteur de caractéristiques par unité — socle du modèle de coût.

Port du principe de StatHammer (voir son `features.py`) sur le modèle de données
natif d'aospy : chaque unité est sondée offensivement contre trois défenseurs
synthétiques (save 2+, save 4+, aucune save) pour capter à la fois la magnitude
brute des dégâts et la sensibilité au rend, en réutilisant le moteur de
`combat.py` (`unit_damage_moments`) — aucun calcul de dés n'est réécrit ici.

Simplifications assumées par rapport à StatHammer, dues au schéma aospy :

* pas de dés dans les caractéristiques (`Weapon.attacks`/`damage` sont des
  entiers déjà résolus par l'import BSData) : `dmg_cv_vs_save4` ne capte que
  l'aléa hit/wound/save/ward, pas une éventuelle variabilité d'attaques/dégâts
  en dés (perdue à l'import) ;
* `move`/`control` sont déjà des entiers propres (pas de texte à parser) ;
* la répartition mêlée/distance vient directement de `Weapon.kind`, pas d'un
  parsing de texte (`Weapon.kind` distingue déjà "melee"/"ranged").
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import duckdb

from .combat import CombatModifiers, unit_damage_moments
from .models import Unit
from .repository import load_all_units_with_weapons

#: Défenseurs synthétiques pour la sonde offensive. Save 7 = aucune sauvegarde
#: possible (convention identique à StatHammer), ward toujours absent : on veut
#: mesurer l'attaquant, pas la défense.
_PROBE_SAVE2 = Unit(name="_probe", army_id=0, move=0, save=2, health=1, control=0, models=1, points=0)
_PROBE_SAVE4 = Unit(name="_probe", army_id=0, move=0, save=4, health=1, control=0, models=1, points=0)
_PROBE_NOSAVE = Unit(name="_probe", army_id=0, move=0, save=7, health=1, control=0, models=1, points=0)

_NO_MODS = CombatModifiers()


@dataclass(frozen=True)
class UnitFeatures:
    """Vecteur de caractéristiques d'une unité, prêt pour la régression de coût."""

    unit_id: int | None
    army_id: int
    name: str
    points: int
    is_hero: bool

    dmg_vs_save2: float
    dmg_vs_save4: float
    dmg_vs_nosave: float
    dmg_ranged_vs_nosave: float
    dmg_pen: float  # dmg_vs_save2 / dmg_vs_nosave (0 si dmg_vs_nosave == 0)
    dmg_cv_vs_save4: float  # écart-type / moyenne contre save4 (fiabilité offensive)

    wounds_total: int  # health * models
    save_num: int
    ward_num: int  # ward, ou 7 si aucun ward

    move: int
    control: int
    unit_size: int  # models


def _ranged_only(unit: Unit) -> Unit:
    """Copie de `unit` ne conservant que ses profils d'arme à distance."""
    return dataclasses.replace(unit, weapons=[w for w in unit.weapons if w.kind == "ranged"])


def compute_features(unit: Unit) -> UnitFeatures:
    """Calcule le vecteur de caractéristiques d'une unité (cœur pur, sans DB)."""
    mean2, _v2, _s2 = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, _NO_MODS)
    mean4, var4, _s4 = unit_damage_moments(unit, unit.models, _PROBE_SAVE4, _NO_MODS)
    mean_nosave, _vn, _sn = unit_damage_moments(unit, unit.models, _PROBE_NOSAVE, _NO_MODS)

    ranged_unit = _ranged_only(unit)
    dmg_ranged_vs_nosave = (
        unit_damage_moments(ranged_unit, unit.models, _PROBE_NOSAVE, _NO_MODS)[0]
        if ranged_unit.weapons
        else 0.0
    )

    dmg_pen = (mean2 / mean_nosave) if mean_nosave > 0 else 0.0
    dmg_cv_vs_save4 = (var4**0.5 / mean4) if mean4 > 0 else 0.0

    return UnitFeatures(
        unit_id=unit.id,
        army_id=unit.army_id,
        name=unit.name,
        points=unit.points,
        is_hero=unit.is_hero,
        dmg_vs_save2=mean2,
        dmg_vs_save4=mean4,
        dmg_vs_nosave=mean_nosave,
        dmg_ranged_vs_nosave=dmg_ranged_vs_nosave,
        dmg_pen=dmg_pen,
        dmg_cv_vs_save4=dmg_cv_vs_save4,
        wounds_total=unit.health * unit.models,
        save_num=unit.save,
        ward_num=unit.ward if unit.ward is not None else 7,
        move=unit.move,
        control=unit.control,
        unit_size=unit.models,
    )


def all_features(con: duckdb.DuckDBPyConnection) -> list[UnitFeatures]:
    """Calcule le vecteur de caractéristiques de toutes les unités de la base."""
    by_army = load_all_units_with_weapons(con)
    return [compute_features(unit) for units in by_army.values() for unit in units]

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
  parsing de texte (`Weapon.kind` distingue déjà "melee"/"ranged") ;
* pas d'axe « puissance d'aptitudes » général (aucun texte d'aptitude par unité en
  base) — sauf pour les profils sorciers/prêtres : `wizard_level`/`priest_level`
  extraient le `WIZARD (N)`/`PRIEST (N)` que BSData capture tel quel dans
  `Unit.keywords` (seule `WARD (N+)` y est traitée à part par l'import), un proxy
  ponctuel mais direct de cet axe pour ces deux mots-clés précis.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass

import duckdb

from ..domain.models import Unit
from ..engine.combat import CombatModifiers, unit_damage_moments, weapon_crit_type
from ..persistence.repository import load_all_units_with_weapons

#: Repère les mots-clés `WIZARD (N)`/`PRIEST (N)` (BSData les capture tels quels
#: dans `Unit.keywords` — seule `WARD (N+)` est traitée à part comme pseudo-catégorie).
_CASTER_RE = re.compile(r"^(WIZARD|PRIEST) \((\d+)\)$")

#: Catégories de "type d'unité" AoS4 — quasi mutuellement exclusives (une unité
#: porte normalement exactement l'une de ces cinq, cf. audit sur la base BSData :
#: INFANTRY+CAVALRY+MONSTER+WAR MACHINE+BEAST ≈ nombre total d'unités).
_UNIT_TYPE_KEYWORDS: tuple[str, ...] = ("INFANTRY", "CAVALRY", "MONSTER", "WAR MACHINE", "BEAST")


def _caster_level(keywords: frozenset[str], kind: str) -> int:
    """Niveau de lanceur (nombre de sorts/prières castables), 0 si absent.

    Proxy direct de la puissance d'aptitudes pour les seuls profils sorciers/prêtres
    (aospy ne stocke pas le texte des aptitudes en général — voir la note de module) :
    un `Wizard (2)` coûte structurellement plus cher qu'un profil de combat identique
    sans incantation, et le modèle de coût était jusqu'ici aveugle à ce facteur.
    """
    best = 0
    for kw in keywords:
        m = _CASTER_RE.match(kw)
        if m and m.group(1) == kind:
            best = max(best, int(m.group(2)))
    return best


def _unit_type(keywords: frozenset[str]) -> str:
    """Type d'unité (INFANTRY/CAVALRY/MONSTER/WAR MACHINE/BEAST), "OTHER" si aucun ne matche."""
    for t in _UNIT_TYPE_KEYWORDS:
        if t in keywords:
            return t
    return "OTHER"

#: Défenseurs synthétiques pour la sonde offensive. Save 7 = aucune sauvegarde
#: possible (convention identique à StatHammer), ward toujours absent : on veut
#: mesurer l'attaquant, pas la défense.
_PROBE_SAVE2 = Unit(name="_probe", army_id=0, move=0, save=2, health=1, control=0, models=1, points=0)
_PROBE_SAVE4 = Unit(name="_probe", army_id=0, move=0, save=4, health=1, control=0, models=1, points=0)
_PROBE_NOSAVE = Unit(name="_probe", army_id=0, move=0, save=7, health=1, control=0, models=1, points=0)

_NO_MODS = CombatModifiers()
_CHARGED_MODS = CombatModifiers(attacker_charged=True)


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
    charge_bonus_save2: float  # supplément de dmg_vs_save2 apporté par un `Charge (+N <Stat>)`
    # (0 si l'unité n'a aucun profil d'arme avec ce texte) — sans ce champ, ce bonus était
    # invisible au modèle de coût (les sondes ci-dessous ne simulent jamais une charge).
    # Magnitude, pas simple indicateur de présence : cf. `scratch/experiment_weapon_tags.py`,
    # même constat que `dmg_pen`→`dmg_vs_save2` (la magnitude explique le prix, pas la
    # présence — `has_charge` seul n'était pas significatif, p=0.150 vs p=0.001 en magnitude).
    # `Anti-<MOT-CLÉ>` a été testé dans le même essai et écarté : ni la présence
    # (`has_anti`, p=0.500) ni la magnitude (`anti_bonus_save2`, p=0.83-0.91) n'étaient
    # significatives, contre un défenseur sonde portant tous les mots-clés jamais visés
    # par un Anti-X dans la base — GW ne semble pas facturer ce tag séparément.

    wounds_total: int  # health * models
    save_num: int
    ward_num: int  # ward, ou 7 si aucun ward

    move: int
    control: int
    unit_size: int  # models

    grand_alliance: str  # résolu par `all_features` (nécessite la DB) ; gardé comme métadonnée,
    # mais absorbé par `army_name` dans `cost_model.CATEGORICAL_FEATURES` (armée ⊂ alliance,
    # les deux ensemble seraient colinéaires — cf. `scratch/experiment_army_factor.py`)
    army_name: str  # facteur catégoriel plus fin que grand_alliance, résolu par `all_features`
    weapon_mix: str  # "melee" / "ranged" / "mixed" — facteur catégoriel dérivé des profils d'arme

    unit_type: str  # INFANTRY / CAVALRY / MONSTER / WAR MACHINE / BEAST / OTHER, cf. _unit_type
    is_flying: bool  # mot-clé FLY
    wizard_level: int  # WIZARD (N), 0 si aucun
    priest_level: int  # PRIEST (N), 0 si aucun
    is_unique: bool  # mot-clé UNIQUE — proxy grossier de la prime "aptitudes/narratif" d'un
    # personnage nommé, qu'aospy ne modélise pas autrement (pas de texte d'aptitude en base) ;
    # cf. `scratch/experiment_unique_factor.py`, +16.6 pts significatif (p<0.001)
    crit_type: str  # type de Crit (none/2hits/mortal/autowound) du profil d'arme qui contribue
    # le plus à dmg_vs_save2 (proxy du "crit dominant" d'une unité multi-profils) — significatif
    # au-delà de la magnitude de dégât déjà captée par dmg_vs_save2 : cf.
    # `scratch/experiment_weapon_tags.py` (autowound +17.1 pts, mortal -15.9 pts vs 2hits, p<0.05)


def _ranged_only(unit: Unit) -> Unit:
    """Copie de `unit` ne conservant que ses profils d'arme à distance."""
    return dataclasses.replace(unit, weapons=[w for w in unit.weapons if w.kind == "ranged"])


def _dominant_crit_type(unit: Unit) -> str:
    """Type de Crit du profil d'arme qui contribue le plus à `dmg_vs_save2` — proxy du
    "crit dominant" d'une unité à profils d'arme multiples (chacun peut porter un Crit
    différent). "none" si l'unité n'a aucune arme ou aucun Crit."""
    best_type = "none"
    best_dmg = -1.0
    for w in unit.weapons:
        dmg, _v, _s = unit_damage_moments(
            dataclasses.replace(unit, weapons=[w]), unit.models, _PROBE_SAVE2, _NO_MODS,
        )
        if dmg > best_dmg:
            best_dmg = dmg
            best_type = weapon_crit_type(w.abilities)
    return best_type


def compute_features(unit: Unit) -> UnitFeatures:
    """Calcule le vecteur de caractéristiques d'une unité (cœur pur, sans DB)."""
    mean2, _v2, _s2 = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, _NO_MODS)
    mean4, var4, _s4 = unit_damage_moments(unit, unit.models, _PROBE_SAVE4, _NO_MODS)
    mean_nosave, _vn, _sn = unit_damage_moments(unit, unit.models, _PROBE_NOSAVE, _NO_MODS)
    mean2_charged, _v2c, _s2c = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, _CHARGED_MODS)
    charge_bonus_save2 = max(0.0, mean2_charged - mean2)

    ranged_unit = _ranged_only(unit)
    dmg_ranged_vs_nosave = (
        unit_damage_moments(ranged_unit, unit.models, _PROBE_NOSAVE, _NO_MODS)[0]
        if ranged_unit.weapons
        else 0.0
    )

    dmg_pen = (mean2 / mean_nosave) if mean_nosave > 0 else 0.0
    dmg_cv_vs_save4 = (var4**0.5 / mean4) if mean4 > 0 else 0.0

    kinds = {w.kind for w in unit.weapons}
    if kinds == {"melee"}:
        weapon_mix = "melee"
    elif kinds == {"ranged"}:
        weapon_mix = "ranged"
    elif kinds:
        weapon_mix = "mixed"
    else:
        weapon_mix = "melee"

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
        charge_bonus_save2=charge_bonus_save2,
        wounds_total=unit.health * unit.models,
        save_num=unit.save,
        ward_num=unit.ward if unit.ward is not None else 7,
        move=unit.move,
        control=unit.control,
        unit_size=unit.models,
        grand_alliance="",
        army_name="",
        weapon_mix=weapon_mix,
        unit_type=_unit_type(unit.keywords),
        is_flying="FLY" in unit.keywords,
        wizard_level=_caster_level(unit.keywords, "WIZARD"),
        priest_level=_caster_level(unit.keywords, "PRIEST"),
        is_unique="UNIQUE" in unit.keywords,
        crit_type=_dominant_crit_type(unit),
    )


def all_features(con: duckdb.DuckDBPyConnection) -> list[UnitFeatures]:
    """Calcule le vecteur de caractéristiques de toutes les unités de la base."""
    from ..persistence.repository import list_armies

    armies = list_armies(con)
    alliance_by_army = {a.id: a.grand_alliance for a in armies}
    name_by_army = {a.id: a.name for a in armies}
    by_army = load_all_units_with_weapons(con)
    return [
        dataclasses.replace(
            compute_features(unit),
            grand_alliance=alliance_by_army.get(unit.army_id, "Order"),
            army_name=name_by_army.get(unit.army_id, "?"),
        )
        for units in by_army.values()
        for unit in units
    ]

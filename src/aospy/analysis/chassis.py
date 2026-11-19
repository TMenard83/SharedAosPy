"""Couche 2 — le châssis : ce que vaut la charte nue, sans ses aptitudes.

Architecture « aptitude ≠ châssis » (cf. CLAUDE.md, « Ability analysis ») : une stat de charte
est acquise, un bonus d'aptitude se joue. Ce module décrit la charte seule — PV, sauvegarde,
profils d'arme et leurs capacités d'arme (Crit, Anti-X, Charge, Companion, qui font partie du
profil) — avec deux familles de mesures :

* **performance** (moteur de combat, `engine/combat.py`) : dégâts moyens d'un round contre une
  cible à sauvegarde 4+, séparés mêlée / tir, et durabilité effective (coups à porter pour
  tuer l'unité), bruts et pour 100 pts ;
* **descripteurs de compatibilité**, ce que la couche 3 (rencontre aptitude × châssis) lira
  pour savoir si une aptitude « prend » sur cette charte : part des dégâts venant d'armes à
  1 dégât (« +1 Damage » double leur sortie), d'armes Compagnon (insensibles à la plupart des
  bonus), de la mêlée ; type de critique dominant ; nombre d'attaques.

Le prix GW du châssis (résidu du modèle de coût) et l'efficacité en duel (`unit_benchmark`)
sont joints par `build_chassis_rows` quand ils sont disponibles ; aucun score composite n'est
calculé ici (le partage attaque/défense reste à trancher avec l'utilisateur).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Optional

from ..domain.models import Unit, Weapon
from ..engine.combat import unit_damage_moments
from .features import _NO_MODS, _PROBE_SAVE4, _dominant_crit_type, _effective_wounds, _unit_type


def is_companion(weapon: Weapon) -> bool:
    """Arme Compagnon : capacité d'arme « Companion » (ou profil fusionné d'une sous-entrée)."""
    return weapon.is_companion or "companion" in (weapon.abilities or "").lower()


@dataclass(frozen=True)
class ChassisProfile:
    unit_id: Optional[int]
    name: str
    army_id: int
    points: int
    is_hero: bool
    unit_type: str
    models: int
    health: int
    save: int
    ward: Optional[int]
    move: int
    is_flying: bool
    # performance (moteur)
    dmg_melee: float            # dégâts moyens / round vs sauvegarde 4+, mêlée
    dmg_ranged: float           # idem, tir
    effective_wounds: float     # coups à porter pour tuer l'unité (rend 1 représentatif)
    dmg_per_100: float          # (mêlée + tir) pour 100 pts
    ewounds_per_100: float      # durabilité pour 100 pts
    # descripteurs de compatibilité (couche 3)
    attacks_total: float        # attaques totales de l'unité (toutes armes, tous porteurs)
    share_melee: float          # part des dégâts en mêlée (0-1)
    share_damage1: float        # part des dégâts venant d'armes à 1 dégât
    share_companion: float      # part des dégâts venant d'armes Compagnon
    crit_type: str              # critique dominant (none / 2hits / mortal / autowound)


def _damage(unit: Unit, weapons: list[Weapon]) -> float:
    if not weapons:
        return 0.0
    return unit_damage_moments(dataclasses.replace(unit, weapons=weapons), unit.models, _PROBE_SAVE4, _NO_MODS)[0]


def _attacks_total(unit: Unit) -> float:
    total = 0.0
    for w in unit.weapons:
        carriers = w.wielders if w.wielders else unit.models
        total += w.attacks * carriers
    return total


def chassis_profile(unit: Unit) -> ChassisProfile:
    """Profil de châssis d'une unité (pur, sans DB)."""
    melee = [w for w in unit.weapons if w.kind == "melee"]
    ranged = [w for w in unit.weapons if w.kind == "ranged"]
    dmg_melee, dmg_ranged = _damage(unit, melee), _damage(unit, ranged)
    total = dmg_melee + dmg_ranged
    d1 = _damage(unit, [w for w in unit.weapons if w.damage <= 1])
    comp = _damage(unit, [w for w in unit.weapons if is_companion(w)])
    ward_num = unit.ward if unit.ward is not None else 7
    ew = _effective_wounds(unit.health * unit.models, unit.save, ward_num)
    per100 = 100.0 / unit.points if unit.points > 0 else 0.0
    share = (lambda x: x / total) if total > 0 else (lambda x: 0.0)
    return ChassisProfile(
        unit_id=unit.id, name=unit.name, army_id=unit.army_id, points=unit.points, is_hero=unit.is_hero,
        unit_type=_unit_type(unit.keywords), models=unit.models, health=unit.health, save=unit.save,
        ward=unit.ward, move=unit.move, is_flying="FLY" in unit.keywords,
        dmg_melee=round(dmg_melee, 3), dmg_ranged=round(dmg_ranged, 3), effective_wounds=round(ew, 2),
        dmg_per_100=round(total * per100, 3), ewounds_per_100=round(ew * per100, 3),
        attacks_total=_attacks_total(unit), share_melee=round(share(dmg_melee), 3),
        share_damage1=round(share(d1), 3), share_companion=round(share(comp), 3),
        crit_type=_dominant_crit_type(unit),
    )


def _pct_rank(values: list[float]) -> list[float]:
    """Rang centile (0 = plus faible, 1 = plus fort), ex æquo au rang moyen."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = ((i + j) / 2) / (len(values) - 1) if len(values) > 1 else 0.5
        for k in range(i, j + 1):
            ranks[order[k]] = round(r, 4)
        i = j + 1
    return ranks


def build_chassis_rows(con) -> tuple[list[tuple], list[str]]:
    """Tuples `repository.CHASSIS_COLS` pour toutes les unités payantes + notes sur les sources absentes."""
    from datetime import datetime

    from ..persistence import repository

    notes: list[str] = []
    units = [u for us in repository.load_all_units_with_weapons(con).values() for u in us if u.points > 0]
    profiles = [chassis_profile(u) for u in units]

    residuals: dict[int, float] = {}
    try:
        from . import cost_model

        res = cost_model.fit_cost_model_factorial(con)
        residuals = {r.unit_id: r.residual_pct for r in res.residuals if r.unit_id is not None}
    except ImportError:
        notes.append("résidu de coût absent : installer l'extra [analysis]")
    roi = repository.duel_roi_by_unit(con)
    if not roi:
        notes.append("efficacité en duel absente : lancer `aospy unit benchmark-all --charge none "
                     "--attacker-mode floor66 --defender-mode mean --include-heroes`")

    ranks: dict[int, tuple[float, float]] = {}
    for hero in (True, False):
        idx = [i for i, p in enumerate(profiles) if p.is_hero == hero]
        dr = _pct_rank([profiles[i].dmg_per_100 for i in idx])
        er = _pct_rank([profiles[i].ewounds_per_100 for i in idx])
        for k, i in enumerate(idx):
            ranks[i] = (dr[k], er[k])

    now = datetime.now()
    rows = []
    for i, p in enumerate(profiles):
        rows.append((
            p.unit_id, p.name, p.army_id, p.points, p.is_hero, p.unit_type, p.models, p.health, p.save, p.ward,
            p.move, p.is_flying, p.dmg_melee, p.dmg_ranged, p.effective_wounds, p.dmg_per_100, p.ewounds_per_100,
            p.attacks_total, p.share_melee, p.share_damage1, p.share_companion, p.crit_type,
            ranks[i][0], ranks[i][1], residuals.get(p.unit_id), roi.get(p.unit_id), now,
        ))
    return rows, notes

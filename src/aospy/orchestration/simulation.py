"""Simulation d'affrontement entre deux compositions (tous vs tous)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import duckdb

from ..domain.models import Composition, Unit
from ..engine.combat import CombatModifiers, expected_unit_damage
from ..persistence import repository


@dataclass
class PairResult:
    """Résultat d'un duel attaquant_entry → défenseur_entry."""
    attacker_entry_id: Optional[int]
    attacker_label: str
    attacker_models: int
    defender_entry_id: Optional[int]
    defender_label: str
    defender_total_hp: int
    raw_damage: float            # dégât brut espéré (non plafonné)
    expected_damage: float       # plafonné par HP du défenseur
    expected_models_killed: float


@dataclass
class SideOptions:
    """Options par côté (offensif + défensif)."""
    charged: bool = True
    all_out_attack: bool = False
    all_out_defense: bool = False


@dataclass
class SideReport:
    """Rapport d'un côté qui attaque l'autre."""
    composition: Composition
    pairs: list[PairResult] = field(default_factory=list)
    best_target_total: float = 0.0  # somme des meilleurs dégâts par attaquant


@dataclass
class BattleReport:
    a_to_b: SideReport
    b_to_a: SideReport
    options_a: SideOptions
    options_b: SideOptions


def _attacker_models(unit: Unit, reinforced: bool) -> int:
    return unit.models * (2 if reinforced else 1)


def _defender_total_hp(unit: Unit, reinforced: bool) -> int:
    return unit.models * (2 if reinforced else 1) * unit.health


def _label(unit: Unit, reinforced: bool) -> str:
    return f"{unit.name}{' (R)' if reinforced else ''}"


def _compute_side(
    con: duckdb.DuckDBPyConnection,
    attackers: Composition,
    defenders: Composition,
    mods_attacker: SideOptions,
    mods_defender: SideOptions,
) -> SideReport:
    units: dict[int, Unit] = {}

    def get_unit(uid: int) -> Unit:
        if uid not in units:
            u = repository.get_unit(con, uid)
            if u is None:
                raise ValueError(f"unité introuvable: {uid}")
            units[uid] = u
        return units[uid]

    pairs: list[PairResult] = []
    best_per_attacker: dict[Optional[int], float] = {}

    combat_mods = CombatModifiers(
        attacker_all_out_attack=mods_attacker.all_out_attack,
        attacker_charged=mods_attacker.charged,
        defender_all_out_defense=mods_defender.all_out_defense,
    )

    for a_entry in attackers.entries:
        a_unit = get_unit(a_entry.unit_id)
        a_models = _attacker_models(a_unit, a_entry.reinforced)
        for b_entry in defenders.entries:
            b_unit = get_unit(b_entry.unit_id)
            b_hp = _defender_total_hp(b_unit, b_entry.reinforced)
            raw = expected_unit_damage(a_unit, a_models, b_unit, combat_mods)
            capped = min(raw, float(b_hp))
            models_killed = min(
                capped / b_unit.health,
                float(b_unit.models * (2 if b_entry.reinforced else 1)),
            )
            pairs.append(PairResult(
                attacker_entry_id=a_entry.id,
                attacker_label=_label(a_unit, a_entry.reinforced),
                attacker_models=a_models,
                defender_entry_id=b_entry.id,
                defender_label=_label(b_unit, b_entry.reinforced),
                defender_total_hp=b_hp,
                raw_damage=raw,
                expected_damage=capped,
                expected_models_killed=models_killed,
            ))
            prev = best_per_attacker.get(a_entry.id, -1.0)
            if capped > prev:
                best_per_attacker[a_entry.id] = capped

    return SideReport(
        composition=attackers,
        pairs=pairs,
        best_target_total=sum(best_per_attacker.values()),
    )


def simulate_battle(
    con: duckdb.DuckDBPyConnection,
    comp_a_id: int,
    comp_b_id: int,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
) -> BattleReport:
    """Simule un affrontement (tous vs tous) entre deux compositions."""
    comp_a = repository.get_composition(con, comp_a_id)
    if comp_a is None:
        raise ValueError(f"composition introuvable: {comp_a_id}")
    comp_b = repository.get_composition(con, comp_b_id)
    if comp_b is None:
        raise ValueError(f"composition introuvable: {comp_b_id}")

    opts_a = options_a or SideOptions()
    opts_b = options_b or SideOptions()

    a_to_b = _compute_side(con, comp_a, comp_b, opts_a, opts_b)
    b_to_a = _compute_side(con, comp_b, comp_a, opts_b, opts_a)

    return BattleReport(
        a_to_b=a_to_b, b_to_a=b_to_a,
        options_a=opts_a, options_b=opts_b,
    )

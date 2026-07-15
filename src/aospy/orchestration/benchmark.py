"""Duel et benchmark unité vs unité (sans passer par les compositions)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import duckdb

from ..domain.models import Unit
from ..engine.combat import CombatModifiers, damage_floor95, expected_unit_damage, unit_damage_moments
from ..persistence import repository
from .simulation import SideOptions


@dataclass
class DuelResult:
    """Résultat d'un duel symétrique unité A vs unité B (1 round, dégât espéré)."""
    attacker: Unit
    attacker_models: int
    attacker_reinforced: bool
    defender: Unit
    defender_models: int
    defender_reinforced: bool
    defender_army_name: str
    raw_a_to_b: float
    expected_a_to_b: float
    expected_models_killed_b: float
    raw_b_to_a: float
    expected_b_to_a: float
    expected_models_killed_a: float
    options_a: SideOptions
    options_b: SideOptions

    @property
    def attacker_total_hp(self) -> int:
        return self.attacker_models * self.attacker.health

    @property
    def defender_total_hp(self) -> int:
        return self.defender_models * self.defender.health

    @property
    def net(self) -> float:
        return self.expected_a_to_b - self.expected_b_to_a

    @property
    def pts_destroyed(self) -> float:
        """Valeur (en pts) détruite chez le défenseur."""
        if self.defender_total_hp == 0:
            return 0.0
        return self.expected_a_to_b / self.defender_total_hp * self.defender.points

    @property
    def pts_lost(self) -> float:
        """Valeur (en pts) perdue chez l'attaquant."""
        if self.attacker_total_hp == 0:
            return 0.0
        return self.expected_b_to_a / self.attacker_total_hp * self.attacker.points

    @property
    def pts_net(self) -> float:
        """Bilan en points : positif = trade rentable indépendamment de l'écart de coût."""
        return self.pts_destroyed - self.pts_lost

    @property
    def roi(self) -> float:
        """Return on investment : pts_net normalisé par le coût de l'attaquant."""
        if self.attacker.points == 0:
            return 0.0
        return self.pts_net / self.attacker.points


def _effective_models(unit: Unit, reinforced: bool) -> int:
    return unit.models * (2 if reinforced else 1)


def _mods(attacker_opts: SideOptions, defender_opts: SideOptions) -> CombatModifiers:
    return CombatModifiers(
        attacker_all_out_attack=attacker_opts.all_out_attack,
        attacker_charged=attacker_opts.charged,
        defender_all_out_defense=defender_opts.all_out_defense,
    )


def _attack_damage(
    attacker: Unit, attacker_models: int, defender: Unit, modifiers: CombatModifiers,
    *, use_floor95: bool,
) -> float:
    """Dégât total d'une unité en 1 round : espérance, ou plancher 95% de confiance.

    `use_floor95=True` substitue `damage_floor95(moyenne, écart-type)` (via
    `unit_damage_moments`) à la moyenne brute `expected_unit_damage` — même
    modèle probabiliste, juste une lecture pessimiste (95%) au lieu de l'espérance.
    """
    if not use_floor95:
        return expected_unit_damage(attacker, attacker_models, defender, modifiers)
    mean, _var, std = unit_damage_moments(attacker, attacker_models, defender, modifiers)
    return damage_floor95(mean, std)


def unit_duel(
    attacker: Unit,
    defender: Unit,
    defender_army_name: str = "",
    *,
    attacker_reinforced: bool = False,
    defender_reinforced: bool = False,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
    use_floor95: bool = False,
) -> DuelResult:
    """Calcule le duel attaquant vs défenseur dans les deux sens.

    `use_floor95=True` : les dégâts (et donc pts_destroyed/pts_lost/pts_net/roi,
    dérivés de `expected_a_to_b`/`expected_b_to_a`) sont le plancher à 95% de
    confiance plutôt que l'espérance — cf. `_attack_damage`.
    """
    opts_a = options_a or SideOptions(charged=False)
    opts_b = options_b or SideOptions(charged=False)

    a_models = _effective_models(attacker, attacker_reinforced)
    b_models = _effective_models(defender, defender_reinforced)
    a_hp_total = a_models * attacker.health
    b_hp_total = b_models * defender.health

    raw_ab = _attack_damage(attacker, a_models, defender, _mods(opts_a, opts_b), use_floor95=use_floor95)
    raw_ba = _attack_damage(defender, b_models, attacker, _mods(opts_b, opts_a), use_floor95=use_floor95)

    exp_ab = min(raw_ab, float(b_hp_total))
    exp_ba = min(raw_ba, float(a_hp_total))

    return DuelResult(
        attacker=attacker, attacker_models=a_models,
        attacker_reinforced=attacker_reinforced,
        defender=defender, defender_models=b_models,
        defender_reinforced=defender_reinforced,
        defender_army_name=defender_army_name,
        raw_a_to_b=raw_ab, expected_a_to_b=exp_ab,
        expected_models_killed_b=min(exp_ab / defender.health, float(b_models)),
        raw_b_to_a=raw_ba, expected_b_to_a=exp_ba,
        expected_models_killed_a=min(exp_ba / attacker.health, float(a_models)),
        options_a=opts_a, options_b=opts_b,
    )


def find_unit(
    con: duckdb.DuckDBPyConnection, name: str, army_name: Optional[str],
) -> tuple[Unit, str]:
    """Résout une unité par nom (+ armée optionnelle pour lever l'ambiguïté)."""
    if army_name:
        army = repository.get_army_by_name(con, army_name)
        if army is None or army.id is None:
            raise ValueError(f"armée inconnue : {army_name}")
        unit = repository.get_unit_by_name(con, army.id, name)
        if unit is None:
            raise ValueError(f"unité '{name}' introuvable dans {army_name}")
        return unit, army_name
    matches: list[tuple[Unit, str]] = []
    for army in repository.list_armies(con):
        if army.id is None:
            continue
        unit = repository.get_unit_by_name(con, army.id, name)
        if unit is not None:
            matches.append((unit, army.name))
    if not matches:
        raise ValueError(f"unité '{name}' introuvable")
    if len(matches) > 1:
        names = ", ".join(a for _, a in matches)
        raise ValueError(f"unité '{name}' ambiguë ({names}) — précise --attacker-army")
    return matches[0]


def benchmark_attacker(
    con: duckdb.DuckDBPyConnection,
    attacker: Unit,
    *,
    attacker_reinforced: bool = False,
    defender_reinforced: bool = False,
    exclude_army_id: Optional[int] = None,
    target_army: Optional[str] = None,
    include_heroes: bool = False,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
    defenders_by_army: Optional[dict[int, list[Unit]]] = None,
    army_names: Optional[dict[int, str]] = None,
    use_floor95: bool = False,
) -> list[DuelResult]:
    """Lance le duel de `attacker` contre chaque unité défenseur sélectionnée.

    `defenders_by_army` et `army_names` permettent de fournir un cache pré-chargé
    pour éviter les requêtes DB par attaquant (utilisé par run_all_benchmarks).
    """
    results: list[DuelResult] = []
    if defenders_by_army is None or army_names is None:
        armies = repository.list_armies(con)
        defenders_by_army = {}
        army_names = {}
        for army in armies:
            if army.id is None:
                continue
            army_names[army.id] = army.name
            defenders_by_army[army.id] = repository.list_units_for_army(con, army.id)
    for army_id, defenders in defenders_by_army.items():
        army_name = army_names.get(army_id, "")
        if target_army and army_name != target_army:
            continue
        if exclude_army_id is not None and army_id == exclude_army_id:
            continue
        for defender in defenders:
            if defender.is_hero and not include_heroes:
                continue
            results.append(unit_duel(
                attacker, defender, army_name,
                attacker_reinforced=attacker_reinforced,
                defender_reinforced=defender_reinforced,
                options_a=options_a, options_b=options_b,
                use_floor95=use_floor95,
            ))
    return results



def save_results(
    con: duckdb.DuckDBPyConnection, results: list[DuelResult], *, floor95: bool = False,
) -> int:
    """Persiste une liste de DuelResult dans la table `unit_benchmark` (batch executemany)."""
    from datetime import datetime
    now = datetime.now()
    rows: list[tuple] = []
    for r in results:
        if r.attacker.id is None or r.defender.id is None:
            continue
        rows.append((
            r.attacker.id, r.defender.id,
            r.attacker_reinforced, r.defender_reinforced,
            r.options_a.charged, r.options_b.charged, floor95,
            r.raw_a_to_b, r.expected_a_to_b,
            r.raw_b_to_a, r.expected_b_to_a,
            r.pts_destroyed, r.pts_lost, r.pts_net, r.roi, now,
        ))
    repository.save_benchmark_results_many(con, rows)
    return len(rows)


@dataclass
class FullBenchmarkSummary:
    """Bilan d'un run global : nb d'attaquants traités et de duels écrits."""
    attackers: int = 0
    duels: int = 0


def run_all_benchmarks(
    con: duckdb.DuckDBPyConnection,
    *,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
    include_heroes: bool = False,
    progress: Optional[Callable[[str, str, int, int], None]] = None,
    use_floor95: bool = False,
) -> FullBenchmarkSummary:
    """Benchmarke chaque unité (non héros par défaut) contre toutes les autres armées.

    Les résultats sont persistés (upsert) dans `unit_benchmark`.
    `progress(attacker_name, army_name, idx, total)` est appelé avant chaque attaquant.
    `use_floor95` : cf. `unit_duel` — plancher 95% de confiance au lieu de l'espérance.
    """
    summary = FullBenchmarkSummary()
    armies = [a for a in repository.list_armies(con) if a.id is not None]
    army_names: dict[int, str] = {a.id: a.name for a in armies}  # type: ignore[misc]
    defenders_by_army = repository.load_all_units_with_weapons(con)
    all_attackers: list[tuple[Unit, int]] = []
    for army in armies:
        for unit in defenders_by_army.get(army.id, []):  # type: ignore[arg-type]
            if unit.is_hero and not include_heroes:
                continue
            all_attackers.append((unit, army.id))  # type: ignore[arg-type]

    total = len(all_attackers)
    for idx, (attacker, army_id) in enumerate(all_attackers, start=1):
        if progress is not None:
            progress(attacker.name, army_names.get(army_id, "?"), idx, total)
        results = benchmark_attacker(
            con, attacker,
            exclude_army_id=army_id,
            include_heroes=include_heroes,
            options_a=options_a, options_b=options_b,
            defenders_by_army=defenders_by_army,
            army_names=army_names,
            use_floor95=use_floor95,
        )
        summary.duels += save_results(con, results, floor95=use_floor95)
        summary.attackers += 1
    return summary

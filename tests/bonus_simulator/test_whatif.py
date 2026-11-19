"""Tests : classement combat×coût « what-if » d'une unité en mémoire (bonus)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.bonus_simulator import whatif
from aospy.bonus_simulator.bonus import StatDelta, apply_bonus
from aospy.orchestration import benchmark as bench
from aospy.persistence import db, repository, seed


@pytest.fixture()
def con(tmp_path: Path):
    connection = db.connect(tmp_path / "whatif.duckdb")
    seed.load_armies_from_json(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def con_with_benchmark(con):
    bench.run_all_benchmarks(
        con, include_heroes=True, mode_a="floor66", mode_b="mean", rules=whatif.RANKING_DUEL_RULES,
    )
    return con


def _liberators(con):
    sce = repository.get_army_by_name(con, "Stormcast Eternals")
    return repository.get_unit_by_name(con, sce.id, "Liberators")


def test_live_combat_row_matches_manual_benchmark(con):
    libs = _liberators(con)
    row = whatif.live_combat_row(con, libs)

    results = bench.benchmark_attacker(
        con, libs, exclude_army_id=libs.army_id, include_heroes=True,
        mode_a="floor66", mode_b="mean", rules=whatif.RANKING_DUEL_RULES,
    )
    manual_avg_roi = sum(r.roi for r in results) / len(results) * 100.0
    assert row.avg_roi_pct == pytest.approx(manual_avg_roi)
    assert row.avg_floor_roi_pct == pytest.approx(
        (row.roi_floor95_pct + row.roi_floor66_pct + row.roi_floor20_pct) / 3.0
    )


def test_live_combat_row_excludes_own_army(con):
    libs = _liberators(con)
    results = bench.benchmark_attacker(
        con, libs, exclude_army_id=libs.army_id, include_heroes=True,
        mode_a="floor66", mode_b="mean", rules=whatif.RANKING_DUEL_RULES,
    )
    assert all(r.defender_army_name != "Stormcast Eternals" for r in results)


def test_rank_against_pool_requires_populated_benchmark(con):
    libs = _liberators(con)
    with pytest.raises(ValueError):
        whatif.rank_against_pool(con, libs)


def test_rank_against_pool_target_appears_in_neighbors(con_with_benchmark):
    libs = _liberators(con_with_benchmark)
    result = whatif.rank_against_pool(con_with_benchmark, libs)
    assert 1 <= result.rank <= result.total
    targets = [n for n in result.neighbors if n.is_target]
    assert len(targets) == 1
    assert targets[0].rank == result.rank


def test_beneficial_bonus_improves_rank(con_with_benchmark):
    libs = _liberators(con_with_benchmark)
    before = whatif.rank_against_pool(con_with_benchmark, libs)

    buffed = apply_bonus(libs, StatDelta(wound=1, save=1))
    after = whatif.rank_against_pool(con_with_benchmark, buffed)

    # +1 pour blesser / +1 pour sauvegarder ne peut pas dégrader ni le ROI de
    # combat, ni le rang dans le pool troupe.
    assert after.combat.avg_floor_roi_pct >= before.combat.avg_floor_roi_pct
    assert after.rank <= before.rank


def test_bonus_unit_excluded_from_its_own_pool(con_with_benchmark):
    """La ligne hypothétique remplace l'entrée réelle de l'unité (même `unit_id`)
    plutôt que de s'y ajouter en double."""
    libs = _liberators(con_with_benchmark)
    buffed = apply_bonus(libs, StatDelta(wound=1))
    result = whatif.rank_against_pool(con_with_benchmark, buffed)
    names = [n.name for n in result.neighbors]
    assert names.count(libs.name) <= 1

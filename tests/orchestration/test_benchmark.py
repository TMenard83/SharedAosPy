"""Tests : duel et benchmark unité vs unité."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.orchestration import benchmark as bench
from aospy.persistence import db, repository, seed
from aospy.cli import main as cli_main
from aospy.engine.combat import CombatModifiers, expected_unit_damage
from aospy.cli.report import format_benchmark, format_benchmark_table, format_duel_detail
from aospy.orchestration.simulation import SideOptions


@pytest.fixture()
def con(tmp_path: Path):
    connection = db.connect(tmp_path / "bench.duckdb")
    seed.load_armies_from_json(connection)
    try:
        yield connection
    finally:
        connection.close()


def _pair(con):
    sce = repository.get_army_by_name(con, "Stormcast Eternals")
    sk = repository.get_army_by_name(con, "Skaven")
    libs = repository.get_unit_by_name(con, sce.id, "Liberators")
    clan = repository.get_unit_by_name(con, sk.id, "Clanrats")
    return libs, clan


def test_find_unit_unique(con):
    unit, army = bench.find_unit(con, "Liberators", None)
    assert army == "Stormcast Eternals"
    assert unit.name == "Liberators"


def test_find_unit_unknown_raises(con):
    with pytest.raises(ValueError):
        bench.find_unit(con, "Unknown Unit", None)


def test_find_unit_with_explicit_army(con):
    unit, army = bench.find_unit(con, "Clanrats", "Skaven")
    assert army == "Skaven"
    assert unit.name == "Clanrats"


def test_unit_duel_matches_combat_math(con):
    libs, clan = _pair(con)
    result = bench.unit_duel(
        libs, clan, "Skaven",
        options_a=SideOptions(charged=False),
        options_b=SideOptions(charged=False),
    )
    expected = expected_unit_damage(libs, libs.models, clan, CombatModifiers())
    assert result.raw_a_to_b == pytest.approx(expected)
    assert result.expected_a_to_b == pytest.approx(min(expected, clan.models * clan.health))


def test_unit_duel_capped_by_hp(con):
    libs, clan = _pair(con)
    r = bench.unit_duel(libs, clan, "Skaven")
    assert r.expected_a_to_b <= r.defender_total_hp + 1e-9
    assert r.expected_b_to_a <= r.attacker_total_hp + 1e-9


def test_unit_duel_charge_has_no_universal_bonus(con):
    # AoS4 : pas de bonus universel de charge. Les Liberators n'ont aucun texte
    # d'arme "Charge (+N <Stat>)", donc charger ne change rien à leurs dégâts.
    libs, clan = _pair(con)
    no_charge = bench.unit_duel(
        libs, clan, "Skaven",
        options_a=SideOptions(charged=False),
        options_b=SideOptions(charged=False),
    )
    with_charge = bench.unit_duel(
        libs, clan, "Skaven",
        options_a=SideOptions(charged=True),
        options_b=SideOptions(charged=False),
    )
    assert with_charge.raw_a_to_b == pytest.approx(no_charge.raw_a_to_b)


def test_unit_duel_aod_reduces_incoming(con):
    libs, clan = _pair(con)
    base = bench.unit_duel(libs, clan, "Skaven")
    aod = bench.unit_duel(
        libs, clan, "Skaven",
        options_b=SideOptions(charged=False, all_out_defense=True),
    )
    assert aod.expected_a_to_b <= base.expected_a_to_b


def test_pts_net_and_roi_consistency(con):
    libs, clan = _pair(con)
    r = bench.unit_duel(libs, clan, "Skaven")
    expected_pts_dest = r.expected_a_to_b / r.defender_total_hp * clan.points
    expected_pts_lost = r.expected_b_to_a / r.attacker_total_hp * libs.points
    assert r.pts_destroyed == pytest.approx(expected_pts_dest)
    assert r.pts_lost == pytest.approx(expected_pts_lost)
    assert r.pts_net == pytest.approx(r.pts_destroyed - r.pts_lost)
    assert r.roi == pytest.approx(r.pts_net / libs.points)


def test_benchmark_table_contains_pts_net_columns(con):
    libs, _ = _pair(con)
    results = bench.benchmark_attacker(con, libs, target_army="Skaven")
    text = format_benchmark_table(results, sort_by="pts-net")
    assert "Pts net" in text
    assert "ROI" in text


def test_unit_duel_reinforced_scales(con):
    libs, clan = _pair(con)
    base = bench.unit_duel(libs, clan, "Skaven")
    reinf = bench.unit_duel(libs, clan, "Skaven", defender_reinforced=True)
    assert reinf.defender_total_hp == 2 * base.defender_total_hp
    assert reinf.raw_b_to_a > base.raw_b_to_a


def test_benchmark_attacker_filters_heroes(con):
    libs, _ = _pair(con)
    results = bench.benchmark_attacker(con, libs, include_heroes=False)
    assert all(not r.defender.is_hero for r in results)


def test_benchmark_attacker_excludes_self_army(con):
    libs, _ = _pair(con)
    sce = repository.get_army_by_name(con, "Stormcast Eternals")
    results = bench.benchmark_attacker(con, libs, exclude_army_id=sce.id)
    assert all(r.defender_army_name != "Stormcast Eternals" for r in results)


def test_benchmark_attacker_target_army_only(con):
    libs, _ = _pair(con)
    results = bench.benchmark_attacker(con, libs, target_army="Skaven")
    assert results
    assert all(r.defender_army_name == "Skaven" for r in results)


def test_format_benchmark_outputs_table_headers(con):
    libs, _ = _pair(con)
    results = bench.benchmark_attacker(con, libs, target_army="Skaven")
    text = format_benchmark(
        "Liberators [SCE]", results,
        SideOptions(charged=False), SideOptions(charged=False),
    )
    assert "Benchmark" in text
    assert "Défenseur" in text
    assert "Pts net" in text
    assert "ROI" in text


def test_format_duel_detail_contains_units(con):
    libs, clan = _pair(con)
    r = bench.unit_duel(libs, clan, "Skaven")
    text = format_duel_detail(r)
    assert "Liberators" in text
    assert "Clanrats" in text
    assert "Skaven" in text


def test_cli_unit_duel_end_to_end(tmp_path: Path, capsys):
    dbp = tmp_path / "cli.duckdb"
    cli_main(["--db", str(dbp), "init"])
    capsys.readouterr()
    rc = cli_main([
        "--db", str(dbp), "unit", "duel",
        "--attacker", "Liberators", "--defender", "Clanrats",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Liberators" in out and "Clanrats" in out


def test_cli_unit_benchmark_end_to_end(tmp_path: Path, capsys):
    dbp = tmp_path / "cli.duckdb"
    cli_main(["--db", str(dbp), "init"])
    capsys.readouterr()
    rc = cli_main([
        "--db", str(dbp), "unit", "benchmark",
        "--attacker", "Liberators", "--vs-army", "Skaven",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Benchmark" in out

"""Tests d'intégration : simulation de bataille de bout en bout."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.persistence import db, repository, seed
from aospy.cli import main as cli_main
from aospy.cli.report import format_report
from aospy.orchestration.simulation import SideOptions, simulate_battle


@pytest.fixture()
def con(tmp_path: Path):
    connection = db.connect(tmp_path / "sim.duckdb")
    seed.load_armies_from_json(connection)
    seed.load_compositions_from_json(connection)
    try:
        yield connection
    finally:
        connection.close()


def _comp_ids(con) -> tuple[int, int]:
    comps = repository.list_compositions(con, kind="tournament")
    a = next(c for c in comps if "Stormcast" in c.name)
    b = next(c for c in comps if "Skaven" in c.name)
    return a.id, b.id


def test_simulate_battle_returns_full_matrix(con):
    a_id, b_id = _comp_ids(con)
    a = repository.get_composition(con, a_id)
    b = repository.get_composition(con, b_id)
    report = simulate_battle(con, a_id, b_id)

    expected_pairs_a = len(a.entries) * len(b.entries)
    assert len(report.a_to_b.pairs) == expected_pairs_a
    assert len(report.b_to_a.pairs) == len(b.entries) * len(a.entries)


def test_expected_damage_capped_by_defender_hp(con):
    a_id, b_id = _comp_ids(con)
    report = simulate_battle(con, a_id, b_id)
    for pr in report.a_to_b.pairs + report.b_to_a.pairs:
        assert pr.expected_damage <= pr.defender_total_hp + 1e-9
        assert pr.expected_models_killed >= 0
        assert pr.raw_damage >= pr.expected_damage - 1e-9


def test_charge_has_no_universal_bonus(con):
    # AoS4 : pas de bonus universel de charge. La composition de test n'a aucun
    # texte d'arme "Charge (+N <Stat>)", donc charger ne change rien aux dégâts.
    a_id, b_id = _comp_ids(con)
    no_charge = simulate_battle(
        con, a_id, b_id,
        SideOptions(charged=False), SideOptions(charged=False),
    )
    with_charge = simulate_battle(
        con, a_id, b_id,
        SideOptions(charged=True), SideOptions(charged=False),
    )
    assert with_charge.a_to_b.best_target_total == pytest.approx(no_charge.a_to_b.best_target_total)


def test_aod_reduces_incoming_damage(con):
    a_id, b_id = _comp_ids(con)
    base = simulate_battle(con, a_id, b_id, SideOptions(), SideOptions())
    b_defends = simulate_battle(
        con, a_id, b_id, SideOptions(), SideOptions(all_out_defense=True),
    )
    assert b_defends.a_to_b.best_target_total <= base.a_to_b.best_target_total


def test_format_report_contains_key_sections(con):
    a_id, b_id = _comp_ids(con)
    report = simulate_battle(con, a_id, b_id)
    text = format_report(report)
    assert "Bataille" in text
    assert "A → B" in text
    assert "B → A" in text
    assert "Synthèse" in text
    assert "Net (A − B)" in text


def test_cli_battle_simulate_end_to_end(tmp_path: Path, capsys):
    dbp = tmp_path / "cli_sim.duckdb"
    cli_main(["--db", str(dbp), "init"])
    capsys.readouterr()
    rc = cli_main([
        "--db", str(dbp), "battle", "simulate",
        "--a", "1", "--b", "2", "--charge", "both",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Bataille" in out
    assert "Synthèse" in out


def test_simulate_unknown_composition_raises(con):
    with pytest.raises(ValueError):
        simulate_battle(con, 9999, 1)

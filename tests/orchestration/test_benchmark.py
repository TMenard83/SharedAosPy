"""Tests : duel et benchmark unité vs unité."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.domain.models import Unit, Weapon
from aospy.orchestration import benchmark as bench
from aospy.persistence import db, repository, seed
from aospy.cli import main as cli_main
from aospy.engine.combat import CombatModifiers, RANGED_DOUBLE_MULT, expected_unit_damage
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


def test_unit_duel_default_mode_is_mean(con):
    libs, clan = _pair(con)
    r = bench.unit_duel(libs, clan, "Skaven")
    assert r.mode_a == "mean"
    assert r.mode_b == "mean"


def test_unit_duel_asymmetric_modes(con):
    # A→B au plancher pessimiste 80%, B→A à la moyenne : la lecture peut différer
    # par sens du duel (pas de symétrie imposée par unit_duel).
    libs, clan = _pair(con)
    mean_result = bench.unit_duel(libs, clan, "Skaven")
    asym = bench.unit_duel(libs, clan, "Skaven", mode_a="floor80", mode_b="mean")
    assert asym.mode_a == "floor80"
    assert asym.mode_b == "mean"
    assert asym.raw_a_to_b <= mean_result.raw_a_to_b
    assert asym.raw_b_to_a == pytest.approx(mean_result.raw_b_to_a)


def test_unit_duel_floor66_less_pessimistic_than_floor80(con):
    libs, clan = _pair(con)
    floor66 = bench.unit_duel(libs, clan, "Skaven", mode_a="floor66", mode_b="mean")
    floor80 = bench.unit_duel(libs, clan, "Skaven", mode_a="floor80", mode_b="mean")
    assert floor66.mode_a == "floor66"
    assert floor66.raw_a_to_b >= floor80.raw_a_to_b


def test_benchmark_attacker_propagates_modes(con):
    libs, _ = _pair(con)
    results = bench.benchmark_attacker(
        con, libs, target_army="Skaven", mode_a="floor80", mode_b="floor95",
    )
    assert results
    assert all(r.mode_a == "floor80" and r.mode_b == "floor95" for r in results)


def test_save_results_persists_modes_and_coexists(con):
    libs, clan = _pair(con)
    mean_result = bench.unit_duel(libs, clan, "Skaven")
    floor_result = bench.unit_duel(libs, clan, "Skaven", mode_a="floor80", mode_b="mean")
    bench.save_results(con, [mean_result, floor_result])
    rows = con.execute(
        "SELECT attacker_mode, defender_mode, raw_a_to_b FROM unit_benchmark "
        "WHERE attacker_id = ? AND defender_id = ? ORDER BY attacker_mode",
        [libs.id, clan.id],
    ).fetchall()
    assert rows == [
        ("floor80", "mean", pytest.approx(floor_result.raw_a_to_b)),
        ("mean", "mean", pytest.approx(mean_result.raw_a_to_b)),
    ]


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


def test_cli_unit_duel_asymmetric_modes_end_to_end(tmp_path: Path, capsys):
    dbp = tmp_path / "cli.duckdb"
    cli_main(["--db", str(dbp), "init"])
    capsys.readouterr()
    rc = cli_main([
        "--db", str(dbp), "unit", "duel",
        "--attacker", "Liberators", "--defender", "Clanrats",
        "--attacker-mode", "floor80", "--defender-mode", "mean",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "plancher 80%" in out
    assert "moyenne" in out


def test_cli_unit_benchmark_all_persists_modes(tmp_path: Path, capsys):
    dbp = tmp_path / "cli.duckdb"
    cli_main(["--db", str(dbp), "init"])
    capsys.readouterr()
    rc = cli_main([
        "--db", str(dbp), "unit", "benchmark-all",
        "--attacker-mode", "floor80", "--defender-mode", "mean",
    ])
    capsys.readouterr()
    assert rc == 0
    con = db.connect(dbp)
    try:
        row = con.execute(
            "SELECT DISTINCT attacker_mode, defender_mode FROM unit_benchmark"
        ).fetchall()
        assert row == [("floor80", "mean")]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Règles optionnelles (DuelRules) : tir double + seuil de charge à 30% de Move
# --------------------------------------------------------------------------- #

def _melee_unit(name, move, save=7, weapons=None, models=1):
    return Unit(
        name=name, army_id=1, move=move, save=save, health=1, control=1,
        models=models, points=100, weapons=weapons or [],
    )


def test_duel_rules_default_does_not_change_behavior():
    # DuelRules() désactivées par défaut : aucun changement vs sans `rules`.
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1, range_in=18)
    charge_weapon = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                           abilities="Charge (+1 Damage)")
    attacker = _melee_unit("A", move=8, weapons=[charge_weapon])
    defender = _melee_unit("B", move=4, weapons=[ranged])
    without_rules = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
    )
    with_default_rules = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
        rules=bench.DuelRules(),
    )
    assert with_default_rules.raw_a_to_b == pytest.approx(without_rules.raw_a_to_b)
    assert with_default_rules.raw_b_to_a == pytest.approx(without_rules.raw_b_to_a)


def test_charge_move_threshold_disables_charge_bonus_below_30_percent():
    weapon = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Charge (+1 Damage)")
    # Move 6 vs Move 5 : 6 n'est pas > 5*1.3=6.5 → bonus neutralisé.
    attacker = _melee_unit("A", move=6, weapons=[weapon])
    defender = _melee_unit("B", move=5)
    result = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
        rules=bench.DuelRules(charge_move_threshold=True),
    )
    no_rule = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=False), options_b=SideOptions(charged=False),
    )
    assert result.raw_a_to_b == pytest.approx(no_rule.raw_a_to_b)


def test_charge_move_threshold_keeps_charge_bonus_above_30_percent():
    weapon = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Charge (+1 Damage)")
    # Move 8 vs Move 5 : 8 > 5*1.3=6.5 → bonus conservé.
    attacker = _melee_unit("A", move=8, weapons=[weapon])
    defender = _melee_unit("B", move=5)
    result = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
        rules=bench.DuelRules(charge_move_threshold=True),
    )
    charged_no_rule = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
    )
    assert result.raw_a_to_b == pytest.approx(charged_no_rule.raw_a_to_b)


def test_charge_move_threshold_triggers_without_charge_flag():
    # --charge none (options_a.charged=False) : la règle active détermine
    # quand même l'état chargé toute seule, à partir du seul écart de Move.
    weapon = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Charge (+1 Damage)")
    attacker = _melee_unit("A", move=8, weapons=[weapon])
    defender = _melee_unit("B", move=5)
    result = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=False), options_b=SideOptions(charged=False),
        rules=bench.DuelRules(charge_move_threshold=True),
    )
    charged_no_rule = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
    )
    assert result.raw_a_to_b == pytest.approx(charged_no_rule.raw_a_to_b)


def test_charge_move_threshold_cancels_charge_flag_when_below_threshold():
    # --charge a (options_a.charged=True) : la règle active peut désormais
    # aussi ANNULER une charge déclarée si l'écart de Move est insuffisant.
    weapon = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Charge (+1 Damage)")
    attacker = _melee_unit("A", move=6, weapons=[weapon])
    defender = _melee_unit("B", move=5)
    result = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=False),
        rules=bench.DuelRules(charge_move_threshold=True),
    )
    no_charge_no_rule = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=False), options_b=SideOptions(charged=False),
    )
    assert result.raw_a_to_b == pytest.approx(no_charge_no_rule.raw_a_to_b)


def test_double_shoot_triggers_when_reach_below_defender_range():
    # A n'a pas d'arme ranged (portée 0), B a un tireur de portée 18 : A est
    # déduit chargeur (plus petite portée) sans avoir besoin de --charge.
    # reach(A) = Move 4 + charge_dist défaut 7 = 11 < 18 → B tire deux fois sur A.
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1, range_in=18)
    attacker = _melee_unit("A", move=4)
    defender = _melee_unit("B", move=5, weapons=[ranged])
    base = bench.unit_duel(attacker, defender, "B-army")
    doubled = bench.unit_duel(
        attacker, defender, "B-army", rules=bench.DuelRules(double_shoot=True),
    )
    assert doubled.raw_b_to_a == pytest.approx(RANGED_DOUBLE_MULT * base.raw_b_to_a)
    assert doubled.raw_a_to_b == pytest.approx(base.raw_a_to_b)  # A n'a pas d'arme ranged


def test_double_shoot_inactive_when_reach_covers_defender_range():
    # reach = 4 + 7 = 11 > portée 10 : A (chargeur déduit) peut couvrir la
    # distance, pas de tir double — sans aucun --charge non plus.
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1, range_in=10)
    attacker = _melee_unit("A", move=4)
    defender = _melee_unit("B", move=5, weapons=[ranged])
    base = bench.unit_duel(attacker, defender, "B-army")
    result = bench.unit_duel(
        attacker, defender, "B-army", rules=bench.DuelRules(double_shoot=True),
    )
    assert result.raw_b_to_a == pytest.approx(base.raw_b_to_a)


def test_double_shoot_ran_and_charged_extends_reach():
    # portée 12 : sans course+charge reach=11 < 12 → tir double ; avec course
    # (ran_and_charged côté A, +3.5) reach=14.5 >= 12 → plus de tir double.
    # A est déduit chargeur (portée 0 < 12), donc c'est bien options_a qui compte.
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1, range_in=12)
    attacker = _melee_unit("A", move=4)
    defender = _melee_unit("B", move=5, weapons=[ranged])
    base = bench.unit_duel(attacker, defender, "B-army")
    without_run = bench.unit_duel(
        attacker, defender, "B-army", rules=bench.DuelRules(double_shoot=True),
    )
    with_run = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(ran_and_charged=True),
        rules=bench.DuelRules(double_shoot=True),
    )
    assert without_run.raw_b_to_a == pytest.approx(RANGED_DOUBLE_MULT * base.raw_b_to_a)
    assert with_run.raw_b_to_a == pytest.approx(base.raw_b_to_a)


def test_double_shoot_only_doubles_ranged_profile_not_melee():
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1, range_in=18)
    melee = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1)
    attacker = _melee_unit("A", move=4)
    defender = _melee_unit("B", move=5, weapons=[ranged, melee])
    base = bench.unit_duel(attacker, defender, "B-army")
    doubled = bench.unit_duel(
        attacker, defender, "B-army", rules=bench.DuelRules(double_shoot=True),
    )
    # seul le profil ranged double, le profil melee reste identique
    assert doubled.raw_b_to_a < 2 * base.raw_b_to_a
    assert doubled.raw_b_to_a > base.raw_b_to_a


def test_double_shoot_does_not_need_charge_flag_at_all():
    # Le camp chargeur est déduit des portées, pas de --charge : même résultat
    # que --charge a/b/both/none n'ait aucune incidence sur ce calcul.
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1, range_in=18)
    attacker = _melee_unit("A", move=4)
    defender = _melee_unit("B", move=5, weapons=[ranged])
    rules = bench.DuelRules(double_shoot=True)
    none_charged = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=False), options_b=SideOptions(charged=False),
        rules=rules,
    )
    both_charged = bench.unit_duel(
        attacker, defender, "B-army",
        options_a=SideOptions(charged=True), options_b=SideOptions(charged=True),
        rules=rules,
    )
    assert none_charged.raw_b_to_a == pytest.approx(both_charged.raw_b_to_a)


def test_double_shoot_inactive_when_ranges_tied():
    # Portées égales (y compris 0-0, mêlée pure des deux côtés) : aucun camp
    # n'est désigné chargeur par ce critère, la règle ne s'applique pas.
    melee_a = Weapon(name="ma", kind="melee", attacks=2, hit=4, wound=4, damage=1)
    melee_b = Weapon(name="mb", kind="melee", attacks=2, hit=4, wound=4, damage=1)
    attacker = _melee_unit("A", move=4, weapons=[melee_a])
    defender = _melee_unit("B", move=4, weapons=[melee_b])
    base = bench.unit_duel(attacker, defender, "B-army")
    result = bench.unit_duel(
        attacker, defender, "B-army", rules=bench.DuelRules(double_shoot=True),
    )
    assert result.raw_a_to_b == pytest.approx(base.raw_a_to_b)
    assert result.raw_b_to_a == pytest.approx(base.raw_b_to_a)


def test_cli_unit_duel_optional_rules_flags_parse_and_report(tmp_path: Path, capsys):
    dbp = tmp_path / "cli.duckdb"
    cli_main(["--db", str(dbp), "init"])
    capsys.readouterr()
    rc = cli_main([
        "--db", str(dbp), "unit", "duel",
        "--attacker", "Liberators", "--defender", "Clanrats",
        "--charge", "a", "--rule-double-shoot", "--rule-charge-threshold",
        "--ran-and-charged", "a",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Règles optionnelles" in out
    assert "tir double" in out
    assert "seuil de charge 30%" in out

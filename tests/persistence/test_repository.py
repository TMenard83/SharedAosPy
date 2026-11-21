"""Tests Phase 1 : schéma + CRUD armées/unités/armes + seed JSON."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.domain.models import Army, Unit, Weapon
from aospy.persistence import db, repository, seed


@pytest.fixture()
def con(tmp_path: Path):
    connection = db.connect(tmp_path / "test.duckdb")
    try:
        yield connection
    finally:
        connection.close()


def test_add_and_get_army(con):
    army_id = repository.add_army(con, Army(name="Sylvaneth", grand_alliance="Order"))
    fetched = repository.get_army_by_name(con, "Sylvaneth")
    assert fetched is not None
    assert fetched.id == army_id
    assert fetched.grand_alliance == "Order"


def test_add_unit_with_weapons(con):
    army_id = repository.add_army(con, Army(name="Nighthaunt", grand_alliance="Death"))
    unit = Unit(
        name="Chainrasps", army_id=army_id,
        move=6, save=6, health=1, control=1,
        models=10, points=120, is_hero=False, ward=5,
        weapons=[
            Weapon(name="Malignant Weapon", kind="melee",
                   attacks=2, hit=4, wound=4, rend=0, damage=1),
            Weapon(name="Companion Blade", kind="melee",
                   attacks=1, hit=4, wound=4, rend=0, damage=1, is_companion=True),
        ],
    )
    unit_id = repository.add_unit(con, unit)
    got = repository.get_unit(con, unit_id)
    assert got is not None
    assert got.name == "Chainrasps"
    assert got.ward == 5
    assert len(got.weapons) == 2
    by_name = {w.name: w for w in got.weapons}
    assert by_name["Malignant Weapon"].kind == "melee"
    assert by_name["Malignant Weapon"].is_companion is False
    assert by_name["Companion Blade"].is_companion is True


def test_load_armies_from_json(con):
    ids = seed.load_armies_from_json(con)  # utilise data/json/armies.json par défaut
    assert "Stormcast Eternals" in ids
    assert "Skaven" in ids

    stormcast = repository.get_army_by_name(con, "Stormcast Eternals")
    assert stormcast is not None and stormcast.id is not None
    units = repository.list_units_for_army(con, stormcast.id)
    names = {u.name for u in units}
    assert {"Liberators", "Annihilators", "Lord-Imperatant"} <= names

    libs = next(u for u in units if u.name == "Liberators")
    assert libs.save == 3 and libs.health == 2 and libs.points == 110
    assert any(w.name == "Warhammer" for w in libs.weapons)


def test_seed_is_idempotent(con):
    seed.load_armies_from_json(con)
    seed.load_armies_from_json(con)
    armies = repository.list_armies(con)
    names = [a.name for a in armies]
    assert names.count("Stormcast Eternals") == 1
    assert names.count("Skaven") == 1


def test_get_ranking_pool_columns_and_filters(con):
    """Le pool lu en direct par les registres (`reports/combat_report.py`,
    `best_report.py`) et `bonus_simulator/whatif.py` : une ligne par attaquant,
    seulement le scénario sans charge, attaquant floor66 / défenseur mean."""
    army_id = repository.add_army(con, Army(name="Nighthaunt", grand_alliance="Death"))
    ids = [
        repository.add_unit(con, Unit(name=n, army_id=army_id, move=6, save=6, health=1, control=1,
                                      models=10, points=100, is_hero=False))
        for n in ("A", "B", "C")
    ]

    def duel(defender, roi, *, charged=False, mode="floor66"):
        repository.save_benchmark_result(
            con, attacker_id=ids[0], defender_id=defender,
            attacker_reinforced=False, defender_reinforced=False,
            attacker_charged=charged, defender_charged=False,
            attacker_mode=mode, defender_mode="mean",
            raw_a_to_b=0.0, expected_a_to_b=0.0, raw_b_to_a=0.0, expected_b_to_a=0.0,
            pts_destroyed=0.0, pts_lost=0.0, pts_net=roi * 10, roi=roi,
        )

    duel(ids[1], 0.5)
    duel(ids[2], -0.1)
    duel(ids[2], 9.0, charged=True)   # autre scénario : ignoré
    duel(ids[1], 9.0, mode="mean")    # autre mode : ignoré

    pool = repository.get_ranking_pool(con)
    assert len(pool) == 1
    row = pool[0]
    assert list(row) == [
        "unit_id", "name", "army", "grand_alliance", "points", "is_hero",
        "avg_roi_pct", "avg_pts_net", "pct_positive",
        "roi_floor95_pct", "roi_floor66_pct", "roi_floor20_pct", "avg_floor_roi_pct",
    ]
    assert row["unit_id"] == ids[0]
    assert row["avg_roi_pct"] == pytest.approx(20.0)
    assert row["avg_pts_net"] == pytest.approx(2.0)
    assert row["pct_positive"] == pytest.approx(50.0)
    assert row["avg_floor_roi_pct"] == pytest.approx(
        (row["roi_floor95_pct"] + row["roi_floor66_pct"] + row["roi_floor20_pct"]) / 3.0
    )

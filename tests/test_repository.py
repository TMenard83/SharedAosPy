"""Tests Phase 1 : schéma + CRUD armées/unités/armes + seed JSON."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy import db, repository, seed
from aospy.models import Army, Unit, Weapon


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
        ],
    )
    unit_id = repository.add_unit(con, unit)
    got = repository.get_unit(con, unit_id)
    assert got is not None
    assert got.name == "Chainrasps"
    assert got.ward == 5
    assert len(got.weapons) == 1
    assert got.weapons[0].kind == "melee"


def test_load_armies_from_json(con):
    ids = seed.load_armies_from_json(con)  # utilise data/armies.json par défaut
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

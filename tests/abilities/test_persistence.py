"""Aller-retour DuckDB des tables ability* et vue unit_ability."""

from __future__ import annotations

from dataclasses import replace

from aospy.abilities.models import AbilityOwner
from aospy.abilities.pipeline import analyze_one, to_rows
from aospy.domain.models import Army, Unit
from aospy.persistence import db, repository

from .test_extract import _raw


def test_round_trip_search_and_unit_view(tmp_path):
    con = db.connect(tmp_path / "t.duckdb")
    owner = AbilityOwner("SE", "Stormcast Eternals", "warscroll", "Liberators", "w1")
    raw = replace(_raw("This unit has WARD (5+)."), uid="u1", name="Shield's Grace", owners=(owner,))
    raw2 = replace(_raw("Add 1 to run rolls for this unit."), uid="u2", name="Quick", owners=(owner,))
    repository.replace_ability_analyses(con, *to_rows([analyze_one(raw), analyze_one(raw2)]))

    rows = repository.search_abilities(con, faction="SE", tags=["protection"])
    assert [r["name"] for r in rows] == ["Shield's Grace"]
    assert rows[0]["owners"] == "Liberators" and "fiable" in rows[0]["tags"]
    assert repository.search_abilities(con, verdict="anecdotique")[0]["uid"] == "u2"

    army_id = repository.add_army(con, Army(name="Stormcast Eternals", grand_alliance="Order"))
    repository.add_unit(con, Unit(army_id=army_id, name="Liberators", move=5, save=3, control=1,
                                  health=2, models=5, points=100))
    view = con.execute("SELECT unit_name, name FROM unit_ability ORDER BY name").fetchall()
    assert view == [("Liberators", "Quick"), ("Liberators", "Shield's Grace")]

    # reconstruction complète : pas de doublons
    repository.replace_ability_analyses(con, *to_rows([analyze_one(raw)]))
    assert con.execute("SELECT count(*) FROM ability").fetchone()[0] == 1
    con.close()

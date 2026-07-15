"""Tests Phase 2 : traits héroïques, artefacts, compositions de tournoi."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.persistence import db, repository, seed
from aospy.domain.models import Artefact, Composition, CompositionUnit, HeroicTrait


@pytest.fixture()
def con(tmp_path: Path):
    connection = db.connect(tmp_path / "test.duckdb")
    seed.load_armies_from_json(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_heroic_traits_and_artefacts_seeded(con):
    stormcast = repository.get_army_by_name(con, "Stormcast Eternals")
    assert stormcast is not None and stormcast.id is not None
    traits = repository.list_heroic_traits(con, stormcast.id)
    artefacts = repository.list_artefacts(con, stormcast.id)
    assert {t.name for t in traits} >= {"Heroic Stature", "Lightning Reflexes"}
    assert {a.name for a in artefacts} >= {"Amulet of Destiny", "Arcane Tome"}


def test_add_custom_trait_and_artefact(con):
    sk = repository.get_army_by_name(con, "Skaven")
    assert sk is not None and sk.id is not None
    repository.add_heroic_trait(con, HeroicTrait(army_id=sk.id, name="Test Trait"))
    repository.add_artefact(con, Artefact(army_id=sk.id, name="Test Artefact"))
    assert repository.get_heroic_trait_by_name(con, sk.id, "Test Trait") is not None
    assert repository.get_artefact_by_name(con, sk.id, "Test Artefact") is not None


def test_add_composition_computes_total_points(con):
    sk = repository.get_army_by_name(con, "Skaven")
    assert sk is not None and sk.id is not None
    units = {u.name: u for u in repository.list_units_for_army(con, sk.id)}

    comp = Composition(
        army_id=sk.id, name="Skaven Test", kind="custom", format_points=1000,
        entries=[
            CompositionUnit(unit_id=units["Grey Seer"].id, is_general=True),
            CompositionUnit(unit_id=units["Clanrats"].id, reinforced=True),
            CompositionUnit(unit_id=units["Stormvermin"].id, reinforced=False),
        ],
    )
    comp_id = repository.add_composition(con, comp)

    fetched = repository.get_composition(con, comp_id)
    assert fetched is not None
    # 140 (Grey Seer) + 2*120 (Clanrats renforcé) + 130 (Stormvermin) = 510
    assert fetched.total_points == 140 + 2 * 120 + 130
    assert len(fetched.entries) == 3
    assert any(e.is_general for e in fetched.entries)


def test_load_compositions_from_json(con):
    ids = seed.load_compositions_from_json(con)
    assert "Stormcast - GT Top 2025-Q1 (fictif)" in ids
    assert "Skaven - Open 2025 Hordes (fictif)" in ids

    sc = repository.get_army_by_name(con, "Stormcast Eternals")
    assert sc is not None and sc.id is not None
    comps = repository.list_compositions(con, army_id=sc.id, kind="tournament")
    assert len(comps) == 1
    comp = comps[0]
    # 130 (Lord-Imperatant) + 2*110 (Lib renf) + 110 (Lib) + 180 + 180 = 820
    assert comp.total_points == 130 + 2 * 110 + 110 + 180 + 180

    general_entry = next(e for e in comp.entries if e.is_general)
    assert general_entry.heroic_trait_id is not None
    assert general_entry.artefact_id is not None


def test_load_compositions_is_idempotent(con):
    seed.load_compositions_from_json(con)
    seed.load_compositions_from_json(con)
    all_comps = repository.list_compositions(con)
    names = [c.name for c in all_comps]
    assert names.count("Stormcast - GT Top 2025-Q1 (fictif)") == 1


def test_list_compositions_filter_by_kind(con):
    seed.load_compositions_from_json(con)
    sk = repository.get_army_by_name(con, "Skaven")
    assert sk is not None and sk.id is not None
    # Ajout d'une composition custom à côté
    units = {u.name: u for u in repository.list_units_for_army(con, sk.id)}
    repository.add_composition(con, Composition(
        army_id=sk.id, name="Skaven Custom Probe", kind="custom",
        format_points=1000,
        entries=[CompositionUnit(unit_id=units["Clanrats"].id)],
    ))

    tournament = repository.list_compositions(con, kind="tournament")
    custom = repository.list_compositions(con, kind="custom")
    assert all(c.kind == "tournament" for c in tournament)
    assert any(c.name == "Skaven Custom Probe" for c in custom)

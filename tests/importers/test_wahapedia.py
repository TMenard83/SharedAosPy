"""Tests de l'import Wahapedia (parsers + dédoublonnage + import de bout en bout)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy.persistence import db, repository
from aospy.importers.wahapedia import (
    INGESTIBLE_ROLES,
    _canonical_ids,
    _legends_warscroll_ids,
    _parse_unit,
    _parse_weapon,
    import_faction,
)

WARSCROLLS_HEADER = (
    "id|name|faction_id|source_id|legend|regiment_options|notes|description|role|"
    "virtual|no_reinforced|link|Move|Save|Control|Health|Ward|UnitSize|Cost|"
)
WEAPONS_HEADER = "warscroll_id|line|name|Rng|Atk|Hit|Wnd|Rnd|Dmg|type|abilities|has_battle_damage|"
KEYWORDS_HEADER = "warscroll_id|keyword|is_faction_keyword|parameter|"
SOURCE_HEADER = "id|name|type|edition|version|errata_date|errata_link|"
FACTIONS_HEADER = "id|name|link|"


@pytest.fixture()
def con(tmp_path: Path):
    connection = db.connect(tmp_path / "test.duckdb")
    try:
        yield connection
    finally:
        connection.close()


def _write(data_dir: Path, name: str, header: str, rows: list[str]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / name).write_text("\n".join([header, *rows]) + "\n", encoding="utf-8-sig")


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wahapedia"
    _write(d, "Factions.csv", FACTIONS_HEADER, ["BoC|Beasts of Chaos|http://example.com|"])
    _write(d, "Source.csv", SOURCE_HEADER, [
        "S1|Core Book|Rulebook|4|||",
        "S2|Warhammer Legends|Legends||||",
    ])
    _write(d, "Warscrolls.csv", WARSCROLLS_HEADER, [
        # Unité normale, canonique, ingestible (Monster + HERO)
        'W1|Gorbeast|BoC|S1|||||Monster|false|false||8"|3+|3|12||1|380|',
        # Exclue : source Legends
        'W2|OldBeast|BoC|S2|||||Monster|false|false||6"|4+|1|5||1|120|',
        # Exclue : rôle non-combat (Endless Spell)
        'W3|SpellThing|BoC|S1|||||Endless Spell|false|false||0"|-|0|3||1|60|',
        # Coquille virtuelle d'une unité "Gors" (dominée par W5)
        "W4|Gors|BoC|S1|||||Infantry|true|false||||||||",
        # Version canonique de "Gors"
        'W5|Gors|BoC|S1|||||Infantry|false|false||6"|5+|1|1||10|100|',
        # Autre faction : doit être ignorée par le filtre faction_id
        'W6|OtherFactionUnit|OTHER|S1|||||Infantry|false|false||6"|4+|1|1||5|100|',
    ])
    _write(d, "Warscrolls_weapons.csv", WEAPONS_HEADER, [
        "W1|1|Massive Maw|-|3|3+|3+|1|3|MELEE||false|",
        "W5|1|Beast-thorn Club|-|1|4+|4+|-|1|MELEE||false|",
    ])
    _write(d, "Warscrolls_keywords.csv", KEYWORDS_HEADER, [
        "W1|MONSTER|false||",
        "W1|HERO|false||",
        "W5|INFANTRY|false||",
    ])
    return d


def test_legends_warscroll_ids_flags_legends_source(data_dir: Path):
    assert _legends_warscroll_ids(data_dir) == {"W2"}


def test_canonical_ids_drops_virtual_shell_dominated_by_real_sibling():
    ws = [
        {"faction_id": "BoC", "name": "Gors", "virtual": "true", "role": "Infantry", "Cost": ""},
        {"faction_id": "BoC", "name": "Gors", "virtual": "false", "role": "Infantry", "Cost": "100"},
    ]
    ids = {"gors-shell": ws[0], "gors-real": ws[1]}
    for key, row in ids.items():
        row["id"] = key
    assert _canonical_ids(list(ids.values())) == {"gors-real"}


def test_canonical_ids_keeps_both_when_costs_distinct():
    # Deux variantes légitimes (ex. tailles ×5/×10), toutes deux virtual=false.
    a = {"id": "a", "faction_id": "BoC", "name": "Gutter Runners", "virtual": "false",
         "role": "Infantry", "Cost": "110"}
    b = {"id": "b", "faction_id": "BoC", "name": "Gutter Runners", "virtual": "false",
         "role": "Infantry", "Cost": "160"}
    assert _canonical_ids([a, b]) == {"a", "b"}


def test_canonical_ids_drops_ror_reference_dominated_by_non_ror_sibling():
    a = {"id": "a", "faction_id": "BoC", "name": "Morgok's Krushas", "virtual": "false",
         "role": "Regiment of Renown", "Cost": ""}
    b = {"id": "b", "faction_id": "BoC", "name": "Morgok's Krushas", "virtual": "false",
         "role": "Infantry", "Cost": "100"}
    assert _canonical_ids([a, b]) == {"b"}


def test_parse_unit_maps_wahapedia_fields():
    row = {
        "name": "Gorbeast", "Move": '8"', "Save": "3+", "Health": "12",
        "Control": "3", "UnitSize": "1", "Cost": "380", "Ward": "",
        "description": "Each model is armed with Massive Maw.",
    }
    unit = _parse_unit(row, army_id=1, weapon_rows=[], keywords={"MONSTER", "HERO"})
    assert unit.name == "Gorbeast"
    assert unit.move == 8
    assert unit.save == 3
    assert unit.health == 12
    assert unit.control == 3
    assert unit.models == 1
    assert unit.points == 380
    assert unit.is_hero is True
    assert unit.ward is None
    assert unit.keywords == frozenset({"MONSTER", "HERO"})
    assert unit.description == "Each model is armed with Massive Maw."


def test_parse_unit_description_none_when_absent():
    row = {"name": "T", "Move": "5", "Save": "4+", "Health": "2", "Control": "1",
           "UnitSize": "5", "Cost": "150", "Ward": ""}
    unit = _parse_unit(row, army_id=1, weapon_rows=[], keywords=set())
    assert unit.description is None
    assert unit.keywords == frozenset()


def test_parse_unit_parses_ward_when_present():
    row = {"name": "T", "Move": "5", "Save": "4+", "Health": "2", "Control": "1",
           "UnitSize": "5", "Cost": "150", "Ward": "5+"}
    unit = _parse_unit(row, army_id=1, weapon_rows=[], keywords=set())
    assert unit.ward == 5
    assert unit.is_hero is False


def test_parse_weapon_maps_type_and_dash_rend():
    row = {"name": "Club", "Rng": "", "Atk": "2", "Hit": "4+", "Wnd": "4+",
           "Rnd": "-", "Dmg": "1", "type": "MELEE", "abilities": ""}
    weapon = _parse_weapon(row)
    assert weapon.kind == "melee"
    assert weapon.range_in == 1
    assert weapon.attacks == 2
    assert weapon.rend == 0
    assert weapon.abilities is None
    assert weapon.wielders == 0


def test_parse_weapon_ranged_kind_and_range():
    row = {"name": "Bow", "Rng": '18"', "Atk": "2", "Hit": "4+", "Wnd": "5+",
           "Rnd": "-", "Dmg": "1", "type": "RANGED", "abilities": ""}
    weapon = _parse_weapon(row)
    assert weapon.kind == "ranged"
    assert weapon.range_in == 18


def test_import_faction_end_to_end(con, data_dir: Path):
    summary = import_faction(con, "Beasts of Chaos", data_dir=data_dir)

    assert summary.inserted == 2
    assert summary.updated == 0

    army = repository.get_army_by_name(con, "Beasts of Chaos")
    assert army is not None
    assert army.grand_alliance == "Chaos"

    units = repository.list_units_for_army(con, army.id)
    names = {u.name for u in units}
    assert names == {"Gorbeast", "Gors"}  # Legends/Endless Spell/coquille/autre-faction exclus

    gorbeast = next(u for u in units if u.name == "Gorbeast")
    assert gorbeast.health == 12
    assert gorbeast.is_hero is True
    assert gorbeast.keywords == frozenset({"MONSTER", "HERO"})
    assert [w.name for w in gorbeast.weapons] == ["Massive Maw"]

    gors = next(u for u in units if u.name == "Gors")
    assert gors.models == 10
    assert gors.points == 100
    assert gors.is_hero is False


def test_import_faction_unknown_faction_raises(con, data_dir: Path):
    with pytest.raises(ValueError):
        import_faction(con, "Not A Real Faction", data_dir=data_dir)


def test_ingestible_roles_excludes_non_combat_roles():
    assert "Endless Spell" not in INGESTIBLE_ROLES
    assert "Regiment of Renown" not in INGESTIBLE_ROLES
    assert "Faction Terrain" not in INGESTIBLE_ROLES
    assert "Monster" in INGESTIBLE_ROLES
    assert "Hero" in INGESTIBLE_ROLES

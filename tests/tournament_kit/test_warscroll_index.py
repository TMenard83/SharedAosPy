"""Tests : chargement et résolution de `data/json/warscroll_index.json`."""

from __future__ import annotations

from pathlib import Path

from aospy.tournament_kit.translation.warscroll_index import (
    battletome_path, find_generic_manifestation_lore, find_lore_pages, find_pages, find_tactic_card_pages,
    generic_manifestation_lores_path, load_index, tactic_cards_path, unit_pdf_path,
)

_INDEX_PATH = "data/json/warscroll_index.json"


def test_load_index_reads_both_curated_factions():
    index = load_index(_INDEX_PATH)
    assert "Lumineth Realm-lords" in index.factions
    assert "Slaves to Darkness" in index.factions
    assert index.factions["Lumineth Realm-lords"].file.startswith("AOSv4 - LRL")


def test_find_pages_exact_match():
    index = load_index(_INDEX_PATH)
    pages = find_pages(index, "Lumineth Realm-lords", "Vanari Auralan Wardens")
    assert pages == [17]


def test_find_pages_normalizes_accents_and_case():
    index = load_index(_INDEX_PATH)
    pages = find_pages(index, "Slaves to Darkness", "be'lakor, the dark master".upper())
    assert pages == [17]


def test_find_pages_missing_unit_returns_none():
    index = load_index(_INDEX_PATH)
    assert find_pages(index, "Lumineth Realm-lords", "Not A Real Unit") is None


def test_find_pages_unknown_faction_returns_none():
    index = load_index(_INDEX_PATH)
    assert find_pages(index, "Not A Real Faction", "Anything") is None


def test_battletome_path_joins_battletome_dir():
    index = load_index(_INDEX_PATH)
    path = battletome_path(index, "Lumineth Realm-lords", "data/Battle tome/Done")
    assert isinstance(path, Path)
    assert path.exists()


def test_unit_pdf_path_defaults_to_faction_battletome():
    index = load_index(_INDEX_PATH)
    path = unit_pdf_path(index, "Lumineth Realm-lords", "Vanari Auralan Wardens", "data/Battle tome/Done")
    assert path == Path("data/Battle tome/Done") / index.factions["Lumineth Realm-lords"].file
    assert path.exists()


def test_unit_pdf_path_uses_per_unit_file_override():
    # Les variantes Scourge of Aqshy de Disciples of Tzeentch ont leur propre
    # charte dans un supplément séparé du battletome de base.
    index = load_index(_INDEX_PATH)
    faction_file = index.factions["Disciples of Tzeentch"].file
    path = unit_pdf_path(
        index, "Disciples of Tzeentch", "Ogroid Thaumaturge (Scourge of Aqshy)", "data/Battle tome/Done",
    )
    assert path is not None
    assert path.name != faction_file
    assert path.exists()
    assert find_pages(index, "Disciples of Tzeentch", "Ogroid Thaumaturge (Scourge of Aqshy)") == [1]


def test_unit_pdf_path_missing_unit_returns_none():
    index = load_index(_INDEX_PATH)
    assert unit_pdf_path(index, "Lumineth Realm-lords", "Not A Real Unit", "data/Battle tome/Done") is None


def test_load_index_missing_file_returns_empty(tmp_path):
    index = load_index(tmp_path / "nope.json")
    assert index.factions == {}
    assert index.tactic_cards is None


def test_faction_rules_static_sections_present():
    index = load_index(_INDEX_PATH)
    rules = index.factions["Lumineth Realm-lords"].rules
    assert rules.battle_traits == [2]
    assert rules.formations == [3]
    assert rules.heroic_traits_artefacts == [4]


def test_find_lore_pages_exact_and_with_point_cost_suffix():
    index = load_index(_INDEX_PATH)
    faction_index = index.factions["Lumineth Realm-lords"]
    rules = faction_index.rules
    assert find_lore_pages(faction_index, rules.spell_lores, "Lore of Hysh") == [6]
    assert find_lore_pages(faction_index, rules.spell_lores, "Lore of the Awakened Realms") == [7]
    # les exports de liste peuvent suffixer un domaine avec son coût en points
    # ; le domaine de Manifestations of Hysh couvre la page de convocation
    # (8) et les chartes de ses 3 manifestations propres (9, 10).
    assert find_lore_pages(faction_index, rules.manifestation_lores, "Manifestations of Hysh (20 Points)") == [8, 9, 10]


def test_find_lore_pages_missing_returns_none():
    index = load_index(_INDEX_PATH)
    faction_index = index.factions["Lumineth Realm-lords"]
    # "Twilit Sorceries" est un domaine générique, absent des domaines propres
    # à Lumineth (résolu ailleurs, voir find_generic_manifestation_lore).
    assert find_lore_pages(faction_index, faction_index.rules.manifestation_lores, "Twilit Sorceries") is None


def test_find_generic_manifestation_lore_returns_domain_and_manifestation_pages():
    index = load_index(_INDEX_PATH)
    lore = find_generic_manifestation_lore(index, "Twilit Sorceries")
    assert lore is not None
    assert lore.domain_pages == [22]
    assert lore.manifestations == {
        "Geminids of Uhl-Gysh": [23],
        "Prismatic Palisade": [24],
        "Umbral Spellportal": [25],
    }
    assert lore.all_pages() == [22, 23, 24, 25]


def test_find_generic_manifestation_lore_strips_point_cost_suffix():
    index = load_index(_INDEX_PATH)
    assert find_generic_manifestation_lore(index, "Morbid Conjuration (20 Points)") is not None


def test_find_generic_manifestation_lore_missing_returns_none():
    index = load_index(_INDEX_PATH)
    assert find_generic_manifestation_lore(index, "Not A Real Lore") is None


def test_generic_manifestation_lores_path_resolves_under_manuel_du_general():
    index = load_index(_INDEX_PATH)
    path = generic_manifestation_lores_path(index)
    assert path is not None
    assert path.exists()


def test_find_tactic_card_pages():
    index = load_index(_INDEX_PATH)
    assert find_tactic_card_pages(index, "Burning for Vengeance") == [4]
    assert find_tactic_card_pages(index, "burning for vengeance") == [4]
    assert find_tactic_card_pages(index, "Not A Real Card") is None


def test_tactic_cards_path_resolves_under_manuel_du_general():
    index = load_index(_INDEX_PATH)
    path = tactic_cards_path(index)
    assert path is not None
    assert path.exists()

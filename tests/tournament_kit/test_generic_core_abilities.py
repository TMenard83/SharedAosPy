"""Aptitudes génériques et couches anglaises (`sources/generic_core_abilities.py`, `season_rules.py`, `tactic_cards.py`)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pypdf")


def test_generic_core_abilities_requires_unit_keyword(tmp_path):
    from aospy.tournament_kit.sources.generic_core_abilities import load_generic_core_abilities

    path = tmp_path / "generic.json"
    path.write_text(
        """[
            {"name": "Musicien", "requires_unit_keyword": "MUSICIAN", "description": "", "condition": "Passive"},
            {"name": "Porte-Étendard", "requires_unit_keyword": "STANDARD BEARER", "description": "", "condition": "Passive"},
            {"name": "Champion", "requires_unit_keyword": "CHAMPION", "description": "", "condition": "Passive"},
            {"name": "Ralliement", "description": "", "condition": "Any Hero Phase"}
        ]""",
        encoding="utf-8",
    )
    names = lambda kws: [ab.name for ab in load_generic_core_abilities(path, unit_keywords=kws)]
    assert names(frozenset({"HERO", "INFANTRY"})) == ["Ralliement"]
    assert names(frozenset({"STANDARD BEARER"})) == ["Porte-Étendard", "Ralliement"]
    assert names(frozenset({"CHAMPION (1/9)"})) == ["Champion", "Ralliement"]
    assert names(None) == ["Musicien", "Porte-Étendard", "Champion", "Ralliement"]


def test_generic_core_abilities_requires_any_of_unit_keywords(tmp_path):
    from aospy.tournament_kit.sources.generic_core_abilities import load_generic_core_abilities

    path = tmp_path / "generic.json"
    path.write_text(
        """[
            {"name": "Dissipation", "requires_unit_keyword": "WIZARD", "description": "", "condition": "Passive"},
            {"name": "Intervention Magique", "requires_unit_keyword": ["WIZARD", "PRIEST"], "description": "", "condition": "Passive"},
            {"name": "Rites Sacrés", "requires_unit_keyword": "PRIEST", "description": "", "condition": "Passive"}
        ]""",
        encoding="utf-8",
    )
    names = lambda kws: [ab.name for ab in load_generic_core_abilities(path, unit_keywords=kws)]
    assert names(frozenset({"HERO"})) == []
    assert names(frozenset({"WIZARD (1)"})) == ["Dissipation", "Intervention Magique"]
    assert names(frozenset({"PRIEST"})) == ["Intervention Magique", "Rites Sacrés"]


def test_generic_core_abilities_english_layer_replaces_matched_entries(tmp_path):
    from aospy.tournament_kit.sources.generic_core_abilities import load_generic_core_abilities

    fr_path = tmp_path / "generic.json"
    fr_path.write_text(
        json.dumps(
            [
                {
                    "name": "Dissipation",
                    "requires_unit_keyword": "WIZARD",
                    "description": "fr",
                    "condition": "Reaction: L’adversaire a annoncé une aptitude de Sort",
                    "ability_phase": "Hero Phase",
                },
                {"name": "Attaque en Règle", "description": "fr", "points_type": "Command", "points": "1"},
            ]
        ),
        encoding="utf-8",
    )
    en_path = tmp_path / "generic_en.json"
    en_path.write_text(
        json.dumps(
            [
                {
                    "fr_name": "Dissipation",
                    "name": "Unbind",
                    "description": "en",
                    "condition": "Reaction: Opponent declared a Spell ability",
                    "keywords": "Unbind",
                },
            ]
        ),
        encoding="utf-8",
    )
    unbind, all_out = load_generic_core_abilities(fr_path, en_path=en_path)
    assert (unbind.name, unbind.description, unbind.condition) == (
        "Unbind",
        "en",
        "Reaction: Opponent declared a Spell ability",
    )
    assert unbind.keywords == "Unbind, Core Rules" and unbind.ability_phase == "Hero Phase"
    # sans ligne anglaise : l'entrée française reste telle quelle
    assert (all_out.name, all_out.points) == ("Attaque en Règle", "1")
    # `requires_unit_keyword` vient de l'entrée française
    assert [ab.name for ab in load_generic_core_abilities(fr_path, frozenset({"HERO"}), en_path=en_path)] == [
        "Attaque en Règle"
    ]


def test_generic_core_abilities_english_file_matches_french_names():
    """Chaque ligne de `generic_core_abilities_en.json` remplace une entrée
    française existante (une faute de `fr_name` la rendrait silencieusement inopérante)."""
    from aospy.tournament_kit.sources.generic_core_abilities import (
        DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE,
        DEFAULT_GENERIC_CORE_ABILITIES_FILE,
    )

    fr_names = {row["name"] for row in json.loads(DEFAULT_GENERIC_CORE_ABILITIES_FILE.read_text(encoding="utf-8"))}
    en_rows = json.loads(DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE.read_text(encoding="utf-8"))
    assert {row["fr_name"] for row in en_rows} <= fr_names


def test_english_layers_cover_every_french_entry():
    """Season rules, tactic cards and generic abilities: every French entry
    has its English counterpart (`en-split-simple` stays fully English)."""
    from aospy.tournament_kit.sources.generic_core_abilities import (
        DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE,
        load_generic_core_abilities,
    )
    from aospy.tournament_kit.sources.season_rules import DEFAULT_SEASON_RULES_EN_FILE, load_season_rules
    from aospy.tournament_kit.sources.tactic_cards import DEFAULT_TACTIC_CARDS_EN_FILE, load_tactic_cards

    fr_season = {ab.name for ab in load_season_rules()}
    en_season = {ab.name for ab in load_season_rules(en_path=DEFAULT_SEASON_RULES_EN_FILE)}
    assert not fr_season & en_season
    en_names = {row["name"] for row in json.loads(DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE.read_text(encoding="utf-8"))}
    assert {ab.name for ab in load_generic_core_abilities(en_path=DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE)} <= en_names
    cards = load_tactic_cards(en_path=DEFAULT_TACTIC_CARDS_EN_FILE)
    assert cards and all(card.english for card in cards.values())
    # clés = noms de l'export de liste, inchangées ; type et points du français
    assert cards.keys() == load_tactic_cards().keys()
    first = cards["Blazing Onslaught"]
    assert first.sub_tactics[0].name == "Master of Arms" and first.sub_tactics[0].kind == "Échauffourée"
    assert "hideout" in first.special_rule

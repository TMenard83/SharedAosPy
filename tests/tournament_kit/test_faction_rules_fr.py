"""Tests : chargement et application des correctifs/additions vérbatim
français de `data/json/faction_rules_fr.json` (`faction_rules_fr.py`)."""

from __future__ import annotations

import json

from aospy.tournament_kit.sources.faction_rules_fr import (
    FactionRulesFr,
    apply_fr_overrides,
    get_faction_category_overrides,
    get_unit_ability_overrides,
    load_faction_rules_fr,
)
from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

_SAMPLE = {
    "factions": {
        "Slaves to Darkness": {
            "rules": {
                "battle_traits": [
                    {
                        "wahapedia_name": "DARK BLESSINGS",
                        "name": "Bénédictions Sombres",
                        "description": "<b>Texte français final.</b>",
                        "origin": "BT",
                        "provenance": {"bt_text": "texte brut", "errata_patch": None, "errata_source": None},
                    },
                    {
                        "name": "Rage d'Aqshy",
                        "description": "Aptitude propre à Scourge of Aqshy, absente de Wahapedia.",
                        "condition": "Passive",
                        "ability_phase": "",
                        "origin": "Aqshy",
                    },
                ],
                "formations": [
                    {
                        "scope": "Despoilers",
                        "wahapedia_name": "RUTHLESS RAIDERS",
                        "name": "Pillards Impitoyables",
                        "description": "...",
                        "origin": "BT",
                    },
                ],
            },
            "units": {
                "Chaos Lord on Karkadrak": {
                    "abilities": [
                        {
                            "wahapedia_name": "TERROR OF THE DARK GODS",
                            "name": "Terreur des Dieux Sombres",
                            "description": "...",
                            "origin": "FP",
                        },
                    ],
                },
            },
        },
    },
}


def test_load_faction_rules_fr_missing_file_returns_empty(tmp_path):
    frf = load_faction_rules_fr(tmp_path / "does-not-exist.json")
    assert frf == FactionRulesFr()
    assert get_faction_category_overrides(frf, "Slaves to Darkness", "battle_traits") == []
    assert get_unit_ability_overrides(frf, "Slaves to Darkness", "Chaos Lord on Karkadrak") == []


def test_load_faction_rules_fr_reads_curated_factions(tmp_path):
    path = tmp_path / "faction_rules_fr.json"
    path.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    frf = load_faction_rules_fr(path)
    assert "Slaves to Darkness" in frf.factions
    assert "Lumineth Realm-lords" not in frf.factions


def test_get_faction_category_overrides_flat_category_no_scope(tmp_path):
    frf = load_faction_rules_fr(_write(tmp_path))
    rows = get_faction_category_overrides(frf, "Slaves to Darkness", "battle_traits")
    assert [r["name"] for r in rows] == ["Bénédictions Sombres", "Rage d'Aqshy"]


def test_get_faction_category_overrides_filters_by_scope(tmp_path):
    frf = load_faction_rules_fr(_write(tmp_path))
    assert [
        r["name"] for r in get_faction_category_overrides(frf, "Slaves to Darkness", "formations", "Despoilers")
    ] == ["Pillards Impitoyables"]
    assert get_faction_category_overrides(frf, "Slaves to Darkness", "formations", "Warhost of Duality") == []


def test_get_faction_category_overrides_tolerates_doubled_letter_typo():
    # l'App et Wahapedia écrivent « Blood Blesssings of Khorne » (3 s)
    frf = FactionRulesFr(
        factions={
            "Blades of Khorne": {
                "rules": {
                    "prayer_lores": [
                        {"scope": "Blood Blessings of Khorne", "wahapedia_name": "BLOOD BOIL", "name": "Sang Bouillant"}
                    ]
                }
            }
        }
    )
    rows = get_faction_category_overrides(frf, "Blades of Khorne", "prayer_lores", "Blood Blesssings of Khorne")
    assert [r["name"] for r in rows] == ["Sang Bouillant"]


def test_get_faction_category_overrides_unknown_faction_or_category(tmp_path):
    frf = load_faction_rules_fr(_write(tmp_path))
    assert get_faction_category_overrides(frf, "Nighthaunt", "battle_traits") == []
    assert get_faction_category_overrides(frf, "Slaves to Darkness", "spell_lores") == []


def test_get_unit_ability_overrides(tmp_path):
    frf = load_faction_rules_fr(_write(tmp_path))
    rows = get_unit_ability_overrides(frf, "Slaves to Darkness", "Chaos Lord on Karkadrak")
    assert [r["name"] for r in rows] == ["Terreur des Dieux Sombres"]
    assert get_unit_ability_overrides(frf, "Slaves to Darkness", "Not A Real Unit") == []


def test_apply_fr_overrides_patches_existing_entry_by_wahapedia_name():
    entries = [
        AbilityEntry(
            name="DARK BLESSINGS", description="original EN", legend="", condition="Passive", ability_phase="Hero Phase"
        )
    ]
    overrides = [
        {"wahapedia_name": "DARK BLESSINGS", "name": "Bénédictions Sombres", "description": "texte FR", "origin": "BT"}
    ]
    result = apply_fr_overrides(entries, overrides)
    assert len(result) == 1
    patched = result[0]
    assert patched.name == "Bénédictions Sombres"
    assert patched.description == "texte FR"
    # champs hérités de l'entrée Wahapedia d'origine, jamais retranscrits :
    assert patched.condition == "Passive"
    assert patched.ability_phase == "Hero Phase"
    assert "BT" in patched.keywords


def test_apply_fr_overrides_matches_typographic_apostrophe():
    # Wahapedia écrit « ’ », la curation du JSON « ' » : sans normalisation le
    # correctif devenait une addition nette et l'anglais restait à côté.
    entries = [AbilityEntry(name="BASH ’EM LADZ!", description="original EN", legend="")]
    overrides = [{"wahapedia_name": "BASH 'EM LADZ!", "name": "Kognez D'ssus, Lé Gars !", "description": "texte FR"}]
    result = apply_fr_overrides(entries, overrides)
    assert [e.name for e in result] == ["Kognez D'ssus, Lé Gars !"]


def test_apply_fr_overrides_patches_homonyms_in_order():
    # Deux aptitudes Wahapedia de même nom sur une charte (Pesticrates Putrides
    # Fléau d'Aqshy) : chaque ligne de correctif consomme la suivante.
    entries = [
        AbilityEntry(name="Putrescent Piety", description="EN 1", legend=""),
        AbilityEntry(name="Putrescent Piety", description="EN 2", legend=""),
    ]
    overrides = [
        {"wahapedia_name": "Putrescent Piety", "name": "Piété Putrescente", "description": "FR 1"},
        {"wahapedia_name": "Putrescent Piety", "name": "Dévotion Dégoûtante", "description": "FR 2"},
    ]
    result = apply_fr_overrides(entries, overrides)
    assert [(e.name, e.description) for e in result] == [("Piété Putrescente", "FR 1"), ("Dévotion Dégoûtante", "FR 2")]


def test_apply_fr_overrides_matches_empty_wahapedia_name():
    # Wahapedia laisse parfois le nom vide (« Stigmates de Guerre » de Festus).
    entries = [AbilityEntry(name="", description="EN", legend="")]
    overrides = [{"wahapedia_name": "", "name": "Stigmates de Guerre", "description": "FR"}]
    assert [e.name for e in apply_fr_overrides(entries, overrides)] == ["Stigmates de Guerre"]


def test_get_faction_category_overrides_scope_ignores_typographic_apostrophe(tmp_path):
    path = tmp_path / "faction_rules_fr.json"
    path.write_text(
        json.dumps({"factions": {"F": {"rules": {"formations": [{"scope": "Nurgle’s Menagerie", "name": "X"}]}}}}),
        encoding="utf-8",
    )
    frf = load_faction_rules_fr(path)
    assert len(get_faction_category_overrides(frf, "F", "formations", scope="Nurgle's Menagerie")) == 1


def test_apply_fr_overrides_adds_standalone_entry_without_wahapedia_match():
    overrides = [
        {
            "name": "Rage d'Aqshy",
            "description": "texte FR",
            "condition": "Passive",
            "ability_phase": "",
            "origin": "Aqshy",
        }
    ]
    result = apply_fr_overrides([], overrides)
    assert len(result) == 1
    assert result[0].name == "Rage d'Aqshy"
    assert "Aqshy" in result[0].keywords


def test_apply_fr_overrides_no_overrides_returns_entries_unchanged():
    entries = [AbilityEntry(name="X", description="Y", legend="")]
    assert apply_fr_overrides(entries, []) is entries


def _write(tmp_path):
    path = tmp_path / "faction_rules_fr.json"
    path.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    return path


def test_load_faction_rules_fr_sanitizes_non_breaking_hyphen(tmp_path):
    # texte de l'App : « FLESH‑EATER » (U+2011), carré noir en Helvetica
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"factions": {"X": {"note": "FLESH‑EATER"}}}, ensure_ascii=False), encoding="utf-8")
    assert load_faction_rules_fr(p).factions["X"]["note"] == "FLESH-EATER"


def test_apply_fr_overrides_typed_homonyms_patch_their_own_category():
    # BoK : deux correctifs « FRENZIED TASKMASTER » (Trait Héroïque et
    # Mutation d'Airain) — chacun ne corrige que l'entrée de sa catégorie
    from aospy.tournament_kit.sources.faction_rules_fr import apply_fr_overrides
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    overrides = [
        {
            "wahapedia_name": "FRENZIED TASKMASTER",
            "wahapedia_type": "Heroic Traits",
            "name": "Contremaître",
            "description": "HT",
        },
        {
            "wahapedia_name": "FRENZIED TASKMASTER",
            "wahapedia_type": "Brazen Mutations",
            "name": "Membres",
            "description": "BM",
        },
    ]
    heroic = AbilityEntry(name="FRENZIED TASKMASTER", description="x", legend="", wahapedia_type="Heroic Traits")
    assert [e.name for e in apply_fr_overrides([heroic], overrides)][0] == "Contremaître"
    mutation = AbilityEntry(name="FRENZIED TASKMASTER", description="x", legend="", wahapedia_type="Brazen Mutations")
    assert apply_fr_overrides([mutation], overrides)[0].name == "Membres"

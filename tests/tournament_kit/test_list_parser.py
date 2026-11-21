"""Tests : parsing d'une liste brute (export Warhammer Age of Sigmar: The App)
sur des exports réels figés dans `tests/fixtures/lists/` (format stable)."""

from __future__ import annotations

from aospy.tournament_kit.list_parser import RegimentOfRenown, parse_list, parse_list_file

_LISTS_DIR = "tests/fixtures/lists"


def test_parses_regiments_options_and_terrain():
    pl = parse_list_file(f"{_LISTS_DIR}/LRL L3 Avengers Wardens.txt")

    assert pl.faction == "Lumineth Realm-lords"
    assert pl.base_faction == "Lumineth Realm-lords"
    assert pl.allegiance == "Warhost of Duality (20 Points)"
    assert pl.drops == 4
    assert pl.spell_lore == "Lore of Hysh"
    assert pl.manifestation_lore == "Manifestations of Hysh"
    assert pl.battle_tactic_cards == ["Burning for Vengeance", "Flanking Firestorm"]
    assert pl.faction_terrain == ["Shrine Luminor"]

    general_regiment = pl.regiments[0]
    assert general_regiment.title == "General's Regiment"
    first_unit = general_regiment.units[0]
    assert first_unit.name == "Ellania and Ellathor, Eclipsian Warsages"
    assert first_unit.points == 310
    assert first_unit.options == ["General"]

    reinforced = general_regiment.units[1]
    assert reinforced.name == "Vanari Auralan Wardens"
    assert reinforced.options == ["Reinforced"]


def test_unique_unit_names_dedupes_and_includes_terrain():
    pl = parse_list_file(f"{_LISTS_DIR}/LRL L3 Avengers Wardens.txt")
    names = pl.unique_unit_names()
    # "Vanari Auralan Wardens" apparaît deux fois dans la liste (deux unités
    # distinctes, même nom) -> un seul profil à chercher.
    assert names.count("Vanari Auralan Wardens") == 1
    assert "Shrine Luminor" in names


def test_option_with_embedded_point_cost_kept_as_single_option():
    pl = parse_list_file(f"{_LISTS_DIR}/STD L3 Cavalerie 2000.txt")
    daemon_prince = pl.regiments[1].units[0]
    assert daemon_prince.name == "Daemon Prince"
    assert "Radiance of Dark Glory - (20) Points" in daemon_prince.options


def test_zero_point_companion_units_are_parsed():
    pl = parse_list_file(f"{_LISTS_DIR}/STD L3 Cavalerie 2000.txt")
    last_regiment = pl.regiments[-1]
    names_points = [(u.name, u.points) for u in last_regiment.units]
    assert ("Singri Brand", 0) in names_points
    assert ("The Oathsworn Kin", 0) in names_points


def test_army_of_renown_splits_faction_from_base_faction():
    pl = parse_list_file(f"{_LISTS_DIR}/STD L3 First Prince 1980.txt")
    assert pl.faction == "Slaves to Darkness | Legion of the First Prince"
    assert pl.base_faction == "Slaves to Darkness"
    assert pl.army_of_renown == "Legion of the First Prince"
    assert pl.allegiance == "Army of Renown"


def test_regiments_of_renown_parsed_with_member_units():
    pl = parse_list_file(f"{_LISTS_DIR}/STD L3 Prince Warriors Launcher.txt")
    assert pl.regiments_of_renown == [RegimentOfRenown(name="The Exiled One", points=390, units=["Skarbrand"])]
    assert "Skarbrand" in pl.unique_unit_names()


def test_parse_list_handles_missing_optional_lores():
    text = (
        "STD - Sample 2000/2000 pts\n\n"
        "Slaves to Darkness\n"
        "Despoilers\n"
        "General's Handbook 2026-27\n"
        "Drops: 1\n\n"
        "General's Regiment\n"
        "Daemon Prince (250)\n"
        " • General\n\n"
        "Created with Warhammer Age of Sigmar: The App\n"
        "App: 1.37.0 | Data: 476\n"
    )
    pl = parse_list(text)
    assert pl.spell_lore is None
    assert pl.manifestation_lore is None
    assert pl.battle_tactic_cards == []
    assert pl.regiments[0].units[0].name == "Daemon Prince"


def test_options_parsed_with_or_without_leading_space():
    # Certains exports de l'App écrivent « • Option » sans espace devant
    # (ex. OMT - Sharowkin - CHAAARGEZ), d'autres « • Option ».
    text = (
        "OMT - Sample 2000/2000 pts\n\n"
        "Ogor Mawtribes\n"
        "Hunger-Filled Tribe\n"
        "General's Handbook 2026-27\n"
        "Drops: 1\n\n"
        "General's Regiment\n"
        "Frostlord on Stonehorn (350)\n"
        "• General\n"
        " • Trophy Rack\n\n"
        "Created with Warhammer Age of Sigmar: The App\n"
    )
    unit = parse_list(text).regiments[0].units[0]
    assert unit.options == ["General", "Trophy Rack"]


def test_compact_export_format_normalized():
    # format « compact » : pas de titre, « Clé: valeur », options inline,
    # préfixe « 6x », coût d'option « (10 pts) », Faction Terrain en en-tête
    pl = parse_list_file(f"{_LISTS_DIR}/Sylv compact export.txt")

    assert pl.title == "Sylv compact export"
    assert pl.faction == "Sylvaneth"
    assert pl.allegiance == "Lords of the Clan"
    assert pl.drops == 4
    assert pl.spell_lore == "Lore of the Deepwood"
    assert pl.prayer_lore == "Lore of the Spirit-song"
    assert pl.manifestation_lore == "Manifestations of the Deepwood"
    assert pl.battle_tactic_cards == ["Blazing Onslaught", "Flanking Firestorm"]
    assert pl.faction_terrain == ["Awakened Wyldwood"]
    assert [r.title for r in pl.regiments] == ["General's Regiment", "Regiment 1", "Regiment 2", "Regiment 3"]
    assert pl.regiments[0].units[0].options == ["General"]
    warsong, kurnoth = pl.regiments[3].units[:2]
    assert warsong.options == ["Realmroot Guide", "Dancing Mystiflies"]
    assert kurnoth.name == "Kurnoth Hunters with Kurnoth Greatswords"
    assert kurnoth.points == 420
    assert kurnoth.options == ["Reinforced", "Aspect of Heartwood - (10) Points"]
    assert sum(u.points for r in pl.regiments for u in r.units) == 1990


def test_sigdex_export_variants_normalized():
    # export Sigdex : « Wounds: N » dans l'en-tête, variante saisonnière en
    # suffixe, coût d'option nu « (10) »
    pl = parse_list_file(f"{_LISTS_DIR}/IDK sigdex export.txt")

    assert pl.spell_lore == "Lore of the Deeps"
    assert pl.manifestation_lore == "Lore of the Abyss"
    assert pl.battle_tactic_cards == ["Flanking Firestorm", "Blazing Onslaught"]
    assert pl.regiments[0].units[1].name == "Scourge of Aqshy: Namarti Reavers"
    assert pl.regiments[1].units[1].options == ["Aqshian Sea Nettles - (10) Points"]
    assert pl.faction_terrain == ["Gloomtide Shipwreck"]


def test_compact_export_format_with_leading_title():
    # même format compact, mais le joueur a ajouté son propre titre en 1re
    # ligne (ex. « Vae Victis Vernou/Pierrodactyl ... ») avant la faction
    text = (
        "Pierrodactyl - ma liste\n\n"
        "Sylvaneth | Lords of the Clan\n"
        "2000/2000 points - 4 drops\n"
        "Battle Tactic Cards: Blazing Onslaught / Flanking Firestorm\n"
        "Spell Lore: Lore of the Deepwood\n"
        "Faction Terrain: Awakened Wyldwood\n\n"
        "General’s Regiment\n"
        "Alarielle the Everqueen (620)  • General\n"
    )
    pl = parse_list(text)
    assert pl.title == "Pierrodactyl - ma liste"
    assert pl.faction == "Sylvaneth"
    assert pl.allegiance == "Lords of the Clan"
    assert pl.drops == 4
    assert pl.battle_tactic_cards == ["Blazing Onslaught", "Flanking Firestorm"]
    assert pl.regiments[0].units[0].name == "Alarielle the Everqueen"
    assert pl.regiments[0].units[0].options == ["General"]

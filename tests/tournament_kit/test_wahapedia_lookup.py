"""Tests : repli en anglais sur data/wahapedia/*.csv (domaines génériques,
armées de renom, Régiments de Renom, profils d'unité de secours)."""

from __future__ import annotations

from aospy.tournament_kit.sources.wahapedia_lookup import load_wahapedia


def test_load_wahapedia_finds_the_local_data_dir():
    wh = load_wahapedia()
    assert wh.available


def test_find_generic_lore_returns_entries_sorted_by_line():
    wh = load_wahapedia()
    entries = wh.find_generic_lore("Twilit Sorceries")
    assert entries is not None
    assert [e.name for e in entries] == [
        "SUMMON GEMINIDS OF UHL-GYSH", "SUMMON PRISMATIC PALISADE", "SUMMON UMBRAL SPELLPORTAL",
    ]


def test_find_generic_lore_strips_point_cost_suffix():
    wh = load_wahapedia()
    assert wh.find_generic_lore("Morbid Conjuration (20 Points)") is not None


def test_find_generic_lore_missing_returns_none():
    wh = load_wahapedia()
    assert wh.find_generic_lore("Not A Real Lore") is None


def test_find_renown_army_rules_groups_by_subtype():
    wh = load_wahapedia()
    grouped = wh.find_renown_army_rules("Legion of the First Prince")
    assert grouped is not None
    assert "Battle Traits" in grouped
    assert "Spell Lore" in grouped
    assert any(e.name == "DARK CANTRIP" for e in grouped["Spell Lore"])


def test_find_renown_army_rules_missing_returns_none():
    wh = load_wahapedia()
    assert wh.find_renown_army_rules("Not A Real Army Of Renown") is None


def test_find_regiment_of_renown():
    wh = load_wahapedia()
    ror = wh.find_regiment_of_renown("The Exiled One")
    assert ror is not None
    assert ror.points == "400"
    assert any("Skarbrand" in c for c in ror.composition)
    assert any(a.name == "HATRED FOR ALL" for a in ror.abilities)


def test_find_regiment_of_renown_missing_returns_none():
    wh = load_wahapedia()
    assert wh.find_regiment_of_renown("Not A Real Regiment") is None


def test_find_warscroll_returns_full_profile():
    wh = load_wahapedia()
    ws = wh.find_warscroll("Skarbrand")
    assert ws is not None
    assert ws.faction_id == "BoK"
    assert ws.move == '8"'
    assert "UNIQUE" in ws.keywords
    assert len(ws.weapons) == 2
    assert any(a.name == "Roar of Total Rage" for a in ws.abilities)


def test_find_warscroll_excludes_regiment_of_renown_stub_rows():
    # "The Exiled One" existe aussi comme ligne Warscrolls.csv (role
    # "Regiment of Renown", sans profil de combat propre) : find_warscroll
    # ne doit pas la renvoyer à la place d'une vraie unité.
    wh = load_wahapedia()
    assert wh.find_warscroll("The Exiled One") is None


def test_find_warscroll_missing_returns_none():
    wh = load_wahapedia()
    assert wh.find_warscroll("Not A Real Unit") is None


def test_find_warscroll_tolerates_known_singular_plural_alias():
    # Wahapedia orthographie ce warscroll au singulier ("Berzerker"), alors
    # que BSData/l'App (et donc data/json/faction_rules_fr.json) utilisent le
    # pluriel -- cf. _WARSCROLL_NAME_ALIASES. Sans l'alias, cette unité
    # échouait à se résoudre dans les 3 modes de `aospy roster pdf`.
    wh = load_wahapedia()
    ws = wh.find_warscroll("Hearthguard Berzerkers with Berzerker Broadaxes")
    assert ws is not None
    assert ws.faction_id == "FY"


def test_find_warscroll_accepts_sigdex_seasonal_suffix():
    # Sigdex exporte « Namarti Reavers (Scourge of Aqshy) » là où Wahapedia
    # nomme le warscroll « Scourge of Aqshy Namarti Reavers ».
    wh = load_wahapedia()
    ws = wh.find_warscroll("Namarti Reavers (Scourge of Aqshy)")
    assert ws is not None
    assert ws.name == "Scourge of Aqshy Namarti Reavers"


def test_colspan_wound_marker_renders_as_dashes():
    """« #3 » dans `Wnd` (colspan Wahapedia, ex. Warp Lightning Blast) : pas
    de Blessure/Perforation/Dégâts — affichés « - », jamais le marqueur brut."""
    wh = load_wahapedia()
    ws = wh.find_warscroll("Warp Lightning Cannon", prefer_faction="Skaven")
    (blast,) = [w for w in ws.weapons if w.name == "Warp Lightning Blast"]
    assert (blast.wound, blast.rend, blast.damage) == ("-", "-", "-")


def test_find_unit_enhancement_disambiguates_homonyms_by_paid_suffix():
    # BoK : « FRENZIED TASKMASTER » est à la fois un Trait Héroïque (gratuit)
    # et une Mutation d'Airain (payante, nom erroné côté Wahapedia)
    wh = load_wahapedia()
    label, _ = wh.find_unit_enhancement("Blades of Khorne", "Frenzied Taskmaster")
    assert label == "Trait Héroïque"
    label, _ = wh.find_unit_enhancement("Blades of Khorne", "Frenzied Taskmaster - (10) Points")
    assert label == "Mutation d'Airain"

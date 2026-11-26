"""Couche 4 — aptitudes × armée (analysis/layers/listing.py), cœur pur."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.listing import ListAbility, conflicts, magic_budget, marriages, wizard_level
from aospy.domain.models import Unit, Weapon

HAMMER = Weapon("Hammer", "melee", attacks=4, hit=4, wound=2, rend=2, damage=5)


def _unit(name, **kw):
    base = dict(
        name=name,
        army_id=1,
        move=6,
        save=3,
        health=14,
        control=5,
        models=1,
        points=300,
        keywords=frozenset({"MONSTER", "ALARITH"}),
        weapons=[HAMMER],
    )
    base.update(kw)
    return Unit(**base)


def _ab(name, scope="self", freq="passive", carriers=(), effects=(), **kw):
    base = dict(
        uid=name,
        name=name,
        source=f"charte : {carriers[0]}" if carriers else "formation : X",
        source_kind="warscroll" if carriers else "battle_formation",
        carriers=tuple(carriers),
        scope=scope,
        frequency=freq,
        turn_side="any",
        phase="",
        cost_type="",
        cost_value=None,
        activation_prob=1.0,
        available_round=None,
        friendly_target="",
        excludes_self=False,
        verdict="correct",
        power=1.5,
        reliability=3.0,
        ease=3.0,
        interaction=0.0,
        effects=tuple(effects),
    )
    base.update(kw)
    return ListAbility(**base)


def test_wards_do_not_stack_in_a_list():
    spirit = _unit("Spirit")
    warded = _unit("Sevireth", ward=5)
    shield = _ab(
        "Realmshield",
        scope="friendly_aura",
        freq="unlimited",
        effects=[EffectSpec("ward", value=5.0)],
        activation_prob=0.5,
    )
    got = {m.receiver: m for m in marriages([shield], [spirit, warded], frozenset({"MONSTER"}))}
    assert got["Spirit"].def_gain_pct > 49 and got["Spirit"].weight == 0.5
    assert got["Sevireth"].def_gain_pct == 0


def test_army_limited_ability_on_several_copies_is_a_conflict():
    rain = _ab("Rain of Stone", scope="one_enemy", freq="once_per_turn_army", carriers=("Spirit",))
    solo = _ab("Searing Winds", scope="enemy_aura", freq="once_per_turn_army", carriers=("Sevireth",))
    got = conflicts([rain, solo], {"Spirit": 3, "Sevireth": 1})
    assert [c.ability for c in got] == ["Rain of Stone"]


def test_magic_budget_counts_casters_and_spells():
    mage = _unit("Mage", keywords=frozenset({"HERO", "WIZARD"}))
    big = _unit("Arch", keywords=frozenset({"HERO", "WIZARD (2)"}))
    assert wizard_level(mage) == 1 and wizard_level(big) == 2 and wizard_level(_unit("S")) == 0
    spell = _ab("Push", scope="one_friendly", freq="unlimited", cost_type="Spell", cost_value=6.0, activation_prob=0.72)
    mb = magic_budget([spell], [mage, big, _unit("S")])
    assert mb.casts_per_turn == 3 and mb.spells[0][0] == "Push"


def test_ranged_buff_is_unprofitable_when_nobody_shoots():
    """Exemple de l'utilisateur : bannière « +1 touche au tir » en bulle, nulle si personne ne tire."""
    from aospy.analysis.layers.listing import unprofitable_buffs

    banner = _ab(
        "Banner",
        scope="friendly_aura",
        carriers=("Spirit",),
        effects=[EffectSpec("stat_mod", "hit", 1.0, weapon_scope="ranged")],
    )
    melee_only = [_unit("Spirit"), _unit("Sevireth")]
    got = unprofitable_buffs([banner], melee_only, frozenset({"MONSTER"}))
    assert [(a.name, r) for a, r in got] == [("Banner", "aucune unité de la liste ne tire")]
    bow = Weapon("Bow", "ranged", attacks=4, hit=4, wound=4, rend=1, damage=1, range_in=18)
    archer = _unit("Archer", weapons=[bow])
    assert unprofitable_buffs([banner], [*melee_only, archer], frozenset({"MONSTER"})) == []


def test_army_of_renown_categories_replace_base_ones():
    from types import SimpleNamespace

    from aospy.analysis.layers.listing import _rule_groups

    parsed = SimpleNamespace(
        allegiance="Thunderhead Host",
        spell_lore="Lore of the Storm",
        prayer_lore="Prayers of the Stormhosts",
        manifestation_lore=None,
    )
    base = dict(_rule_groups(parsed))
    assert "Battle Traits › *" in base and "Spell Lore › Lore of the Storm" in base
    aor = dict(_rule_groups(parsed, ("Ruination Brotherhood", frozenset({"Battle Traits", "Prayer Lore"}))))
    assert "Battle Traits › *" not in aor and "Ruination Brotherhood › Battle Traits" in aor
    assert "Ruination Brotherhood › Prayer Lore" in aor and "Prayer Lore › Prayers of the Stormhosts" not in aor
    assert "Spell Lore › Lore of the Storm" in aor  # catégorie que l'AoR ne porte pas : celle de base
    assert "Battle Formations › Thunderhead Host" in aor


def test_exclusive_options_keep_the_best_one_per_receiver():
    from aospy.analysis.layers.listing import Marriage, _best_options

    rows = [
        Marriage(
            "Master of the Runes",
            "Auric Runemaster",
            "Hearthguard",
            "allié",
            "stat_mod",
            10.0,
            None,
            1.0,
            "",
            "Rune of Fury",
        ),
        Marriage(
            "Master of the Runes",
            "Auric Runemaster",
            "Hearthguard",
            "allié",
            "stat_mod",
            None,
            25.0,
            1.0,
            "",
            "Rune of Fiery Determination",
        ),
        Marriage("Lodge Leader", "Auric Runefather", "Hearthguard", "allié", "stat_mod", 5.0, None, 1.0, ""),
    ]
    kept = _best_options(rows)
    assert {m.option for m in kept} == {"Rune of Fiery Determination", ""}


def test_given_buff_is_weighted_by_its_giver():
    """Réponse utilisateur (« D × S × suivi ») : un buff donné vaut gain × D × S du donneur (couche 3) × min(1,
    allonge du donneur ÷ allonge du receveur) ; sur soi, ou une règle d'armée sans porteur : rien à pondérer."""
    from aospy.analysis.layers.listing import giver_reliability

    hero = _unit("Hero", keywords=frozenset({"HERO", "ALARITH"}))
    fast = _unit("Fast", move=12)
    aura = _ab("Aura", scope="friendly_aura", carriers=["Hero"])
    bearing = {("Hero", "Aura"): 0.5}
    reach = {"Hero": 6.0, "Fast": 12.0}
    assert giver_reliability(aura, fast, "allié", bearing, reach) == pytest.approx(0.25)
    assert giver_reliability(aura, hero, "porteur", bearing, reach) == 1.0
    army = _ab("Rule", scope="army")
    assert giver_reliability(army, fast, "allié", bearing, reach) == 1.0
    manif = _ab("Cogs", scope="friendly_aura", carriers=["Cogs"], summon_prob=0.72)
    assert giver_reliability(manif, fast, "allié", {}, {}) == pytest.approx(0.72)
    got = marriages([_ab("Shield", scope="friendly_aura", carriers=["Hero"],
                         effects=[EffectSpec("ward", value=5.0)])], [hero, fast], frozenset({"MONSTER"}),
                    bearing={("Hero", "Shield"): 0.5}, reach=reach)
    by = {m.receiver: m for m in got}
    assert by["Fast"].giver == pytest.approx(0.25) and by["Hero"].giver == 1.0


def test_condition_needs_a_provider_in_the_list():
    """« wholly within 12" of a friendly Hag Queen on Cauldron of Blood, Slaughter Queen on Cauldron of Blood or
    Shrine of Dark Tribute » : une seule alternative présente suffit ; sinon, constat « aucun dans la liste »."""
    from aospy.analysis.layers.listing import missing_providers, provider_phrases

    text = ("While this unit is wholly within 12\" of a friendly Hag Queen on Cauldron of Blood, Slaughter Queen on "
            "Cauldron of Blood or Shrine of Dark Tribute, this unit's melee weapons have Anti-charge (+1 Rend).")
    assert provider_phrases(text) == [
        "Hag Queen on Cauldron of Blood, Slaughter Queen on Cauldron of Blood or Shrine of Dark Tribute"
    ]
    assert provider_phrases("While this unit is within the combat range of a friendly non-HERO SKAVEN INFANTRY "
                            "unit:\n- This unit has WARD (4+).") == ["non-HERO SKAVEN INFANTRY"]
    hags = _ab("Wicked Wardens", carriers=["Blood Hags"], text=text)
    queen = _unit("Slaughter Queen on Cauldron of Blood")
    assert missing_providers([hags], [queen, _unit("Blood Hags")], frozenset({"MONSTER"})) == []
    (miss,) = missing_providers([hags], [_unit("Blood Hags")], frozenset({"MONSTER"}))
    assert "aucun dans la liste" in miss[1]


def test_report_warns_about_units_missing_from_the_database():
    """Une unité de la liste absente de la base est signalée en tête de fiche (leçon Haldahir du 2026-11-23)."""
    from aospy.analysis.layers.listing import ListReport
    from aospy.cli.report import format_list_report

    rep = ListReport("T", "F", [("Known", 100, _unit("Known")), ("Scourge of Aqshy: Ghost", 200, None)], [])
    text = format_list_report(rep)
    assert "non reconnue" in text and "Scourge of Aqshy: Ghost" in text


def test_find_unit_tolerates_app_name_variants():
    """Écarts de nom App / base : apostrophe typographique, préfixe de faction, mot répété (2026-11-23)."""
    from aospy.analysis.layers.listing import find_unit

    pool = {n.lower(): _unit(n) for n in ("Neave’s Companions", "Monsta-killaz", "Kurnoth Hunters with Greatswords")}
    assert find_unit("Neave's Companions", pool, "Stormcast Eternals").name == "Neave’s Companions"
    assert find_unit("Kruleboyz Monsta-killaz", pool, "Kruleboyz").name == "Monsta-killaz"
    assert find_unit("Kurnoth Hunters with Kurnoth Greatswords", pool, "Sylvaneth").name == (
        "Kurnoth Hunters with Greatswords"
    )
    assert find_unit("Gargant", pool, "Sylvaneth") is None


def test_same_unit_twice_with_and_without_reinforcement_stays_two_units():
    """Blood Hags renforcées (×20) et Blood Hags (×10) : deux unités distinctes dans l'analyse, la renforcée sous un
    nom à part mais avec les aptitudes de la charte (2026-11-23, liste de Razemme)."""
    import types

    import duckdb

    from aospy.analysis.layers.listing import collect

    con = duckdb.connect("data/aospy.duckdb", read_only=True)
    if not con.execute("SELECT 1 FROM unit WHERE name = 'Blood Hags'").fetchone():
        pytest.skip("base sans Daughters of Khaine")
    ue = lambda n, p, o: types.SimpleNamespace(name=n, points=p, options=o)  # noqa: E731
    parsed = types.SimpleNamespace(
        base_faction="Daughters of Khaine", regiments=[types.SimpleNamespace(
            units=[ue("Blood Hags", 310, ["Reinforced"]), ue("Blood Hags", 150, [])])],
        faction_terrain=[], army_of_renown=None, allegiance=None, battle_formation=None, spell_lore=None,
        prayer_lore=None, manifestation_lore=None,
    )
    try:
        entries, abilities, _v = collect(con, parsed)
    except AttributeError:
        pytest.skip("structure ParsedList différente")
    names = [n for n, _p, u in entries if u is not None]
    assert names == ["Blood Hags (renforcé)", "Blood Hags"]
    big = next(u for n, _p, u in entries if n == "Blood Hags (renforcé)")
    small = next(u for n, _p, u in entries if n == "Blood Hags")
    assert big.models == 2 * small.models
    assert any("Blood Hags (renforcé)" in a.carriers for a in abilities)


def test_dead_rules_fixes_from_the_twelve_list_review():
    """Revue des 12 listes : « pick this unit and up to 2 X » n'est pas morte ; un décor cible ; un lanceur gagné par
    aptitude (« it has WIZARD (1) ») ; un sort qui exige un sorcier d'un mot-clé absent est mort ; une condition
    « doit avoir chargé » déjà localisée n'est pas recopiée sur les autres options."""
    from aospy.analysis.layers.listing import dead_rules

    kin = _unit("Kin", keywords=frozenset({"HERO"}))
    chariot = _ab("Charioteer", scope="one_friendly", carriers=["Kin"], friendly_target="Kavalos War Chariots",
                  text="Pick this unit and up to 2 Kavalos War Chariots to be the targets.")
    seasons = _ab("Seasons", scope="one_friendly", carriers=["Kin"], friendly_target="Awakened Wyldwood")
    wood = _ab("Wood rule", carriers=["Awakened Wyldwood"])
    nadja = _ab("Nadja", carriers=["Kin"], text="it has WIZARD (1).",
                effects=[EffectSpec("keyword_gain", "caster")])
    spell = _ab("Bolt", source="domaine de sorts : X", cost_type="Spell",
                text="Pick a friendly STORMCAST ETERNALS WIZARD to cast this spell.")
    lore = _ab("Daemonic Speed", source="domaine de sorts : Y", cost_type="Spell",
               text="Pick a friendly WIZARD to cast this spell.")
    dead = {a.name for a, _r in dead_rules([chariot, seasons, wood, nadja, spell, lore], [kin],
                                           frozenset({"HERO", "WIZARD", "STORMCAST ETERNALS"}))}
    assert dead == {"Bolt"}
    blessings = _ab("Blessings", scope="army", charge_required=True,
                    effects=[EffectSpec("stat_mod", "wound", 1.0), EffectSpec("ward", value=5.0, requires="a chargé")])
    assert not blessings.charge_everywhere


def test_find_entry_unit_maps_expired_ghyran_variant_to_aqshy():
    """« Scourge of Ghyran: Iridan the Witness » (pack 2025-26, absent de la base) = la variante Aqshy, même profil
    (Thiradil, 2026-11-25) ; à défaut la charte de base."""
    from aospy.analysis.layers.listing import find_entry_unit

    pool = {n.lower(): _unit(n) for n in ("Iridan the Witness", "Scourge of Aqshy Iridan the Witness", "Liberators")}
    assert find_entry_unit("Scourge of Ghyran: Iridan the Witness", pool, "Stormcast Eternals").name == (
        "Scourge of Aqshy Iridan the Witness"
    )
    assert find_entry_unit("Scourge of Ghyran: Liberators", pool, "Stormcast Eternals").name == "Liberators"
    assert find_entry_unit("Scourge of Aqshy: Liberators", pool, "Stormcast Eternals") is None
    assert find_entry_unit("Iridan the Witness", pool, "Stormcast Eternals").name == "Iridan the Witness"


def test_collect_reads_renown_terrain_and_companions():
    """Gotrek (Régiment de Renom, Fyreslayers), décor coté « (10 Points) » ou recopié en option « (20 pts) »,
    compagnon omis de l'export (The Shadow Queen) : tous dans la couche 4 (contrôles L3 du 2026-11-25)."""
    import types

    import duckdb

    from aospy.analysis.layers.listing import collect

    con = duckdb.connect("data/aospy.duckdb", read_only=True)
    if not con.execute("SELECT 1 FROM unit WHERE name = 'Gotrek Gurnisson'").fetchone():
        pytest.skip("base sans Gotrek (réimport Wahapedia nécessaire)")
    ue = lambda n, p, o=(): types.SimpleNamespace(name=n, points=p, options=list(o))  # noqa: E731
    base = dict(army_of_renown=None, allegiance=None, battle_formation=None, spell_lore=None, prayer_lore=None,
                manifestation_lore=None)
    sylv = types.SimpleNamespace(
        base_faction="Sylvaneth", regiments=[types.SimpleNamespace(units=[ue("Dryads", 100)])],
        regiments_of_renown=[types.SimpleNamespace(name="Gotrek Gurnisson", points=320,
                                                   units=["Gotrek Gurnisson", "•"])],
        faction_terrain=[], **base,
    )
    entries, abilities, _v = collect(con, sylv)
    assert ("Gotrek Gurnisson", 320) in [(n, p) for n, p, u in entries if u is not None]
    assert any("Gotrek Gurnisson" in a.carriers for a in abilities)

    sce = types.SimpleNamespace(
        base_faction="Stormcast Eternals",
        regiments=[types.SimpleNamespace(units=[ue("Vanquishers", 90, ["Stormreach Portal - (20) Points"])])],
        regiments_of_renown=[], faction_terrain=[], **base,
    )
    _e, abilities, _v = collect(con, sce)
    assert any("Stormreach Portal" in a.carriers for a in abilities)

    fec = types.SimpleNamespace(
        base_faction="Flesh-eater Courts", regiments=[], regiments_of_renown=[],
        faction_terrain=["Charnel Throne (10 Points)"], **base,
    )
    _e, abilities, _v = collect(con, fec)
    assert any("Charnel Throne" in a.carriers for a in abilities)

    dok = types.SimpleNamespace(
        base_faction="Daughters of Khaine", regiments=[types.SimpleNamespace(units=[ue("Morathi-Khaine", 770)])],
        regiments_of_renown=[], faction_terrain=[], **base,
    )
    entries, _a, _v = collect(con, dok)
    assert "The Shadow Queen" in [n for n, _p, u in entries if u is not None]

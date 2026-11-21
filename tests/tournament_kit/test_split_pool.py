"""Pool d'aptitudes des modes étendus/split (`tournament_kit/split_pool.py`) : sous-sections de choix, alias, ordre du déploiement, retraits."""

from __future__ import annotations

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pypdf")


def test_warscroll_ability_pool_merges_identical_abilities_across_units():
    from dataclasses import replace

    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry, WarscrollData
    from aospy.tournament_kit.split_pool import _warscroll_ability_pool

    shared = AbilityEntry("SHARED", "Same text.", "", condition="Passive")
    own = AbilityEntry("OWN", "Own text.", "", condition="Your Hero Phase")
    base = WarscrollData("A", "", "", "", "", "", "", "", "", "", "", [], [], [shared, own])
    pool = _warscroll_ability_pool([base, replace(base, name="B", abilities=[shared])])

    assert [(ab.name, ab.warscrolls) for ab in pool] == [("SHARED", ("A", "B")), ("OWN", ("A",))]


def test_delusion_cluster_groups_chooser_and_delusions_at_start_of_turn():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _CHOICE_CLUSTERS, _choice_cluster

    spec = next(c for c in _CHOICE_CLUSTERS if c.category == "delusion")
    chooser = AbilityEntry("Royaume Délirant", "", "", keywords="BT", ability_phase="Start of Turn")
    combat = AbilityEntry("Banquet Glorieux", "", "", keywords="Delusion,BT", ability_phase="Combat Phase")
    other = AbilityEntry("Sang Royal", "", "", keywords="BT", ability_phase="Hero Phase")
    cluster = _choice_cluster([chooser, combat, other], spec)
    assert [ab.name for ab in cluster] == ["Royaume Délirant", "Banquet Glorieux"]
    assert all(ab.ability_phase == "Start of Turn" and ab.ability_category == "delusion" for ab in cluster)
    assert _choice_cluster([chooser, other], spec) == []


def test_blood_tithe_cluster_orders_skulls_then_blood_drenched_then_options_by_cost():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _apply_choice_clusters

    def bt(name, phase, cost):
        return AbilityEntry(
            name, "", "", keywords="Blood Tithe", ability_phase=phase, points_type="Blood tithe", points=cost
        )

    drenched = AbilityEntry("Trempés de Sang", "", "", ability_phase="Start of Turn", is_reaction=True)
    skulls = AbilityEntry("Des Crânes pour le Trône de Crânes", "", "", ability_phase="Start of Turn")
    slaughter = bt("Massacre Triomphal", "Combat Phase", "4")
    scorn = bt("Mépris Divin", "Start of Turn", "1")
    pool = [drenched, slaughter, skulls, scorn]

    out = _apply_choice_clusters(pool, "fr-extended")
    cluster = [ab for ab in out if ab.ability_category == "blood_tithe"]
    assert [ab.name for ab in cluster] == [
        "Des Crânes pour le Trône de Crânes",
        "Trempés de Sang",
        "Mépris Divin",
        "Massacre Triomphal",
    ]
    # l'option hors « Début de tour » reste aussi à sa place, les autres sont déplacées
    assert [ab.name for ab in out if ab.ability_category != "blood_tithe"] == ["Massacre Triomphal"]
    assert _apply_choice_clusters(pool, "fr") == pool


def test_choice_cluster_copy_stays_at_start_of_turn_despite_condition_phase():
    from aospy.tournament_kit.render.phases import classify_phase
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _CHOICE_CLUSTERS, _choice_cluster

    spec = next(c for c in _CHOICE_CLUSTERS if c.category == "blood_tithe")
    punish = AbilityEntry(
        "Punissez les Pacifistes",
        "",
        "",
        keywords="Blood Tithe",
        condition="Once Per Turn (Army), Your Combat Phase",
        ability_phase="Combat Phase",
    )
    assert classify_phase(punish) == "melee"
    assert [classify_phase(ab) for ab in _choice_cluster([punish], spec)] == ["start"]


def test_khaine_blessing_cluster_moves_blood_rites_then_blessings_to_end_of_turn():
    from aospy.tournament_kit.render.phases import classify_phase
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _apply_choice_clusters

    rites = AbilityEntry("Rites de Sang", "", "", condition="Passive", ability_phase="Start of Turn")
    blessings = AbilityEntry(
        "Bénédictions de Khaine", "", "", condition="Once Per Turn (Army), End of Any Turn", ability_phase="End of Turn"
    )
    other = AbilityEntry("Ritualiste Consacrée", "", "", ability_phase="Start of Turn")

    out = _apply_choice_clusters([rites, other, blessings], "fr-split")
    assert [ab.name for ab in out] == ["Ritualiste Consacrée", "Rites de Sang", "Bénédictions de Khaine"]
    assert [ab.ability_category for ab in out] == ["", "khaine_blessing", "khaine_blessing"]
    assert {classify_phase(ab) for ab in out[1:]} == {"end"}
    assert _apply_choice_clusters([other], "fr-split") == [other]


def test_choice_cluster_moves_reactions_to_the_choice_ability():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _apply_choice_clusters

    blessings = AbilityEntry(
        "Bénédictions de Khaine", "", "", condition="Once Per Turn (Army), End of Any Turn", ability_phase="End of Turn"
    )
    offerings = AbilityEntry(
        "Offrandes Pourpres",
        "",
        "",
        is_reaction=True,
        ability_phase="End of Turn",
        condition="Once Per Turn (Army), Reaction: You declared the ‘%000021998Blessings of Khaine%’ ability",
    )
    redeploy = AbilityEntry("Autre", "", "", condition="Reaction: You declared the ‘%000009837Redeploy%’ command")

    out = _apply_choice_clusters([offerings, redeploy, blessings], "fr-extended")
    assert [(ab.name, ab.ability_category) for ab in out] == [
        ("Autre", ""),
        ("Bénédictions de Khaine", "khaine_blessing"),
        ("Offrandes Pourpres", "khaine_blessing"),
    ]


def test_delusion_cluster_also_applies_in_fr_extended():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _apply_choice_clusters

    combat = AbilityEntry("Banquet Glorieux", "", "", keywords="Delusion", ability_phase="Combat Phase")
    out = _apply_choice_clusters([combat], "fr-extended")
    assert [ab.ability_category for ab in out] == ["", "delusion"]


def test_mark_self_profile_survives_french_patch():
    """Décidé sur le texte Wahapedia, le marquage survit au correctif
    français qui traduit le nom de l'arme dans le texte seulement."""
    from aospy.tournament_kit.render.phases import is_self_profile_modifier
    from aospy.tournament_kit.sources.faction_rules_fr import apply_fr_overrides
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry, WarscrollData, WeaponEntry
    from aospy.tournament_kit.split_pool import _mark_self_profile

    en = "<b>Effect:</b> If this unit charged this turn, add 1 to the Rend characteristic of its <b>Cursed Lances</b>."
    weapon = WeaponEntry(*(["Cursed Lance"] + [""] * (len(WeaponEntry.__dataclass_fields__) - 1)))
    ws = WarscrollData(
        "Chaos Knights",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        [],
        [weapon],
        [AbilityEntry("Impaling Charge", en, "", condition="Passive")],
    )
    ws = _mark_self_profile(ws)
    fr = "<b>Effet :</b> Si cette unité a chargé à ce tour, ajoutez 1 à la Perforation de ses Lances Maudites."
    patched = apply_fr_overrides(
        ws.abilities, [{"wahapedia_name": "Impaling Charge", "name": "Charge Empaleuse", "description": fr}]
    )
    assert is_self_profile_modifier(patched[0], [weapon.name])


def test_order_deploy_game_sequence_full_width():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _order_deploy

    names = ["Autre", "Souffler sur les Braises", "Déploiement d’Unité", "Placez le Champ de Bataille"]
    out = _order_deploy([AbilityEntry(name=n, description="", legend="") for n in names])
    assert [ab.name for ab in out] == [
        "Placez le Champ de Bataille",
        "Déploiement d’Unité",
        "Souffler sur les Braises",
        "Autre",
    ]
    assert [ab.full_width for ab in out] == [True, True, True, False]


def test_tactic_special_rules_join_deployment():
    from types import SimpleNamespace

    from aospy.tournament_kit.sources.tactic_cards import load_tactic_cards
    from aospy.tournament_kit.split_pool import _tactic_special_rules

    parsed = SimpleNamespace(battle_tactic_cards=["Blazing Onslaught", "Siege of Ashes"])
    (rule,) = _tactic_special_rules(parsed, load_tactic_cards())
    assert rule.name == "Assaut Flamboyant : Règle Spéciale" and "repaire" in rule.description
    assert rule.ability_phase == "Deployment Phase" and rule.full_width


def test_enemy_turn_drops_charge_reroll_unless_charge_keyword():
    """« En Avant, vers la Victoire » quitte « Tour adverse », sauf si une
    autre aptitude de cette carte porte le mot-clé Charge."""
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _drop_enemy_charge_reroll

    reroll = AbilityEntry("En Avant, vers la Victoire", "", "", ability_phase="Charge Phase")
    counter = AbilityEntry("Contre-Charge", "", "", condition="Enemy Charge Phase")
    assert _drop_enemy_charge_reroll([reroll, counter]) == [counter]
    ambush = AbilityEntry("Drawn to Magic", "", "", keywords="Core, Move, Charge", condition="Any Charge Phase")
    assert _drop_enemy_charge_reroll([reroll, counter, ambush]) == [reroll, counter, ambush]
    glued = AbilityEntry("Paramount Hunter", "", "", keywords="Core, Move, Charge Rampage")
    assert reroll in _drop_enemy_charge_reroll([reroll, glued])


def test_identical_warscroll_abilities_merge_ignoring_flavor_text():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry, WarscrollData
    from aospy.tournament_kit.split_pool import _warscroll_ability_pool

    def ws(name, flavor):
        ab = AbilityEntry(
            "Descendez-les",
            f"<i>{flavor}</i><br/><br/><b>Effet :</b> +1 touche.",
            "",
            condition="Your Shooting Phase",
            ability_phase="Shooting Phase",
        )
        return WarscrollData(name, "KB", "", "", "", "", "", "", "", "", "", [], [], [ab])

    pool = _warscroll_ability_pool([ws("Boltboyz", "Tirs ajustés."), ws("Killbow", "Tirs mortels.")])
    assert [(ab.name, ab.warscrolls) for ab in pool] == [("Descendez-les", ("Boltboyz", "Killbow"))]


def test_chaos_pledge_cluster_in_hero_phase_keeps_pledges_where_used():
    from aospy.tournament_kit.render.phases import TURN_ENEMY, TURN_MINE, classify_phase
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _apply_choice_clusters, _fold_warscroll_copies, _turn_sides

    pledge = AbilityEntry(
        "Vocation au Chaos", "", "", condition="Once Per Turn (Army), Your Hero Phase", ability_phase="Hero Phase"
    )
    khorne = AbilityEntry(
        "Voué à Khorne", "<b>Effet :</b> +1 A.", "", condition="Passive", ability_phase="Combat Phase"
    )
    khorne_ws = AbilityEntry(
        "Voué à Khorne",
        "<i>Rage.</i><br/><br/><b>Effet :</b> +1 A.",
        "",
        condition="Passive",
        ability_phase="Combat Phase",
        warscrolls=("Chaos Knights",),
    )
    nurgle = AbilityEntry("Voué à Nurgle", "", "", condition="Passive", ability_phase="Defensive reaction")

    folded = _fold_warscroll_copies([pledge, khorne, nurgle, khorne_ws])
    assert [(ab.name, ab.warscrolls) for ab in folded] == [
        ("Vocation au Chaos", ()),
        ("Voué à Khorne", ("Chaos Knights",)),
        ("Voué à Nurgle", ()),
    ]
    out = _apply_choice_clusters(folded, "fr-split")
    cluster = [ab for ab in out if ab.ability_category == "chaos_pledge"]
    assert [ab.name for ab in cluster] == ["Vocation au Chaos", "Voué à Khorne", "Voué à Nurgle"]
    assert {classify_phase(ab) for ab in cluster} == {"hero"}
    # chaque vœu reste aussi dans sa phase d'usage
    assert [classify_phase(ab) for ab in out if ab.ability_category == ""] == ["melee", "any"]
    # la sous-section suit le tour de « Vocation au Chaos » (votre phase des héros)
    assert all(_turn_sides(ab, out) == {TURN_MINE} for ab in cluster)
    assert _turn_sides(out[0], out) == {TURN_MINE, TURN_ENEMY}


def test_split_drops_alias_card_identical_to_its_unit():
    from dataclasses import replace

    from aospy.tournament_kit.sources.wahapedia_lookup import WarscrollData
    from aospy.tournament_kit.split_pool import _drop_identical_alias_cards

    base = WarscrollData(
        "Verminlord Warbringer", "ST", "", "", '10"', "4+", "5", "13", "5+", "1", "260", ["HERO"], [], []
    )
    alias = replace(base, name="Warbringer riche", subtitle="Verminlord Warbringer")
    sources = {"Warbringer riche": "Verminlord Warbringer"}
    assert _drop_identical_alias_cards([base, alias], sources) == [base]
    # une différence (points d'une optimisation payante) garde la carte
    paid = replace(alias, points="260+10")
    assert _drop_identical_alias_cards([base, paid], sources) == [base, paid]


def test_section_order_puts_named_unit_section_first_in_its_phase():
    from dataclasses import replace

    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _apply_section_order

    base = AbilityEntry(name="X", description="d", legend="", condition="Your Hero Phase", ability_phase="Hero Phase")
    skreech = replace(base, name="Rat", warscrolls=("Lord Skreech Verminking",))
    thanquol = replace(base, name="Jet", warscrolls=("Thanquol on Boneripper",))
    out = _apply_section_order([thanquol, skreech], {"hero": ("Lord Skreech Verminking",)})
    assert out[1].section_rank is not None and out[1].section_rank < 0
    assert out[0].section_rank is None


def test_alias_pill_dropped_when_base_unit_also_carries_the_ability():
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.split_pool import _collapse_alias_pills

    both = AbilityEntry(name="Coup", description="d", legend="", warscrolls=("Rich", "Verminlord Warbringer"))
    alone = AbilityEntry(name="Soupe", description="d", legend="", warscrolls=("Rich",))
    out = _collapse_alias_pills([both, alone], {"Rich": "Verminlord Warbringer"})
    assert out[0].warscrolls == ("Verminlord Warbringer",)
    assert out[1].warscrolls == ("Rich",)


def test_added_caster_level_replaces_existing_one():
    from aospy.tournament_kit.split_pool import _merge_unit_keywords

    assert _merge_unit_keywords(["HERO", "WIZARD (1)"], ["WIZARD (2)"]) == ["HERO", "WIZARD (2)"]
    assert _merge_unit_keywords(["HERO", "PRIEST (1)"], ["WIZARD (1)"]) == ["HERO", "PRIEST (1)", "WIZARD (1)"]

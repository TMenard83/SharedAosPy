"""Couche 4 — lectures corrigées après les contrôles des analyses de listes L3 (2026-11-25, analyseur v42)."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.assault import (
    AMBUSH_GAP,
    ChargeSource,
    _bonus,
    ambushers,
    charge_sources,
    move_bonuses,
)
from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.listing import (
    ListAbility,
    dead_rules,
    exclusive_group_of,
    list_receivers,
    marriages,
    missing_providers,
    prayer_turn_factor,
)
from aospy.analysis.layers.stacking import single_target_stacks, stack_for, stacks, target_choices
from aospy.domain.models import Unit, Weapon

AXE = Weapon("Axe", "melee", attacks=4, hit=4, wound=3, rend=1, damage=2)


def _u(name, kw=("SERAPHON", "INFANTRY"), move=6, save=4, ward=None):
    return Unit(name, 1, move, save, 10, 2, 5, 150, "HERO" in kw, ward=ward, keywords=frozenset(kw), weapons=[AXE])


def _ab(name, *, effects=(), scope="army", ft="", carriers=(), text="", freq="passive", source=None, **kw):
    base = dict(
        uid="u-" + name,
        name=name,
        source=source or (f"charte : {carriers[0]}" if carriers else "trait de bataille : Battle Traits"),
        source_kind="warscroll" if carriers else "battle_trait",
        carriers=tuple(carriers),
        scope=scope,
        frequency=freq,
        turn_side="any",
        phase="",
        cost_type="",
        cost_value=None,
        activation_prob=1.0,
        available_round=None,
        friendly_target=ft,
        excludes_self=False,
        verdict="plan",
        power=2.0,
        reliability=3.0,
        ease=3.0,
        interaction=3.0,
        effects=tuple(effects),
        text=text,
    )
    base.update(kw)
    return ListAbility(**base)


VOCAB = frozenset({"SERAPHON", "INFANTRY", "HERO", "WIZARD", "STORMCAST ETERNALS", "SKYVESSEL", "IRONJAWZ"})


# ----- options exclusives entre aptitudes (Délires, Astérismes) -------------------------------------------


def test_exclusive_group_from_keywords_or_text():
    assert exclusive_group_of("Asterism") == "Astérisme"
    text = "While you believe this DELUSION and this unit is on the battlefield, add 1"
    assert exclusive_group_of("", text) == "Délire"
    assert exclusive_group_of("Spell, Unlimited") == ""


def test_asterisms_one_per_unit_in_marriages_and_stack():
    u = _u("Saurus")
    hit = _ab("ITZL", effects=[EffectSpec("stat_mod", "hit", 1.0)], keywords="Asterism")
    save = _ab("QUETZL", effects=[EffectSpec("stat_mod", "save", 1.0)], keywords="Asterism")
    rows = marriages([hit, save], [u], VOCAB)
    assert len({m.ability for m in rows}) == 1
    st = stacks([hit, save], [u], VOCAB, core_costs={})[0]
    assert len(st.items) == 1
    # sans groupe, les deux s'empilent
    st2 = stacks([hit, _ab("QUETZL2", effects=[EffectSpec("stat_mod", "save", 1.0)])], [u], VOCAB, core_costs={})[0]
    assert len(st2.items) == 2


def test_stack_for_keeps_old_six_field_offers():
    u = _u("Saurus")
    st = stack_for(u, [("A", "x", EffectSpec("stat_mod", "hit", 1.0), "", "", 0)])
    assert st is not None and st.items[0].ability == "A"


# ----- assaut : paliers, Délires, bonus après une charge, embuscade, mouvement ---------------------------------


def test_charge_bonus_tiers_and_delusions_do_not_add_up():
    u = _u("Ushoran")
    names = (u.name,)
    srcs = [
        ChargeSource("Defenders", "charte", "bonus", 1, names, 1.0, False, group="Délire"),
        ChargeSource("Defenders", "charte", "bonus", 2, names, 1.0, False, group="Délire"),
        ChargeSource("One True King", "charte", "bonus", 1, names, 1.0, False, group="Délire"),
        ChargeSource("Banner", "charte", "bonus", 1, names, 1.0, False),
    ]
    assert _bonus(u, srcs, False) == 3  # Délire : +2 (palier le plus fort), + bannière +1 — pas +5


def test_charge_bonus_after_own_charge_is_not_permanent():
    paragon = _u("Thricefold", kw=("SERAPHON", "HERO"))
    ab = _ab(
        "CHIEF OF REVELS",
        scope="friendly_aura",
        ft="non-UNIQUE PARAGON",
        freq="once_per_turn_army",
        effects=[EffectSpec("stat_mod", "charge", 2.0)],
        text="Pick a friendly non-UNIQUE PARAGON that charged this turn and has not used a TEMPTATION ability this "
        "turn to use this ability. Until the start of your next turn, add 2 to charge rolls for friendly units.",
    )
    srcs = charge_sources([ab], [paragon], VOCAB)
    assert srcs and srcs[0].after_charge
    assert _bonus(paragon, srcs, False) == 0


def test_same_hero_limit_is_not_once_per_battle():
    hero = _u("Warchanter", kw=("IRONJAWZ", "HERO"))
    ab = _ab(
        "IRONJAWZ WAAAGH!",
        scope="one_friendly",
        ft="IRONJAWZ HERO",
        freq="once_per_turn_army",
        effects=[EffectSpec("stat_mod", "charge", 1.0)],
        text="Pick a friendly IRONJAWZ HERO to be the target. You cannot pick the same HERO to be the target of this "
        "ability more than once per battle. For the rest of the turn, add 1 to charge rolls.",
    )
    srcs = charge_sources([ab], [hero], VOCAB)
    assert srcs and not srcs[0].per_battle


def test_ambush_and_move_bonuses():
    drycha = _ab(
        "Merciless Ambush",
        carriers=("Drycha",),
        scope="self",
        freq="unlimited",
        text="You can remove this unit from the battlefield and set it up again within ½\" of an enemy unit and wholly "
        "within X\" of a terrain feature that has a friendly overgrown token, where X is equal to the charge roll. "
        "If you do so, this unit has charged.",
    )
    assert ambushers([drycha]) == {"Drycha"} and AMBUSH_GAP < 9
    k = _u("Kurnoth", kw=("SERAPHON", "INFANTRY"))
    horn = _ab("War-horn", scope="friendly_aura", carriers=("Belthanos",), ft="SERAPHON",
               effects=[EffectSpec("stat_mod", "move", 2.0)])
    aspect = _ab("Harvestboon", scope="self", carriers=("Kurnoth",), effects=[EffectSpec("stat_mod", "move", 2.0)])
    assert move_bonuses([horn, aspect], [k, _u("Belthanos")], VOCAB)["Kurnoth"] == 4.0


# ----- règles mortes à tort ---------------------------------------------------------------------------------


def test_provider_phrase_stops_before_to_use():
    slann = _u("Slann Starmaster", kw=("SERAPHON", "WIZARD", "HERO"))
    tl = _ab(
        "CELESTIAL TRANSLOCATION",
        scope="self",
        text='Pick a friendly SERAPHON unit wholly within 12" of a friendly SERAPHON WIZARD to use this ability. '
        "Remove that unit from the battlefield and set it up again.",
    )
    assert missing_providers([tl], [slann], VOCAB) == []
    assert missing_providers([tl], [_u("Saurus")], VOCAB)  # sans sorcier : toujours morte


def test_user_in_reserve_state_is_not_a_keyword():
    frigate = _u("Arkanaut Frigate", kw=("SKYVESSEL",))
    ab = _ab("DESCEND FROM THE CLOUDS", scope="self", freq="unlimited",
             text="Pick a friendly SKYVESSEL in the clouds to use this ability. Set up that SKYVESSEL anywhere.")
    assert dead_rules([ab], [frigate], VOCAB) == []


def test_optional_target_and_summon_target():
    relictor = _ab(
        "Relictor Soulguide",
        scope="one_friendly",
        ft="Knight-Questor",
        carriers=("Questor Soulsworn",),
        freq="once_per_battle",
        text="You can pick a friendly Knight-Questor within this unit's combat range to be the target. Remove this "
        "unit from the battlefield and set it up again.",
    )
    arcanum = _u("Knight-Arcanum", kw=("STORMCAST ETERNALS", "INFANTRY", "HERO", "WIZARD"))
    dais = _ab(
        "SUMMON DAIS ARCANUM",
        scope="one_friendly",
        ft="STORMCAST ETERNALS INFANTRY HERO",
        source_kind="manifestation",
        source="domaine de manifestations : Manifestations of the Storm",
        text="pick a friendly STORMCAST ETERNALS INFANTRY HERO that does not have FLY to be the target",
    )
    soul = _u("Questor Soulsworn", kw=("STORMCAST ETERNALS", "HERO"))
    assert dead_rules([relictor, dais], [soul, arcanum], VOCAB) == []


def test_named_battle_trait_only_on_its_warscroll():
    morathi = _u("Morathi-Khaine", kw=("SERAPHON", "HERO"))
    sisters = _u("Blood Sisters")
    dm = _ab("DARK MAJESTY", scope="self",
             text="If the unmodified hit roll for an attack made by a non-HERO unit that targets the friendly "
             "Morathi-Khaine is 1-4, the attack fails.")
    assert [u.name for u, _r in list_receivers(dm, [morathi, sisters], VOCAB)] == ["Morathi-Khaine"]


# ----- vœux (mot-clé gagné une unité par tour), prières répétées ---------------------------------------------


def test_pledge_keyword_counts_on_one_unit_only():
    units = [_u(f"U{i}") for i in range(3)]
    pledge = _ab("PLEDGED TO NURGLE", ft="PLEDGED TO NURGLE", effects=[EffectSpec("ward", value=6.0)])
    sts = stacks([pledge], units, VOCAB, core_costs={})
    assert len(target_choices([pledge], sts)) == 1
    single, _tcs = single_target_stacks([pledge], units, VOCAB, core_costs={})
    assert len(single) == 1


def test_repeated_prayer_rate_per_turn():
    bless = _ab("BLESS WEAPONS", cost_type="Prayer", cost_value="6", freq="unlimited", activation_prob=0.6389)
    frost = _ab("HOARFROST", cost_type="Prayer", cost_value="4", freq="unlimited", activation_prob=0.7778)
    assert bless.activation_prob * prayer_turn_factor(bless) == pytest.approx(0.32, abs=0.01)
    assert frost.activation_prob * prayer_turn_factor(frost) == pytest.approx(0.5, abs=0.01)
    once = _ab("ONCE", cost_type="Prayer", cost_value="6", freq="once_per_battle", activation_prob=0.64)
    assert prayer_turn_factor(once) == 1.0

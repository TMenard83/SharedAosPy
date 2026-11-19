"""Couche 3 — rencontre aptitude × châssis (analysis/encounter.py), cœur pur."""

from __future__ import annotations

import pytest

from aospy.analysis.encounter import EffectSpec, encounter, is_translatable, matches_friendly_target, receivers
from aospy.domain.models import Unit, Weapon


def _unit(weapons, **kw):
    base = dict(name="U", army_id=1, move=5, save=4, health=2, control=1, models=5, points=100,
                keywords=frozenset({"INFANTRY"}), weapons=weapons)
    base.update(kw)
    return Unit(**base)


SWORD = Weapon("Sword", "melee", attacks=2, hit=3, wound=3, damage=1)
AXE = Weapon("Great Axe", "melee", attacks=2, hit=3, wound=3, damage=3)
JAWS = Weapon("Jaws", "melee", attacks=2, hit=4, wound=3, damage=1, abilities="Companion")
BOW = Weapon("Bow", "ranged", attacks=1, hit=4, wound=4, damage=1, range_in=18)


def test_plus_one_damage_doubles_damage1_weapons_only_a_third_on_damage3():
    eff = EffectSpec("stat_mod", "damage", 1.0, weapon_scope="melee")
    assert encounter(_unit([SWORD]), eff).off_gain_pct == pytest.approx(100.0)
    assert encounter(_unit([AXE]), eff).off_gain_pct == pytest.approx(100.0 / 3)


def test_companion_weapons_excluded_unless_stated():
    eff = EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee")
    assert encounter(_unit([JAWS]), eff) is None
    both = encounter(_unit([SWORD, JAWS]), eff)
    assert 0 < both.off_gain_pct < 50.0           # seule l'épée profite
    incl = EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee", includes_companion=True)
    assert encounter(_unit([SWORD, JAWS]), incl).off_gain_pct == pytest.approx(50.0)


def test_scope_named_and_ranged():
    named = EffectSpec("stat_mod", "rend", 1.0, weapon_scope="named", weapon_name="Great Axe")
    assert encounter(_unit([SWORD]), named) is None
    assert encounter(_unit([SWORD, AXE]), named).off_gain_pct > 0
    ranged = EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="ranged")
    assert encounter(_unit([SWORD]), ranged) is None


def test_chosen_weapon_takes_the_best():
    chosen = EffectSpec("stat_set", detail="Double the Damage", weapon_scope="chosen")
    enc = encounter(_unit([SWORD, AXE]), chosen)
    single_axe = encounter(_unit([SWORD, AXE]), EffectSpec("stat_set", detail="Double the Damage",
                                                           weapon_scope="named", weapon_name="Great Axe"))
    assert enc.off_after == pytest.approx(single_axe.off_after)


def test_hit_modifier_capped_and_crit_on_5():
    big = encounter(_unit([SWORD]), EffectSpec("stat_mod", "hit", 2.0))
    one = encounter(_unit([SWORD]), EffectSpec("stat_mod", "hit", 1.0))
    assert big.off_after == pytest.approx(one.off_after)
    crit = encounter(_unit([SWORD]), EffectSpec("crit", detail="score critical hits on unmodified hit rolls of 5+ "
                                                              "Crit (Mortal)", weapon_scope="melee"))
    assert crit.off_gain_pct > 0


def test_wards_do_not_stack_and_save_capped():
    warded = _unit([SWORD], ward=5)
    assert encounter(warded, EffectSpec("ward", value=6.0)).def_gain_pct == pytest.approx(0.0)
    assert encounter(warded, EffectSpec("ward", value=4.0)).def_gain_pct > 0
    assert encounter(_unit([]), EffectSpec("stat_mod", "save", 1.0)).def_gain_pct > 0


def test_fight_twice_doubles_melee_only():
    enc = encounter(_unit([SWORD, BOW]), EffectSpec("fight_twice"))
    melee = encounter(_unit([SWORD]), EffectSpec("fight_twice"))
    assert melee.off_gain_pct == pytest.approx(100.0)
    assert 0 < enc.off_gain_pct < 100.0


def test_untranslated_effects():
    assert not is_translatable(EffectSpec("extra_fight", detail="can be picked to use a FIGHT ability"))
    assert not is_translatable(EffectSpec("stat_mod", "hit", -1.0, side="enemy"))
    assert not is_translatable(EffectSpec("reroll", detail="re-roll"))


VOCAB = frozenset({"HERO", "INFANTRY", "CAVALRY", "WARRIORS OF CHAOS", "SLAVES TO DARKNESS", "CHAOS"})


def test_friendly_target_resolution():
    warriors = _unit([], name="Chaos Warriors", keywords=frozenset({"INFANTRY", "WARRIORS OF CHAOS", "CHAOS"}))
    lord = _unit([], name="Chaos Lord", is_hero=True,
                 keywords=frozenset({"HERO", "INFANTRY", "WARRIORS OF CHAOS", "CHAOS"}))
    knights = _unit([], name="Chaos Knights", keywords=frozenset({"CAVALRY", "WARRIORS OF CHAOS", "CHAOS"}))
    phrase = "non-HERO WARRIORS OF CHAOS INFANTRY"
    assert matches_friendly_target(warriors, phrase, VOCAB)
    assert not matches_friendly_target(lord, phrase, VOCAB)
    assert not matches_friendly_target(knights, phrase, VOCAB)
    assert matches_friendly_target(knights, "Chaos Knights", VOCAB)
    assert matches_friendly_target(knights, "INFANTRY or CAVALRY", VOCAB)
    assert matches_friendly_target(knights, "PLEDGED TO SOMEONE", VOCAB)  # mot-clé acquis en jeu : ne filtre pas
    got = receivers("warscroll", "one_friendly", "warscroll", "Chaos Lord", [warriors, lord, knights], phrase, VOCAB)
    assert [u.name for u, _ in got] == ["Chaos Warriors"]
    self_only = receivers("warscroll", "self", "warscroll", "Chaos Lord", [warriors, lord, knights])
    assert self_only == [(lord, "porteur")]
    traits = receivers("heroic_trait", "self", "faction_rule", "Heroic Traits", [warriors, lord, knights])
    assert [u.name for u, _ in traits] == ["Chaos Lord"]


def test_ward_against_spells_only_is_worth_nothing_vs_weapons():
    u = _unit([SWORD])
    assert encounter(u, EffectSpec("ward", value=3.0, target_condition="vs sorts/manifestations")) is None
    assert encounter(u, EffectSpec("ward", value=3.0)).def_gain_pct > 0

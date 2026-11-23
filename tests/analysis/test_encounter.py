"""Couche 3 — rencontre aptitude × châssis (analysis/layers/encounter.py), cœur pur."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.encounter import EffectSpec, encounter, is_translatable, matches_friendly_target, receivers
from aospy.domain.models import Unit, Weapon


@pytest.fixture(autouse=True)
def _mean_reading(monkeypatch):
    """Ces tests vérifient la traduction des effets (rapports exacts sur les moyennes) : lecture à la
    moyenne. Le plancher `FLOOR_COVERAGE` a ses propres tests (`test_floor_*`)."""
    monkeypatch.setattr("aospy.analysis.layers.encounter.FLOOR_COVERAGE", None)


def _unit(weapons, **kw):
    base = dict(
        name="U",
        army_id=1,
        move=5,
        save=4,
        health=2,
        control=1,
        models=5,
        points=100,
        keywords=frozenset({"INFANTRY"}),
        weapons=weapons,
    )
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
    assert 0 < both.off_gain_pct < 50.0  # seule l'épée profite
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
    single_axe = encounter(
        _unit([SWORD, AXE]),
        EffectSpec("stat_set", detail="Double the Damage", weapon_scope="named", weapon_name="Great Axe"),
    )
    assert enc.off_after == pytest.approx(single_axe.off_after)


def test_hit_modifier_capped_and_crit_on_5():
    big = encounter(_unit([SWORD]), EffectSpec("stat_mod", "hit", 2.0))
    one = encounter(_unit([SWORD]), EffectSpec("stat_mod", "hit", 1.0))
    assert big.off_after == pytest.approx(one.off_after)
    crit = encounter(
        _unit([SWORD]),
        EffectSpec(
            "crit", detail="score critical hits on unmodified hit rolls of 5+ Crit (Mortal)", weapon_scope="melee"
        ),
    )
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
    assert not is_translatable(EffectSpec("stat_mod", "health", -1.0))  # faux effet ami (COLOSSAL SLAM)


VOCAB = frozenset({"HERO", "INFANTRY", "CAVALRY", "WARRIORS OF CHAOS", "SLAVES TO DARKNESS", "CHAOS"})


def test_friendly_target_resolution():
    warriors = _unit([], name="Chaos Warriors", keywords=frozenset({"INFANTRY", "WARRIORS OF CHAOS", "CHAOS"}))
    lord = _unit(
        [], name="Chaos Lord", is_hero=True, keywords=frozenset({"HERO", "INFANTRY", "WARRIORS OF CHAOS", "CHAOS"})
    )
    knights = _unit([], name="Chaos Knights", keywords=frozenset({"CAVALRY", "WARRIORS OF CHAOS", "CHAOS"}))
    phrase = "non-HERO WARRIORS OF CHAOS INFANTRY"
    assert matches_friendly_target(warriors, phrase, VOCAB)
    assert not matches_friendly_target(lord, phrase, VOCAB)
    assert not matches_friendly_target(knights, phrase, VOCAB)
    assert matches_friendly_target(knights, "Chaos Knights", VOCAB)
    assert matches_friendly_target(knights, "INFANTRY or CAVALRY", VOCAB)
    assert matches_friendly_target(knights, "PLEDGED TO SOMEONE", VOCAB)  # mot-clé acquis en jeu : ne filtre pas
    # mot-clé de régiment de renom : aucune charte de l'armée ne le porte, il ne s'étend pas à toute l'armée
    assert not matches_friendly_target(knights, "DROGGZ'S GITMOB", VOCAB)
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


def test_friendly_target_star_means_any_friendly_unit():
    """'*' (analyseur v27) : ligne d'option « for friendly units » sans mot-clé = toute unité amie."""
    u = Unit("Clanrats", 1, 6, 5, 1, 1, 20, 100, keywords=frozenset({"SKAVEN", "INFANTRY"}))
    assert matches_friendly_target(u, "*", VOCAB)


def test_mixed_unit_shoots_or_fights_each_round_not_both():
    from aospy.analysis.cost.features import _NO_MODS, _PROBE_SAVE4
    from aospy.analysis.layers.encounter import offense_parts, plan_offense, play_plan

    sic = Weapon("Pistol", "ranged", attacks=1, hit=4, wound=4, damage=1, range_in=9, abilities="Shoot in Combat")
    u = _unit([SWORD, SWORD, BOW, sic])
    melee, in_combat, other = offense_parts(u, _PROBE_SAVE4, _NO_MODS)
    plan = play_plan(u)
    assert plan.name == "mêlée"
    # au contact, l'arc ne tire plus ; le pistolet « Shoot in Combat » si
    assert plan.weapon_share(3) > plan.weapon_share(2)
    assert plan_offense(u, _PROBE_SAVE4, _NO_MODS) < melee + in_combat + other
    assert play_plan(_unit([BOW])).name.startswith("tir")


def test_slow_melee_unit_does_not_fight_in_round_1():
    from aospy.analysis.layers.approach import melee_plan

    slow, fast = melee_plan(_unit([SWORD], move=5)), melee_plan(_unit([SWORD], move=12))
    assert slow.weapon_share(0) == pytest.approx(8 / 9)  # 18" : ni charge ni tir au round 1, il court
    assert 8 / 9 < fast.weapon_share(0) < 1.0  # 12" + 2D6 ≥ 6 : 72 % au round 1


def test_short_range_shooter_gets_charged_more_than_long_range():
    from aospy.analysis.layers.approach import shooting_plan

    short = Weapon("Pistol", "ranged", attacks=2, hit=4, wound=4, damage=1, range_in=10)
    long_ = Weapon("Rifle", "ranged", attacks=2, hit=4, wound=4, damage=1, range_in=24)
    assert shooting_plan(_unit([short]), 10).weapon_share(0) < shooting_plan(_unit([long_]), 24).weapon_share(0)
    assert shooting_plan(_unit([long_]), 24).weapon_share(0) == pytest.approx(1.0)


def test_weapon_split_keeps_exclusive_choice_resolved_on_whole_unit():
    """Mêlée + tir mesurés à part = total de l'unité (pas de choix exclusif résolu par sous-ensemble)."""
    from aospy.analysis.cost.features import _NO_MODS, _PROBE_SAVE4
    from aospy.analysis.layers.chassis import chassis_profile
    from aospy.engine.combat import unit_damage_moments

    gun = Weapon("Big Gun", "ranged", attacks=3, hit=4, wound=3, damage=2, range_in=18)
    u = _unit(
        [SWORD, gun],
        models=3,
        description="1/3 models must be armed with 1 of the following options:<ul><li>Sword</li><li>Big Gun</li></ul>",
    )
    p = chassis_profile(u)
    total = unit_damage_moments(u, u.models, _PROBE_SAVE4, _NO_MODS)[0]
    assert p.dmg_melee + p.dmg_ranged == pytest.approx(total, abs=1e-3)


def test_smooth_floor_interpolates_between_integers():
    from aospy.analysis.layers.encounter import smooth_floor

    assert smooth_floor([1.0], 0.75) == 0.0  # rien de certain
    assert smooth_floor([0, 0, 0, 1.0], 0.75) == pytest.approx(3.0)  # 3 certain
    pmf = [0.2, 0.3, 0.5]  # P(≥1)=0,8, P(≥2)=0,5
    lo, hi = smooth_floor(pmf, 0.79), smooth_floor(pmf, 0.51)
    assert 0.5 < lo < hi < 2.0  # monotone, entre les entiers
    assert smooth_floor(pmf, 0.8 + 1e-9) == pytest.approx(smooth_floor(pmf, 0.8), abs=1e-6)  # continu


def _contact():
    from aospy.analysis.layers.approach import Plan

    return Plan("contact", ((1.0, frozenset({0})),))


def test_floor_penalises_swingy_profiles(monkeypatch):
    # Même dégât moyen : 12 attaques à 1 dégât vs 1 attaque à 12 dégâts (4+/4+ vs save 7).
    from aospy.analysis.cost.features import _NO_MODS
    from aospy.analysis.layers.encounter import plan_offense

    monkeypatch.setattr("aospy.analysis.layers.encounter.FLOOR_COVERAGE", 0.75)
    probe = Unit(name="p", army_id=0, move=0, save=7, health=1, control=0, models=1, points=0)
    steady = _unit([Weapon("Many", "melee", attacks=12, hit=4, wound=4, damage=1)], models=1)
    swingy = _unit([Weapon("Big", "melee", attacks=1, hit=4, wound=4, damage=12)], models=1)
    # même moyenne (3), mais 75 % du temps la grosse attaque ne fait rien : fort rabais (palier de 12 interpolé,
    # 2026-11-23), bien plus que pour le profil régulier
    sw = plan_offense(swingy, probe, _NO_MODS, _contact())
    st = plan_offense(steady, probe, _NO_MODS, _contact())
    assert sw <= 1.0 and 1.5 < st < 3.0 and sw < 0.5 * st


def test_fractional_damage_keeps_the_mean(monkeypatch):
    from aospy.analysis.cost.features import _NO_MODS, _PROBE_SAVE4
    from aospy.analysis.layers.encounter import plan_offense

    monkeypatch.setattr("aospy.analysis.layers.encounter.FLOOR_COVERAGE", None)
    d1 = plan_offense(
        _unit([Weapon("A", "melee", attacks=2, hit=4, wound=4, damage=1)]), _PROBE_SAVE4, _NO_MODS, _contact()
    )
    d2 = plan_offense(
        _unit([Weapon("A", "melee", attacks=2, hit=4, wound=4, damage=2)]), _PROBE_SAVE4, _NO_MODS, _contact()
    )
    d15 = plan_offense(
        _unit([Weapon("A", "melee", attacks=2, hit=4, wound=4, damage=1.5)]), _PROBE_SAVE4, _NO_MODS, _contact()
    )
    assert d15 == pytest.approx((d1 + d2) / 2)


def test_smooth_floor_interpolates_across_the_damage_step():
    """Arme à 4 dégâts : la distribution avance par paliers de 4 ; l'interpolation porte sur tout le palier, sinon
    un +1 pour toucher ne se voit presque pas au plancher (Avalenor : +10 % au lieu de ~+40 %)."""
    from aospy.analysis.layers.encounter import smooth_floor

    assert smooth_floor([0, 0, 0, 0, 1.0], 0.75) == pytest.approx(4.0)  # 4 certain
    lo = smooth_floor([0.30, 0, 0, 0, 0.70], 0.75)  # 4 dégâts à 70 % : sous le plancher de 75 %
    hi = smooth_floor([0.26, 0, 0, 0, 0.74], 0.75)  # 4 dégâts à 74 %
    # palier de 4 : x = 4 × (1 − c) / P(0) − 4 × (1 − c)
    assert lo == pytest.approx(4 * 0.25 / 0.30 - 1.0) and hi == pytest.approx(4 * 0.25 / 0.26 - 1.0)
    assert hi - lo > 0.4  # l'ancienne interpolation (un seul point) ne bougeait que de 0,13

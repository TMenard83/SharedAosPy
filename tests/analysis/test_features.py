"""Tests du vecteur de caractéristiques (features.py)."""

from __future__ import annotations

import pytest

from aospy.engine.combat import CombatModifiers, unit_damage_moments
from aospy.analysis.features import _PROBE_NOSAVE, _PROBE_SAVE2, _PROBE_SAVE4, compute_features
from aospy.domain.models import Unit, Weapon


def _unit(**overrides):
    base = dict(
        name="T", army_id=1, move=6, save=4, health=2, control=2,
        models=5, points=150, is_hero=False, ward=None, weapons=[],
    )
    base.update(overrides)
    return Unit(**base)


def test_no_weapons_gives_zero_offense():
    unit = _unit(weapons=[])
    feats = compute_features(unit)
    assert feats.dmg_vs_save2 == 0.0
    assert feats.dmg_vs_save4 == 0.0
    assert feats.dmg_vs_nosave == 0.0
    assert feats.dmg_ranged_vs_nosave == 0.0
    assert feats.dmg_pen == 0.0
    assert feats.dmg_cv_vs_save4 == 0.0


def test_offense_increases_as_save_weakens():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    assert feats.dmg_vs_save2 < feats.dmg_vs_save4 < feats.dmg_vs_nosave


def test_dmg_pen_matches_manual_ratio():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    mean2, _, _ = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, CombatModifiers())
    mean_nosave, _, _ = unit_damage_moments(unit, unit.models, _PROBE_NOSAVE, CombatModifiers())
    assert feats.dmg_pen == pytest.approx(mean2 / mean_nosave)


def test_dmg_cv_matches_manual_coefficient_of_variation():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    mean4, var4, _ = unit_damage_moments(unit, unit.models, _PROBE_SAVE4, CombatModifiers())
    assert feats.dmg_cv_vs_save4 == pytest.approx(var4**0.5 / mean4)


def test_ranged_split_isolates_ranged_weapons_only():
    melee = Weapon(name="m", kind="melee", attacks=2, hit=3, wound=3, damage=2, wielders=5)
    ranged = Weapon(name="r", kind="ranged", attacks=1, hit=4, wound=4, damage=1, wielders=5)
    mixed = _unit(weapons=[melee, ranged])
    ranged_only = _unit(weapons=[ranged])

    feats_mixed = compute_features(mixed)
    feats_ranged_only = compute_features(ranged_only)

    assert feats_mixed.dmg_ranged_vs_nosave == pytest.approx(feats_ranged_only.dmg_vs_nosave)
    assert feats_mixed.dmg_vs_nosave > feats_mixed.dmg_ranged_vs_nosave


def test_raw_characteristics_are_passed_through():
    unit = _unit(health=3, models=4, save=3, ward=5, move=8, control=2, is_hero=True, points=240)
    feats = compute_features(unit)
    assert feats.wounds_total == 12
    assert feats.save_num == 3
    assert feats.ward_num == 5
    assert feats.move == 8
    assert feats.control == 2
    assert feats.unit_size == 4
    assert feats.is_hero is True
    assert feats.points == 240


def test_ward_num_defaults_to_7_when_absent():
    unit = _unit(ward=None)
    feats = compute_features(unit)
    assert feats.ward_num == 7


def test_unit_type_and_caster_levels_from_keywords():
    unit = _unit(keywords=frozenset({"MONSTER", "FLY", "WIZARD (2)"}))
    feats = compute_features(unit)
    assert feats.unit_type == "MONSTER"
    assert feats.is_flying is True
    assert feats.wizard_level == 2
    assert feats.priest_level == 0


def test_unit_type_defaults_to_other_without_a_type_keyword():
    unit = _unit(keywords=frozenset({"HERO", "UNIQUE"}))
    feats = compute_features(unit)
    assert feats.unit_type == "OTHER"
    assert feats.is_flying is False


def test_charge_bonus_save2_zero_without_charge_ability():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    assert feats.charge_bonus_save2 == 0.0


def test_charge_bonus_save2_reflects_weapon_charge_ability():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2,
                    wielders=5, abilities="Charge (+1 Damage)")
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    mean2, _, _ = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, CombatModifiers())
    mean2_charged, _, _ = unit_damage_moments(
        unit, unit.models, _PROBE_SAVE2, CombatModifiers(attacker_charged=True),
    )
    assert feats.charge_bonus_save2 == pytest.approx(mean2_charged - mean2)
    assert feats.charge_bonus_save2 > 0.0


def test_crit_type_none_without_weapons_or_crit_text():
    unit = _unit(weapons=[])
    assert compute_features(unit).crit_type == "none"
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, damage=2, wielders=5)
    assert compute_features(_unit(weapons=[weapon])).crit_type == "none"


def test_crit_type_picks_the_highest_damage_weapon_profile():
    # "main" cogne beaucoup plus fort que "side" : le crit dominant doit être celui
    # de "main" (Mortal), pas celui de "side" (2 Hits), même si "side" est listé en premier.
    side = Weapon(name="side", kind="melee", attacks=1, hit=5, wound=5, damage=1,
                  wielders=5, abilities="Crit (2 Hits)")
    main = Weapon(name="main", kind="melee", attacks=4, hit=3, wound=3, damage=3,
                  wielders=5, abilities="Crit (Mortal)")
    unit = _unit(weapons=[side, main])
    assert compute_features(unit).crit_type == "mortal"

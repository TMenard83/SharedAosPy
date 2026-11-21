"""Tests du vecteur de caractéristiques (features.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.cost.features import _PROBE_SAVE2, _PROBE_SAVE4, _PROBE_SAVE6, compute_features
from aospy.domain.models import Unit, Weapon
from aospy.engine.combat import CombatModifiers, unit_damage_moments


def _unit(**overrides):
    base = dict(
        name="T",
        army_id=1,
        move=6,
        save=4,
        health=2,
        control=2,
        models=5,
        points=150,
        is_hero=False,
        ward=None,
        weapons=[],
    )
    base.update(overrides)
    return Unit(**base)


def test_no_weapons_gives_zero_offense():
    unit = _unit(weapons=[])
    feats = compute_features(unit)
    assert feats.dmg_vs_save2 == 0.0
    assert feats.dmg_vs_save4 == 0.0
    assert feats.dmg_vs_save6 == 0.0
    assert feats.dmg_melee_vs_save6 == 0.0
    assert feats.dmg_ranged_vs_save6 == 0.0
    assert feats.dmg_melee_vs_save2 == 0.0
    assert feats.dmg_ranged_vs_save2 == 0.0
    assert feats.dmg_pen == 0.0
    assert feats.dmg_vs_save2_sq == 0.0
    assert feats.dmg_cv_vs_save4 == 0.0


def test_offense_increases_as_save_weakens():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    assert feats.dmg_vs_save2 < feats.dmg_vs_save4 < feats.dmg_vs_save6


def test_dmg_pen_matches_manual_ratio():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    mean2, _, _ = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, CombatModifiers())
    mean6, _, _ = unit_damage_moments(unit, unit.models, _PROBE_SAVE6, CombatModifiers())
    assert feats.dmg_pen == pytest.approx(mean2 / mean6)


def test_dmg_vs_save2_sq_is_the_square_of_dmg_vs_save2():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    assert feats.dmg_vs_save2_sq == pytest.approx(feats.dmg_vs_save2**2)


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

    assert feats_mixed.dmg_ranged_vs_save6 == pytest.approx(feats_ranged_only.dmg_vs_save6)
    assert feats_mixed.dmg_vs_save6 > feats_mixed.dmg_ranged_vs_save6


def test_melee_split_isolates_melee_weapons_only():
    melee = Weapon(name="m", kind="melee", attacks=2, hit=3, wound=3, damage=2, wielders=5)
    ranged = Weapon(name="r", kind="ranged", attacks=1, hit=4, wound=4, damage=1, wielders=5)
    mixed = _unit(weapons=[melee, ranged])
    melee_only = _unit(weapons=[melee])

    feats_mixed = compute_features(mixed)
    feats_melee_only = compute_features(melee_only)

    assert feats_mixed.dmg_melee_vs_save6 == pytest.approx(feats_melee_only.dmg_vs_save6)
    assert feats_mixed.dmg_melee_vs_save6 + feats_mixed.dmg_ranged_vs_save6 == pytest.approx(feats_mixed.dmg_vs_save6)


def test_melee_ranged_split_isolates_weapons_on_the_pen_axis_too():
    melee = Weapon(name="m", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5)
    ranged = Weapon(name="r", kind="ranged", attacks=1, hit=4, wound=4, rend=1, damage=1, wielders=5)
    mixed = _unit(weapons=[melee, ranged])
    melee_only = _unit(weapons=[melee])
    ranged_only = _unit(weapons=[ranged])

    feats_mixed = compute_features(mixed)
    feats_melee_only = compute_features(melee_only)
    feats_ranged_only = compute_features(ranged_only)

    assert feats_mixed.dmg_melee_vs_save2 == pytest.approx(feats_melee_only.dmg_vs_save2)
    assert feats_mixed.dmg_ranged_vs_save2 == pytest.approx(feats_ranged_only.dmg_vs_save2)
    assert feats_mixed.dmg_melee_vs_save2 + feats_mixed.dmg_ranged_vs_save2 == pytest.approx(feats_mixed.dmg_vs_save2)


def test_raw_characteristics_are_passed_through():
    unit = _unit(health=3, models=4, save=3, ward=5, move=8, control=2, is_hero=True, points=240)
    feats = compute_features(unit)
    assert feats.wounds_total == 12
    assert feats.save_num == 3
    assert feats.ward_num == 5
    assert feats.move == 8
    assert feats.control == 2
    assert feats.unit_size == 4
    assert feats.unit_size_sq == 16
    assert feats.is_hero is True
    assert feats.points == 240


def test_ward_num_defaults_to_7_when_absent():
    unit = _unit(ward=None)
    feats = compute_features(unit)
    assert feats.ward_num == 7


def test_effective_wounds_matches_manual_formula_without_ward():
    # save nue 4+, dégradée par _REPRESENTATIVE_REND=1 -> save effective 5+, P(échec)=4/6
    unit = _unit(health=2, models=5, save=4, ward=None)  # wounds_total=10
    feats = compute_features(unit)
    assert feats.effective_wounds == pytest.approx(10 / (4 / 6))


def test_effective_wounds_accounts_for_ward():
    # save nue 4+ -> effective 5+ (Rend représentatif 1), P(échec save)=4/6 ; P(échec ward 5+)=4/6
    unit = _unit(health=2, models=5, save=4, ward=5)
    feats = compute_features(unit)
    assert feats.effective_wounds == pytest.approx(10 / ((4 / 6) * (4 / 6)))


def test_effective_wounds_grows_with_better_defense():
    weak = _unit(health=2, models=5, save=6, ward=None)
    strong = _unit(health=2, models=5, save=2, ward=4)
    assert compute_features(weak).effective_wounds < compute_features(strong).effective_wounds


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
    weapon = Weapon(
        name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=5, abilities="Charge (+1 Damage)"
    )
    unit = _unit(weapons=[weapon])
    feats = compute_features(unit)
    mean2, _, _ = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, CombatModifiers())
    mean2_charged, _, _ = unit_damage_moments(
        unit,
        unit.models,
        _PROBE_SAVE2,
        CombatModifiers(attacker_charged=True),
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
    side = Weapon(name="side", kind="melee", attacks=1, hit=5, wound=5, damage=1, wielders=5, abilities="Crit (2 Hits)")
    main = Weapon(name="main", kind="melee", attacks=4, hit=3, wound=3, damage=3, wielders=5, abilities="Crit (Mortal)")
    unit = _unit(weapons=[side, main])
    assert compute_features(unit).crit_type == "mortal"


# ----- contrôle tacite (expected_control) -----------------------------------

import pytest as _pytest

from aospy.analysis.cost.features import expected_control
from aospy.domain.models import Unit as _Unit


def _u(name="U", models=1, health=5, control=2, hero=False, kw=()):
    return _Unit(
        name=name,
        army_id=1,
        move=5,
        save=4,
        health=health,
        control=control,
        models=models,
        points=100,
        is_hero=hero,
        keywords=frozenset(kw),
    )


@_pytest.mark.parametrize(
    "unit,expected",
    [
        (_u(models=10, health=1, kw=("INFANTRY",)), 1),  # infanterie légère
        (_u(models=3, health=5, kw=("INFANTRY",)), 2),  # grosse infanterie (5 PV)
        (_u(models=3, health=4, kw=("INFANTRY", "OGOR MAWTRIBES")), 2),  # Ogors : 2 dès 4 PV
        (_u(models=3, health=3, hero=True, kw=("INFANTRY", "HERO")), 2),  # équipe de héros
        (_u(health=8, kw=("BEAST",)), 1),  # bête
        (_u(health=8, kw=("MONSTER",)), 5),  # monstre, même léger
        (_u(health=14, kw=("MONSTER", "OGOR MAWTRIBES")), 10),  # monstre Ogor
        (_u(health=12, kw=("MONSTER", "SONS OF BEHEMAT", "LITTLE")), 5),  # petit Gargant
        (_u(health=25, kw=("MONSTER", "SONS OF BEHEMAT", "BIG")), 10),  # Mega-Gargant
        (_u(name="Knight-Vexillor", health=6, hero=True, kw=("INFANTRY", "HERO")), 5),  # porte-étendard
        (_u(health=8, hero=True, kw=("INFANTRY", "HERO", "OGOR MAWTRIBES")), 3),  # héros Ogor à pied
        (_u(health=10, kw=("WAR MACHINE",)), 2),  # char / artillerie
        (_u(health=12, kw=("WAR MACHINE",)), 5),  # autel / grosse machine
        (_u(health=9, hero=True, kw=("INFANTRY", "HERO")), 2),
        (_u(health=10, hero=True, kw=("CAVALRY", "HERO")), 5),  # héros monté : 2 = déficit voulu
        (_u(name="Loonboss on Giant Cave Squig", health=6, hero=True, kw=("CAVALRY", "HERO")), 5),
    ],
)
def test_expected_control_rule(unit, expected):
    assert expected_control(unit) == expected


def test_control_bonus_and_deficit_features():
    epic = compute_features(_u(health=25, control=10, kw=("MONSTER",)))
    assert (epic.control_expected, epic.control_bonus, epic.control_deficit) == (5, 5, 0)
    mounted = compute_features(_u(health=10, control=2, hero=True, kw=("CAVALRY", "HERO")))
    assert (mounted.control_bonus, mounted.control_deficit) == (0, 3)

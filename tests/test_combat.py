"""Tests Phase 4 : math de dégât espéré + simulation."""

from __future__ import annotations

import math

import pytest

from aospy.combat import (
    CombatModifiers,
    _parse_crit,
    _prob_x_plus,
    expected_unit_damage,
    expected_weapon_damage,
)
from aospy.models import Unit, Weapon


def _unit(save=4, health=2, ward=None, weapons=None, models=5):
    return Unit(
        name="T", army_id=1, move=5, save=save, health=health, control=1,
        models=models, points=100, ward=ward, weapons=weapons or [],
    )


def test_prob_x_plus_basic():
    assert _prob_x_plus(3) == pytest.approx(4 / 6)
    assert _prob_x_plus(6) == pytest.approx(1 / 6)
    assert _prob_x_plus(2) == pytest.approx(5 / 6)


def test_prob_x_plus_modifier_caps_at_2():
    # 3+ avec +1 → 2+ (5/6), 2+ avec +1 → reste 2+
    assert _prob_x_plus(3, 1) == pytest.approx(5 / 6)
    assert _prob_x_plus(2, 1) == pytest.approx(5 / 6)


def test_prob_x_plus_impossible_when_above_6():
    assert _prob_x_plus(7) == 0.0
    assert _prob_x_plus(8) == 0.0


def test_parse_crit_variants():
    assert _parse_crit("Crit (2 Hits)") == "2hits"
    assert _parse_crit("Crit (Mortal Wounds)") == "mortal"
    assert _parse_crit("Crit (Auto-Wound)") == "autowound"
    assert _parse_crit("rien") == "none"
    assert _parse_crit(None) == "none"


def test_expected_damage_simple_no_ward_no_rend():
    # 10 attaques, 4+ hit, 4+ wound, save 4+, rend 0, dmg 1, ward off
    # E = 10 * 1/2 * 1/2 * (1 - 1/2) * 1 = 1.25
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, rend=0, damage=1)
    defender = _unit(save=4, ward=None)
    mods = CombatModifiers()
    result = expected_weapon_damage(weapon, attacker_models=5, defender=defender, modifiers=mods)
    assert result == pytest.approx(1.25)


def test_expected_damage_with_rend_and_ward():
    # 10 atk, 3+ hit (4/6), 3+ wound (4/6), save 4+ rend 1 → save 5+ (2/6),
    # unsaved = 1 - 2/6 = 4/6 ; ward 5+ (2/6) → ward_mult = 4/6
    # dmg = 2 ; E = 10 * 4/6 * 4/6 * 4/6 * 2 * 4/6 ≈ 1.97...
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2)
    defender = _unit(save=4, ward=5)
    mods = CombatModifiers()
    result = expected_weapon_damage(weapon, 5, defender, mods)
    expected = 10 * (4/6) * (4/6) * (4/6) * 2 * (4/6)
    assert result == pytest.approx(expected)


def test_rend_makes_save_impossible_when_eff_above_6():
    # save 6+ + rend 2 → 8+ → P_save = 0
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=2, wound=2, rend=2, damage=1)
    defender = _unit(save=6, ward=None)
    # 5 atk, hit 5/6, wound 5/6, unsaved 1, ward 1, dmg 1
    expected = 5 * (5/6) * (5/6) * 1.0 * 1
    assert expected_weapon_damage(weapon, 5, defender, CombatModifiers()) == pytest.approx(expected)


def test_charge_bonus_adds_attack_to_melee_only():
    melee = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1)
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1)
    defender = _unit(save=7)  # save impossible → P_unsaved = 1
    mods = CombatModifiers(attacker_charged=True)

    # Mêlée : 3 atk/model * 5 models = 15, hit 1/2, wound 1/2, dmg 1 = 3.75
    assert expected_weapon_damage(melee, 5, defender, mods) == pytest.approx(15 * 0.5 * 0.5)
    # Distance : pas de bonus
    assert expected_weapon_damage(ranged, 5, defender, mods) == pytest.approx(10 * 0.5 * 0.5)


def test_all_out_attack_improves_hit():
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=4, wound=4, damage=1)
    defender = _unit(save=7)
    base = expected_weapon_damage(weapon, 5, defender, CombatModifiers())
    boosted = expected_weapon_damage(
        weapon, 5, defender, CombatModifiers(attacker_all_out_attack=True)
    )
    # base: 5 * 3/6 * 3/6 = 1.25 ; boosted: 5 * 4/6 * 3/6 ≈ 1.667
    assert base == pytest.approx(1.25)
    assert boosted == pytest.approx(5 * (4/6) * (3/6))


def test_all_out_defense_improves_save():
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=2, wound=2, rend=0, damage=1)
    defender = _unit(save=4)
    base = expected_weapon_damage(weapon, 5, defender, CombatModifiers())
    defended = expected_weapon_damage(
        weapon, 5, defender, CombatModifiers(defender_all_out_defense=True)
    )
    # base: save 4+ (3/6), unsaved 3/6. defended: save 3+ (4/6), unsaved 2/6.
    assert defended < base


def test_crit_2_hits():
    # 6 atk, 4+ hit, 4+ wound, save 7 (impossible), dmg 1, Crit (2 Hits)
    # P_normal_hit = 1/2 - 1/6 = 2/6 ; P_crit = 1/6
    # E[hits] = 6 * (2/6 + 2 * 1/6) = 6 * 4/6 = 4
    # E[unsaved] = 4 * 1/2 = 2
    weapon = Weapon(name="w", kind="melee", attacks=6, hit=4, wound=4, damage=1,
                    abilities="Crit (2 Hits)")
    defender = _unit(save=7)
    result = expected_weapon_damage(weapon, 1, defender, CombatModifiers())
    assert result == pytest.approx(2.0)


def test_crit_auto_wound_skips_wound_roll():
    # 6 atk, 4+ hit, 6+ wound, save 7. Normal: 6*1/2*1/6 = 0.5
    # Auto-wound: normal_hits=6*2/6=2, crit_hits=6*1/6=1
    # wounds = 2*1/6 + 1 = 1.333..., unsaved = wounds (no save), dmg 1
    weapon = Weapon(name="w", kind="melee", attacks=6, hit=4, wound=6, damage=1,
                    abilities="Crit (Auto-Wound)")
    defender = _unit(save=7)
    result = expected_weapon_damage(weapon, 1, defender, CombatModifiers())
    assert result == pytest.approx(2 * (1/6) + 1)


def test_crit_mortal_bypasses_wound_and_save():
    # crit dmg passe outre save & wound mais subit ward
    weapon = Weapon(name="w", kind="melee", attacks=6, hit=4, wound=6, damage=2,
                    abilities="Crit (Mortal Wounds)")
    defender = _unit(save=2, ward=5)  # save 2+ bloque presque tout, mortels passent
    result = expected_weapon_damage(weapon, 1, defender, CombatModifiers())
    # crit_hits = 1, mortels = 1 * 2 = 2 ; normal_hits = 2, wounds = 2*1/6, save 2+ (5/6) unsaved 1/6
    # normal damage = (2*1/6)*1/6 * 2 ≈ 0.111
    # ward = 5+ → 1 - 2/6 = 4/6 multiplier
    expected = ((2 * (1/6) * (1/6) * 2) + (1 * 2)) * (4/6)
    assert result == pytest.approx(expected)

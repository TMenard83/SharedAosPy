"""Tests : application de bonus génériques (StatDelta) à une unité, hors DB."""

from __future__ import annotations

from aospy.bonus_simulator.bonus import Bonus, StatDelta, apply_bonus, combine
from aospy.domain.models import Unit, Weapon


def _unit(save=4, ward=None, weapons=None):
    return Unit(
        name="T", army_id=1, move=5, save=save, health=2, control=1,
        models=5, points=100, ward=ward, weapons=weapons or [_weapon()],
    )


def _weapon(hit=3, wound=3, rend=0, damage=1, attacks=2):
    return Weapon(name="Warhammer", kind="melee", attacks=attacks, hit=hit, wound=wound, rend=rend, damage=damage)


def test_no_delta_is_noop():
    unit = _unit()
    assert apply_bonus(unit, StatDelta()) is unit


def test_delta_applies_to_hit_wound_rend_damage_attacks():
    unit = _unit()
    bonus = apply_bonus(unit, StatDelta(hit=1, wound=1, rend=1, damage=1, attacks=1))
    w = bonus.weapons[0]
    assert w.hit == 2  # 3+ -> 2+
    assert w.wound == 2
    assert w.rend == 1
    assert w.damage == 2
    assert w.attacks == 3
    # arme d'origine inchangée (copie), nom préservé (matching loadout.py)
    assert unit.weapons[0].hit == 3
    assert w.name == "Warhammer"


def test_hit_wound_capped_at_2_plus():
    unit = _unit(weapons=[_weapon(hit=2, wound=2)])
    bonus = apply_bonus(unit, StatDelta(hit=5, wound=5))
    assert bonus.weapons[0].hit == 2
    assert bonus.weapons[0].wound == 2


def test_negative_delta_worsens_stats():
    unit = _unit()
    bonus = apply_bonus(unit, StatDelta(hit=-1, wound=-1))
    assert bonus.weapons[0].hit == 4
    assert bonus.weapons[0].wound == 4


def test_rend_and_damage_floor_at_zero():
    unit = _unit(weapons=[_weapon(rend=0, damage=1)])
    bonus = apply_bonus(unit, StatDelta(rend=-5, damage=-5))
    assert bonus.weapons[0].rend == 0
    assert bonus.weapons[0].damage == 0


def test_save_bonus_improves_and_caps_at_2_plus():
    unit = _unit(save=4)
    bonus = apply_bonus(unit, StatDelta(save=1))
    assert bonus.save == 3
    bonus2 = apply_bonus(unit, StatDelta(save=10))
    assert bonus2.save == 2


def test_ward_bonus_grants_ward_when_absent():
    unit = _unit(ward=None)
    bonus = apply_bonus(unit, StatDelta(ward=1))
    assert bonus.ward == 6


def test_ward_bonus_improves_existing_ward():
    unit = _unit(ward=5)
    bonus = apply_bonus(unit, StatDelta(ward=1))
    assert bonus.ward == 4


def test_ward_penalty_can_remove_ward():
    unit = _unit(ward=6)
    bonus = apply_bonus(unit, StatDelta(ward=-1))
    assert bonus.ward is None


def test_combine_sums_deltas():
    total = combine([StatDelta(hit=1), StatDelta(hit=1, wound=1), StatDelta()])
    assert total == StatDelta(hit=2, wound=1)


def test_bonus_dataclass_holds_named_delta():
    b = Bonus(name="Heure de Gloire", description="...", delta=StatDelta(wound=1, save=1))
    assert b.delta.wound == 1 and b.delta.save == 1

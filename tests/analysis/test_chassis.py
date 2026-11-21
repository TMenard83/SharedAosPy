"""Couche 2 — profil de châssis (analysis/layers/chassis.py), cœur pur."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.chassis import chassis_profile, is_companion, pct_rank
from aospy.domain.models import Unit, Weapon


def _unit(weapons, **kw):
    base = dict(name="U", army_id=1, move=5, save=4, health=2, control=1, models=5, points=100,
                keywords=frozenset({"INFANTRY"}), weapons=weapons)
    base.update(kw)
    return Unit(**base)


def test_shares_damage1_companion_and_melee():
    sword = Weapon("Sword", "melee", attacks=2, hit=3, wound=3, damage=1)
    beast = Weapon("Jaws", "melee", attacks=2, hit=4, wound=3, damage=2, abilities="Companion")
    bow = Weapon("Bow", "ranged", attacks=1, hit=4, wound=4, damage=1, range_in=18)
    p = chassis_profile(_unit([sword, beast, bow]))
    total = p.dmg_melee + p.dmg_ranged
    assert 0 < p.share_companion < 1 and 0 < p.share_damage1 < 1 and 0 < p.share_melee < 1
    assert p.dmg_per_100 == pytest.approx(total, abs=0.01)          # 100 pts
    assert p.attacks_total == (2 + 2 + 1) * 5
    assert is_companion(beast) and not is_companion(sword)


def test_durability_counts_ward_and_points():
    plain = chassis_profile(_unit([], save=4))
    warded = chassis_profile(_unit([], save=4, ward=5))
    assert warded.effective_wounds == pytest.approx(plain.effective_wounds * 1.5)
    assert plain.dmg_per_100 == 0 and plain.share_melee == 0


def test_pct_rank_ties_and_bounds():
    assert pct_rank([1.0, 3.0, 2.0]) == [0.0, 1.0, 0.5]
    assert pct_rank([2.0, 2.0]) == [0.5, 0.5]


def test_attacks_total_follows_loadout_description():
    pistol = Weapon("Pistol", "ranged", attacks=2, hit=4, wound=4, damage=1, range_in=9)
    heavy = Weapon("Heavy Gun", "ranged", attacks=2, hit=4, wound=3, damage=2, range_in=12)
    u = _unit([pistol, heavy], models=10,
              description="Each model is armed with a Pistol. 2/10 models can replace their Pistol with a Heavy Gun.")
    assert chassis_profile(u).attacks_total == 2 * 8 + 2 * 2

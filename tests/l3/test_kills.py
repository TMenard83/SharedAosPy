from types import SimpleNamespace

import pytest

from aospy.domain.models import Unit, Weapon
from aospy.l3 import kills
from aospy.l3 import matchups as mx
from aospy.l3.layer4 import L4Indices


def _list(player, names, l4=None):
    w = Weapon(name="Lame", kind="melee", attacks=4, hit=3, wound=3, rend=1, damage=2)
    al = mx.ArmyList(player, "T", "F")
    for n in names:
        u = Unit(name=n, army_id=1, move=5, save=4, health=5, control=1, models=1, points=100, weapons=[w])
        al.entries.append(mx.Entry(u, 1, False, 100, n))
    al.prof = SimpleNamespace(charge_unit={}, charge_army=0.0)
    al.l4 = l4
    return al


def test_groups_merge_identical_entries():
    al = _list("A", ["X", "Y", "X"])
    assert [(e.label, n) for e, n in kills.groups(al)] == [("X", 2), ("Y", 1)]


def test_buffs_scale_activations():
    a, b = _list("A", ["X"]), _list("B", ["Y"])
    bare = kills.matrix(a, b, {}, buffs=False)[0][0]
    a.l4 = L4Indices(unit_off={"X": 2.0})
    b.l4 = L4Indices(unit_def={"Y": 1.5})
    buffed = kills.matrix(a, b, {}, buffs=True)[0][0]
    assert buffed.damage == pytest.approx(2 * bare.damage)
    assert buffed.activations == pytest.approx(bare.activations * 1.5 / 2)
    assert kills.matrix(a, b, {}, buffs=False)[0][0].activations == pytest.approx(bare.activations)

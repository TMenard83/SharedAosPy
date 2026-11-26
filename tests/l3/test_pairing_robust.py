import random

import pytest

from aospy.l3.pairing_robust import guaranteed, pivots
from aospy.l3.pairing_scores import assemble

OURS = [f"n{i}" for i in range(6)]
THEIRS = [f"e{i}" for i in range(6)]
MAPS = ["m1", "m2", "m3"]


def _input(seed=1):
    rnd = random.Random(seed)
    grid = {(u, t): rnd.uniform(-8, 8) for u in OURS for t in THEIRS}
    return assemble("Nous", "Eux", 1, OURS, THEIRS, MAPS, grid, lambda u, t, m: 0.0)


def test_guaranteed_is_worst_column():
    assert guaranteed([[1, 3], [2, 0]], [0.5, 0.5]) == pytest.approx(1.5)
    assert guaranteed([[1, 3], [2, 0]], [1.0, 0.0]) == pytest.approx(1.0)


@pytest.mark.parametrize("mode", ["prudent", "mixte"])
def test_regret_is_never_negative(mode):
    (v0, mix), rows = pivots(_input(), mode, delta=3.0)
    assert len(rows) == 72  # 36 cases × ±δ
    assert sum(mix.values()) == pytest.approx(1.0, abs=0.02)
    assert all(r[4] >= -1e-6 for r in rows)  # rejouer l'ancien plan ne fait jamais mieux que l'optimum
    assert [r[4] for r in rows] == sorted((r[4] for r in rows), reverse=True)


def test_zero_shift_has_no_regret():
    _, rows = pivots(_input(), "mixte", delta=0.0)
    assert max(r[4] for r in rows) == pytest.approx(0.0, abs=1e-6)

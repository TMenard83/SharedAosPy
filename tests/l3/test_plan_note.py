import math

from aospy.l3.plan_note import _round, _spearman, fit, loo


def test_ridge_recovers_linear_relation():
    xs = [[float(i), float(i % 3)] for i in range(20)]
    ys = [0.1 * x[0] + 0.5 * x[1] for x in xs]
    pred, _w = fit(xs, ys, lam=1e-6)
    assert all(math.isclose(pred(x), y, abs_tol=1e-6) for x, y in zip(xs, ys))


def test_loo_leaves_the_point_out():
    xs = [[float(i)] for i in range(10)]
    ys = [float(i) for i in range(10)]
    ys[5] = 50.0  # point aberrant : sa prédiction ne doit pas le voir
    p = loo(xs, ys, lam=1e-6)
    assert p[5] < 20


def test_round_clamps_to_scale():
    assert _round(3.7) == 3 and _round(-0.4) == 0 and _round(1.5) == 2 and _round(1.49) == 1


def test_spearman_ties_and_order():
    assert math.isclose(_spearman([1, 2, 3], [10, 20, 30]), 1.0)
    assert math.isclose(_spearman([1, 2, 3], [3, 2, 1]), -1.0)
    assert -1 <= _spearman([1, 1, 2, 2], [1, 2, 1, 2]) <= 1

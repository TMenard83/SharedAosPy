import random

import pytest

from aospy.l3.pairing import Pairing, solve_mixed, solve_pure

US = ["u1", "u2", "u3", "u4", "u5", "u6"]
THEM = ["t1", "t2", "t3", "t4", "t5", "t6"]
MAPS = ["A", "B", "C"]


def test_matching_pennies():
    v, x, y = solve_mixed([[1, -1], [-1, 1]])
    assert v == pytest.approx(0) and x == pytest.approx([0.5, 0.5]) and y == pytest.approx([0.5, 0.5])


def test_saddle_point_is_pure():
    assert solve_mixed([[3, 5], [1, 4]])[:2] == (3, [1.0, 0.0])
    assert solve_pure([[3, 5], [1, 4]])[0] == 3


def test_rock_paper_scissors():
    pytest.importorskip("scipy")
    v, x, _ = solve_mixed([[0, -1, 1], [1, 0, -1], [-1, 1, 0]])
    assert v == pytest.approx(0, abs=1e-9) and x == pytest.approx([1 / 3] * 3)


@pytest.mark.parametrize("mode", ["mixte", "prudent"])
def test_separable_score_ignores_pairing(mode):
    a = {p: i for i, p in enumerate(US)}
    b = {q: 2 * i for i, q in enumerate(THEM)}
    P = Pairing(lambda p, q, m: a[p] - b[q], US, THEM, MAPS, mode)
    assert P.value(frozenset(US), frozenset(THEM)) == pytest.approx(sum(a.values()) - sum(b.values()))


def test_two_games_per_map():
    P = Pairing(lambda p, q, m: {"A": 1, "B": 10, "C": 100}[m], US, THEM, MAPS, "prudent")
    assert P.value(frozenset(US), frozenset(THEM)) == 222


def test_defender_avoids_its_bad_matchup():
    # u1 ne perd que contre t1 : en défense, il choisit l'autre attaquant proposé.
    def score(p, q, m):
        return -10 if (p, q) == ("u1", "t1") else 0

    P = Pairing(score, US, THEM, MAPS, "prudent")
    U, T = frozenset(US), frozenset(THEM)
    M = P.picks(U, T, "u1", "t6", ("u2", "u3"), ("t1", "t2"))
    assert M[1][0] > M[0][0]  # face à t2 plutôt que t1
    assert P.value(U, T) == 0  # u1 en défense dès l'étape 1 neutralise t1


def test_mixed_at_least_prudent():
    pytest.importorskip("scipy")
    rng = random.Random(3)
    g = {(p, q): rng.randint(-8, 8) for p in US for q in THEM}
    U, T = frozenset(US), frozenset(THEM)
    vm = Pairing(lambda p, q, m: g[(p, q)], US, THEM, MAPS, "mixte").value(U, T)
    vp = Pairing(lambda p, q, m: g[(p, q)], US, THEM, MAPS, "prudent").value(U, T)
    assert vm >= vp - 1e-9

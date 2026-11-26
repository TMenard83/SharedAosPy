import json

import pytest

from aospy.l3 import pairing_noise as pn
from aospy.l3.pairing_scores import assemble

OURS = [f"n{i}" for i in range(6)]
THEIRS = [f"e{i}" for i in range(6)]


def _input():
    grid = {(u, t): (i - j) * 1.5 for i, u in enumerate(OURS) for j, t in enumerate(THEIRS)}
    return assemble("Nous", "Eux", 1, OURS, THEIRS, ["m1", "m2", "m3"], grid, lambda u, t, m: 0.0)


def test_confidence_levels(tmp_path):
    (tmp_path / "combos").mkdir()
    (tmp_path / "auto" / "Eux").mkdir(parents=True)
    (tmp_path / "combos" / "Nous.json").write_text(json.dumps({
        "_équipe": {}, "A": {"strategie": {"auteur": "tmenard"}}, "B": {"strategie": {"auteur": "claude (brouillon)"}},
        "C": {}, "D": {}}))
    (tmp_path / "auto" / "Eux" / "D.json").write_text("{}")
    assert pn.confidence(tmp_path) == {"A": "validee", "B": "claude", "C": "claude", "D": "brouillon"}


def test_sigma_grows_with_uncertainty():
    inp = _input()
    sig = pn.pair_sigmas(inp, {"n0": "validee", "e0": "validee"}, {"n0", "e0"})
    assert sig[("n0", "e0")] == pytest.approx((2.0 ** 2 + 1 + 1) ** 0.5)
    assert sig[("n1", "e1")] > sig[("n0", "e0")]


def test_zero_noise_reproduces_reference():
    inp = _input()
    (v0, mix), rows = pn.simulate(inp, {k: 0.0 for k in pn.pair_sigmas(inp, {}, set())}, draws=4)
    assert sum(mix.values()) == pytest.approx(1.0, abs=0.02)
    assert all(r[0] == pytest.approx(v0) and r[1] == pytest.approx(0.0, abs=1e-6) for r in rows)

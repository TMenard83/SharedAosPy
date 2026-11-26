import pytest

from aospy.l3.pairing_scores import assemble, notes_model


def _grid():
    return {("A", "X"): 3, ("A", "Y"): -2, ("B", "X"): 0, ("B", "Y"): 5}


def test_assemble_adds_map_correction_from_our_side():
    ours = {"A": {"notes": {"m1": ["++", ""]}}, "B": {"notes": {}}}
    theirs = {"X": {"notes": {"m1": ["−", ""]}}, "Y": {"notes": {}}}
    pi = assemble("T", "O", 1, ["A", "B"], ["X", "Y"], ["m1", "m2"], _grid(), notes_model(ours, theirs))
    assert pi.at("A", "X", "m1") == 3 + 2 * (2 - (-1))
    assert pi.at("A", "X", "m2") == 3  # note absente = « = »
    assert pi.at("B", "Y", "m1") == 5
    assert pi.base[("A", "X", "m1")] == 3
    assert ("A", "X", "m1") in pi.detail and ("A", "X", "m2") not in pi.detail


def test_custom_map_model_replaces_notes():
    pi = assemble("T", "O", 1, ["A", "B"], ["X", "Y"], ["m1"], _grid(), lambda u, t, m: 1.5)
    assert pi.at("A", "Y", "m1") == -0.5


def test_incomplete_grid_is_rejected():
    g = _grid()
    del g[("B", "Y")]
    with pytest.raises(KeyError):
        assemble("T", "O", 1, ["A", "B"], ["X", "Y"], ["m1"], g, lambda u, t, m: 0)

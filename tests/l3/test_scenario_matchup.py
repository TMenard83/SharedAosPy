import pytest

from aospy.l3.scenario_matchup import ScenarioMatchup

MAPS = ["m1", "m2", "m3", "m4"]
HAND = {"A": {"m1": ["++", "vole partout"], "m2": ["+", ""], "m3": ["=", ""], "m4": ["+", ""]}, "B": {"m1": ["−", ""]}}


def model(player, carte):
    return {"B": {"m2": 1, "m3": 0, "m4": 0}}.get(player, {}).get(carte, 0)


def test_hand_note_wins_over_model():
    sm = ScenarioMatchup(HAND, model, MAPS)
    assert (sm.aisance("A", "m1").cran, sm.aisance("A", "m1").source) == (2, "main")
    assert (sm.aisance("B", "m2").cran, sm.aisance("B", "m2").source) == (1, "modèle")


def test_centred_correction_removes_each_list_average():
    sm = ScenarioMatchup(HAND, model, MAPS, k=2.0)
    assert sm.moyenne("A") == pytest.approx(1.0) and sm.moyenne("B") == pytest.approx(0.0)
    # m1 : A +2 − 1 = +1 ; B −1 − 0 = −1 → 2 × 2 = +4
    assert sm.correction("A", "B", "m1") == pytest.approx(4.0)
    # somme nulle sur les cartes : la part générale est laissée à la grille
    assert sum(sm.correction("A", "B", m) for m in MAPS) == pytest.approx(0.0)
    assert sm.correction("B", "A", "m1") == pytest.approx(-4.0)


def test_raw_correction_is_note_difference():
    sm = ScenarioMatchup(HAND, model, MAPS, k=2.0, centre=False)
    assert sm.correction("A", "B", "m1") == pytest.approx(2.0 * (2 - (-1)))
    assert sm("A", "B", "m3") == pytest.approx(0.0)  # utilisable comme MapModel

import pytest

from aospy.l3 import scenario_model as sm
from aospy.l3.pairing_scores import assemble, combine
from aospy.l3.tactics import DOMINATION_REALISM, MODEL_OFFSET, POINTS, ROUNDS, TacticsModel, card_tactics, probability

CARDS = {
    "C1": {"Échauffourée": "E1", "Frappe": "F1", "Domination": "D1"},
    "C2": {"Échauffourée": "E2", "Frappe": "F2", "Domination": "D2"},
}


def _pool():
    raws = {"A": {k: 1.0 for k in sm.INDICATORS}, "B": {k: 0.0 for k in sm.INDICATORS}}
    return sm.standardize(raws)  # z = +1 pour A, −1 pour B


def _model(**kw):
    models = {
        t: sm.Model(t, "tactique", {}, 0.0, kw.get("scen", {}).get(t, {}), against=kw.get("against", {}).get(t, {}))
        for c in CARDS.values()
        for t in c.values()
    }
    hand = kw.get("hand", {"A": {"E1": "facile", "E2": "moyen", "F1": "difficile", "F2": "moyen", "D1": "abandon",
                                 "D2": "abandon"}})
    return TacticsModel(_pool(), {"A": ("C1", "C2"), "B": ("C1", "C2")}, hand, models, CARDS, weight=1.0)


def test_best_tactic_per_family_from_hand_levels():
    T = _model()
    ch = {c.family: (c.tactic, c.source) for c in T.choices("A")}
    assert ch == {"Échauffourée": ("E1", "main"), "Frappe": ("F2", "main"), "Domination": ("D1", "main")}
    expected = ROUNDS * POINTS * (probability(0.6) + probability(0.0) + probability(-1.6))
    assert T.expected("A") == pytest.approx(expected)


def test_model_domination_is_discounted():
    T = _model()
    (d,) = [c for c in T.choices("B") if c.family == "Domination"]
    assert d.source == "modèle" and d.p == pytest.approx(probability(MODEL_OFFSET) * DOMINATION_REALISM)


def test_map_and_opponent_shift_hand_levels():
    T = _model(scen={"E1": {"m": -0.6}}, against={"F2": {"durabilite": -0.5}})
    assert T.value("A", "E1", None, "m")[0] == pytest.approx(0.0)
    assert T.value("A", "F2", "A", None)[0] == pytest.approx(-0.5)  # adversaire durable (z = +1)
    assert T.value("A", "F2", "B", None)[0] == pytest.approx(0.5)


def test_correction_is_antisymmetric_and_combines():
    T = _model()
    assert T.correction("A", "B", "m") == pytest.approx(-T.correction("B", "A", "m"))
    grid = {("A", "B"): 2.0}
    pi = assemble("T", "O", 1, ["A"], ["B"], ["m"], grid, combine(T, lambda *_: 1.0))
    assert pi.at("A", "B", "m") == pytest.approx(2.0 + 1.0 + T.correction("A", "B", "m"))


def test_real_cards_have_three_families():
    cards = card_tactics()
    assert len(cards) == 6 and all(set(c) == {"Échauffourée", "Frappe", "Domination"} for c in cards.values())

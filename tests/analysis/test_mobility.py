"""Axe mobilité du classement (analysis/layers/mobility.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.mobility import FLY_IN, MOBILITY_WEIGHT, RUN_IN, ability_bonus, mobility_factor, reach
from aospy.domain.models import Unit


def _unit(move=5, keywords=("INFANTRY",)):
    return Unit(
        name="U", army_id=1, move=move, save=4, health=2, control=1, models=5, points=100, keywords=frozenset(keywords)
    )


def test_reach_is_move_plus_run_plus_fly():
    assert reach(_unit(5)) == pytest.approx(5 + RUN_IN)
    assert reach(_unit(12, ("CAVALRY", "FLY"))) == pytest.approx(12 + RUN_IN + FLY_IN)


def test_move_abilities_weighted_by_probability_and_frequency():
    assert ability_bonus("deep_strike", "", 0, 1.0, "once_per_battle") == pytest.approx(1.5)
    assert ability_bonus("extra_move", "", 0, 0.5, "once_per_turn") == pytest.approx(1.5)
    assert ability_bonus("stat_mod", "move", 2, 1.0, "passive") == pytest.approx(2.0)
    assert ability_bonus("stat_mod", "save", 1, 1.0, "passive") == 0.0  # pas un mouvement
    # par type d'effet, seul le plus fort compte ; types différents s'additionnent
    effs = [("extra_move", "", 0, 1.0, ""), ("extra_move", "", 0, 0.5, ""), ("run_and_charge", "", 0, 1.0, "")]
    assert reach(_unit(5), effs) == pytest.approx(5 + RUN_IN + 3.0 + 1.5)


def test_gained_fly_counts_only_if_likely():
    assert reach(_unit(5), [("fly", "", 0, 1.0, "")]) == pytest.approx(5 + RUN_IN + FLY_IN)
    assert reach(_unit(5), [("fly", "", 0, 0.3, "")]) == pytest.approx(5 + RUN_IN)


def test_mobility_factor_is_neutral_at_median_and_uses_user_weight():
    assert MOBILITY_WEIGHT == 0.35
    assert mobility_factor(11.5, 11.5) == pytest.approx(1.0)
    assert mobility_factor(23.0, 11.5) == pytest.approx(2**0.35)
    assert mobility_factor(5.75, 11.5) < 1.0


def test_action_reach_takes_the_longest_significant_channel():
    from aospy.analysis.layers.mobility import CHARGE_IN, action_reach

    move_reach = 5 + RUN_IN  # infanterie à 5"
    # rien d'autre que le déplacement : canal « score »
    assert action_reach(move_reach) == (pytest.approx(move_reach), "score")
    # mêlée significative : déplacement + charge
    assert action_reach(move_reach, [("melee", 1, 1.0)]) == (pytest.approx(5 + CHARGE_IN), "mêlée")
    # arme de tir à 24" mais anecdotique (10 % des dégâts) : ignorée
    r, c = action_reach(move_reach, [("melee", 1, 0.9), ("ranged", 24, 0.1)])
    assert c == "mêlée"
    # sorcier à pied, sort à 18" : agit à 23"
    r, c = action_reach(move_reach, [("melee", 1, 1.0)], [("sort", 18, 0.58)])
    assert (r, c) == (pytest.approx(23.0), "sort")
    # canal trop improbable écarté ; aptitude au contact = portée de mêlée
    assert action_reach(move_reach, [], [("sort", 18, 0.2)])[1] == "score"
    assert action_reach(move_reach, [], [("ciblage", 1, 1.0)]) == (pytest.approx(5 + CHARGE_IN), "ciblage")

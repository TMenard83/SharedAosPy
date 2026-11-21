"""Dégâts directs (blessures mortelles) lus dans le texte des aptitudes — `analysis/layers/mortals.py`."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.encounter import smooth_floor
from aospy.analysis.layers.mortals import TARGET_MODELS, expected_mortals, mortal_pmf


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Roll a D3. On a 2+, inflict an amount of mortal damage on the target equal to the roll.", 5 / 3),
        ("Roll a dice. On a 4+, inflict an amount of mortal damage on the target equal to the roll.", 15 / 6),
        ("Roll 10 dice. For each 4+, inflict 1 mortal damage on the target.", 5.0),
        (
            "Roll a dice for each model in the target unit. For each 5+, inflict 1 mortal damage on the target.",
            TARGET_MODELS / 3,
        ),
        ("Inflict D3 mortal damage on each target.", 2.0),
        (
            "Roll a dice. On a 3-5, inflict D3 mortal damage on the target. On a 6, inflict 2D3 mortal damage on "
            "the target.",
            0.5 * 2 + 4 / 6,
        ),
        (
            "Roll a dice. On a 2+, add 1 to save rolls for the target. On a 1, inflict D3 mortal damage on the target.",
            2 / 6,
        ),
        (
            "Roll a dice. On a 3+, roll a dice for each model in the target unit. For each 5+, inflict 1 mortal "
            "damage on the target.",
            2 / 3 * TARGET_MODELS / 3,
        ),
        (
            "Inflict D3 mortal damage on the target and then roll 2D6. This unit can move a distance in inches up "
            "to the value of the roll.",
            2.0,
        ),
    ],
)
def test_expected_mortals(text, expected):
    assert expected_mortals(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        "Each time this unit attacks with its Sceptre, if the attack scores a hit, inflict D3 mortal damage.",
        "Until the start of your next turn, each time the target is picked to use a CORE ability, roll a D3. "
        "On a 2+, inflict an amount of mortal damage on the target equal to the roll.",
        "Your opponent must pick 1 of the following effects: - Inflict D6 mortal damage on the target.",
    ],
)
def test_triggers_and_opponent_choices_are_not_counted(text):
    assert expected_mortals(text) is None


def test_pick_one_option_takes_the_best():
    text = (
        "Pick 1 of the following effects: - Inflict 1 mortal damage on the target. - Roll 6 dice. For each 4+, "
        "inflict 1 mortal damage on the target."
    )
    assert expected_mortals(text) == pytest.approx(3.0)


def test_random_burst_floor_is_below_its_mean():
    burst = mortal_pmf("Roll a D3. On a 2+, inflict an amount of mortal damage on the target equal to the roll.")
    many = mortal_pmf("Roll 10 dice. For each 4+, inflict 1 mortal damage on the target.")
    assert smooth_floor(burst, 0.75) < 0.5 * 5 / 3  # rafale aléatoire : fort rabais
    assert smooth_floor(many, 0.75) > 0.75 * 5.0  # beaucoup de dés : proche de la moyenne

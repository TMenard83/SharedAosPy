"""Analyseur v34, chantier C : rythmes des ressources de faction et niveau de fureur (validés le 2026-11-22)."""

from __future__ import annotations

import pytest

from aospy.abilities.extract import extract
from aospy.abilities.models import RawAbility
from aospy.abilities.pipeline import analyze_one
from aospy.abilities.resources import FURY_LEVEL, SPEND_RATES, resource_usage
from aospy.abilities.scoring import EFFECT_WEIGHTS, FURY_RESET_WEIGHT


def _raw(effect: str, declare: str = "", condition: str = "Your Hero Phase", cost_type: str = "",
         cost_value: str = "") -> RawAbility:
    return RawAbility(
        uid="x", name="Test", source_kind="battle_trait", group_name="", condition=condition, phase="",
        wahapedia_type="", is_reaction=False, keywords="", cost_type=cost_type, cost_value=cost_value,
        declare=declare, effect=effect,
    )


_BUFF = "For the rest of the turn, add 1 to the Damage characteristic of the target's melee weapons."


@pytest.mark.parametrize(
    "declare,usage",
    [
        ("Spend 20 raw ingredients to pick a friendly unit to be the target.", 8 / 20),
        ("Spend 2 oath points to pick a friendly unit to be the target.", 1 / 2),
        ("Spend 1 relentless discipline point to pick a friendly unit to be the target.", 1.0),  # 3/round ≥ 1
        ("Spend 1 rage dice to pick a friendly unit to be the target.", 1.0),
    ],
)
def test_spending_a_resource_scales_power_by_rate_over_cost(declare, usage):
    """Facteur d'usage = min(1, rythme / coût) : « Spend 20 raw ingredients » à 8/round = ×0,4."""
    plain = analyze_one(_raw(_BUFF, declare="Pick a friendly unit to be the target."))
    spent = analyze_one(_raw(_BUFF, declare=declare))
    assert spent.extraction.resource_usage == pytest.approx(usage, abs=1e-3)
    assert spent.score.power == pytest.approx(plain.score.power * usage, abs=0.02)


def test_fate_cost_type_is_spent_per_use():
    """Coût « Fate » (DoT) : dépensé à chaque usage, au rythme des points de destin."""
    usage, note = resource_usage(_raw(_BUFF, cost_type="Fate", cost_value="2"))
    assert usage == pytest.approx(SPEND_RATES["fate point"] / 2, abs=1e-3)
    assert "fate point" in note


def test_once_per_battle_spend_is_financed_over_the_battle():
    """Coût 3 en destin (1,5/round) une fois par bataille : se finance en 2 rounds → pas de facteur d'usage."""
    raw = _raw(_BUFF, cost_type="Fate", cost_value="3", condition="Once Per Battle, Your Hero Phase")
    usage, _ = resource_usage(raw)
    assert usage == 1.0


def test_no_known_resource_means_no_usage_factor():
    assert resource_usage(_raw(_BUFF, declare="Spend 1 command point."))[0] is None


def test_fury_level_value_in_modifiers():
    """« Add half your fury level (rounding up) to run rolls and charge rolls » : fureur moyenne 2 → +1."""
    ex, _ = extract(_raw("Add half your fury level (rounding up) to run rolls and charge rolls for this unit.",
                         condition="Passive"))
    mods = {e.stat: e.value for e in ex.effects if e.kind == "stat_mod"}
    assert mods == {"run": FURY_LEVEL / 2, "charge": FURY_LEVEL / 2}


@pytest.mark.parametrize(
    "text,weight",
    [
        ("If this unit is not in combat, your opponent must reduce their fury level by 1, to a minimum of 0.",
         EFFECT_WEIGHTS["fury_debuff"]),
        ("If an enemy Hero was destroyed by this unit's combat attacks this turn, your opponent must reduce their "
         "fury level to 0.", FURY_RESET_WEIGHT),
    ],
)
def test_lowering_the_opponent_fury_level(text, weight):
    """−1 à la fureur adverse = 0,5 ; remise à 0 = 1,0 (validés)."""
    a = analyze_one(_raw(text, condition="End of Your Turn"))
    eff = next(e for e in a.extraction.effects if e.kind == "fury_debuff")
    assert eff.side == "enemy"
    assert a.score.power == pytest.approx(weight, abs=0.01)

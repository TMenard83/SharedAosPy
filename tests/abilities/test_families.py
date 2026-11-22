"""Familles fonctionnelles des effets (abilities/families.py)."""

from __future__ import annotations

import pytest

from aospy.abilities.extract import extract
from aospy.abilities.families import FAMILIES, effect_family, main_family
from aospy.abilities.models import RawAbility


def _families(effect: str, declare: str = "", condition: str = "Passive") -> list[str]:
    raw = RawAbility(
        uid="x",
        name="T",
        source_kind="warscroll",
        group_name="",
        condition=condition,
        phase="",
        wahapedia_type="",
        is_reaction=False,
        keywords="",
        cost_type="",
        cost_value="",
        declare=declare,
        effect=effect,
    )
    ex, _ = extract(raw)
    return [effect_family(e, ex.scope) for e in ex.effects]


@pytest.mark.parametrize(
    "effect,declare,family",
    [
        ("Add 1 to hit rolls for this unit's combat attacks.", "", "buff-perso-offensif"),
        ("Subtract 1 from hit rolls for attacks that target this unit.", "", "buff-perso-defensif"),
        (
            "Friendly SKAVEN INFANTRY HEROES have WARD (5+) while they are within this unit's combat range.",
            "",
            "buff-donne",
        ),
        (
            "Add 1 to wound rolls for the target's combat attacks for the rest of the turn.",
            'Pick a visible friendly unit wholly within 12" of this unit to be the target.',
            "buff-donne",
        ),
        (
            "Subtract 1 from hit rolls for the target's attacks for the rest of the turn.",
            'Pick a visible enemy unit within 12" of this unit to be the target.',
            "debuff",
        ),
        (
            "Inflict D3 mortal damage on the target.",
            'Pick a visible enemy unit within 12" of this unit to be the target.',
            "degats-directs",
        ),
        ("Heal (3) this unit.", "", "soin"),
    ],
)
def test_effect_family(effect, declare, family):
    assert family in _families(effect, declare)


def test_main_family_ignores_autre_and_breaks_ties_by_priority():
    assert main_family(["autre", "soin"]) == "soin"
    assert main_family(["autre"]) == "autre"
    assert main_family(["soin", "debuff"]) == "debuff"
    assert set(FAMILIES) >= {"buff-donne", "debuff", "mobilite"}


def test_v35_enemy_bonus_is_a_counterpart_not_a_debuff():
    """Dark Temptations : « Add 1 to hit rolls for attacks made by that enemy unit that target this unit »."""
    fams = _families(
        "Add 1 to hit rolls for attacks made by that enemy unit that target this unit.",
        declare="Pick an enemy unit in combat with this unit to be the target.",
        condition="Any Combat Phase",
    )
    assert "debuff" not in fams and "autre" in fams


def test_v35_weapon_abilities_negated_against_a_friendly_unit_is_a_given_protection():
    """Miasma of Pestilence : les aptitudes d'arme des attaques qui ciblent cette unité AMIE n'ont pas d'effet."""
    fams = _families(
        "Until the start of your next turn, other than the Companion weapon ability, weapon abilities for attacks "
        "that target that friendly unit have no effect.",
        declare='Pick a visible friendly unit within 12" of this unit to be the target, '
        "then make a casting roll of 2D6.",
        condition="Your Hero Phase",
    )
    assert fams == ["buff-donne"]

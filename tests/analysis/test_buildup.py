"""Couche 4 : montée en puissance, la liste round par round (analysis/layers/buildup.py)."""

from __future__ import annotations

from aospy.analysis.layers.buildup import power_curve
from aospy.analysis.layers.encounter import EffectSpec

from .test_listing import _ab, _unit

ALA = "Alaithi, Rune of the Mountain"
VAR = "Varinor, Rune of Strength"


def test_runes_accumulate_on_the_board():
    """Une rune par round, qui reste au tableau : « +1 Attaque pour chaque Alaithi » grandit round après round
    (plan glouton) ; la liste monte en puissance."""
    hammer = _unit("Hammer")
    board = _ab("DEPICT RUNE", scope="army",
                text="Pick 1 of the following runes. Each rune remains on your battle scripture for the rest of the "
                     "battle.",
                effects=[EffectSpec("ward", value=6.0, option_group=ALA),
                         EffectSpec("stat_mod", "run", 1.0, option_group=VAR)])
    slide = _ab("Landslide", carriers=["Hammer"],
                text="Add 1 to the Attacks characteristic of this unit's melee weapons for each instance of "
                     "Alaithi, Rune of the Mountain depicted on your battle scripture.",
                effects=[EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee")])
    curve = power_curve([board, slide], [hammer], frozenset())
    assert [r.rune for r in curve.rounds] == [ALA] * 5
    dmg = [r.damage for r in curve.rounds]
    assert dmg == sorted(dmg) and dmg[-1] > dmg[0]
    assert curve.peak == 5 and curve.grows


def test_resource_unlocks_from_its_round():
    """Une aptitude disponible à partir du round 3 (Dîme de Sang) n'entre qu'à partir de ce round."""
    hammer = _unit("Hammer")
    tithe = _ab("Slaughter", scope="army", available_round=3,
                effects=[EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee")])
    curve = power_curve([tithe], [hammer], frozenset())
    assert curve.rounds[1].damage < curve.rounds[2].damage
    assert curve.rounds[2].unlocked == ("Slaughter",)

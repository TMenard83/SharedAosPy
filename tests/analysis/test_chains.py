"""Couche 4 : enchaînements (analysis/layers/chains.py)."""

from __future__ import annotations

from aospy.analysis.layers.chains import chain_notes, rally_chains, rally_dice
from aospy.analysis.layers.encounter import EffectSpec

from .test_listing import _ab, _unit


def test_disengage_then_rally_is_measured():
    """Une unité qui peut se dégager se Rallie (1 PC, hors combat) : 3 points par défaut, + les dés que la liste
    ajoute ; gain de survie × P(dégagement) ; rien pour une unité qui ne peut pas se dégager."""
    hero = _unit("Hero", health=8)
    other = _unit("Other", health=8)
    push = _ab("Push", carriers=["Hero"], effects=[EffectSpec("free_retreat")])
    banner = _ab("Banner", scope="army", text="you can make 3 additional rally rolls of D6.",
                 effects=[EffectSpec("rally", detail="make 3 additional rally rolls")])
    assert rally_dice(hero, [banner], frozenset()) == 9
    (r,) = rally_chains([push, banner], [hero, other], frozenset(), {"Push": "mobilite", "Banner": "soin"},
                        {None: (5.0, 0.0)}, {"Hero": 1.0, "Other": 1.0})
    assert r.unit == "Hero" and r.rally_points == 4.5 and r.cp_per_round == 1
    assert r.survival_gain is not None and r.survival_gain > 0


def test_mobile_shooting_and_range_relay_are_listed():
    shoot = _ab("Spirit of the Wind", carriers=["Sevireth"],
                text="If this unit used a SHOOT ability this phase, this unit can move D6\".")
    relay = _ab("Arcane Passage", carriers=["Gate"],
                text="you can measure range and visibility from either part of this MANIFESTATION")
    kinds = {(n.kind, n.ability) for n in chain_notes([shoot, relay], [], frozenset(), {"Enlightener": "Shrine"})}
    assert ("tir mobile", "Spirit of the Wind") in kinds and ("relais de portée", "Arcane Passage") in kinds
    assert ("relais de portée", "gardien de Shrine") in kinds

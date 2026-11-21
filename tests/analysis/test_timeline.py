"""Frise de la partie en 10 demi-tours (analysis/layers/timeline.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.timeline import DEF_SHARE_ENEMY_TURN, KAIROS_SHORT, coverage, relevance, span


def test_relevance_sums_to_one_per_round():
    for pol in ("off", "def", "autre"):
        assert sum(relevance(pol, 0.6)) == pytest.approx(1.0)
    assert relevance("off", 0.0) == (1.0, 0.0)          # tir : seulement à mon tour
    assert relevance("off", 1.0) == (0.5, 0.5)          # mêlée : combat + riposte


def test_spans():
    assert span(2, "tour") == [2]
    assert span(2, "jusqu'au prochain tour") == [2, 3]
    assert span(3, "round") == [3]
    assert span(2, "round") == [2, 3]
    assert span(8, "bataille") == [8, 9]


def test_passive_and_permanent_cover_everything():
    assert coverage("passive", "permanent", "any", "off") == pytest.approx(1.0)
    assert coverage("unlimited", "jusqu'au prochain tour", "yours", "def") == pytest.approx(1.0)


def test_turn_side_matters_for_repeatable_effects():
    """« Your Combat Phase, rest of the turn » : une unité de mêlée combat aussi au tour adverse → moitié."""
    assert coverage("unlimited", "tour", "yours", "off", share_melee=1.0) == pytest.approx(0.5)
    assert coverage("unlimited", "tour", "yours", "off", share_melee=0.0) == pytest.approx(1.0)
    assert coverage("unlimited", "tour", "any", "off", share_melee=1.0) == pytest.approx(1.0)


def test_once_per_battle_short_is_half_spread_by_turn():
    """Scroll of Petrification (protection 2+ pour le tour) : jouée au tour adverse, elle couvre l'essentiel des
    coups reçus ; limitée à mon tour, presque rien."""
    any_side = coverage("once_per_battle", "tour", "any", "def")
    mine = coverage("once_per_battle", "tour", "yours", "def")
    assert any_side == pytest.approx(KAIROS_SHORT * DEF_SHARE_ENEMY_TURN)
    assert mine == pytest.approx(KAIROS_SHORT * (1 - DEF_SHARE_ENEMY_TURN))
    assert coverage("once_per_battle", "round", "yours", "def") == pytest.approx(KAIROS_SHORT)


def test_once_per_battle_lasting_starts_round_two():
    assert coverage("once_per_battle", "bataille", "yours", "autre") == pytest.approx(8 / 9)


def test_alive_profile_and_start_round():
    dead_after_r2 = [1, 1, 0, 0, 0]
    assert coverage("passive", "permanent", "any", "autre", alive=dead_after_r2) == pytest.approx((1 / 3 + 1) / 3)
    assert coverage("passive", "permanent", "any", "autre", start_round=3) == pytest.approx((1 + 2 / 3) / 3)

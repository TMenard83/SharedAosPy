"""Facteurs de mariage châssis × aptitude (analysis/marriage.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.marriage import (CHARGE_FIGHT_SHARE, alive_profile, p_2d6_at_least, p_charge, rounds_alive,
                                     survival_coverage, territory_round, trigger)
from aospy.domain.models import Unit


def _unit(move: int, health: int = 5, models: int = 1, hero: bool = True, fly: bool = False) -> Unit:
    kws = {"HERO"} if hero else set()
    if fly:
        kws.add("FLY")
    return Unit(id=1, army_id=1, name="U", move=move, save=4, control=1, health=health, ward=None, points=100,
                models=models, is_hero=hero, keywords=frozenset(kws), weapons=[])


def test_p_2d6():
    assert p_2d6_at_least(2) == 1.0 and p_2d6_at_least(13) == 0.0
    assert p_2d6_at_least(7) == pytest.approx(21 / 36)


def test_slow_bearer_charges_less_and_reaches_enemy_territory_later():
    """Oath of Supremacy : Warqueen (5") vs châssis rapide (10"). Distances vérifiées sur les plans de
    bataille 2026-27 : territoires jointifs, déploiement à plus de 9" du territoire ennemi."""
    slow, fast = _unit(5), _unit(10)
    assert p_charge(slow) < 0.3 < 0.85 < p_charge(fast)
    # au round 1 les armées sont à ≥ 18" : 5" + 2D6 n'y arrive jamais
    assert p_charge(slow, start=1) < p_charge(slow, start=2)
    assert territory_round(slow, with_charge=False) == 2
    assert territory_round(fast, with_charge=False) == 1
    t = trigger(slow, "a chargé | en territoire", "a chargé | en territoire", share_melee=1.0, melee_effect=True)
    assert t.bearer_only and t.charged and t.p == pytest.approx(p_charge(slow, t.start))
    assert t.p_off_timeline == pytest.approx(t.p * CHARGE_FIGHT_SHARE)


def test_conditions_held_by_others_stay_good_case():
    t = trigger(_unit(6), "près d'une unité amie", "près d'une unité amie", 1.0, True)
    assert not t.bearer_only
    t = trigger(_unit(6), "", "vs HERO", 1.0, True)
    assert not t.bearer_only


def test_charge_bonus_implies_charging():
    t = trigger(_unit(6), "", "", 1.0, True, kind="charge_bonus")
    assert t.charged and t.p == pytest.approx(p_charge(_unit(6)))


def test_objective_more_likely_for_troops():
    troop = _unit(5, models=10, hero=False)
    assert trigger(troop, "sur objectif", "sur objectif", 1.0, False).p > \
        trigger(_unit(5), "sur objectif", "sur objectif", 1.0, False).p


def test_staged_pressure_one_two_two_one_one():
    """1 unité ennemie au round 1, 2 aux rounds 2-3, 1 aux rounds 4-5 (choix utilisateur)."""
    # 10 PV, 2 dégâts par unité : r1 −2 (8), r2 −4 (4), r3 −4 (0) → mort à la fin du round 3
    assert alive_profile(10, 2.0) == pytest.approx([1.0, 1.0, 1.0, 0.0, 0.0])
    # 3 PV, 2 dégâts : round 1 entier (reste 1), round 2 : 1/4 du round
    assert alive_profile(3, 2.0) == pytest.approx([1.0, 0.25, 0.0, 0.0, 0.0])
    # exposé seulement à partir du round 2
    assert alive_profile(3, 2.0, start=2) == pytest.approx([1.0, 0.75, 0.0, 0.0, 0.0])
    assert rounds_alive(10, 2.0, 0.0, "contact") == pytest.approx(3.0)


def test_survival_coverage():
    assert survival_coverage([1.0] * 5) == pytest.approx(1.0)
    assert survival_coverage([0.0] * 5) == 0.0
    # vivant au round 2 seulement, depuis le round 2 : 1 sur 1 + 1 + 1/3 + 1/3
    assert survival_coverage([1.0, 1.0, 0.0, 0.0, 0.0], start=2) == pytest.approx(1.0 / (8 / 3))
    # effet court : seul le round d'usage compte
    assert survival_coverage([1.0, 1.0, 0.0, 0.0, 0.0], start=2, lasting=False) == 1.0

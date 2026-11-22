"""Facteurs de mariage châssis × aptitude (analysis/layers/marriage.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.marriage import (
    CHARGE_FIGHT_SHARE,
    FACTOR_BOUNDS,
    ChassisProfile,
    alive_profile,
    effect_timing,
    marriage_of,
    p_2d6_at_least,
    p_charge,
    role_fit,
    rounds_alive,
    survival_coverage,
    tempo,
    territory_round,
    trigger,
)
from aospy.domain.models import Unit


def _unit(move: int, health: int = 5, models: int = 1, hero: bool = True, fly: bool = False) -> Unit:
    kws = {"HERO"} if hero else set()
    if fly:
        kws.add("FLY")
    return Unit(
        id=1,
        army_id=1,
        name="U",
        move=move,
        save=4,
        control=1,
        health=health,
        ward=None,
        points=100,
        models=models,
        is_hero=hero,
        keywords=frozenset(kws),
        weapons=[],
    )


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
    assert (
        trigger(troop, "sur objectif", "sur objectif", 1.0, False).p
        > trigger(_unit(5), "sur objectif", "sur objectif", 1.0, False).p
    )


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


# ----- grille par famille (F tempo, A amplification, R rôle) ------------------------------------------


def _eff(kind="stat_mod", duration="tour", wscope="melee", stat="attacks"):
    # (kind, requires, target_condition, target_keywords, duration, weapon_scope, stat) — `load_effects`
    return (kind, "", "", "", duration, wscope, stat)


def test_tempo_melee_buff_for_the_turn_misses_the_riposte():
    """Un buff de mêlée « pour le reste du tour » joué à mon tour : l'unité de mêlée combat aussi au tour
    adverse, il n'en couvre que la moitié ; « jusqu'au prochain tour » couvre tout ; un tireur ne perd rien."""
    assert tempo("buff-perso-offensif", "unlimited", "tour", "yours", 1.0) == pytest.approx(0.5)
    assert tempo("buff-perso-offensif", "unlimited", "jusqu'au prochain tour", "yours", 1.0) == 1.0
    assert tempo("buff-perso-offensif", "unlimited", "tour", "yours", 0.0) == pytest.approx(1.0)
    assert tempo("buff-perso-offensif", "passive", "permanent", "any", 1.0) == 1.0
    # familles hors grille : neutres
    assert tempo("debuff", "unlimited", "tour", "yours", 1.0) == 1.0


def test_effect_timing_reads_given_buffs_from_their_effects():
    # buff de tir donné : mon seul tour compte → F = 1 même joué « pour le tour »
    pol, sm = effect_timing("buff-donne", [_eff(wscope="ranged", stat="hit")], 1.0)
    assert (pol, sm) == ("off", 0.0)
    assert tempo("buff-donne", "unlimited", "tour", "yours", sm, pol) == pytest.approx(1.0)
    # protection donnée jouée à mon tour : l'essentiel des coups arrive au tour adverse
    pol, _ = effect_timing("buff-donne", [_eff(kind="ward", wscope="", stat="")], 1.0)
    assert pol == "def"
    assert tempo("buff-donne", "unlimited", "tour", "yours", 1.0, pol) < 0.5


def test_role_fit_by_family():
    lo, hi = FACTOR_BOUNDS
    hammer, weak = ChassisProfile(off_rank=0.95, def_rank=0.2), ChassisProfile(off_rank=0.1, def_rank=0.2)
    assert role_fit("buff-perso-offensif", hammer) > 1.0 > role_fit("buff-perso-offensif", weak) >= lo
    anvil = ChassisProfile(off_rank=0.2, def_rank=0.9, share_melee=1.0)
    gunline = ChassisProfile(off_rank=0.2, def_rank=0.2, share_melee=0.0)
    assert role_fit("buff-perso-defensif", anvil) > 1.0 > role_fit("buff-perso-defensif", gunline)
    # buff donné : un porteur lent ne suit pas ses receveurs, un porteur rapide n'est jamais bonifié
    assert role_fit("buff-donne", ChassisProfile(reach=7.5), 18.5) == lo
    assert role_fit("buff-donne", ChassisProfile(reach=14.0), 10.0) == 1.0
    assert role_fit("debuff", hammer) == 1.0
    assert role_fit("buff-perso-offensif", ChassisProfile(off_rank=1.0)) <= hi


def test_marriage_combines_grid_factors_and_keeps_bearing():
    u = _unit(8, health=10, models=5, hero=False)
    base = marriage_of(u, [_eff()], "buff-perso-offensif", "self", None, "unlimited", 1.0, (0.0, 0.0), "yours")
    assert base.bearing == pytest.approx(1.0)
    assert base.tempo == pytest.approx(0.5) and base.amplification == 1.0 and base.role_fit == 1.0
    assert base.marriage == pytest.approx(0.5)
    m = marriage_of(
        u,
        [_eff()],
        "buff-perso-offensif",
        "self",
        None,
        "unlimited",
        1.0,
        (0.0, 0.0),
        "yours",
        amplification=3.0,
        role=1.2,
    )
    assert m.amplification == FACTOR_BOUNDS[1]
    assert m.marriage == pytest.approx(0.5 * FACTOR_BOUNDS[1] * 1.2)
    # famille hors grille : A et R ignorés
    d = marriage_of(
        u, [_eff()], "debuff", "one_enemy", 12, "unlimited", 1.0, (0.0, 0.0), "yours", amplification=3.0, role=1.4
    )
    assert d.marriage == pytest.approx(d.bearing)


def test_chained_fight_counts_at_its_share():
    from aospy.analysis.layers.marriage import CHAINED_FIGHT_SHARE

    t = trigger(_unit(5), "combat enchaîné", "combat enchaîné", share_melee=1.0, melee_effect=True)
    assert t.p == pytest.approx(CHAINED_FIGHT_SHARE) and t.bearer_only

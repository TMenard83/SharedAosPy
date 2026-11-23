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


def test_once_trigger_sets_a_start_round_not_a_per_fight_probability():
    """v34 : Oath of Supremacy — charge en territoire ennemi réussie UNE fois, puis +1 touche toute la bataille."""
    slow = _unit(5)
    req = "déclencheur unique (charge, en territoire)"
    t = trigger(slow, req, req, 1.0, True)
    assert t.bearer_only and not t.charged and t.p == 1.0
    assert t.start == territory_round(slow, with_charge=True)
    t = trigger(slow, "déclencheur unique (sur objectif)", "déclencheur unique (sur objectif)", 1.0, False)
    assert t.bearer_only and t.p == 1.0 and t.start == 2


def test_either_charge_is_a_charge_turn_fight_without_charge_roll():
    """v34 : Brutal Troof — « if it charged … or if it is in combat with an enemy unit that charged »."""
    t = trigger(_unit(5), "a chargé ou charge ennemie", "a chargé ou charge ennemie", 1.0, True)
    assert t.bearer_only and t.charged and t.p == 1.0


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
    # débuff sans polarité (ordres, contrôle…) : neutre
    assert tempo("debuff", "unlimited", "tour", "yours", 1.0) == 1.0
    assert tempo("soin", "unlimited", "tour", "yours", 1.0) == 1.0


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
        u, [_eff()], "autre", "one_friendly", 12, "unlimited", 1.0, (0.0, 0.0), "yours", amplification=3.0, role=1.4
    )
    assert d.marriage == pytest.approx(d.bearing)


def test_chained_fight_counts_at_its_share():
    from aospy.analysis.layers.marriage import CHAINED_FIGHT_SHARE

    t = trigger(_unit(5), "combat enchaîné", "combat enchaîné", share_melee=1.0, melee_effect=True)
    assert t.p == pytest.approx(CHAINED_FIGHT_SHARE) and t.bearer_only


# ----- grille des débuffs (réponses utilisateur du 2026-11-22) -----------------------------------------------


def _deb(kind="stat_mod", stat="hit", duration="tour", wscope="all", requires=""):
    return (kind, requires, "", "", duration, wscope, stat, "debuff")


def test_debuff_polarity():
    """Débuff des attaques ennemies = protection (« def ») ; de leur défense = sert nos coups (« off »)."""
    from aospy.analysis.layers.marriage import debuff_polarity

    assert debuff_polarity([_deb(stat="hit"), _deb(kind="strike_last", stat="")]) == "def"
    assert debuff_polarity([_deb(stat="save")]) == debuff_polarity([_deb(kind="no_ward", stat="")]) == "off"
    assert debuff_polarity([_deb(kind="lockout", stat="")]) == ""
    assert debuff_polarity([_deb(stat="control")]) == ""
    # les effets d'une autre famille ne comptent pas
    assert debuff_polarity([("stat_mod", "", "", "", "tour", "melee", "hit", "buff-perso-offensif")]) == ""


def test_debuff_tempo_follows_the_buff_rule():
    """Whispers of Desire : sort de mon tour, −1 Attaque en mêlée « pour le reste du tour » → F = 0,3 ;
    « jusqu'au prochain tour » → 1 ; joué en « n'importe quelle phase de combat » → 1."""
    pol, sm = effect_timing("debuff", [_deb(stat="attacks", wscope="melee")], 1.0)
    assert pol == "def"
    assert tempo("debuff", "unlimited", "tour", "yours", sm, pol) == pytest.approx(0.3)
    assert tempo("debuff", "unlimited", "jusqu'au prochain tour", "yours", sm, pol) == 1.0
    assert tempo("debuff", "unlimited", "tour", "any", sm, pol) == 1.0


def test_debuff_role_fit_rewards_the_one_who_profits():
    """Au contact : débuff des attaques → rang défensif (Abraxia 1,5) ; de la défense → rang offensif ;
    à distance → neutre."""
    from aospy.analysis.layers.marriage import debuff_role_fit

    lo, hi = FACTOR_BOUNDS
    abraxia, executioner = ChassisProfile(off_rank=0.78, def_rank=1.0), ChassisProfile(off_rank=0.41, def_rank=0.11)
    assert debuff_role_fit("def", "contact", abraxia) == hi
    assert debuff_role_fit("def", "contact", executioner) == pytest.approx(0.61)
    assert debuff_role_fit("off", "contact", ChassisProfile(off_rank=0.77)) == pytest.approx(1.27)
    assert debuff_role_fit("def", "longue", executioner) == 1.0
    assert debuff_role_fit("", "contact", executioner) == 1.0
    assert debuff_role_fit("def", "contact", ChassisProfile(def_rank=0.0)) >= lo


def test_contact_debuff_needs_the_bearer_in_combat():
    """Netters : « an enemy INFANTRY unit in combat with this unit » → D × 0,8 (mêlée) / × 0,3 (tir), mêmes
    constantes que les buffs « au combat » ; pas en plus d'une charge, qui dit déjà comment on y arrive."""
    from aospy.analysis.layers.marriage import P_IN_COMBAT_MELEE, P_IN_COMBAT_SHOOTER

    u = _unit(5, health=1, models=10, hero=False)
    args = ("one_enemy", 1, "unlimited")
    melee = marriage_of(u, [_deb()], "debuff", *args, 1.0, (0.0, 0.0), "any")
    shoot = marriage_of(u, [_deb()], "debuff", *args, 0.3, (0.0, 0.0), "any")
    assert melee.p_trigger == pytest.approx(P_IN_COMBAT_MELEE)
    assert shoot.p_trigger == pytest.approx(P_IN_COMBAT_SHOOTER)
    ranged = marriage_of(u, [_deb()], "debuff", "one_enemy", 18, "unlimited", 1.0, (0.0, 0.0), "any")
    assert ranged.p_trigger == 1.0
    charged = marriage_of(u, [_deb(requires="a chargé")], "debuff", *args, 1.0, (0.0, 0.0), "any")
    assert charged.p_trigger == pytest.approx(p_charge(u))
    prof = ChassisProfile(off_rank=0.5, def_rank=0.9)
    m = marriage_of(u, [_deb()], "debuff", *args, 1.0, (0.0, 0.0), "any", chassis_profile=prof)
    assert m.role_fit == pytest.approx(1.4) and m.marriage == pytest.approx(m.bearing * 1.4)


def test_debuff_set_by_shooting_is_held_at_shooting_range():
    """Hurricane Winds : la cible est désignée par les tirs du porteur → exposition à sa portée de tir."""
    from aospy.abilities.perimeter import SHOT_BY_BEARER
    from aospy.analysis.layers.marriage import exposure_of

    assert exposure_of("one_enemy", None, SHOT_BY_BEARER, "debuff", 24) == "longue"
    assert exposure_of("one_enemy", None, SHOT_BY_BEARER, "debuff", 8) == "courte"
    assert exposure_of("one_enemy", None, "", "debuff", 24) == "contact"
    # règle d'armée (The One True King) : pas de contact à tenir
    assert exposure_of("army", None, "", "debuff") == "longue"


# ----- grille des dégâts directs (réponses utilisateur du 2026-11-22) ------------------------------------------


def _dd(requires="", kind="mortal_damage"):
    return (kind, requires, "", "", "immédiat", "", "", "degats-directs")


def test_overfly_by_reach():
    """Survoler la cible : rounds où mouvement + vol + course + 3" ≥ l'écart (18" puis 14")."""
    from aospy.analysis.layers.marriage import p_overfly

    assert p_overfly(_unit(10, fly=True)) == 1.0  # Ironclad : 12" de vol
    assert p_overfly(_unit(10)) == pytest.approx((8 / 3) / 3)  # Hellflayer : pas au round 1
    assert p_overfly(_unit(4)) == 0.0
    t = trigger(_unit(10), "a survolé la cible", "a survolé la cible", 1.0, False)
    assert t.bearer_only and t.p == pytest.approx(p_overfly(_unit(10)))


def test_direct_damage_at_contact_and_retaliation():
    """BM « au combat avec cette unité » : D × P(au combat) ; riposte : au contact, R = 0,5 + rang défensif ;
    BM sur ses attaques : R = 0,5 + rang offensif, exposition selon la part de mêlée ; F = A = 1."""
    from aospy.abilities.perimeter import ON_OWN_ATTACKS, RETALIATION
    from aospy.analysis.layers.marriage import P_IN_COMBAT_MELEE, P_IN_COMBAT_SHOOTER

    u = _unit(5, health=1, models=10, hero=False)
    anvil = ChassisProfile(off_rank=0.2, def_rank=1.0)
    m = marriage_of(u, [_dd()], "degats-directs", "one_enemy", 1, "unlimited", 0.3, (0.0, 0.0), "any")
    assert m.p_trigger == pytest.approx(P_IN_COMBAT_SHOOTER) and m.tempo == 1.0
    r = marriage_of(
        u, [_dd(RETALIATION)], "degats-directs", "self", None, "passive", 1.0, (0.0, 0.0), "any", chassis_profile=anvil
    )
    assert r.exposure == "contact" and r.p_trigger == pytest.approx(P_IN_COMBAT_MELEE)
    assert r.role_fit == FACTOR_BOUNDS[1]
    w = marriage_of(
        u,
        [_dd(ON_OWN_ATTACKS)],
        "degats-directs",
        "self",
        None,
        "passive",
        0.0,
        (0.0, 0.0),
        "any",
        chassis_profile=anvil,
    )
    assert w.exposure == "longue" and w.p_trigger == 1.0 and w.role_fit == pytest.approx(0.7)
    far = marriage_of(u, [_dd()], "degats-directs", "one_enemy", 18, "unlimited", 1.0, (0.0, 0.0), "yours")
    assert far.marriage == pytest.approx(far.bearing) and far.p_trigger == 1.0


# ----- grille mobilité (réponses utilisateur du 2026-11-23, toutes = propositions) ------------------------------


def _mob(kind="move", stat="", value=0.0, detail="", requires=""):
    # (kind, requires, target_condition, target_keywords, duration, weapon_scope, stat, family, value, detail)
    return (kind, requires, "", "", "immédiat", "", stat, "mobilite", value, detail)


def test_in_combat_without_weapon_scope_is_weighted():
    """« au combat » n'est gratuit que pour un effet sur des armes de mêlée ; sans portée d'arme (Share The Pain,
    « If this unit is in combat, it can move 3" ») il se paie P(au combat) — all() vide valait vrai."""
    from aospy.analysis.layers.marriage import P_IN_COMBAT_MELEE

    u = _unit(5, health=1, models=10, hero=False)
    m = marriage_of(u, [_mob(requires="au combat")], "mobilite", "self", None, "unlimited", 1.0, (0.0, 0.0), "any")
    assert m.p_trigger == pytest.approx(P_IN_COMBAT_MELEE) and m.exposure == "contact"
    buff = marriage_of(
        u, [_eff()[:1] + ("au combat",) + _eff()[2:]], "buff-perso-offensif", "self", None, "unlimited", 1.0,
        (0.0, 0.0), "any",
    )
    assert buff.p_trigger == 1.0  # buff de mêlée : il ne joue de toute façon qu'au combat


def test_mobility_kind():
    from aospy.analysis.layers.marriage import (
        MOBILITY_DISENGAGE,
        MOBILITY_ENGAGE,
        MOBILITY_REPOSITION,
        mobility_kind,
    )

    assert mobility_kind([_mob("dice_count", "charge", 1.0, "somme")]) == MOBILITY_ENGAGE  # Inescapable Wrath
    assert mobility_kind([_mob("deep_strike")], "Set up this unit in reserve.") == MOBILITY_REPOSITION
    assert mobility_kind([_mob("extra_move", requires="au combat")], "use the 'Retreat' ability") == MOBILITY_DISENGAGE
    # Strike and Fade : se retirer après avoir chargé
    assert mobility_kind([_mob("redeploy", requires="a chargé")], "set it up again more than 9\"") == MOBILITY_DISENGAGE
    # « has not used a RUN or RETREAT ability » n'est pas un dégagement (Merciless Ambush)
    text = "If this unit has not used a RUN or RETREAT ability this turn … set it up again within ½\" of an enemy unit"
    assert mobility_kind([_mob("redeploy")], text) == MOBILITY_REPOSITION
    assert mobility_kind([_mob()], "It must end that move in combat.") == MOBILITY_ENGAGE


def test_charge_gain_favours_slow_chassis():
    """Gain relatif A : +1 dé de charge rapporte beaucoup à Skarbrand (8"), presque rien aux Prosecutors (12" + vol)."""
    from aospy.analysis.layers.marriage import MobilityReference, charge_gain, mobility_amplification

    aid = (0.0, False, "3d6")
    slow, fast = _unit(8), _unit(12, fly=True)
    assert charge_gain(slow, aid) > 0.2 > 0.02 > charge_gain(fast, aid)
    ref = MobilityReference([_unit(m) for m in (8, 10, 10, 12, 12)])  # médiane : 10"
    e = [_mob("dice_count", "charge", 1.0, "somme")]
    assert mobility_amplification(slow, e, "engagement", ref) > 1 > mobility_amplification(fast, e, "engagement", ref)
    # réserve / téléportation : allonge médiane ÷ allonge du porteur
    assert mobility_amplification(_unit(4), [_mob("deep_strike")], "repositionnement", ref) == pytest.approx(10 / 4)
    assert mobility_amplification(slow, [_mob("free_retreat")], "dégagement", ref) is None


def test_mobility_role_fit():
    """R : engagement = 0,5 + rang off. ; dégagement = 0,5 + max(rang off., 1 − rang déf.)."""
    from aospy.analysis.layers.marriage import mobility_role_fit

    lo, hi = FACTOR_BOUNDS
    assert mobility_role_fit("engagement", ChassisProfile(off_rank=1.0)) == hi  # Loonsmasha Fanatics
    assert mobility_role_fit("repositionnement", ChassisProfile(off_rank=0.03)) == pytest.approx(0.53)
    furies = ChassisProfile(off_rank=0.39, def_rank=0.04)
    assert mobility_role_fit("dégagement", furies) == pytest.approx(1.46)
    assert mobility_role_fit("dégagement", ChassisProfile(off_rank=0.08, def_rank=0.71)) == pytest.approx(0.79)


def test_personal_mobility_marriage():
    """Mobilité perso : exposition d'un buff perso, A et R de la grille, F neutre ; donnée : le porteur suit."""
    from aospy.analysis.layers.marriage import MobilityReference

    u = _unit(8, health=10, hero=False)
    ref = MobilityReference([_unit(m) for m in (10, 10, 12, 12, 14)])
    prof = ChassisProfile(off_rank=0.84, def_rank=0.45)
    e = [_mob("dice_count", "charge", 1.0, "somme")]
    m = marriage_of(u, e, "mobilite", "self", None, "passive", 1.0, (0.0, 0.0), "any", chassis_profile=prof,
                    mobility_ref=ref)
    assert m.exposure == "contact" and m.tempo == 1.0
    assert m.role_fit == pytest.approx(1.34) and m.amplification > 1.0
    assert marriage_of(u, e, "mobilite", "self", None, "passive", 0.0, (0.0, 0.0), "any").exposure == "longue"
    # mobilité donnée (bulle de +1 à la charge) : règle des buffs donnés, A neutre
    lo, _ = FACTOR_BOUNDS
    assert role_fit("mobilite", ChassisProfile(reach=7.5), 18.5) == lo
    g = marriage_of(u, e, "mobilite", "friendly_aura", 12, "passive", 1.0, (0.0, 0.0), "any", role=0.66,
                    chassis_profile=prof, mobility_ref=ref)
    assert g.amplification == 1.0 and g.role_fit == pytest.approx(0.66)


# ----- soins (v36, réponses utilisateur du 2026-11-23) ---------------------------------------------------------


def _heal(kind="heal", value=2.0, requires="", detail="", scope=""):
    return (kind, requires, "", "", "immédiat", scope, "", "soin", value, detail)


def test_heal_points_follow_the_healing_rules():
    """Un soin ne retire que les dégâts de la figurine entamée : nul à 1 PV par figurine, plafonné à PV − 1 ;
    un retour de figurines vaut N × PV, nul sur une figurine unique."""
    from aospy.analysis.layers.marriage import heal_points

    assert heal_points(_unit(5, health=14), [_heal(value=3.5)]) == 3.5
    assert heal_points(_unit(5, health=1, models=20, hero=False), [_heal(value=3.5)]) == 0.0
    assert heal_points(_unit(5, health=3, models=5, hero=False), [_heal(value=3.5)]) == 2.0
    assert heal_points(_unit(5, health=2, models=10, hero=False), [_heal("return_models", 2.0)]) == 4.0
    assert heal_points(_unit(5, health=14), [_heal("return_models", 1.0)]) == 0.0
    assert heal_points(_unit(5, health=14), [_heal(value=0.0)]) is None  # « Heal (X) »


def test_heal_uses_per_round():
    from aospy.analysis.layers.marriage import heal_uses_per_round

    assert heal_uses_per_round("unlimited", "any") == 2  # fin de chaque tour
    assert heal_uses_per_round("unlimited", "yours") == 1  # sa phase des héros
    assert heal_uses_per_round("once_per_battle", "any") is None


def test_heal_survival_gain():
    """A d'un soin sur soi : rounds de survie gagnés sous la pression de S ; rien sur des figurines à 1 PV."""
    from aospy.analysis.layers.marriage import heal_survival_gain

    big = _unit(5, health=15)
    g_small = heal_survival_gain(big, [_heal(value=2.0)], "unlimited", "any", (7.0, 0.0), "contact")
    g_big = heal_survival_gain(big, [_heal(value=3.5)], "unlimited", "any", (7.0, 0.0), "contact")
    assert 0 < g_small < g_big
    horde = _unit(5, health=1, models=20, hero=False)
    assert heal_survival_gain(horde, [_heal(value=3.5)], "unlimited", "any", (4.0, 0.0), "contact") == 0.0


def test_self_heal_marriage():
    """Soin sur soi : exposition d'un buff perso, A = gain ÷ référence, R règle du buff défensif ; « au combat »
    (soin après ses attaques de mêlée) se paie P(au combat), même avec une portée d'arme « melee »."""
    from aospy.analysis.layers.marriage import P_IN_COMBAT_MELEE

    u = _unit(5, health=15)
    prof = ChassisProfile(off_rank=0.3, def_rank=0.9, share_melee=1.0)
    m = marriage_of(u, [_heal(value=2.0)], "soin", "self", None, "unlimited", 1.0, (4.0, 0.0), "any",
                    chassis_profile=prof, heal_ref=0.5)
    assert m.exposure == "contact" and m.tempo == 1.0
    assert m.role_fit == pytest.approx(1.45) and m.amplification == FACTOR_BOUNDS[1]
    fight = marriage_of(u, [_heal(value=2.0, requires="au combat", scope="melee")], "soin", "self", None,
                        "unlimited", 1.0, (4.0, 0.0), "any", chassis_profile=prof, heal_ref=0.5)
    assert fight.p_trigger == pytest.approx(P_IN_COMBAT_MELEE)


def test_given_heal_in_combat_range_of_an_ally_is_not_contact():
    """Mobile Repairs : soigner un allié « within this unit's combat range » colle le porteur à son allié, pas à
    l'ennemi ; soin donné : R = le porteur suit-il ses receveurs."""
    u = _unit(4, health=5)
    m = marriage_of(u, [_heal(value=3.0)], "soin", "one_friendly", 1, "unlimited", 1.0, (1.0, 1.0), "yours",
                    role=role_fit("soin", ChassisProfile(reach=7.5), 15.0))
    assert m.exposure == "courte" and m.role_fit == pytest.approx(0.5)


# ----- contrôle (v36, réponses utilisateur du 2026-11-23) -----------------------------------------------------


def _ctl(value=3.0, requires=""):
    return ("stat_mod", requires, "", "", "permanent", "", "control", "controle", value, "utilitaire")


def test_control_reference_measures_tipping_objectives():
    """A : P(l'emporter sur une charte au hasard) gagnée — un bonus qui fait basculer un petit score vaut plus."""
    from aospy.analysis.layers.marriage import ControlReference

    ref = ControlReference([1, 2, 2, 5, 5, 5, 10, 10, 20])
    assert ref.p_win(5) == pytest.approx((3 + 1.5) / 9)
    small = _unit(5, health=1, models=3, hero=False)  # contrôle 3 × 1
    big = _unit(5, health=1, models=25, hero=False)  # gagne déjà contre tout
    assert ref.gain(small, 3) > ref.gain(big, 3) == 0.0


def test_personal_control_marriage():
    """Contrôle sur soi : toujours au contact ; A = gain ÷ médiane ; R = 0,5 + moyenne(rang de contrôle, rang déf.).
    « You control the target objective » (scope battlefield) n'est pas tenu par une unité."""
    from aospy.analysis.layers.marriage import ControlReference

    ref = ControlReference([1, 2, 2, 5, 5, 5, 10, 10, 20], gain_median=0.2)
    u = _unit(5, health=1, models=3, hero=False)
    prof = ChassisProfile(def_rank=0.9, share_melee=0.0)
    m = marriage_of(u, [_ctl(10.0)], "controle", "self", None, "passive", 0.0, (1.0, 1.0), "any",
                    chassis_profile=prof, control_ref=ref)
    assert m.exposure == "contact" and m.amplification == FACTOR_BOUNDS[1]
    assert m.role_fit == pytest.approx(0.5 + (ref.p_win(3) + 0.9) / 2)
    flip = marriage_of(u, [("control", "", "", "", "", "", "", "controle", 0.0, "")], "controle", "battlefield",
                       None, "once_per_battle_army", 0.0, (1.0, 1.0), "any", control_ref=ref)
    assert flip.exposure == "longue"

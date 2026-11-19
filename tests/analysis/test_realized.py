"""Couche 3 — valeur réalisée (analysis/realized.py) : pondération validée par l'utilisateur."""

from __future__ import annotations

import pytest

from aospy.analysis.encounter import EffectSpec
from aospy.analysis.realized import (ONCE_PER_BATTLE_LASTING, ONCE_PER_BATTLE_SHORT, OwnEffect, applicable,
                                     coverage, realize)
from aospy.domain.models import Unit, Weapon

SWORD = Weapon("Sword", "melee", attacks=2, hit=3, wound=3, damage=1)


def _unit(**kw):
    base = dict(name="U", army_id=1, move=5, save=4, health=2, control=1, models=5, points=100,
                keywords=frozenset({"INFANTRY"}), weapons=[SWORD])
    base.update(kw)
    return Unit(**base)


def _eff(spec, freq="passive", p=1.0, name="A"):
    return OwnEffect(ability=name, spec=spec, frequency=freq, activation_prob=p)


def test_coverage_weights():
    assert coverage("passive", "permanent") == 1.0
    assert coverage("once_per_turn_army", "tour") == 1.0          # anti-spam : compte en liste, pas ici
    assert coverage("once_per_battle", "tour") == ONCE_PER_BATTLE_SHORT == 0.5
    assert coverage("once_per_battle_army", "bataille") == ONCE_PER_BATTLE_LASTING == pytest.approx(8 / 9)


def test_permanent_effects_combine_multiplicatively():
    u = _unit()
    both = realize(u, [_eff(EffectSpec("stat_mod", "damage", 1.0, weapon_scope="melee")),
                       _eff(EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee"))])
    assert both.off_realized == pytest.approx(both.off_chassis * 2 * 1.5)


def test_once_per_battle_and_activation_weighting():
    u = _unit()
    r = realize(u, [_eff(EffectSpec("fight_twice", duration="phase"), freq="once_per_battle", p=0.5)])
    assert r.off_realized == pytest.approx(r.off_chassis * (1 + 0.5 * 0.5))


def test_conditional_effects_only_in_good_case():
    u = _unit()
    r = realize(u, [_eff(EffectSpec("stat_mod", "damage", 1.0, weapon_scope="melee", requires="a chargé"))])
    assert r.off_realized == pytest.approx(r.off_chassis)
    assert r.off_good_case == pytest.approx(r.off_chassis * 2)
    assert r.n_conditional == 1


def test_charge_bonus_is_good_case_only():
    u = _unit()
    r = realize(u, [_eff(EffectSpec("charge_bonus", detail="Charge (+1 Damage)", weapon_scope="melee"))])
    assert r.off_realized == pytest.approx(r.off_chassis)
    assert r.off_good_case == pytest.approx(r.off_chassis * 2)


def test_applicable_respects_target_and_excludes_self():
    u = _unit(keywords=frozenset({"INFANTRY", "HERO"}))
    e = _eff(EffectSpec("stat_mod", "hit", 1.0))
    vocab = frozenset({"INFANTRY", "HERO", "CAVALRY"})
    assert applicable(u, [("self", "", False, "A", e)], vocab) == [e]
    assert applicable(u, [("friendly_aura", "INFANTRY", False, "A", e)], vocab) == [e]
    assert applicable(u, [("friendly_aura", "non-HERO INFANTRY", False, "A", e)], vocab) == []
    assert applicable(u, [("one_friendly", "", True, "A", e)], vocab) == []      # « another friendly »
    assert applicable(u, [("one_enemy", "", False, "A", e)], vocab) == []


def test_resource_weighting():
    assert coverage("unlimited", "tour", uses_resource=True) == 0.5
    assert coverage("unlimited", "tour", available_round=3) == pytest.approx((1 + 1 / 3 + 1 / 3) / 3)
    assert coverage("passive", "permanent") == 1.0


def test_alternatives_keep_strongest():
    from aospy.analysis.realized import strongest_alternatives

    one = _eff(EffectSpec("stat_mod", "damage", 1.0, weapon_scope="melee", requires="porteur blessé"), name="Runic")
    two = _eff(EffectSpec("stat_mod", "damage", 2.0, weapon_scope="melee", requires="porteur blessé"), name="Runic")
    other = _eff(EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee"), name="Runic")
    assert strongest_alternatives([one, two, other]) == [two, other]


def test_spending_a_resource_halves_weight_but_is_not_a_condition():
    from aospy.abilities.perimeter import SPENDS_RESOURCE

    u = _unit()
    e = _eff(EffectSpec("fight_twice", duration="phase", requires=SPENDS_RESOURCE), freq="unlimited")
    assert not e.conditional and e.weight == 0.5
    r = realize(u, [e])
    assert r.off_realized == pytest.approx(r.off_chassis * 1.5)

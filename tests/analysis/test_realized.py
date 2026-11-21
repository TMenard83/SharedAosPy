"""Couche 3 — valeur réalisée (analysis/layers/realized.py) : pondération validée par l'utilisateur."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.realized import ONCE_PER_BATTLE_SHORT, OwnEffect, applicable, coverage, realize
from aospy.domain.models import Unit, Weapon


@pytest.fixture(autouse=True)
def _mean_reading(monkeypatch):
    """Pondérations vérifiées sur les moyennes ; le plancher a ses tests dans test_encounter.py."""
    monkeypatch.setattr("aospy.analysis.layers.encounter.FLOOR_COVERAGE", None)


SWORD = Weapon("Sword", "melee", attacks=2, hit=3, wound=3, damage=1)


def _unit(**kw):
    base = dict(
        name="U",
        army_id=1,
        move=5,
        save=4,
        health=2,
        control=1,
        models=5,
        points=100,
        keywords=frozenset({"INFANTRY"}),
        weapons=[SWORD],
    )
    base.update(kw)
    return Unit(**base)


def _eff(spec, freq="passive", p=1.0, name="A"):
    return OwnEffect(ability=name, spec=spec, frequency=freq, activation_prob=p)


def test_coverage_weights():
    assert coverage("passive", "permanent") == 1.0
    assert coverage("once_per_turn_army", "tour") == 1.0  # anti-spam : compte en liste, pas ici
    # une fois par bataille, effet court : 1/2 (kairos) réparti sur la part du round couverte (frise, 2026-11-20)
    assert coverage("once_per_battle", "round") == ONCE_PER_BATTLE_SHORT == 0.5
    assert coverage("once_per_battle", "tour") == pytest.approx(0.25)
    assert coverage("once_per_battle_army", "bataille") == pytest.approx(8 / 9)


def test_permanent_effects_combine_multiplicatively():
    u = _unit()
    both = realize(
        u,
        [
            _eff(EffectSpec("stat_mod", "damage", 1.0, weapon_scope="melee")),
            _eff(EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee")),
        ],
    )
    assert both.off_realized == pytest.approx(both.off_chassis * 2 * 1.5)


def test_once_per_battle_and_activation_weighting():
    u = _unit()
    r = realize(u, [_eff(EffectSpec("fight_twice", duration="phase"), freq="once_per_battle", p=0.5)])
    # combat doublé une phase : 1/2 (kairos) × moitié des combats d'une unité de mêlée (l'autre tour) × P 0,5
    assert r.off_realized == pytest.approx(r.off_chassis * (1 + 0.25 * 0.5))


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
    assert applicable(u, [("one_friendly", "", True, "A", e)], vocab) == []  # « another friendly »
    assert applicable(u, [("one_enemy", "", False, "A", e)], vocab) == []


def test_resource_weighting():
    assert coverage("unlimited", "tour", uses_resource=True) == 0.5
    assert coverage("unlimited", "tour", available_round=3) == pytest.approx((1 + 1 / 3 + 1 / 3) / 3)
    assert coverage("passive", "permanent") == 1.0


def test_alternatives_keep_strongest():
    from aospy.analysis.layers.realized import strongest_alternatives

    one = _eff(EffectSpec("stat_mod", "damage", 1.0, weapon_scope="melee", requires="porteur blessé"), name="Runic")
    two = _eff(EffectSpec("stat_mod", "damage", 2.0, weapon_scope="melee", requires="porteur blessé"), name="Runic")
    other = _eff(EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee"), name="Runic")
    assert strongest_alternatives([one, two, other]) == [two, other]


def test_spending_a_resource_halves_weight_but_is_not_a_condition():
    from aospy.abilities.perimeter import SPENDS_RESOURCE

    u = _unit()
    e = _eff(EffectSpec("fight_twice", duration="phase", requires=SPENDS_RESOURCE), freq="unlimited")
    assert not e.conditional and e.weight() == 0.5
    r = realize(u, [e])
    assert r.off_realized == pytest.approx(r.off_chassis * 1.5)


def test_combined_penalises_glass_cannons():
    from aospy.analysis.layers.realized import combined

    assert combined(10.0, 4.5) < combined(5.0, 20.0)
    assert combined(4.0, 9.0) == pytest.approx(6.0)
    assert combined(0.0, 30.0) == 0.0


# --- Soutien des héros (variante B) -------------------------------------------------------------------------


def test_support_receivers_by_scope():
    from aospy.analysis.layers.realized import support_receivers

    assert support_receivers("one_friendly", 12) == 1
    assert support_receivers("friendly_aura", 12) == 2
    assert support_receivers("friendly_aura", 18) == 3
    assert support_receivers("army", None) == 3
    assert support_receivers("self", None) == 0


def test_hero_mobility_without_support_is_variant_a():
    from aospy.analysis.layers.realized import hero_mobility

    assert hero_mobility(5.0, 20.0, 0.9, 8.5, [], 12.0) == 0.9


def test_hero_mobility_weights_support_by_its_value():
    from aospy.analysis.layers.mobility import mobility_factor
    from aospy.analysis.layers.realized import Support, hero_mobility

    sup = Support("Buff", "aura", 18.0, off=5.0, def_=0.0)  # autant que sa propre offense, portée 5 + 18
    f = hero_mobility(5.0, 20.0, 0.9, 8.5, [sup], 12.0)
    f_off = (0.9 + mobility_factor(23.0, 12.0)) / 2
    assert abs(f - (f_off * 0.9) ** 0.5) < 1e-9


def test_friendly_target_matches_curly_apostrophe_keyword():
    import dataclasses

    from aospy.analysis.layers.encounter import matches_friendly_target

    vocab = frozenset({"GUNNAR’S OATHSWORN", "INFANTRY"})
    base = _unit()
    kin = dataclasses.replace(base, keywords=frozenset({"GUNNAR’S OATHSWORN", "INFANTRY"}))
    other = dataclasses.replace(base, keywords=frozenset({"INFANTRY"}))
    assert matches_friendly_target(kin, "GUNNAR'S OATHSWORN", vocab)
    assert not matches_friendly_target(other, "GUNNAR'S OATHSWORN", vocab)

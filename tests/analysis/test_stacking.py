"""Couche 4 : empilement des effets reçus par une unité de la liste (analysis/layers/stacking.py)."""

from __future__ import annotations

from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.stacking import core_command_costs, stack_for, stacks

from .test_listing import _ab, _unit


def _hit(scope="melee"):
    return EffectSpec("stat_mod", "hit", 1.0, weapon_scope=scope)


def test_core_command_costs_come_from_the_handbook_json():
    """Coûts en PC lus dans le verbatim du MdG (`generic_core_abilities.json`)."""
    costs = core_command_costs()
    assert costs == {"All-out Attack": 1, "All-out Defence": 1}


def test_total_modifier_is_capped_and_duplicates_flagged():
    """Deux « +1 pour toucher » font +1 (plafond sur le TOTAL) : chacun est plafonné (l'autre en place, il n'ajoute
    rien) ; le +1 Attaque ne l'est pas ; l'ensemble vaut l'ensemble sans le doublon."""
    u = _unit("Hammer")
    offers = [
        ("Bless", "charte : A", _hit(), "", "", 0),
        ("Fury", "charte : B", _hit(), "", "a chargé", 0),
        ("More", "charte : C", EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee"), "", "", 0),
    ]
    st = stack_for(u, offers)
    by = {i.ability: i for i in st.items}
    assert by["Bless"].capped and by["Fury"].capped and not by["More"].capped
    without = stack_for(u, [offers[0], offers[2]])
    assert st.off_joint_pct == without.off_joint_pct  # deux +1 toucher ne s'additionnent pas
    assert by["Fury"].conditions == "a chargé"


def test_wards_do_not_stack_and_commands_are_offered():
    """Protections non cumulées ; All-out Attack / All-out Defence proposées à chaque unité avec leur coût."""
    u = _unit("Rock")
    ward = _ab("Shield", scope="army", effects=[EffectSpec("ward", value=5.0)])
    ward2 = _ab("Rune", scope="army", effects=[EffectSpec("ward", value=5.0)])
    (st,) = stacks([ward, ward2], [u], frozenset())
    names = {i.ability: i for i in st.items}
    assert "All-out Attack" in names and names["All-out Defence"].cp == 1
    assert names["Shield"].capped or names["Rune"].capped
    assert st.cp == 2


def test_extra_rend_is_flagged_useless_only_against_the_4_plus_save():
    """Perforation 2 + 1 + 1 contre 4+ : la sauvegarde est impossible dès Perforation 3, le second +1 n'ajoute rien
    — « sauvegarde 4+ déjà impossible », pas un doublon : il sert contre 3+ (leçon du 2026-11-23)."""
    import dataclasses

    from aospy.domain.models import Weapon

    glaive = Weapon("Glaive", "melee", attacks=7, hit=3, wound=2, rend=2, damage=3)
    u = dataclasses.replace(_unit("Skreech"), weapons=[glaive])
    rend = lambda: EffectSpec("stat_mod", "rend", 1.0, weapon_scope="melee")  # noqa: E731 (deux effets distincts)
    st = stack_for(u, [("Claw-picked", "formation", rend(), "", "", 0), ("Blades", "charte", rend(), "", "", 0)])
    by = {i.ability: i for i in st.items}
    assert by["Claw-picked"].capped and by["Claw-picked"].capped_reason == "sauvegarde 4+ déjà impossible"
    assert st.off_after_3 > st.off_before_3
    hit = lambda: EffectSpec("stat_mod", "hit", 1.0, weapon_scope="melee")  # noqa: E731
    st2 = stack_for(u, [("A", "x", hit(), "", "", 0), ("B", "y", hit(), "", "", 0)])
    assert {i.capped_reason for i in st2.items} == {"plafond ±1 / non cumulable"}


def test_single_target_choice_counts_what_the_unit_already_receives():
    """Une aptitude à cible unique se juge sur l'apport réel, les autres effets en place : +1 Perforation vaut plus
    sur une unité qui a déjà +1 Attaque (leçon Haldahir : Trempés de Sang sur les Bloodletters)."""
    from aospy.analysis.layers.stacking import stacks, target_choices
    from aospy.domain.models import Weapon

    blades = [Weapon("Blades", "melee", attacks=2, hit=3, wound=3, rend=0, damage=1)]
    a = _unit("A", models=20, health=2, keywords=frozenset({"DAEMON"}), weapons=blades)
    b = _unit("B", models=20, health=2, keywords=frozenset({"BLOODBOUND"}), weapons=blades)
    more = _ab("Commander", scope="one_friendly", friendly_target="DAEMON",
               effects=[EffectSpec("stat_mod", "attacks", 1.0, weapon_scope="melee")])
    rend = _ab("Drenched", scope="one_friendly", effects=[EffectSpec("stat_mod", "rend", 1.0, weapon_scope="melee")])
    (tc,) = [t for t in target_choices([more, rend], stacks([more, rend], [a, b], frozenset({"DAEMON", "BLOODBOUND"})))
             if t.ability == "Drenched"]
    assert tc.candidates[0][0] == "A" and tc.candidates[0][1] > tc.candidates[1][1]

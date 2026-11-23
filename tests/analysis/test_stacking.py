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

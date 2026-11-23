"""Couche 4 : grilles de couche 3 rejouées sur les receveurs d'une liste (analysis/layers/listgrid.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.listgrid import grid_rows, is_drawback, keep_up
from aospy.analysis.layers.marriage import ControlReference

from .test_listing import _ab, _unit


def _grid(abilities, units, **kw):
    args = dict(
        share_melee={u.name: 1.0 for u in units},
        families={a.uid: a.name.split(":")[0] for a in abilities},
        bearer_marriage={},
        reach_in={u.name: float(u.move) for u in units},
        incoming={u.id: (4.0, 0.0) for u in units},
        control_ref=ControlReference([1, 2, 2, 5, 5, 5, 10, 10, 20]),
        damage={u.name: 10.0 for u in units},
    )
    args.update(kw)
    return grid_rows(abilities, units, frozenset(), **args)


def test_keep_up_against_the_list_receivers():
    """Le porteur suit-il les receveurs DE LA LISTE : son allonge ÷ leur allonge médiane, plafonnée à 1."""
    assert keep_up(7.5, [15.0, 18.0, 21.0]) == pytest.approx(0.42)
    assert keep_up(12.0, [8.0]) == 1.0
    assert keep_up(None, [8.0]) is None and keep_up(8.0, []) is None


def test_drawbacks_leave_the_reading():
    """Battle Damaged, « maximum control score of 1 », restriction sur sa propre manifestation : contreparties."""
    bd = _ab("Battle Damaged", effects=[EffectSpec("stat_mod", "power_level", -1.0, detail="malus"),
                                        EffectSpec("battle_damaged", detail="While this unit has 10 or more")])
    swing = _ab("The Pendulum Swings", effects=[EffectSpec("restriction", detail="cannot use CHARGE")])
    heal = _ab("Regeneration", effects=[EffectSpec("heal", value=2.0)])
    assert is_drawback(bd) and is_drawback(swing) and not is_drawback(heal)


def test_given_heal_is_measured_on_each_list_receiver():
    """Soin donné : survie gagnée par CHAQUE receveur de la liste ; rien sur des figurines à 1 PV ; le porteur à
    6" suit mal des receveurs à 10"."""
    hero = _unit("Healer", move=6, health=6, keywords=frozenset({"HERO", "X"}))
    monster = _unit("Big", id=2, move=10, health=14, keywords=frozenset({"MONSTER", "X"}))
    horde = _unit("Horde", id=3, move=10, health=1, models=20, keywords=frozenset({"INFANTRY", "X"}))
    ab = _ab("soin:Mend", scope="friendly_aura", freq="unlimited", carriers=["Healer"],
             effects=[EffectSpec("heal", value=3.0)], excludes_self=True)
    rows, drawbacks = _grid([ab], [hero, monster, horde])
    assert not drawbacks
    (row,) = rows
    got = dict(row.receivers)
    assert got["Big"].startswith("survie +") and got["Horde"].startswith("rien")
    assert row.keep_up == pytest.approx(0.6)


def test_given_control_and_magic_labels():
    """Contrôle donné : objectif avant → après pour chaque receveur ; bonus de lancement : lancers servis."""
    caster = _unit("Wiz", move=6, keywords=frozenset({"HERO", "WIZARD", "WIZARD (2)"}))
    troop = _unit("Troop", id=2, move=6, health=1, models=3, control=1, keywords=frozenset({"INFANTRY"}))
    ctl = _ab("controle:Banner", scope="friendly_aura", carriers=["Wiz"],
              effects=[EffectSpec("stat_mod", "control", 3.0)])
    mag = _ab("magie-ressource:Focus", scope="friendly_aura", carriers=["Wiz"],
              effects=[EffectSpec("stat_mod", "cast", 1.0)])
    rows, _ = _grid([ctl, mag], [caster, troop])
    by = {r.ability: dict(r.receivers) for r in rows}
    assert by["controle:Banner"]["Troop"] == "objectif 33% → 67%"
    assert by["magie-ressource:Focus"]["Wiz"] == "2 sort(s) par tour"
    assert by["magie-ressource:Focus"]["Troop"] == "ne lance rien"

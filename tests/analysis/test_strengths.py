from types import SimpleNamespace as NS

from aospy.analysis.layers import strengths
from aospy.domain.models import Unit, Weapon


def _unit(name, models=1, save=4, ward=None, kw=(), points=200, rend=1, control=1, move=5, anti=""):
    w = Weapon(name="arme", kind="melee", attacks=4, hit=3, wound=3, rend=rend, damage=2, abilities=anti or None)
    return Unit(name=name, army_id=1, move=move, save=save, health=10, control=control, models=models,
                points=points, ward=ward, keywords=frozenset(kw), weapons=[w])


def _rep(units, marriages=()):
    sheets = [NS(name=u.name, points=u.points, copies=1, off_rank=0.5, def_rank=0.5, share_melee=1.0, fly=False,
                 engage_round=1) for u in units]
    return NS(units=[(u.name, u.points, u) for u in units], sheets=sheets, abilities=[], marriages=list(marriages),
              stacks=[], vocab=frozenset(), magic=None, curve=None)


def _texts(traits, kind):
    return " | ".join(t.text for t in traits if t.kind == kind)


def test_monster_list_without_shooting_few_units():
    units = [_unit(f"Monstre{i}", kw=("MONSTER",), save=3, anti="Anti-INFANTRY (+1 Rend)") for i in range(4)]
    traits = strengths.synthesis(_rep(units))
    weak, strong = _texts(traits, "faiblesse"), _texts(traits, "force")
    assert "monstres (MONSTER)" in weak
    assert "4 unités seulement" in weak
    assert "pas de tir" in weak
    assert "3+ ou mieux sans ward" in weak
    assert "Anti-X dans la liste : INFANTRY" in strong
    assert all(t.counter for t in traits)


def test_horde_with_ward_and_charge_dependency():
    units = [_unit(f"Bloc{i}", models=20, save=5, ward=5, kw=("INFANTRY",), points=150, control=1, rend=0)
             for i in range(12)]
    m = [NS(ability="Fureur", receiver="Bloc0", score=40.0, giver=1.0, conditions="a chargé"),
         NS(ability="Bulle", receiver="Bloc1", score=20.0, giver=1.0, conditions="")]
    traits = strengths.synthesis(_rep(units, m))
    weak, strong = _texts(traits, "faiblesse"), _texts(traits, "force")
    assert "12 unités" in strong and "ward" in strong and "contrôle" in strong
    assert "infanterie (INFANTRY)" in weak and "peu de perforation" in weak
    assert "demande d'avoir chargé" in weak
    assert "5+ ou pire" not in weak  # ward 5+ : pas punie par le volume

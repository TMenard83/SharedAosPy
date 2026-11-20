"""Corrections d'erreurs de source et vérification croisée Wahapedia × BSData."""

from __future__ import annotations

from aospy.domain.models import Unit, Weapon
from aospy.importers.bsdata import ParsedUnit, ParsedWeapon
from aospy.importers.corrections import ability_correction, correct_ability_fields, correct_unit
from aospy.importers.verify import compare_units
from aospy.importers.wahapedia import keyword_variants

STAFF = Weapon("Staff", "melee", attacks=4, hit=4, wound=4, rend=1, damage=2)


def _unit(**kw):
    base = dict(name="Thanquol", army_id=1, move=8, save=4, health=14, control=5, models=1, points=310,
                is_hero=True, keywords=frozenset({"HERO", "WIZARD"}), weapons=[STAFF])
    base.update(kw)
    return Unit(**base)


def test_wahapedia_keeps_caster_level():
    assert keyword_variants({"keyword": "Wizard", "parameter": "2"}) == {"WIZARD", "WIZARD (2)"}
    assert keyword_variants({"keyword": "PRIEST", "parameter": "1"}) == {"PRIEST", "PRIEST (1)"}
    assert keyword_variants({"keyword": "WARD", "parameter": "5+"}) == {"WARD"}


def test_unit_correction_wins():
    fixed = correct_unit(_unit(), {"keywords_add": ["wizard (2)"], "stats": {"save": 3},
                                   "weapons": {"Staff": {"damage": 3}}})
    assert "WIZARD (2)" in fixed.keywords and fixed.save == 3 and fixed.weapons[0].damage == 3
    assert fixed.is_hero


def test_ability_correction_replaces_text_only_where_given():
    fixes = [{"faction": "Lumineth Realm-lords", "name": "DEPICT RUNE", "effect": "full text", "declare": None}]
    c = ability_correction(fixes, "lumineth realm-lords", "Depict Rune")
    got = correct_ability_fields({"name": "DEPICT RUNE", "condition": "c", "declare": "d", "effect": "cut"}, c)
    assert got == {"name": "DEPICT RUNE", "condition": "c", "declare": "d", "effect": "full text"}
    assert ability_correction(fixes, "Skaven", "DEPICT RUNE") is None


def test_compare_units_flags_lost_caster_level_and_weapon_stats():
    waha = {"Thanquol": _unit()}
    bs = {"Thanquol": ParsedUnit("t", "Thanquol", 8, 4, 14, 5, 1, True, None,
                                 frozenset({"HERO", "WIZARD (2)"}),
                                 [ParsedWeapon("Staff", "melee", 1, 4, 4, 4, 1, 3)])}
    diffs = {(d.field, d.bsdata) for d in compare_units(waha, bs)}
    assert ("mots-clés", "+WIZARD (2)") in diffs
    assert ("Staff.damage", "3") in diffs
    assert not compare_units({"Thanquol": _unit(keywords=frozenset({"HERO", "WIZARD", "WIZARD (2)"}),
                                                weapons=[Weapon("Staff", "melee", range_in=1, attacks=4, hit=4,
                                                                wound=4, rend=1, damage=3)])}, bs)

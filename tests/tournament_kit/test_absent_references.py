from aospy.tournament_kit.list_parser import parse_list
from aospy.tournament_kit.resolution.absent_references import find_absent_references

_LIST = """Test 2000/2000 pts

Skaven
Claw-horde
General's Handbook 2026-27
Drops: 1

General's Regiment
Lord Skreech Verminking (350)
 • General
Deathmaster Crixxit (150)
Night Runners (130)
"""


def test_flags_abilities_citing_units_missing_from_the_list():
    refs = {(r.ability, r.unit) for r in find_absent_references(parse_list(_LIST))}
    assert ("The Dreaded Thirteenth Spell", "Clanrats") in refs
    assert ("Diversionary Assault", "Gutter Runners") in refs


def test_unit_present_in_the_list_is_not_flagged():
    text = _LIST.replace("Night Runners (130)", "Night Runners (130)\nClanrats (100)\nGutter Runners (90)")
    refs = {(r.ability, r.unit) for r in find_absent_references(parse_list(text))}
    assert ("The Dreaded Thirteenth Spell", "Clanrats") not in refs
    assert ("Diversionary Assault", "Gutter Runners") not in refs


def test_flags_friendly_unit_type_keyword_missing_from_the_list():
    from aospy.tournament_kit.resolution.absent_references import find_absent_keywords

    refs = {(r.ability, r.unit) for r in find_absent_keywords(parse_list(_LIST))}
    assert ("TOO QUICK TO HIT-HIT", "CAVALRY") in refs
    assert not any(kw == "INFANTRY" for _, kw in refs)  # Night Runners = Infanterie

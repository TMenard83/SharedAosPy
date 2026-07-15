"""Tests unitaires pour le parser BSData (sans appel réseau)."""

from __future__ import annotations

from aospy.importers import bsdata
from aospy.importers.bsdata import parse_dice, parse_library_units, parse_main_costs, parse_target


def test_parse_target_basic() -> None:
    assert parse_target("4+") == 4
    assert parse_target("2+") == 2
    assert parse_target("-") == 7
    assert parse_target("") == 7


def test_parse_dice_constants_and_dice() -> None:
    assert parse_dice("3") == 3
    assert parse_dice("0") == 0
    assert parse_dice("-") == 0
    assert parse_dice("D3") == 2
    assert parse_dice("D6") == 4  # round(1*(6+1)/2)=round(3.5)=4
    assert parse_dice("2D6") == 7
    assert parse_dice('5"') == 5
    assert parse_dice("D6+3") == 7   # round(3.5) + 3
    assert parse_dice("2D6+3") == 10
    assert parse_dice("D3+3") == 5
    assert parse_dice('D6+5"') == 9


def _main_xml(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<catalogue xmlns="{bsdata.NS}">'
        f'<entryLinks>{entries}</entryLinks>'
        '</catalogue>'
    )


def test_parse_main_costs_extracts_only_priced_entries() -> None:
    xml = _main_xml(
        '<entryLink targetId="u-abc">'
        '  <costs><cost name="pts" typeId="points" value="120"/></costs>'
        '</entryLink>'
        '<entryLink targetId="u-no-cost"/>'
        '<entryLink targetId="u-zero">'
        '  <costs><cost name="pts" typeId="points" value="0"/></costs>'
        '</entryLink>'
    )
    costs = parse_main_costs(xml)
    assert costs == {"u-abc": 120}


def test_parse_main_costs_keeps_max_for_duplicate_targets() -> None:
    xml = _main_xml(
        '<entryLink targetId="u-dup">'
        '  <costs><cost name="pts" typeId="points" value="310"/></costs>'
        '</entryLink>'
        '<entryLink targetId="u-dup">'
        '  <costs><cost name="pts" typeId="points" value="160"/></costs>'
        '</entryLink>'
    )
    costs = parse_main_costs(xml)
    assert costs == {"u-dup": 310}


def test_parse_main_costs_max_regardless_of_order() -> None:
    xml = _main_xml(
        '<entryLink targetId="u-flip">'
        '  <costs><cost name="pts" typeId="points" value="90"/></costs>'
        '</entryLink>'
        '<entryLink targetId="u-flip">'
        '  <costs><cost name="pts" typeId="points" value="160"/></costs>'
        '</entryLink>'
    )
    costs = parse_main_costs(xml)
    assert costs == {"u-flip": 160}


def _library_xml(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<catalogue xmlns="{bsdata.NS}">'
        f'<sharedSelectionEntries>{entries}</sharedSelectionEntries>'
        '</catalogue>'
    )


_LIBERATORS = '''
<selectionEntry id="u-lib" type="unit" name="Liberators">
  <categoryLinks>
    <categoryLink name="WARD (6+)"/>
  </categoryLinks>
  <profiles>
    <profile typeName="Unit" name="Liberators">
      <characteristics>
        <characteristic name="Move">5"</characteristic>
        <characteristic name="Save">4+</characteristic>
        <characteristic name="Health">2</characteristic>
        <characteristic name="Control">1</characteristic>
      </characteristics>
    </profile>
  </profiles>
  <selectionEntries>
    <selectionEntry type="model" name="Liberator">
      <constraints>
        <constraint type="min" field="selections" value="5"/>
      </constraints>
      <profiles>
        <profile typeName="Melee Weapon" name="Warhammer">
          <characteristics>
            <characteristic name="Atk">2</characteristic>
            <characteristic name="Hit">3+</characteristic>
            <characteristic name="Wnd">3+</characteristic>
            <characteristic name="Rnd">1</characteristic>
            <characteristic name="Dmg">1</characteristic>
            <characteristic name="Ability">Crit (2 Hits)</characteristic>
          </characteristics>
        </profile>
      </profiles>
    </selectionEntry>
  </selectionEntries>
</selectionEntry>
'''


_LORD = '''
<selectionEntry id="u-lord" type="unit" name="Lord-Vigilant">
  <categoryLinks><categoryLink name="HERO"/></categoryLinks>
  <profiles>
    <profile typeName="Unit" name="Lord-Vigilant">
      <characteristics>
        <characteristic name="Move">6"</characteristic>
        <characteristic name="Save">3+</characteristic>
        <characteristic name="Health">7</characteristic>
        <characteristic name="Control">2</characteristic>
      </characteristics>
    </profile>
  </profiles>
</selectionEntry>
'''


def test_parse_library_units_extracts_profiles_and_weapons() -> None:
    units = parse_library_units(_library_xml(_LIBERATORS + _LORD))
    assert set(units) == {"u-lib", "u-lord"}

    lib = units["u-lib"]
    assert lib.name == "Liberators"
    assert lib.move == 5
    assert lib.save == 4
    assert lib.health == 2
    assert lib.control == 1
    assert lib.models == 5
    assert lib.ward == 6
    assert lib.is_hero is False
    assert lib.keywords == frozenset()  # WARD (6+) exclu : ce n'est pas un mot-clé de jeu
    assert len(lib.weapons) == 1
    w = lib.weapons[0]
    assert w.kind == "melee"
    assert w.range_in == 1
    assert (w.attacks, w.hit, w.wound, w.rend, w.damage) == (2, 3, 3, 1, 1)
    assert w.abilities == "Crit (2 Hits)"

    lord = units["u-lord"]
    assert lord.is_hero is True
    assert lord.ward is None
    assert lord.keywords == frozenset({"HERO"})
    assert lord.models == 1
    assert lord.weapons == []

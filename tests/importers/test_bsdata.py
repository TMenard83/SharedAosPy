"""Tests unitaires pour le parser BSData (sans appel réseau)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

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


# ----- Résolution des porteurs (wielders) --------------------------------------

def _frag(xml: str) -> ET.Element:
    """Parse un unique élément fragment dans le namespace BSData."""
    wrapper = ET.fromstring(f'<root xmlns="{bsdata.NS}">{xml}</root>')
    return wrapper[0]


def test_unit_wide_max_ignores_per_instance_scopes() -> None:
    entry = _frag('''
      <selectionEntry>
        <constraints>
          <constraint type="max" field="selections" scope="parent" value="1"/>
          <constraint type="max" field="selections" scope="some-unit-id" value="3"/>
        </constraints>
      </selectionEntry>
    ''')
    assert bsdata._unit_wide_max(entry) == 3


def test_unit_wide_max_keeps_smallest_of_several_unit_scopes() -> None:
    entry = _frag('''
      <selectionEntry>
        <constraints>
          <constraint type="max" field="selections" scope="unit-a" value="2"/>
          <constraint type="max" field="selections" scope="unit-b" value="1"/>
        </constraints>
      </selectionEntry>
    ''')
    assert bsdata._unit_wide_max(entry) == 1


def test_unit_wide_max_none_without_unit_scope_constraint() -> None:
    entry = _frag('''
      <selectionEntry>
        <constraints>
          <constraint type="max" field="selections" scope="parent" value="1"/>
        </constraints>
      </selectionEntry>
    ''')
    assert bsdata._unit_wide_max(entry) is None


def test_replaced_by_reads_conditional_zero_modifier() -> None:
    entry = _frag('''
      <selectionEntry>
        <constraints>
          <constraint id="c1" type="min" field="selections" scope="parent" value="1"/>
        </constraints>
        <modifiers>
          <modifier type="set" value="0" field="c1">
            <conditions>
              <condition type="atLeast" field="selections" childId="replacer-1" value="1"/>
            </conditions>
          </modifier>
        </modifiers>
      </selectionEntry>
    ''')
    assert bsdata._replaced_by(entry) == ["replacer-1"]


def test_replaced_by_empty_without_own_constraint_id() -> None:
    entry = _frag("<selectionEntry/>")
    assert bsdata._replaced_by(entry) == []


def test_replaced_by_ignores_non_zero_modifiers() -> None:
    entry = _frag('''
      <selectionEntry>
        <constraints>
          <constraint id="c1" type="min" field="selections" scope="parent" value="1"/>
        </constraints>
        <modifiers>
          <modifier type="set" value="1" field="c1">
            <conditions>
              <condition type="atLeast" field="selections" childId="replacer-1" value="1"/>
            </conditions>
          </modifier>
        </modifiers>
      </selectionEntry>
    ''')
    assert bsdata._replaced_by(entry) == []


def test_group_cap_reads_max_scope_parent() -> None:
    group = _frag('''
      <selectionEntryGroup>
        <constraints>
          <constraint type="max" field="selections" scope="parent" value="1"/>
        </constraints>
      </selectionEntryGroup>
    ''')
    assert bsdata._group_cap(group) == 1


def test_group_cap_none_without_constraint() -> None:
    group = _frag("<selectionEntryGroup/>")
    assert bsdata._group_cap(group) is None


def test_option_damage_score_ranks_higher_damage_weapon_first() -> None:
    weak = _frag('''
      <selectionEntry name="Sling">
        <profiles>
          <profile typeName="Ranged Weapon" name="Sling">
            <characteristics>
              <characteristic name="Atk">1</characteristic>
              <characteristic name="Hit">5+</characteristic>
              <characteristic name="Wnd">5+</characteristic>
              <characteristic name="Rnd">0</characteristic>
              <characteristic name="Dmg">1</characteristic>
            </characteristics>
          </profile>
        </profiles>
      </selectionEntry>
    ''')
    strong = _frag('''
      <selectionEntry name="Cannon">
        <profiles>
          <profile typeName="Ranged Weapon" name="Cannon">
            <characteristics>
              <characteristic name="Atk">6</characteristic>
              <characteristic name="Hit">2+</characteristic>
              <characteristic name="Wnd">2+</characteristic>
              <characteristic name="Rnd">2</characteristic>
              <characteristic name="Dmg">3</characteristic>
            </characteristics>
          </profile>
        </profiles>
      </selectionEntry>
    ''')
    assert bsdata._option_damage_score(strong) > bsdata._option_damage_score(weak)


_ENDRINRIGGERS_LIKE = '''
<selectionEntry id="u-end" type="unit" name="Endrinriggers">
  <profiles>
    <profile typeName="Unit" name="Endrinriggers">
      <characteristics>
        <characteristic name="Move">10"</characteristic>
        <characteristic name="Save">4+</characteristic>
        <characteristic name="Health">3</characteristic>
        <characteristic name="Control">1</characteristic>
      </characteristics>
    </profile>
  </profiles>
  <selectionEntries>
    <selectionEntry type="model" name="Endrinrigger">
      <constraints>
        <constraint type="min" field="selections" scope="parent" value="3"/>
      </constraints>
      <profiles>
        <profile typeName="Melee Weapon" name="Privateer Pistol Butt">
          <characteristics>
            <characteristic name="Atk">1</characteristic>
            <characteristic name="Hit">4+</characteristic>
            <characteristic name="Wnd">4+</characteristic>
            <characteristic name="Rnd">0</characteristic>
            <characteristic name="Dmg">1</characteristic>
          </characteristics>
        </profile>
      </profiles>
      <selectionEntries>
        <selectionEntry id="skyrigger-bundle" name="Skyrigger Heavy Weapon and Gun Butt">
          <constraints>
            <constraint type="max" field="selections" scope="u-end" value="1"/>
          </constraints>
          <selectionEntries>
            <selectionEntry name="Skyrigger Heavy Weapon">
              <profiles>
                <profile typeName="Ranged Weapon" name="Skyrigger Heavy Weapon">
                  <characteristics>
                    <characteristic name="Atk">1</characteristic>
                    <characteristic name="Hit">3+</characteristic>
                    <characteristic name="Wnd">3+</characteristic>
                    <characteristic name="Rnd">2</characteristic>
                    <characteristic name="Dmg">3</characteristic>
                  </characteristics>
                </profile>
              </profiles>
            </selectionEntry>
            <selectionEntry name="Gun Butt">
              <profiles>
                <profile typeName="Melee Weapon" name="Gun Butt">
                  <characteristics>
                    <characteristic name="Atk">1</characteristic>
                    <characteristic name="Hit">4+</characteristic>
                    <characteristic name="Wnd">4+</characteristic>
                    <characteristic name="Rnd">0</characteristic>
                    <characteristic name="Dmg">1</characteristic>
                  </characteristics>
                </profile>
              </profiles>
            </selectionEntry>
          </selectionEntries>
        </selectionEntry>
      </selectionEntries>
    </selectionEntry>
  </selectionEntries>
</selectionEntry>
'''


def test_extract_weapons_propagates_nested_bundle_unit_wide_cap() -> None:
    """Le plafond du wrapper (1/3 modèles) doit s'appliquer à ses deux sous-armes,
    pas la taille pleine du groupe (cf. CLAUDE.md "BSData wielders resolution")."""
    units = parse_library_units(_library_xml(_ENDRINRIGGERS_LIKE))
    unit = units["u-end"]
    by_name = {w.name: w for w in unit.weapons}
    assert by_name["Privateer Pistol Butt"].wielders == 3
    assert by_name["Skyrigger Heavy Weapon"].wielders == 1
    assert by_name["Gun Butt"].wielders == 1


_STEGADON_LIKE = '''
<selectionEntry id="u-steg" type="unit" name="Stegadon">
  <profiles>
    <profile typeName="Unit" name="Stegadon">
      <characteristics>
        <characteristic name="Move">8"</characteristic>
        <characteristic name="Save">3+</characteristic>
        <characteristic name="Health">14</characteristic>
        <characteristic name="Control">3</characteristic>
      </characteristics>
    </profile>
  </profiles>
  <selectionEntries>
    <selectionEntry type="model" name="Stegadon">
      <constraints>
        <constraint type="min" field="selections" scope="parent" value="1"/>
      </constraints>
    </selectionEntry>
  </selectionEntries>
  <selectionEntryGroups>
    <selectionEntryGroup name="Wargear Options">
      <constraints>
        <constraint type="max" field="selections" scope="parent" value="1"/>
      </constraints>
      <selectionEntries>
        <selectionEntry name="Skystreak Bow">
          <profiles>
            <profile typeName="Ranged Weapon" name="Skystreak Bow">
              <characteristics>
                <characteristic name="Atk">6</characteristic>
                <characteristic name="Hit">3+</characteristic>
                <characteristic name="Wnd">3+</characteristic>
                <characteristic name="Rnd">2</characteristic>
                <characteristic name="Dmg">2</characteristic>
              </characteristics>
            </profile>
          </profiles>
        </selectionEntry>
        <selectionEntry name="Sunfire Throwers">
          <profiles>
            <profile typeName="Ranged Weapon" name="Sunfire Throwers">
              <characteristics>
                <characteristic name="Atk">2</characteristic>
                <characteristic name="Hit">4+</characteristic>
                <characteristic name="Wnd">4+</characteristic>
                <characteristic name="Rnd">0</characteristic>
                <characteristic name="Dmg">1</characteristic>
              </characteristics>
            </profile>
          </profiles>
        </selectionEntry>
      </selectionEntries>
    </selectionEntryGroup>
  </selectionEntryGroups>
</selectionEntry>
'''


def test_extract_weapons_keeps_only_best_option_under_group_cap() -> None:
    """Un `selectionEntryGroup` plafonné sous son nombre d'options (Stegadon : bow OU
    throwers) ne garde que la meilleure par dégât espéré ; l'autre est absente, pas
    seulement à wielders=0 (cf. CLAUDE.md "BSData wielders resolution")."""
    units = parse_library_units(_library_xml(_STEGADON_LIKE))
    unit = units["u-steg"]
    names = {w.name for w in unit.weapons}
    assert names == {"Skystreak Bow"}
    assert unit.weapons[0].wielders == 1

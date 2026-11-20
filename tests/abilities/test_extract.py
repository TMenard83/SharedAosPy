"""Extraction par règles : timing, déclenchement, portée, effets."""

from __future__ import annotations

import pytest

from aospy.abilities.extract import extract, p_2d6, p_d6
from aospy.abilities.models import RawAbility
from aospy.abilities.text import clean, split_declare_effect


def _raw(effect: str, declare: str = "", condition: str = "Passive", cost_type: str = "",
         cost_value: str = "", is_reaction: bool = False) -> RawAbility:
    return RawAbility(uid="x", name="Test", source_kind="warscroll", group_name="",
                      condition=condition, phase="", wahapedia_type="", is_reaction=is_reaction,
                      keywords="", cost_type=cost_type, cost_value=cost_value,
                      declare=declare, effect=effect)


def test_clean_strips_html_tooltips_and_quotes():
    raw = ('<b>Declare:</b> Pick a <a href="/x">visible</a> enemy unit.<br><br>'
           '<b>Effect:</b> Inflict D3 <a href="">mortal damage</a> on the ‘target’.'
           '<br><br><b>Designer’s Note:</b> <i>blah</i>')
    declare, effect = split_declare_effect(clean(raw))
    assert declare == "Pick a visible enemy unit."
    assert effect == "Inflict D3 mortal damage on the 'target'."
    assert clean("Reaction: You declared a %000010870<ky>FIGHT</ky> ability%") == \
        "Reaction: You declared a FIGHT ability"


def test_probabilities():
    assert p_2d6(7) == pytest.approx(21 / 36)
    assert p_d6(3) == pytest.approx(4 / 6)
    assert p_2d6(2) == 1.0 and p_2d6(13) == 0.0


@pytest.mark.parametrize("cond,freq,turn", [
    ("Passive", "passive", "any"),
    ("Once Per Turn (Army), Any Combat Phase", "once_per_turn_army", "any"),
    ("Once Per Battle, Your Hero Phase", "once_per_battle", "yours"),
    ("Deployment Phase", "unlimited", "deployment"),
    ("Enemy Hero Phase", "unlimited", "enemy"),
])
def test_timing(cond, freq, turn):
    ex, _ = extract(_raw("Add 1 to hit rolls for this unit.", condition=cond))
    assert (ex.frequency, ex.turn) == (freq, turn)


def test_spell_activation_and_gate_roll_multiply():
    ex, _ = extract(_raw("Roll a dice. On a 3+, inflict D3 mortal damage on the target.",
                         declare="Pick a visible enemy unit within 18\" of this unit to be the target.",
                         condition="Your Hero Phase", cost_type="Spell", cost_value="7"))
    assert ex.activation_prob == pytest.approx(p_2d6(7) * p_d6(3), abs=1e-3)
    assert ex.scope == "one_enemy" and ex.range_inches == 18
    mortal = [e for e in ex.effects if e.kind == "mortal_damage"]
    assert mortal and mortal[0].value == 2.0 and mortal[0].dice == "D3"
    assert ex.variance == "des"


def test_command_is_automatic():
    ex, _ = extract(_raw("Add 1 to charge rolls for the target.", condition="Your Charge Phase",
                         declare="Pick a friendly unit to be the target.", cost_type="Command", cost_value="1"))
    assert ex.activation_prob == 1.0


def test_friendly_aura_bubble():
    ex, _ = extract(_raw("Add 1 to wound rolls for combat attacks made by friendly STORMCAST ETERNALS "
                         "units while they are wholly within 12\" of this unit."))
    assert ex.scope == "friendly_aura" and ex.range_inches == 12 and ex.wholly_within
    mod = ex.effects[0]
    assert (mod.kind, mod.stat, mod.value, mod.side, mod.detail) == ("stat_mod", "wound", 1, "friendly", "offensif")


def test_target_clause_ignores_caster_pick():
    ex, _ = extract(_raw("Add 1 to save rolls for the target.",
                         declare="Pick a friendly WIZARD to cast this spell, pick a visible friendly unit "
                                 "wholly within 12\" of them to be the target, then make a casting roll of 2D6.",
                         cost_type="Spell", cost_value="6"))
    assert ex.scope == "one_friendly" and ex.range_inches == 12


def test_subtract_hit_against_us_is_defensive():
    ex, _ = extract(_raw("Subtract 1 from hit rolls for attacks that target this unit."))
    e = ex.effects[0]
    assert (e.stat, e.side, e.detail) == ("hit", "enemy", "defensif")


def test_modified_stat_is_first_cited_not_first_in_table():
    ex, _ = extract(_raw("Add 1 to casting rolls for this unit (ward rolls cannot be made for that damage point)."))
    stats = {e.stat for e in ex.effects if e.kind == "stat_mod"}
    assert stats == {"cast"}
    assert not any(e.kind == "no_ward" for e in ex.effects)


def test_placement_constraint_is_not_an_enemy_aura():
    ex, _ = extract(_raw("Remove this unit from the battlefield and set it up again more than 9\" "
                         "from all enemy units.", condition="Your Movement Phase"))
    assert ex.scope == "self"
    assert any(e.kind == "redeploy" for e in ex.effects)


def test_charge_requirement_penalty():
    ex, penalty = extract(_raw("If this unit charged this turn, add 1 to the Damage characteristic "
                               "of its melee weapons."))
    assert "doit avoir chargé" in ex.conditions and penalty >= 1.0


def test_ward_and_battle_damaged():
    ex, _ = extract(_raw("This unit has WARD (5+)."))
    assert any(e.kind == "ward" and e.value == 5 for e in ex.effects)
    ex, _ = extract(_raw("While this unit has 10 or more damage points, the Attacks characteristic "
                         "of its Claws is 4."))
    assert any(e.kind == "battle_damaged" for e in ex.effects)


# ----- périmètre des effets (perimeter.py) -----------------------------------

def _first_mod(text, **kw):
    ex, _ = extract(_raw(text, **kw))
    return next(e for e in ex.effects if e.kind == "stat_mod")


def test_perimeter_melee_target_keyword_charge_and_duration():
    e = _first_mod("If this unit charged this turn, add 1 to the Damage characteristic of this unit's melee "
                   "weapons for attacks that target HEROES or MONSTERS for the rest of the turn.",
                   condition="Your Combat Phase")
    assert (e.stat, e.weapon_scope, e.target_keywords, e.requires, e.duration) == \
        ("damage", "melee", "HERO,MONSTER", "a chargé", "tour")
    assert not e.includes_companion


def test_perimeter_ranged_named_chosen_and_companion():
    assert _first_mod("Add 1 to hit rolls for shooting attacks made by friendly units.").weapon_scope == "ranged"
    named = _first_mod("Add 2 to the Attacks characteristic of this unit's Almighty Stomp for the rest of the battle.",
                       condition="Once Per Battle, Your Combat Phase")
    assert (named.weapon_scope, named.weapon_name, named.duration) == ("named", "Almighty Stomp", "bataille")
    assert _first_mod("Add 1 to hit rolls for attacks made with that weapon.").weapon_scope == "chosen"
    comp = _first_mod("Add 1 to wound rolls for the target's combat attacks, including attacks made with "
                      "Companion weapons.", declare="Pick a friendly unit to be the target.")
    assert comp.includes_companion and comp.weapon_scope == "melee"


def test_perimeter_duration_from_list_header_and_passive_default():
    ex, _ = extract(_raw("For the rest of the turn:\n- Add 1 to the Rend characteristic of this unit's melee weapons.",
                         condition="Your Combat Phase"))
    assert next(e for e in ex.effects if e.stat == "rend").duration == "tour"
    assert _first_mod("Add 1 to save rolls for this unit.").duration == "permanent"


def test_perimeter_target_condition():
    e = _first_mod("Add 1 to hit rolls for this unit's shooting attacks that target an enemy unit that has 10 or "
                   "more models.")
    assert e.target_condition == "cible ≥10 figurines"


@pytest.mark.parametrize("declare, effect, expected", [
    ("Pick a friendly non-HERO WARRIORS OF CHAOS INFANTRY unit that has not used a FIGHT ability this turn "
     "and is within this unit's combat range to be the target.", "The target can fight.",
     "non-HERO WARRIORS OF CHAOS INFANTRY"),
    ("Pick a friendly Crypt Horrors unit within this unit's combat range to be the target.", "x", "Crypt Horrors"),
    ("Pick a friendly STORMCAST ETERNALS PRIEST to chant this prayer, then pick a visible friendly "
     "STORMCAST ETERNALS INFANTRY unit wholly within 12\" of them to be the target.", "x",
     "STORMCAST ETERNALS INFANTRY"),
    ("Pick a friendly unit wholly within 12\" of this unit to be the target.", "x", ""),
    ("", "Add 1 to hit rolls for attacks made by friendly DEATHRATTLE or DEADWALKERS units wholly within 12\".",
     "DEATHRATTLE or DEADWALKERS"),
])
def test_friendly_target_of(declare, effect, expected):
    from aospy.abilities.extract import friendly_target_of

    assert friendly_target_of(declare, effect) == expected


# ----- revue « contresens » (analyseur v7) -------------------------------------

def test_enemy_target_in_reserve_is_not_a_prerequisite():
    ex, penalty = extract(_raw("Add 1 to hit rolls for attacks made by this unit that target its quarry.",
                               declare="Pick an enemy unit to be this unit's quarry. You can pick a unit that "
                                       "has been deployed in reserve.", condition="Deployment Phase"))
    assert "unité en réserve" not in ex.conditions and penalty == 0
    ex, penalty = extract(_raw("Add 1 to wound rolls for combat attacks made by friendly MAGNATE'S CREW units "
                               "that target the indebted unit.",
                               declare="Pick an enemy unit on the battlefield or in reserve to be indebted.",
                               condition="Once Per Battle (Army), Deployment Phase"))
    assert "unité en réserve" not in ex.conditions and penalty == 0


def test_once_per_battle_in_deployment_is_not_a_limit():
    ex, _ = extract(_raw("Add 1 to hit rolls for this unit.", condition="Once Per Battle (Army), Deployment Phase"))
    assert ex.frequency == "unlimited"


def test_subtract_against_this_unit_protects_the_user():
    ex, _ = extract(_raw("Subtract 1 from hit rolls and wound rolls for attacks made as part of that FIGHT "
                         "ability against this unit.",
                         declare="Pick an enemy MONSTER in combat with this unit to be the target.",
                         condition="Any Combat Phase"))
    mods = {(e.stat, e.side, e.detail) for e in ex.effects if e.kind == "stat_mod"}
    assert mods == {("hit", "enemy", "defensif"), ("wound", "enemy", "defensif")}


def test_control_of_that_unit_is_the_enemy_target():
    ex, _ = extract(_raw("Subtract 1 from the control score of that unit for each damage point allocated to it "
                         "this turn by a shooting attack made by a friendly EXPEDITIONARY FORCE unit.",
                         declare="Pick an enemy unit to be the target.", condition="End of Any Turn"))
    e = next(e for e in ex.effects if e.kind == "stat_mod")
    assert (e.stat, e.side) == ("control", "enemy")


def test_self_weapon_bonus_against_target_is_not_a_mark():
    ex, _ = extract(_raw("Add 1 to the Damage characteristic of this unit's Templar Weapon for attacks that "
                         "target that unit.",
                         declare="Pick an enemy MONSTER in combat with this unit to be the target.",
                         condition="Your Combat Phase"))
    assert not any(e.detail == "marquage" for e in ex.effects)
    assert score_of(ex).interaction == 0.0


@pytest.mark.parametrize("effect, declare, ft, inter", [
    ("Add 1 to wound rolls for attacks made by this unit and friendly Hobgrot Slittaz units that target the bet.",
     "Pick an enemy unit on the battlefield to be the bet.", "Hobgrot Slittaz", 1.5),
    ("For the rest of the battle, add 1 to the Rend characteristic of melee weapons used for attacks made by "
     "friendly NIGHTHAUNT units that target the condemned enemy unit.",
     "If there is not a condemned enemy unit on the battlefield, pick an enemy unit to be condemned.",
     "NIGHTHAUNT", 2.0),
])
def test_mark_shared_with_friendly_units(effect, declare, ft, inter):
    ex, _ = extract(_raw(effect, declare=declare, condition="Any Hero Phase"))
    assert any(e.detail == "marquage" for e in ex.effects)
    assert ex.friendly_target == ft
    assert score_of(ex).interaction == inter


def test_secondary_if_clause_does_not_penalize_whole_ability():
    ex, penalty = extract(_raw(
        "For the rest of the phase, the following effects apply:\n"
        "- This unit's combat attacks that target that enemy unit have Crit (2 Hits) and score critical hits "
        "on unmodified hit roll of 5+.\n"
        "- If the target is destroyed by this unit's combat attacks this phase, add 1 to the Attacks "
        "characteristic of melee weapons used by other friendly DAEMON units.",
        declare="Pick an enemy HERO or MONSTER in combat with this unit to be the target.",
        condition="Any Combat Phase"))
    assert penalty == 0
    assert any(c.endswith("(effet secondaire seulement)") for c in ex.conditions)


def score_of(ex):
    from aospy.abilities.scoring import score

    return score(ex, 0.0, "", False, "")


def test_fight_twice_is_not_activation_chaining():
    from aospy.abilities.extract import effects_of, scope_of

    gunnar = ("This unit can use 2 FIGHT abilities this phase. After the first is used, however, this unit has "
              "STRIKE-LAST for the rest of the turn. When using the second FIGHT ability, this unit must pick an "
              "enemy HERO to be the target of all of its attacks.")
    assert scope_of("", gunnar)[0] == "self"
    kinds = {e.kind for e in effects_of("", gunnar, "self", passive=False)[0]}
    assert "fight_twice" in kinds and "extra_fight" not in kinds
    chain = ("Pick a friendly Crypt Horrors unit that has not used a FIGHT ability this turn to be the target. "
             "The target can be picked to use a FIGHT ability immediately after the FIGHT ability used by this unit.")
    kinds = {e.kind for e in effects_of("", chain, "one_friendly", passive=False)[0]}
    assert "extra_fight" in kinds and "fight_twice" not in kinds


def test_if_line_followed_by_its_consequence_stays_a_condition():
    from aospy.abilities.extract import split_main_secondary

    text = ("This unit must use this ability each turn.\n"
            "If this unit used any FIGHT abilities this turn, place a rage token next to it.\n"
            "Add 1 to the Attacks characteristic of this unit's Companion weapons for each rage token it has.")
    assert split_main_secondary(text) == (text, "")


def test_prayer_banking_beats_single_roll_and_never_lowers_it():
    from aospy.abilities.extract import p_d6, p_prayer_banked

    assert p_prayer_banked(4) == pytest.approx(1 / 36 * 3 + 5 / 6 * 5 / 6)   # 1 au round 1 : rien de stocké
    assert p_prayer_banked(6) > p_d6(6) * 3
    assert p_prayer_banked(2) == pytest.approx(p_d6(2))                      # petite valeur : prier tout de suite
    assert p_prayer_banked(8) > 0 == p_d6(8)


def test_excludes_self_of():
    from aospy.abilities.extract import excludes_self_of

    assert excludes_self_of("Pick another friendly unit wholly within 12\" of this unit to be the target.", "x")
    assert excludes_self_of("", "Add 1 to hit rolls for other friendly units wholly within 12\" of this unit.")
    assert not excludes_self_of("Pick a friendly unit wholly within 12\" of this unit to be the target.", "x")


# ----- qui a chargé ? (analyseur v11) -------------------------------------------

def test_enemy_target_charged_is_not_our_charge():
    ex, penalty = extract(_raw(
        "Until the start of your next turn:\n"
        "- If the target charged in the same turn, friendly DISCIPLES OF TZEENTCH units in combat with the "
        "target have STRIKE-FIRST.\n"
        "- The target's weapons cannot be affected by the Charge (+1 Damage) weapon ability.",
        declare="Pick a visible enemy unit within 18\" of this unit to be the target, then make a casting roll "
                "of 2D6.", condition="Your Hero Phase", cost_type="Spell", cost_value="7"))
    assert "doit avoir chargé" not in ex.conditions
    assert "dépend d'une charge ennemie" in ex.conditions and penalty == 0.5


def test_enemy_unit_that_charged_and_not_charged():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects("Pick an enemy unit that charged this turn to be the target.", True) == {"ennemi"}
    assert charge_subjects("Pick a friendly unit that has not charged this turn.", False) == set()
    assert charge_subjects("If this unit charged this turn, add 1 to the Damage characteristic.", True) == {"nous"}
    assert charge_subjects("If the target charged this turn, add 1 to hit rolls for the target.", False) == {"nous"}


def test_friendly_units_that_have_not_charged_is_an_action_constraint():
    ex, _ = extract(_raw("Add 1 to hit rolls for friendly units that have not charged this turn.",
                         condition="Your Combat Phase"))
    assert "doit avoir chargé" not in ex.conditions
    assert "contrainte d'action préalable" in ex.conditions


def test_has_charged_as_consequence_is_not_a_prerequisite():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects("Remove this unit and set it up again within 1\" of an enemy unit. This unit has "
                           "charged.", False) == set()
    assert charge_subjects("If it does so, this unit has charged, and that HERO's CHARGE ability has no "
                           "effect.", False) == set()
    assert charge_subjects("If this unit has charged this turn, add 1 to hit rolls.", False) == {"nous"}


def test_charge_in_enemy_territory_and_having_charged():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects("If this unit is wholly within enemy territory and charged this phase, add 1.",
                           False) == {"nous"}
    assert charge_subjects("If the charge roll is 3 or less, it does not count as having charged.", False) == set()


def test_charge_subject_is_the_closest_mention():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects("Pick an enemy unit in combat with a friendly DROGGZ'S GITMOB unit that has charged "
                           "this turn to be the target.", True) == {"nous"}


@pytest.mark.parametrize("sentence, text, field, expected", [
    ("This unit has WARD (3+) against mortal damage inflicted by SPELL abilities.", None,
     "target_condition", "vs sorts/manifestations"),
    ("This unit has WARD (5+) against mortal damage.", None, "target_condition", "vs blessures mortelles"),
    ("Add 1 to the Damage characteristic of this unit's melee weapons while this unit has 1 damage point.", None,
     "requires", "porteur blessé"),
    ("- This unit has WARD (4+).",
     "While this unit is within the combat range of a friendly Dire Wolves unit:\n- This unit has WARD (4+).",
     "requires", "près d'une unité amie"),
])
def test_perimeter_sources_and_requirements(sentence, text, field, expected):
    from aospy.abilities.perimeter import perimeter_of

    assert expected in perimeter_of(sentence, text or sentence, passive=True, offensive=False).get(field, "")


def test_once_per_battle_lasting_effect_is_not_penalized():
    """« Once Per Battle » + « for the rest of the battle » : déclencheur anti-cumul, effet permanent."""
    from aospy.abilities.scoring import score

    def power(text, condition):
        return score(extract(_raw(text, condition=condition))[0], 0.0, "", False, text).power

    text = ("For the rest of the battle, add 1 to hit rolls for combat attacks made by friendly DARKOATH "
            "units while they are wholly within 12\" of this unit.")
    once = power(text, "Once Per Battle, Any Charge Phase")
    assert once == power(text.replace("For the rest of the battle, a", "A"), "Passive")
    assert power(text.replace("For the rest of the battle", "For the rest of the turn"),
                 "Once Per Battle, Any Charge Phase") < once


def test_rest_of_the_battle_round_is_not_lasting():
    """« for the rest of the battle round » ne dure qu'un round : pas de bonus « reste de la bataille »."""
    from aospy.abilities.scoring import score

    def power(text):
        return score(extract(_raw(text, condition="Your Hero Phase"))[0], 0.0, "", False, text).power

    body = "add 1 to hit rolls for combat attacks made by this unit."
    assert power(f"For the rest of the battle round, {body}") == power(f"For the rest of the turn, {body}")
    assert power(f"For the rest of the battle, {body}") > power(f"For the rest of the turn, {body}")


def _effect(ex, stat):
    return next(e for e in ex.effects if e.kind == "stat_mod" and e.stat == stat)


def test_friendly_target_in_combat_with_enemy_is_friendly():
    """M1 : « Pick a friendly X unit in combat with an enemy MONSTER to be the target » = cible amie."""
    ex, _ = extract(_raw(
        "For the rest of the turn, add 1 to wound rolls for the target's combat attacks and add 1 to save "
        "rolls for the target.",
        declare="Pick a friendly BONESPLITTERZ unit in combat with an enemy MONSTER to be the target.",
        condition="Any Charge Phase"))
    assert ex.scope == "one_friendly"
    assert _effect(ex, "wound").side == "friendly" and _effect(ex, "wound").detail == "offensif"


def test_spell_target_is_the_last_pick_clause():
    """M1 : « Pick a friendly WIZARD to cast this spell, pick a visible enemy unit … to be the target »."""
    ex, _ = extract(_raw("Inflict D3 mortal damage on the target.",
                         declare="Pick a friendly WIZARD to cast this spell, pick a visible enemy unit within 18\" "
                                 "of them to be the target, then make a casting roll of 2D6.",
                         condition="Your Hero Phase"))
    assert ex.scope == "one_enemy"


def test_enemy_casters_debuff():
    """M2 : −1 au lancement des SORCIERS (sans « friendly ») / des PRÊTRES ennemis = débuff ennemi."""
    ex, _ = extract(_raw("Subtract 1 from casting rolls for WIZARDS while they are within 12\" of this unit.\n"
                         "Subtract 1 from chanting rolls for enemy PRIESTS while they are within 12\" of this unit.",
                         condition="Passive"))
    assert _effect(ex, "cast").side == "enemy" and _effect(ex, "chant").side == "enemy"


def test_attacks_that_target_your_general_or_other_friendly_are_protection():
    """M3 : « shooting attacks that target your general / other friendly X units » = protection."""
    for text in ("Subtract 1 from hit rolls and wound rolls for shooting attacks that target your general.",
                 "Subtract 1 from hit rolls for shooting attacks that target other friendly SIGMARITE units "
                 "while they are wholly within 12\" of this unit."):
        ex, _ = extract(_raw(text, condition="Passive"))
        assert _effect(ex, "hit").side == "enemy" and _effect(ex, "hit").detail == "defensif"


def test_sub_ability_picking_an_enemy_sets_the_side():
    """M4 : « Prophecy of Exile: Pick a visible enemy WIZARD … Subtract 1 from that unit's power level »."""
    ex, _ = extract(_raw("Pick 1 of the following effects.\nProphecy of Exile: Pick a visible enemy WIZARD within "
                         "18\" of this unit. Subtract 1 from that unit's power level until the start of your next turn.",
                         condition="Your Hero Phase"))
    assert _effect(ex, "power_level").side == "enemy"
    ex, _ = extract(_raw("Each time a shooting attack made by this unit scores a critical hit, subtract 1\" from "
                         "the target unit's Move characteristic until the start of your next turn.",
                         condition="Passive"))
    assert _effect(ex, "move").side == "enemy"
    ex, _ = extract(_raw("Add 1 to the Attacks characteristic of the target unit's melee weapons.",
                         declare="Pick a friendly Plaguebearers unit wholly within 14\" of this unit to be the target.",
                         condition="Your Hero Phase"))
    assert _effect(ex, "attacks").side == "friendly"


def test_ward_against_our_attacks_is_offensive():
    """M5 : −1 aux jets de protection contre les dégâts de NOS attaques = débuff de l'ennemi."""
    ex, _ = extract(_raw("Subtract 1 from ward rolls for damage points inflicted by attacks made with this unit's "
                         "Godbreaker Cannon this phase.", condition="Your Shooting Phase"))
    e = _effect(ex, "ward")
    assert e.side == "enemy" and e.detail == "debuff"


def test_condition_at_start_of_text_keeps_first_letter():
    """v16 : sans « . » avant l'effet, la phrase commençait à l'index 1 (« hile this unit… »)."""
    ex, _ = extract(_raw("While this unit is contesting an objective you do not control, it has WARD (5+)."))
    ward = next(e for e in ex.effects if e.kind == "ward")
    assert "sur objectif" in ward.requires


def test_friendly_keyword_heroes_in_combat_range_is_an_aura():
    """v16 : Elite Bodyguard protège les HÉROS amis proches, pas les Stormvermin eux-mêmes."""
    ex, _ = extract(_raw("Friendly SKAVEN INFANTRY HEROES have WARD (5+) while they are within this unit's "
                         "combat range."))
    assert ex.scope == "friendly_aura"
    assert ex.friendly_target == "SKAVEN INFANTRY HEROES"


def test_per_resource_point_effect_is_flagged():
    """v16 : « For each daemonic power point this unit has » dépend de l'allocation (couche 4)."""
    from aospy.abilities.perimeter import RESOURCE_SCALED
    ex, _ = extract(_raw("For each daemonic power point this unit has:\n- Add 1\" to its Move characteristic.\n"
                         "- Add 1 to the Attacks characteristic of its weapons."))
    attacks = next(e for e in ex.effects if e.stat == "attacks")
    assert RESOURCE_SCALED in attacks.requires


@pytest.mark.parametrize("effect,label", [
    ("While this unit is contesting a questmarked objective:\n- Add 3 to this unit's control score.\n"
     "- This unit has WARD (5+).", "sur objectif"),
    ("Add 1 to save rolls for this unit while each model in this unit is contesting an objective you control.",
     "sur objectif"),
    ("If this unit is contesting an objective you control that is not within friendly territory, this unit has "
     "WARD (5+) for the rest of the battle.", "sur objectif"),
    ("While this unit's soul-bonded charge is within this unit's combat range, both this unit and that "
     "soul-bonded charge have WARD (5+).", "près d'une unité amie"),
    ("While this unit is within the combat ranges of any damaged friendly FYRESLAYERS HEROES, add 1 to the "
     "Attacks characteristic of this unit's melee weapons.", "près d'une unité amie"),
])
def test_position_conditions_on_the_bearer(effect, label):
    """v16 : conditions de position du porteur lues sous plus de formes (If, each model, questmarked…)."""
    ex, _ = extract(_raw(effect))
    assert all(label in e.requires for e in ex.effects if e.kind in ("ward", "stat_mod") and e.stat != "control")


def test_in_combat_with_enemy_heroes_is_a_target_condition():
    """v16 : Engine of Domination ne combat deux fois qu'au contact de HÉROS ennemis."""
    ex, _ = extract(_raw("If this unit is in combat with any enemy HEROES, it can use 2 FIGHT abilities this "
                         "phase.", condition="Once Per Turn (Army), Any Combat Phase"))
    assert next(e for e in ex.effects if e.kind == "fight_twice").target_keywords == "HERO"


def test_shooting_only_protection_is_tagged_anti_tir():
    """Protection limitée aux tirs : étiquette `anti-tir` (concept de liste, avis utilisateur 2026-11-20)."""
    from aospy.abilities.scoring import score
    from aospy.abilities.tags import tags_for

    text = "Subtract 1 from hit rolls and wound rolls for shooting attacks that target your general."
    raw = _raw(text, condition="Passive")
    ex, pen = extract(raw)
    assert "anti-tir" in tags_for(raw, ex, score(ex, pen, "", False, text))


@pytest.mark.parametrize("text, stat, side, declare", [
    # statut posé sur une unité ennemie (« drenched in vomit », « krump'd ») puis malus « for that unit »
    ("If any damage points are allocated to an enemy unit by attacks made with this unit's Noxious Vomit, that "
     "unit is drenched in vomit.\nWhile a unit is drenched in vomit:\n- Subtract 1 from save rolls for that unit.",
     "save", "enemy", ""),
    # « melee weapons used by enemy units »
    ("Subtract 1 from the Rend characteristic of melee weapons used by enemy units while they are in combat "
     "with this unit.", "rend", "enemy", ""),
    # protection de l'utilisateur : « attacks that target the caster / this general / a friendly unit »
    ("Until the start of your next turn, subtract 1 from the Damage characteristic of melee weapons used for "
     "attacks that target the caster.", "damage", "enemy", ""),
    ("Subtract 1 from hit rolls for combat attacks that target a friendly unit that charged in the same turn.",
     "hit", "enemy", ""),
    # « add 1 … for this unit's attacks and subtract 1 … that target this unit » : deux effets distincts
    ("For the rest of the turn, add 1 to hit rolls for this unit's attacks and subtract 1 from hit rolls for "
     "attacks that target this unit.", "hit", "friendly", ""),
    # « +1 save for attacks made by that enemy unit that target this unit » = défense de l'utilisateur
    ("Add 1 to save rolls for attacks made by that enemy unit that target this unit for the rest of the turn.",
     "save", "friendly", "Pick an enemy unit that charged this turn and is in combat with this unit to be the target."),
    # bonus du lanceur dans un sort à cible ennemie
    ("Inflict D3 mortal damage on the target. For the rest of the turn, add 1 to hit rolls for attacks made by "
     "the caster.", "hit", "friendly", "Pick a friendly WIZARD to cast this spell, pick a visible enemy unit within "
     "18\" of them to be the target, then make a casting roll of 2D6."),
    # « the target's » suit la cible déclarée amie malgré une unité ennemie citée avant
    ("If any damage points were allocated to an enemy unit by the target's combat attacks this turn, add 2 to the "
     "Attacks characteristic of the target's melee weapons.", "attacks", "friendly",
     "Pick each unit in this Regiment of Renown that used a FIGHT ability this turn to be a target."),
    # re-désignation explicite « If the target is an enemy unit »
    ("Roll a dice. On a 4+:\n- If the target is a friendly unit, its Companion weapons have Crit (2 Hits).\n"
     "- If the target is an enemy unit, subtract 1 from hit rolls for the target's attacks.", "hit", "enemy",
     "Pick a friendly OGOR MAWTRIBES unit within this unit's combat range to be the target or pick an enemy unit "
     "in combat with this unit to be the target."),
])
def test_malus_side_readings(text, stat, side, declare):
    """Revue « malus » lot 2 (analyseur v16) : qui subit vraiment le modificateur."""
    ex, _ = extract(_raw(text, declare=declare, condition="Passive" if not declare else "Any Combat Phase"))
    effs = [e for e in ex.effects if e.kind == "stat_mod" and e.stat == stat]
    assert effs and effs[0].side == side, effs


def test_two_digit_modifier_is_read():
    """« add 10 to the control scores » : modificateur à deux chiffres."""
    ex, _ = extract(_raw("Add 10 to the control scores of friendly units while they are wholly within 24\" of "
                         "this unit.", condition="Passive"))
    assert _effect(ex, "control").value == 10


@pytest.mark.parametrize("text, condition, duration", [
    ("Until the end of the phase, add 1 to ward rolls for that unit.", "Once Per Battle, Any Combat Phase", "phase"),
    ("Until the start of the next battle round, add 1 to wound rolls for combat attacks made by friendly units.",
     "Start of Battle Round", "round"),
    ("Add 1 to the Rend characteristic of Companion weapons used by the targets for the rest of turn.",
     "Any Combat Phase", "tour"),
    ("Add 1 to the casting roll for that spell.", "Reaction: You declared a SPELL ability for this unit", "action"),
    ("Add 1 to wound rolls for attacks made as part of that FIGHT ability.",
     "Reaction: You declared a FIGHT ability for this unit", "action"),
    ("Add 1 to hit rolls and wound rolls for attacks made by this unit that target its quarry.",
     "Deployment Phase", "bataille"),
    ("While any of this unit's hounds are next to an enemy unit, add 1 to hit rolls for this unit's attacks.",
     "Your Movement Phase", "conditionnelle"),
])
def test_implicit_durations(text, condition, duration):
    """Revue « duree » (analyseur v19) : durée lue sans formule « for the rest of … »."""
    ex, _ = extract(_raw(text, condition=condition, is_reaction=condition.startswith("Reaction")))
    e = next(e for e in ex.effects if e.kind == "stat_mod")
    assert e.duration == duration

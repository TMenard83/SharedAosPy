"""Extraction par règles : timing, déclenchement, portée, effets."""

from __future__ import annotations

import dataclasses

import pytest

from aospy.abilities.extract import extract, p_2d6, p_d6
from aospy.abilities.models import RawAbility
from aospy.abilities.text import clean, split_declare_effect


def _raw(
    effect: str,
    declare: str = "",
    condition: str = "Passive",
    cost_type: str = "",
    cost_value: str = "",
    is_reaction: bool = False,
) -> RawAbility:
    return RawAbility(
        uid="x",
        name="Test",
        source_kind="warscroll",
        group_name="",
        condition=condition,
        phase="",
        wahapedia_type="",
        is_reaction=is_reaction,
        keywords="",
        cost_type=cost_type,
        cost_value=cost_value,
        declare=declare,
        effect=effect,
    )


def test_clean_strips_html_tooltips_and_quotes():
    raw = (
        '<b>Declare:</b> Pick a <a href="/x">visible</a> enemy unit.<br><br>'
        '<b>Effect:</b> Inflict D3 <a href="">mortal damage</a> on the ‘target’.'
        "<br><br><b>Designer’s Note:</b> <i>blah</i>"
    )
    declare, effect = split_declare_effect(clean(raw))
    assert declare == "Pick a visible enemy unit."
    assert effect == "Inflict D3 mortal damage on the 'target'."
    assert (
        clean("Reaction: You declared a %000010870<ky>FIGHT</ky> ability%") == "Reaction: You declared a FIGHT ability"
    )


def test_probabilities():
    assert p_2d6(7) == pytest.approx(21 / 36)
    assert p_d6(3) == pytest.approx(4 / 6)
    assert p_2d6(2) == 1.0 and p_2d6(13) == 0.0


@pytest.mark.parametrize(
    "cond,freq,turn",
    [
        ("Passive", "passive", "any"),
        ("Once Per Turn (Army), Any Combat Phase", "once_per_turn_army", "any"),
        ("Once Per Battle, Your Hero Phase", "once_per_battle", "yours"),
        ("Deployment Phase", "unlimited", "deployment"),
        ("Enemy Hero Phase", "unlimited", "enemy"),
    ],
)
def test_timing(cond, freq, turn):
    ex, _ = extract(_raw("Add 1 to hit rolls for this unit.", condition=cond))
    assert (ex.frequency, ex.turn) == (freq, turn)


def test_spell_activation_and_gate_roll_multiply():
    ex, _ = extract(
        _raw(
            "Roll a dice. On a 3+, inflict D3 mortal damage on the target.",
            declare='Pick a visible enemy unit within 18" of this unit to be the target.',
            condition="Your Hero Phase",
            cost_type="Spell",
            cost_value="7",
        )
    )
    assert ex.activation_prob == pytest.approx(p_2d6(7) * p_d6(3), abs=1e-3)
    assert ex.scope == "one_enemy" and ex.range_inches == 18
    mortal = [e for e in ex.effects if e.kind == "mortal_damage"]
    assert mortal and mortal[0].value == 2.0 and mortal[0].dice == "D3"
    assert ex.variance == "des"


def test_command_is_automatic():
    ex, _ = extract(
        _raw(
            "Add 1 to charge rolls for the target.",
            condition="Your Charge Phase",
            declare="Pick a friendly unit to be the target.",
            cost_type="Command",
            cost_value="1",
        )
    )
    assert ex.activation_prob == 1.0


def test_friendly_aura_bubble():
    ex, _ = extract(
        _raw(
            "Add 1 to wound rolls for combat attacks made by friendly STORMCAST ETERNALS "
            'units while they are wholly within 12" of this unit.'
        )
    )
    assert ex.scope == "friendly_aura" and ex.range_inches == 12 and ex.wholly_within
    mod = ex.effects[0]
    assert (mod.kind, mod.stat, mod.value, mod.side, mod.detail) == ("stat_mod", "wound", 1, "friendly", "offensif")


def test_target_clause_ignores_caster_pick():
    ex, _ = extract(
        _raw(
            "Add 1 to save rolls for the target.",
            declare="Pick a friendly WIZARD to cast this spell, pick a visible friendly unit "
            'wholly within 12" of them to be the target, then make a casting roll of 2D6.',
            cost_type="Spell",
            cost_value="6",
        )
    )
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
    ex, _ = extract(
        _raw(
            'Remove this unit from the battlefield and set it up again more than 9" from all enemy units.',
            condition="Your Movement Phase",
        )
    )
    assert ex.scope == "self"
    assert any(e.kind == "redeploy" for e in ex.effects)


def test_charge_requirement_penalty():
    ex, penalty = extract(
        _raw("If this unit charged this turn, add 1 to the Damage characteristic of its melee weapons.")
    )
    assert "doit avoir chargé" in ex.conditions and penalty >= 1.0


def test_ward_and_battle_damaged():
    ex, _ = extract(_raw("This unit has WARD (5+)."))
    assert any(e.kind == "ward" and e.value == 5 for e in ex.effects)
    ex, _ = extract(_raw("While this unit has 10 or more damage points, the Attacks characteristic of its Claws is 4."))
    assert any(e.kind == "battle_damaged" for e in ex.effects)


# ----- périmètre des effets (perimeter.py) -----------------------------------


def _first_mod(text, **kw):
    ex, _ = extract(_raw(text, **kw))
    return next(e for e in ex.effects if e.kind == "stat_mod")


def test_perimeter_melee_target_keyword_charge_and_duration():
    e = _first_mod(
        "If this unit charged this turn, add 1 to the Damage characteristic of this unit's melee "
        "weapons for attacks that target HEROES or MONSTERS for the rest of the turn.",
        condition="Your Combat Phase",
    )
    assert (e.stat, e.weapon_scope, e.target_keywords, e.requires, e.duration) == (
        "damage",
        "melee",
        "HERO,MONSTER",
        "a chargé",
        "tour",
    )
    assert not e.includes_companion


def test_perimeter_ranged_named_chosen_and_companion():
    assert _first_mod("Add 1 to hit rolls for shooting attacks made by friendly units.").weapon_scope == "ranged"
    named = _first_mod(
        "Add 2 to the Attacks characteristic of this unit's Almighty Stomp for the rest of the battle.",
        condition="Once Per Battle, Your Combat Phase",
    )
    assert (named.weapon_scope, named.weapon_name, named.duration) == ("named", "Almighty Stomp", "bataille")
    assert _first_mod("Add 1 to hit rolls for attacks made with that weapon.").weapon_scope == "chosen"
    comp = _first_mod(
        "Add 1 to wound rolls for the target's combat attacks, including attacks made with Companion weapons.",
        declare="Pick a friendly unit to be the target.",
    )
    assert comp.includes_companion and comp.weapon_scope == "melee"


def test_perimeter_duration_from_list_header_and_passive_default():
    ex, _ = extract(
        _raw(
            "For the rest of the turn:\n- Add 1 to the Rend characteristic of this unit's melee weapons.",
            condition="Your Combat Phase",
        )
    )
    assert next(e for e in ex.effects if e.stat == "rend").duration == "tour"
    assert _first_mod("Add 1 to save rolls for this unit.").duration == "permanent"


def test_perimeter_target_condition():
    e = _first_mod(
        "Add 1 to hit rolls for this unit's shooting attacks that target an enemy unit that has 10 or more models."
    )
    assert e.target_condition == "cible ≥10 figurines"


@pytest.mark.parametrize(
    "declare, effect, expected",
    [
        (
            "Pick a friendly non-HERO WARRIORS OF CHAOS INFANTRY unit that has not used a FIGHT ability this turn "
            "and is within this unit's combat range to be the target.",
            "The target can fight.",
            "non-HERO WARRIORS OF CHAOS INFANTRY",
        ),
        ("Pick a friendly Crypt Horrors unit within this unit's combat range to be the target.", "x", "Crypt Horrors"),
        (
            "Pick a friendly STORMCAST ETERNALS PRIEST to chant this prayer, then pick a visible friendly "
            'STORMCAST ETERNALS INFANTRY unit wholly within 12" of them to be the target.',
            "x",
            "STORMCAST ETERNALS INFANTRY",
        ),
        ('Pick a friendly unit wholly within 12" of this unit to be the target.', "x", ""),
        (
            "",
            'Add 1 to hit rolls for attacks made by friendly DEATHRATTLE or DEADWALKERS units wholly within 12".',
            "DEATHRATTLE or DEADWALKERS",
        ),
    ],
)
def test_friendly_target_of(declare, effect, expected):
    from aospy.abilities.extract import friendly_target_of

    assert friendly_target_of(declare, effect) == expected


# ----- revue « contresens » (analyseur v7) -------------------------------------


def test_enemy_target_in_reserve_is_not_a_prerequisite():
    ex, penalty = extract(
        _raw(
            "Add 1 to hit rolls for attacks made by this unit that target its quarry.",
            declare="Pick an enemy unit to be this unit's quarry. You can pick a unit that "
            "has been deployed in reserve.",
            condition="Deployment Phase",
        )
    )
    assert "unité en réserve" not in ex.conditions and penalty == 0
    ex, penalty = extract(
        _raw(
            "Add 1 to wound rolls for combat attacks made by friendly MAGNATE'S CREW units "
            "that target the indebted unit.",
            declare="Pick an enemy unit on the battlefield or in reserve to be indebted.",
            condition="Once Per Battle (Army), Deployment Phase",
        )
    )
    assert "unité en réserve" not in ex.conditions and penalty == 0


def test_once_per_battle_in_deployment_is_not_a_limit():
    ex, _ = extract(_raw("Add 1 to hit rolls for this unit.", condition="Once Per Battle (Army), Deployment Phase"))
    assert ex.frequency == "unlimited"


def test_subtract_against_this_unit_protects_the_user():
    ex, _ = extract(
        _raw(
            "Subtract 1 from hit rolls and wound rolls for attacks made as part of that FIGHT "
            "ability against this unit.",
            declare="Pick an enemy MONSTER in combat with this unit to be the target.",
            condition="Any Combat Phase",
        )
    )
    mods = {(e.stat, e.side, e.detail) for e in ex.effects if e.kind == "stat_mod"}
    assert mods == {("hit", "enemy", "defensif"), ("wound", "enemy", "defensif")}


def test_control_of_that_unit_is_the_enemy_target():
    ex, _ = extract(
        _raw(
            "Subtract 1 from the control score of that unit for each damage point allocated to it "
            "this turn by a shooting attack made by a friendly EXPEDITIONARY FORCE unit.",
            declare="Pick an enemy unit to be the target.",
            condition="End of Any Turn",
        )
    )
    e = next(e for e in ex.effects if e.kind == "stat_mod")
    assert (e.stat, e.side) == ("control", "enemy")


def test_self_weapon_bonus_against_target_is_not_a_mark():
    ex, _ = extract(
        _raw(
            "Add 1 to the Damage characteristic of this unit's Templar Weapon for attacks that target that unit.",
            declare="Pick an enemy MONSTER in combat with this unit to be the target.",
            condition="Your Combat Phase",
        )
    )
    assert not any(e.detail == "marquage" for e in ex.effects)
    assert score_of(ex).interaction == 0.0


@pytest.mark.parametrize(
    "effect, declare, ft, inter",
    [
        (
            "Add 1 to wound rolls for attacks made by this unit and friendly Hobgrot Slittaz units that target the bet.",
            "Pick an enemy unit on the battlefield to be the bet.",
            "Hobgrot Slittaz",
            1.5,
        ),
        (
            "For the rest of the battle, add 1 to the Rend characteristic of melee weapons used for attacks made by "
            "friendly NIGHTHAUNT units that target the condemned enemy unit.",
            "If there is not a condemned enemy unit on the battlefield, pick an enemy unit to be condemned.",
            "NIGHTHAUNT",
            2.0,
        ),
    ],
)
def test_mark_shared_with_friendly_units(effect, declare, ft, inter):
    ex, _ = extract(_raw(effect, declare=declare, condition="Any Hero Phase"))
    assert any(e.detail == "marquage" for e in ex.effects)
    assert ex.friendly_target == ft
    assert score_of(ex).interaction == inter


def test_secondary_if_clause_does_not_penalize_whole_ability():
    ex, penalty = extract(
        _raw(
            "For the rest of the phase, the following effects apply:\n"
            "- This unit's combat attacks that target that enemy unit have Crit (2 Hits) and score critical hits "
            "on unmodified hit roll of 5+.\n"
            "- If the target is destroyed by this unit's combat attacks this phase, add 1 to the Attacks "
            "characteristic of melee weapons used by other friendly DAEMON units.",
            declare="Pick an enemy HERO or MONSTER in combat with this unit to be the target.",
            condition="Any Combat Phase",
        )
    )
    assert penalty == 0
    assert any(c.endswith("(effet secondaire seulement)") for c in ex.conditions)


def score_of(ex):
    from aospy.abilities.scoring import score

    return score(ex, 0.0, "", False, "")


def test_fight_twice_is_not_activation_chaining():
    from aospy.abilities.extract import effects_of, scope_of

    gunnar = (
        "This unit can use 2 FIGHT abilities this phase. After the first is used, however, this unit has "
        "STRIKE-LAST for the rest of the turn. When using the second FIGHT ability, this unit must pick an "
        "enemy HERO to be the target of all of its attacks."
    )
    assert scope_of("", gunnar)[0] == "self"
    kinds = {e.kind for e in effects_of("", gunnar, "self", passive=False)[0]}
    assert "fight_twice" in kinds and "extra_fight" not in kinds
    chain = (
        "Pick a friendly Crypt Horrors unit that has not used a FIGHT ability this turn to be the target. "
        "The target can be picked to use a FIGHT ability immediately after the FIGHT ability used by this unit."
    )
    kinds = {e.kind for e in effects_of("", chain, "one_friendly", passive=False)[0]}
    assert "extra_fight" in kinds and "fight_twice" not in kinds


def test_if_line_followed_by_its_consequence_stays_a_condition():
    from aospy.abilities.extract import split_main_secondary

    text = (
        "This unit must use this ability each turn.\n"
        "If this unit used any FIGHT abilities this turn, place a rage token next to it.\n"
        "Add 1 to the Attacks characteristic of this unit's Companion weapons for each rage token it has."
    )
    assert split_main_secondary(text) == (text, "")


def test_prayer_banking_beats_single_roll_and_never_lowers_it():
    from aospy.abilities.extract import p_d6, p_prayer_banked

    assert p_prayer_banked(4) == pytest.approx(1 / 36 * 3 + 5 / 6 * 5 / 6)  # 1 au round 1 : rien de stocké
    assert p_prayer_banked(6) > p_d6(6) * 3
    assert p_prayer_banked(2) == pytest.approx(p_d6(2))  # petite valeur : prier tout de suite
    assert p_prayer_banked(8) > 0 == p_d6(8)


def test_excludes_self_of():
    from aospy.abilities.extract import excludes_self_of

    assert excludes_self_of('Pick another friendly unit wholly within 12" of this unit to be the target.', "x")
    assert excludes_self_of("", 'Add 1 to hit rolls for other friendly units wholly within 12" of this unit.')
    assert not excludes_self_of('Pick a friendly unit wholly within 12" of this unit to be the target.', "x")


# ----- qui a chargé ? (analyseur v11) -------------------------------------------


def test_enemy_target_charged_is_not_our_charge():
    ex, penalty = extract(
        _raw(
            "Until the start of your next turn:\n"
            "- If the target charged in the same turn, friendly DISCIPLES OF TZEENTCH units in combat with the "
            "target have STRIKE-FIRST.\n"
            "- The target's weapons cannot be affected by the Charge (+1 Damage) weapon ability.",
            declare='Pick a visible enemy unit within 18" of this unit to be the target, then make a casting roll '
            "of 2D6.",
            condition="Your Hero Phase",
            cost_type="Spell",
            cost_value="7",
        )
    )
    assert "doit avoir chargé" not in ex.conditions
    assert "dépend d'une charge ennemie" in ex.conditions and penalty == 0.5


def test_enemy_unit_that_charged_and_not_charged():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects("Pick an enemy unit that charged this turn to be the target.", True) == {"ennemi"}
    assert charge_subjects("Pick a friendly unit that has not charged this turn.", False) == set()
    assert charge_subjects("If this unit charged this turn, add 1 to the Damage characteristic.", True) == {"nous"}
    assert charge_subjects("If the target charged this turn, add 1 to hit rolls for the target.", False) == {"nous"}


def test_friendly_units_that_have_not_charged_is_an_action_constraint():
    ex, _ = extract(
        _raw("Add 1 to hit rolls for friendly units that have not charged this turn.", condition="Your Combat Phase")
    )
    assert "doit avoir chargé" not in ex.conditions
    assert "contrainte d'action préalable" in ex.conditions


def test_has_charged_as_consequence_is_not_a_prerequisite():
    from aospy.abilities.perimeter import charge_subjects

    assert (
        charge_subjects(
            'Remove this unit and set it up again within 1" of an enemy unit. This unit has charged.', False
        )
        == set()
    )
    assert (
        charge_subjects("If it does so, this unit has charged, and that HERO's CHARGE ability has no effect.", False)
        == set()
    )
    assert charge_subjects("If this unit has charged this turn, add 1 to hit rolls.", False) == {"nous"}


def test_charge_in_enemy_territory_and_having_charged():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects("If this unit is wholly within enemy territory and charged this phase, add 1.", False) == {
        "nous"
    }
    assert charge_subjects("If the charge roll is 3 or less, it does not count as having charged.", False) == set()


def test_charge_subject_is_the_closest_mention():
    from aospy.abilities.perimeter import charge_subjects

    assert charge_subjects(
        "Pick an enemy unit in combat with a friendly DROGGZ'S GITMOB unit that has charged "
        "this turn to be the target.",
        True,
    ) == {"nous"}


@pytest.mark.parametrize(
    "sentence, text, field, expected",
    [
        (
            "This unit has WARD (3+) against mortal damage inflicted by SPELL abilities.",
            None,
            "target_condition",
            "vs sorts/manifestations",
        ),
        ("This unit has WARD (5+) against mortal damage.", None, "target_condition", "vs blessures mortelles"),
        (
            "Add 1 to the Damage characteristic of this unit's melee weapons while this unit has 1 damage point.",
            None,
            "requires",
            "porteur blessé",
        ),
        (
            "- This unit has WARD (4+).",
            "While this unit is within the combat range of a friendly Dire Wolves unit:\n- This unit has WARD (4+).",
            "requires",
            "près d'une unité amie",
        ),
    ],
)
def test_perimeter_sources_and_requirements(sentence, text, field, expected):
    from aospy.abilities.perimeter import perimeter_of

    assert expected in perimeter_of(sentence, text or sentence, passive=True, offensive=False).get(field, "")


def test_once_per_battle_lasting_effect_is_not_penalized():
    """« Once Per Battle » + « for the rest of the battle » : déclencheur anti-cumul, effet permanent."""
    from aospy.abilities.scoring import score

    def power(text, condition):
        return score(extract(_raw(text, condition=condition))[0], 0.0, "", False, text).power

    text = (
        "For the rest of the battle, add 1 to hit rolls for combat attacks made by friendly DARKOATH "
        'units while they are wholly within 12" of this unit.'
    )
    once = power(text, "Once Per Battle, Any Charge Phase")
    assert once == power(text.replace("For the rest of the battle, a", "A"), "Passive")
    assert (
        power(
            text.replace("For the rest of the battle", "For the rest of the turn"), "Once Per Battle, Any Charge Phase"
        )
        < once
    )


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
    ex, _ = extract(
        _raw(
            "For the rest of the turn, add 1 to wound rolls for the target's combat attacks and add 1 to save "
            "rolls for the target.",
            declare="Pick a friendly BONESPLITTERZ unit in combat with an enemy MONSTER to be the target.",
            condition="Any Charge Phase",
        )
    )
    assert ex.scope == "one_friendly"
    assert _effect(ex, "wound").side == "friendly" and _effect(ex, "wound").detail == "offensif"


def test_spell_target_is_the_last_pick_clause():
    """M1 : « Pick a friendly WIZARD to cast this spell, pick a visible enemy unit … to be the target »."""
    ex, _ = extract(
        _raw(
            "Inflict D3 mortal damage on the target.",
            declare='Pick a friendly WIZARD to cast this spell, pick a visible enemy unit within 18" '
            "of them to be the target, then make a casting roll of 2D6.",
            condition="Your Hero Phase",
        )
    )
    assert ex.scope == "one_enemy"


def test_enemy_casters_debuff():
    """M2 : −1 au lancement des SORCIERS (sans « friendly ») / des PRÊTRES ennemis = débuff ennemi."""
    ex, _ = extract(
        _raw(
            'Subtract 1 from casting rolls for WIZARDS while they are within 12" of this unit.\n'
            'Subtract 1 from chanting rolls for enemy PRIESTS while they are within 12" of this unit.',
            condition="Passive",
        )
    )
    assert _effect(ex, "cast").side == "enemy" and _effect(ex, "chant").side == "enemy"


def test_attacks_that_target_your_general_or_other_friendly_are_protection():
    """M3 : « shooting attacks that target your general / other friendly X units » = protection."""
    for text in (
        "Subtract 1 from hit rolls and wound rolls for shooting attacks that target your general.",
        "Subtract 1 from hit rolls for shooting attacks that target other friendly SIGMARITE units "
        'while they are wholly within 12" of this unit.',
    ):
        ex, _ = extract(_raw(text, condition="Passive"))
        assert _effect(ex, "hit").side == "enemy" and _effect(ex, "hit").detail == "defensif"


def test_sub_ability_picking_an_enemy_sets_the_side():
    """M4 : « Prophecy of Exile: Pick a visible enemy WIZARD … Subtract 1 from that unit's power level »."""
    ex, _ = extract(
        _raw(
            "Pick 1 of the following effects.\nProphecy of Exile: Pick a visible enemy WIZARD within "
            "18\" of this unit. Subtract 1 from that unit's power level until the start of your next turn.",
            condition="Your Hero Phase",
        )
    )
    assert _effect(ex, "power_level").side == "enemy"
    ex, _ = extract(
        _raw(
            'Each time a shooting attack made by this unit scores a critical hit, subtract 1" from '
            "the target unit's Move characteristic until the start of your next turn.",
            condition="Passive",
        )
    )
    assert _effect(ex, "move").side == "enemy"
    ex, _ = extract(
        _raw(
            "Add 1 to the Attacks characteristic of the target unit's melee weapons.",
            declare='Pick a friendly Plaguebearers unit wholly within 14" of this unit to be the target.',
            condition="Your Hero Phase",
        )
    )
    assert _effect(ex, "attacks").side == "friendly"


def test_ward_against_our_attacks_is_offensive():
    """M5 : −1 aux jets de protection contre les dégâts de NOS attaques = débuff de l'ennemi."""
    ex, _ = extract(
        _raw(
            "Subtract 1 from ward rolls for damage points inflicted by attacks made with this unit's "
            "Godbreaker Cannon this phase.",
            condition="Your Shooting Phase",
        )
    )
    e = _effect(ex, "ward")
    assert e.side == "enemy" and e.detail == "debuff"


def test_condition_at_start_of_text_keeps_first_letter():
    """v16 : sans « . » avant l'effet, la phrase commençait à l'index 1 (« hile this unit… »)."""
    ex, _ = extract(_raw("While this unit is contesting an objective you do not control, it has WARD (5+)."))
    ward = next(e for e in ex.effects if e.kind == "ward")
    assert "sur objectif" in ward.requires


def test_friendly_keyword_heroes_in_combat_range_is_an_aura():
    """v16 : Elite Bodyguard protège les HÉROS amis proches, pas les Stormvermin eux-mêmes."""
    ex, _ = extract(
        _raw("Friendly SKAVEN INFANTRY HEROES have WARD (5+) while they are within this unit's combat range.")
    )
    assert ex.scope == "friendly_aura"
    assert ex.friendly_target == "SKAVEN INFANTRY HEROES"


def test_per_resource_point_effect_is_flagged():
    """v16 : « For each daemonic power point this unit has » dépend de l'allocation (couche 4)."""
    from aospy.abilities.perimeter import RESOURCE_SCALED

    ex, _ = extract(
        _raw(
            'For each daemonic power point this unit has:\n- Add 1" to its Move characteristic.\n'
            "- Add 1 to the Attacks characteristic of its weapons."
        )
    )
    attacks = next(e for e in ex.effects if e.stat == "attacks")
    assert RESOURCE_SCALED in attacks.requires


@pytest.mark.parametrize(
    "effect,label",
    [
        (
            "While this unit is contesting a questmarked objective:\n- Add 3 to this unit's control score.\n"
            "- This unit has WARD (5+).",
            "sur objectif",
        ),
        (
            "Add 1 to save rolls for this unit while each model in this unit is contesting an objective you control.",
            "sur objectif",
        ),
        (
            "If this unit is contesting an objective you control that is not within friendly territory, this unit has "
            "WARD (5+) for the rest of the battle.",
            "sur objectif",
        ),
        (
            "While this unit's soul-bonded charge is within this unit's combat range, both this unit and that "
            "soul-bonded charge have WARD (5+).",
            "près d'une unité amie",
        ),
        (
            "While this unit is within the combat ranges of any damaged friendly FYRESLAYERS HEROES, add 1 to the "
            "Attacks characteristic of this unit's melee weapons.",
            "près d'une unité amie",
        ),
    ],
)
def test_position_conditions_on_the_bearer(effect, label):
    """v16 : conditions de position du porteur lues sous plus de formes (If, each model, questmarked…)."""
    ex, _ = extract(_raw(effect))
    assert all(label in e.requires for e in ex.effects if e.kind in ("ward", "stat_mod") and e.stat != "control")


def test_in_combat_with_enemy_heroes_is_a_target_condition():
    """v16 : Engine of Domination ne combat deux fois qu'au contact de HÉROS ennemis."""
    ex, _ = extract(
        _raw(
            "If this unit is in combat with any enemy HEROES, it can use 2 FIGHT abilities this phase.",
            condition="Once Per Turn (Army), Any Combat Phase",
        )
    )
    assert next(e for e in ex.effects if e.kind == "fight_twice").target_keywords == "HERO"


def test_shooting_only_protection_is_tagged_anti_tir():
    """Protection limitée aux tirs : étiquette `anti-tir` (concept de liste, avis utilisateur 2026-11-20)."""
    from aospy.abilities.scoring import score
    from aospy.abilities.tags import tags_for

    text = "Subtract 1 from hit rolls and wound rolls for shooting attacks that target your general."
    raw = _raw(text, condition="Passive")
    ex, pen = extract(raw)
    assert "anti-tir" in tags_for(raw, ex, score(ex, pen, "", False, text))


@pytest.mark.parametrize(
    "text, stat, side, declare",
    [
        # statut posé sur une unité ennemie (« drenched in vomit », « krump'd ») puis malus « for that unit »
        (
            "If any damage points are allocated to an enemy unit by attacks made with this unit's Noxious Vomit, that "
            "unit is drenched in vomit.\nWhile a unit is drenched in vomit:\n- Subtract 1 from save rolls for that unit.",
            "save",
            "enemy",
            "",
        ),
        # « melee weapons used by enemy units »
        (
            "Subtract 1 from the Rend characteristic of melee weapons used by enemy units while they are in combat "
            "with this unit.",
            "rend",
            "enemy",
            "",
        ),
        # protection de l'utilisateur : « attacks that target the caster / this general / a friendly unit »
        (
            "Until the start of your next turn, subtract 1 from the Damage characteristic of melee weapons used for "
            "attacks that target the caster.",
            "damage",
            "enemy",
            "",
        ),
        (
            "Subtract 1 from hit rolls for combat attacks that target a friendly unit that charged in the same turn.",
            "hit",
            "enemy",
            "",
        ),
        # « add 1 … for this unit's attacks and subtract 1 … that target this unit » : deux effets distincts
        (
            "For the rest of the turn, add 1 to hit rolls for this unit's attacks and subtract 1 from hit rolls for "
            "attacks that target this unit.",
            "hit",
            "friendly",
            "",
        ),
        # « +1 save for attacks made by that enemy unit that target this unit » = défense de l'utilisateur
        (
            "Add 1 to save rolls for attacks made by that enemy unit that target this unit for the rest of the turn.",
            "save",
            "friendly",
            "Pick an enemy unit that charged this turn and is in combat with this unit to be the target.",
        ),
        # bonus du lanceur dans un sort à cible ennemie
        (
            "Inflict D3 mortal damage on the target. For the rest of the turn, add 1 to hit rolls for attacks made by "
            "the caster.",
            "hit",
            "friendly",
            "Pick a friendly WIZARD to cast this spell, pick a visible enemy unit within "
            '18" of them to be the target, then make a casting roll of 2D6.',
        ),
        # « the target's » suit la cible déclarée amie malgré une unité ennemie citée avant
        (
            "If any damage points were allocated to an enemy unit by the target's combat attacks this turn, add 2 to the "
            "Attacks characteristic of the target's melee weapons.",
            "attacks",
            "friendly",
            "Pick each unit in this Regiment of Renown that used a FIGHT ability this turn to be a target.",
        ),
        # re-désignation explicite « If the target is an enemy unit »
        (
            "Roll a dice. On a 4+:\n- If the target is a friendly unit, its Companion weapons have Crit (2 Hits).\n"
            "- If the target is an enemy unit, subtract 1 from hit rolls for the target's attacks.",
            "hit",
            "enemy",
            "Pick a friendly OGOR MAWTRIBES unit within this unit's combat range to be the target or pick an enemy unit "
            "in combat with this unit to be the target.",
        ),
    ],
)
def test_malus_side_readings(text, stat, side, declare):
    """Revue « malus » lot 2 (analyseur v16) : qui subit vraiment le modificateur."""
    ex, _ = extract(_raw(text, declare=declare, condition="Passive" if not declare else "Any Combat Phase"))
    effs = [e for e in ex.effects if e.kind == "stat_mod" and e.stat == stat]
    assert effs and effs[0].side == side, effs


def test_two_digit_modifier_is_read():
    """« add 10 to the control scores » : modificateur à deux chiffres."""
    ex, _ = extract(
        _raw(
            'Add 10 to the control scores of friendly units while they are wholly within 24" of this unit.',
            condition="Passive",
        )
    )
    assert _effect(ex, "control").value == 10


@pytest.mark.parametrize(
    "text, condition, duration",
    [
        (
            "Until the end of the phase, add 1 to ward rolls for that unit.",
            "Once Per Battle, Any Combat Phase",
            "phase",
        ),
        (
            "Until the start of the next battle round, add 1 to wound rolls for combat attacks made by friendly units.",
            "Start of Battle Round",
            "round",
        ),
        (
            "Add 1 to the Rend characteristic of Companion weapons used by the targets for the rest of turn.",
            "Any Combat Phase",
            "tour",
        ),
        ("Add 1 to the casting roll for that spell.", "Reaction: You declared a SPELL ability for this unit", "action"),
        (
            "Add 1 to wound rolls for attacks made as part of that FIGHT ability.",
            "Reaction: You declared a FIGHT ability for this unit",
            "action",
        ),
        (
            "Add 1 to hit rolls and wound rolls for attacks made by this unit that target its quarry.",
            "Deployment Phase",
            "bataille",
        ),
        (
            "While any of this unit's hounds are next to an enemy unit, add 1 to hit rolls for this unit's attacks.",
            "Your Movement Phase",
            "conditionnelle",
        ),
    ],
)
def test_implicit_durations(text, condition, duration):
    """Revue « duree » (analyseur v19) : durée lue sans formule « for the rest of … »."""
    ex, _ = extract(_raw(text, condition=condition, is_reaction=condition.startswith("Reaction")))
    e = next(e for e in ex.effects if e.kind == "stat_mod")
    assert e.duration == duration


@pytest.mark.parametrize(
    "declare, effect, scope",
    [
        ("", "Friendly BONESPLITTERZ CAVALRY units have Anti-charge (+1 Rend).", "army"),
        ("", "Friendly FLESH-EATER COURTS HEROES have WARD (5+) if they have destroyed a unit this battle.", "army"),
        ("", 'Heal (3) each friendly DRACONITH SKYWING unit wholly within 12" of this unit.', "friendly_aura"),
        (
            "",
            "While any friendly SLANN units are within this unit's combat range, both this unit and those SLANN units "
            "have WARD (5+).",
            "friendly_aura",
        ),
        (
            "Pick a friendly DAUGHTERS OF KHAINE PRIEST to chant this prayer, pick a visible friendly DAUGHTERS OF KHAINE "
            'AELF INFANTRY unit wholly within 12" of them and that has not been picked to be the target of this ability '
            "this turn to be the target, then make a chanting roll of D6.",
            'The target can move up to 6".',
            "one_friendly",
        ),
        (
            "Pick a friendly ROVING MAW WIZARD to cast this spell, then make a casting roll of 2D6.",
            "Add 2 to the Rend characteristic of the caster's melee weapons until the start of your next turn.",
            "self",
        ),
        (
            "Pick a friendly WIZARD to cast this spell, then make a casting roll of 2D6.",
            'Set up a Bladewind wholly within 12" of the caster, visible to them.',
            "unknown",
        ),  # repère, pas bénéficiaire
        ("", "The friendly Volturnos has STRIKE-FIRST.", "self"),
        ("", "Subtract 1 from charge rolls for enemy units.", "all_enemies"),
        ("", "Each time a unit is destroyed during the battle, you receive 1 blood tithe point.", "army"),
        (
            "",
            "When the unit in this Regiment of Renown is destroyed, inflict 3 mortal damage on each unit (friendly and "
            "enemy) within its combat range.",
            "self",
        ),
    ],
)
def test_scope_readings_v20(declare, effect, scope):
    """Revue « portee » (analyseur v20) : bénéficiaire lu sans clause de cible classique."""
    from aospy.abilities.extract import scope_of

    assert scope_of(declare, effect)[0] == scope


@pytest.mark.parametrize(
    "text, kind",
    [
        (
            "For the rest of the turn, the targets can use CHARGE abilities even if they used a RETREAT ability in the same "
            "turn.",
            "run_and_charge",
        ),
        ("No mortal damage is inflicted on friendly units when they use RETREAT abilities.", "free_retreat"),
        (
            "Each time a friendly unit wholly within 12\" of this unit uses the 'All-out Attack' command, no command points "
            "are spent.",
            "cp_gain",
        ),
        (
            "Roll a dice. On a 2+, the target cannot use the 'All-out Defence' command in the following combat phase.",
            "lockout",
        ),
        ("When this unit moves, it can pass through models in enemy INFANTRY units.", "fly"),
        (
            "Instead of making a casting roll for the next SPELL ability used by this unit this turn, you can use a value "
            "of 12 for the roll that cannot be modified.",
            "fixed_roll",
        ),
        ("If this unit uses the 'Rally' command, you can make 3 additional rally rolls of D6.", "rally"),
        ("This unit can immediately use a SHOOT ability as if it were your shooting phase.", "extra_shoot"),
        ("Until the start of your next turn, ignore positive modifiers to save rolls for the target.", "no_buff"),
    ],
)
def test_qualitative_rules_v21(text, kind):
    """Revue « a-revoir » (analyseur v21) : mécaniques qualitatives jusque-là non lues."""
    ex, _ = extract(_raw(text, condition="Your Hero Phase"))
    assert kind in {e.kind for e in ex.effects}


def test_roll_gated_bonus_is_not_counted():
    """« If the chanting roll was 7+, in addition … » : bonus sur jet élevé, pas un effet acquis."""
    ex, _ = extract(
        _raw(
            "Add 1 to charge rolls for the target for the rest of the turn. If the chanting roll was 7+, "
            "in addition, the target can use CHARGE abilities even if it used a RUN ability.",
            declare="Pick a friendly PRIEST to chant this prayer, pick a visible friendly unit wholly "
            'within 12" of them to be the target, then make a chanting roll of D6.',
            condition="Your Hero Phase",
        )
    )
    assert "run_and_charge" not in {e.kind for e in ex.effects}


def test_charge_weapon_ability_negated_is_not_a_charge_bonus():
    ex, _ = extract(
        _raw(
            "Until the start of your next turn, the Charge (+1 Damage) weapon ability has no effect on "
            "combat attacks that target the target.",
            condition="Your Hero Phase",
        )
    )
    kinds = {e.kind for e in ex.effects}
    assert "charge_bonus" not in kinds and "no_weapon_abilities" in kinds


def test_variable_modifiers_v22():
    """« add X / D3 to … » : modificateur variable lu (X = 1 par prudence, dé = moyenne)."""
    ex, _ = extract(
        _raw(
            "Add X to charge rolls for friendly BLADES OF KHORNE units, where X is the number of friendly "
            "units that have already charged this phase.",
            condition="Your Charge Phase",
        )
    )
    assert _effect(ex, "charge").value == 1
    ex, _ = extract(
        _raw(
            "For the rest of the turn, subtract D3 from the Attacks characteristic of the target's "
            "Companion weapons while it is in combat with this unit.",
            declare="Pick an enemy unit in combat with this unit to be the target.",
            condition="Any Combat Phase",
        )
    )
    e = _effect(ex, "attacks")
    assert e.side == "enemy" and e.value == -1  # −D3 (moy. 2) divisé par 2 : armes Compagnon seules


def test_set_up_targets_on_the_battlefield_is_a_deep_strike():
    ex, _ = extract(
        _raw(
            'Set up the targets on the battlefield wholly within 7" of the battlefield edge and more '
            'than 9" from all enemy units.',
            condition="Your Movement Phase",
        )
    )
    assert "deep_strike" in {e.kind for e in ex.effects}


def test_declare_charge_condition_reaches_effects():
    """« Pick up to 3 friendly Verminus units that charged this turn » : requires « a chargé » sur l'effet (v23)."""
    ex, _ = extract(
        _raw(
            "Add 1 to the Rend characteristic of the targets' melee weapons for the rest of the turn.",
            declare="Pick up to 3 friendly Verminus units that charged this turn to be the targets.",
            condition="Your Combat Phase",
        )
    )
    assert "a chargé" in _effect(ex, "rend").requires


def test_target_keyword_after_article_and_enemy():
    """v24 : « for attacks that target an enemy HERO » (Master of Assassins, Deathmaster Crixxit)."""
    ex, _ = extract(
        _raw("Double the Damage characteristic of this unit's melee weapons for attacks that target an enemy HERO.")
    )
    assert any(e.target_keywords == "HERO" for e in ex.effects)


def test_rerolls_one_effect_per_roll():
    """v25 : une relance par jet relancé, partielle = 0,5 ; « cannot be re-rolled » n'est pas une relance."""
    ex, _ = extract(_raw("You can re-roll run rolls and charge rolls for friendly NAMARTI units."))
    assert sorted((e.stat, e.value) for e in ex.effects if e.kind == "reroll") == [("charge", 1.0), ("run", 1.0)]
    ex, _ = extract(_raw("Until the start of your next turn, you can re roll charge rolls for friendly units."))
    assert [e.stat for e in ex.effects if e.kind == "reroll"] == ["charge"]
    ex, _ = extract(_raw("You can re-roll 1 hit roll, 1 wound roll and 1 save roll for this unit."))
    assert sorted((e.stat, e.value) for e in ex.effects if e.kind == "reroll") == [
        ("hit", 0.5),
        ("save", 0.5),
        ("wound", 0.5),
    ]
    ex, _ = extract(_raw("Roll 3D6 instead of 2D6. This roll cannot be re-rolled or modified."))
    assert not [e for e in ex.effects if e.kind == "reroll"]
    ex, _ = extract(_raw("The charge roll is 5 or less (after any re-rolls)."))
    assert not [e for e in ex.effects if e.kind == "reroll"]


def test_reroll_charge_family_is_mobility():
    from aospy.abilities.families import effect_family

    ex, _ = extract(_raw("You can re-roll charge rolls for this unit."))
    e = next(e for e in ex.effects if e.kind == "reroll")
    assert effect_family(e, "self") == "mobilite"


def test_destiny_dice_are_fixed_rolls():
    """v25 : dés du destin (Tzeentch) = jet remplacé par une valeur choisie."""
    ex, _ = extract(
        _raw(
            "Instead of rolling the dice for 1 of the rolls from the list below, you can pick one of "
            "your destiny dice and use it as the roll."
        )
    )
    assert any(e.kind == "fixed_roll" for e in ex.effects)


def test_friendly_target_per_option():
    """v26 : chaque option d'une aptitude à choix porte sa propre cible amie (The Thirteen-headed One)."""
    raw = _raw(
        "Pick 1 of the following effects to apply until the start of your next turn.\n"
        "Master of Dire Sorcery: Add 1 to casting rolls for friendly MASTERCLAN WIZARDS while they are "
        'wholly within 13" of this unit.\n'
        "Commander of Vermin: Add 1 to charge rolls for friendly VERMINUS units while they are wholly "
        'within 13" of this unit.'
    )
    ex, _ = extract(raw)
    by_stat = {e.stat: e.friendly_target or ex.friendly_target for e in ex.effects if e.kind == "stat_mod"}
    assert by_stat == {"cast": "MASTERCLAN WIZARDS", "charge": "VERMINUS"}


def test_friendly_landmark_is_not_a_receiver():
    """v26 : « within 12\" of any friendly KRULEBOYZ units » est un repère, la cible reste celle de l'Annonce."""
    ex, _ = extract(
        _raw(
            "If the target is an IRONJAWZ unit, add 3 to the target's control score while it is "
            'wholly within 12" of any friendly KRULEBOYZ units.',
            declare="Pick a visible friendly BIG WAAAGH! INFANTRY unit to be the target.",
        )
    )
    assert all(e.friendly_target == "" for e in ex.effects)


def _kinds(effect, declare="", condition="Passive"):
    ex, _ = extract(_raw(effect, declare=declare, condition=condition))
    return {(e.kind, e.side) for e in ex.effects}, ex


def test_v27_generic_mechanics():
    """v27 (revue a-revoir LRL) : caractéristique fixée, portée, anti-malus, provocation, capacité annulée."""
    assert ("stat_set", "friendly") in _kinds("The Rend characteristic of your general's melee weapons is 2.")[0]
    assert ("stat_set", "friendly") in _kinds("While you have 2 runes, this unit's Save characteristic is 3+.")[0]
    assert ("range_bonus", "friendly") in _kinds("Add 6\" to the Range characteristic of this unit's Bows.")[0]
    assert ("ignore_debuff", "friendly") in _kinds("Ignore negative modifiers to hit rolls for this unit's attacks.")[0]
    assert ("taunt", "enemy") in _kinds(
        "Roll a dice. On a 3+, all attacks made by that enemy unit must target this unit.",
        declare="Pick an enemy unit to be the target.",
    )[0]
    assert ("restriction", "enemy") in _kinds(
        "Each time it uses a MOVE ability, roll a dice. On a 1-3, that MOVE ability has no effect."
    )[0]
    assert ("lockout", "enemy") in _kinds("Roll a dice. On a 3+, that command or RAMPAGE ability has no effect.")[0]
    assert ("no_buff", "enemy") in _kinds(
        "Ignore the effect of the Charge (+1 Damage) ability for combat attacks "
        "made by enemy units that target this unit."
    )[0]
    ks, ex = _kinds("Inflict D3+X mortal damage on the target.", declare="Pick an enemy unit to be the target.")
    assert any(e.kind == "mortal_damage" and e.value == 3.0 for e in ex.effects)


def test_this_ability_has_no_effect_is_not_an_effect():
    ks, _ = _kinds("If you do not meet the condition below, this ability has no effect.")
    assert not ks


def test_option_line_any_friendly_unit_is_star():
    """v27 : « for friendly units » sur une ligne d'option = toute unité amie ('*'), distinct du repli ''."""
    ex, _ = extract(
        _raw(
            'If there are any friendly WIZARDS within 3" of this MANIFESTATION, pick 1 of the '
            "following effects:\nIncrease Time Flow: Until the start of your next turn, you can re roll "
            'charge rolls for friendly units while they are wholly within 12" of this MANIFESTATION.'
        )
    )
    assert [e.friendly_target for e in ex.effects if e.kind == "reroll"] == ["*"]


def test_characteristic_condition_and_battle_damage_are_not_stat_set():
    """v27 : « If the target's Save characteristic is 3+ » = condition ; profil dégradé = battle_damaged."""
    ks, _ = _kinds(
        "If the target's Save characteristic is 3+ or better, subtract 1 from charge rolls for the target.",
        declare="Pick an enemy unit to be the target.",
    )
    assert ("stat_set", "enemy") not in ks and ("stat_set", "friendly") not in ks
    ks, _ = _kinds("While this unit has 10 or more damage points:\n- The Attacks characteristic of its Feet is 3.")
    assert {k for k, _ in ks} == {"battle_damaged"}


# --- analyseur v28 (revue « a-revoir » : Skaven, Kruleboyz, StD, OM, FEC, SE, Seraphon, BoK, OB) ---


def _kinds28(effect: str, declare: str = "", condition: str = "Passive") -> dict[str, list]:
    ex, _ = extract(_raw(effect, declare, condition))
    out: dict[str, list] = {}
    for e in ex.effects:
        out.setdefault(e.kind, []).append(e)
    return out


def test_v28_fix_typos_keeps_text_readable():
    from aospy.abilities.text import fix_typos

    assert (
        fix_typos("If it is on the battleeld, inict D3 mortal damage")
        == "If it is on the battlefield, inflict D3 mortal damage"
    )
    assert fix_typos("Ignore negative modiers. Add I to hit rolls.") == "Ignore negative modifiers. Add 1 to hit rolls."
    assert (
        fix_typos("roll l additional dice; add 3 the Attacks characteristic")
        == "roll 1 additional dice; add 3 to the Attacks characteristic"
    )


@pytest.mark.parametrize(
    "text,stat,value,keep,side",
    [
        (
            "Add 1 to the number of dice rolled when making charge rolls for this unit, to a maximum of 3.",
            "charge",
            1.0,
            "somme",
            "friendly",
        ),
        (
            "When making charge rolls for this unit, add 1 to the number of dice rolled, to a maximum of 3, then remove 1 "
            "dice of your choice and use the remaining dice as the charge roll.",
            "charge",
            1.0,
            "garder",
            "friendly",
        ),
        (
            "For the rest of the turn, when making charge rolls for friendly PLEDGED TO SLAANESH units, you can roll 1 "
            "additional dice (to a maximum of 3), but if you do, you must discard 1 dice of your choice.",
            "charge",
            1.0,
            "garder",
            "friendly",
        ),
        (
            "This unit uses the 'Unbind' ability but the unbinding roll is 3D6 instead of 2D6.",
            "unbind",
            1.0,
            "somme",
            "friendly",
        ),
        (
            "Until the start of your next turn, subtract 1 from the number of dice rolled when making charge rolls for the "
            "target, to a minimum of 1.",
            "charge",
            -1.0,
            "somme",
            "enemy",
        ),
    ],
)
def test_v28_dice_count(text, stat, value, keep, side):
    k = _kinds28(text)
    assert "stat_mod" not in k  # plus un simple ±1 à la charge
    (e,) = k["dice_count"]
    assert (e.stat, e.value, e.detail, e.side) == (stat, value, keep, side)


def test_v28_dice_count_own_drawback_and_high_roll_bonus():
    k = _kinds28(
        "Each friendly GOLLOP unit can immediately use a CHARGE ability as if it were your charge phase, but "
        "subtract 1 from the number of dice rolled when making the charge roll for that unit."
    )
    assert k["dice_count"][0].side == "friendly" and k["dice_count"][0].value == -1
    assert "extra_move" in k  # charge hors phase
    k = _kinds28(
        "Add 1 to charge rolls for the target. In addition, if the chanting roll was 8+, add 1 to the number "
        "of dice rolled when making charge rolls for the target, to a maximum of 3."
    )
    assert "dice_count" not in k  # bonus sur jet élevé : pas acquis (v21)


@pytest.mark.parametrize(
    "text,kind,side",
    [
        ("Ward rolls cannot be made for the target for the rest of the turn.", "no_ward", "enemy"),
        ("Roll a dice. On a 5+, that command has no effect, it still counts as having been used.", "lockout", "enemy"),
        (
            "If this unit was picked to be the target of that spell, roll a dice. On a 3+, ignore the effect of that spell "
            "on this unit.",
            "anti_magic",
            "friendly",
        ),
        (
            "This unit can use the 'Bull Charge' ability even if another friendly unit has used it this turn.",
            "extra_use",
            "friendly",
        ),
        (
            "The targets can each use the 'All-out Attack' or 'All-out Defence' command this phase even if that command has "
            "been used by a friendly unit this phase.",
            "extra_use",
            "friendly",
        ),
        (
            "For the rest of the turn, this unit can ignore the effects of the 'Guarded Hero' ability when picking targets "
            "for its shooting attacks.",
            "snipe",
            "friendly",
        ),
        (
            'Enemy units within 12" of this unit cannot be healed and cannot have slain models returned to them.',
            "anti_heal",
            "enemy",
        ),
        ('Models cannot be returned to enemy units within 12" of this unit.', "anti_heal", "enemy"),
        (
            "Friendly units in this Regiment of Renown can use RUN abilities and still use SHOOT abilities later in the turn.",
            "run_and_shoot",
            "friendly",
        ),
        (
            "Set the Attacks characteristic of the target's Warpvolt Scourgers to 10 for the rest of the turn.",
            "stat_set",
            "friendly",
        ),
        ("Your general's Ratling Pistol has an Attacks characteristic of 2D6 instead of D6.", "stat_set", "friendly"),
        (
            'Remove this unit from the battlefield and set up it again on the battlefield more than 9" from all enemy units.',
            "redeploy",
            "friendly",
        ),
        (
            'Set up a replacement unit with half the number of models from the target unit more than 9" from all enemy '
            "units.",
            "summon",
            "friendly",
        ),
        ("Gain D6 raw ingredients.", "resource", "friendly"),
        ("If a friendly HERO is destroyed, give this unit 8 Dark Apotheosis points.", "resource", "friendly"),
        ("This unit has PRIEST (1).", "keyword_gain", "friendly"),
    ],
)
def test_v28_generic_wordings(text, kind, side):
    k = _kinds28(text)
    assert kind in k and k[kind][0].side == side


def test_v28_guards():
    # « If the casting roll is 13 » : une condition, pas un jet fixé ; le 3D6 reste lu
    k = _kinds28(
        "The next time you make a casting roll for this unit this phase, roll 3D6 instead of 2D6. "
        "If the casting roll is 13, the spell cannot be unbound."
    )
    assert "fixed_roll" not in k and k["dice_count"][0].stat == "cast"
    assert "fixed_roll" in _kinds28("Instead of making a casting roll for that spell, the casting roll is 9.")
    # « as if it had WIZARD (1) » ne donne que la dissipation, pas le mot-clé
    k = _kinds28("This unit can use UNBIND abilities as if it had WIZARD (1).")
    assert "keyword_gain" not in k and "anti_magic" in k
    # deux règles du même effet ne le doublent pas
    assert len(_kinds28("Gain 1 fate point.").get("resource", [])) == 1
    # « +1 Control characteristic » est un bonus de contrôle
    (e,) = _kinds28("Add 1 to the Control characteristic of friendly MEATFIST units while they are in combat.")[
        "stat_mod"
    ]
    assert e.stat == "control" and e.value == 1
    # « make a D6" move »
    (e,) = _kinds28(
        'If this unit is not in combat, it can immediately make a D6" move and can end that move in combat.'
    )["move"]
    assert e.value == 3.5


def test_v28_manifestation_summon_and_spell_relay():
    assert "summon" in _kinds28('Set up the first part of the Warp Lightning Vortex within 18" of the caster.')
    assert "summon" in _kinds28('Set up the MANIFESTATION you picked wholly within 12" of the caster,')
    (e,) = _kinds28(
        "Measure the range and visibility of the next SPELL ability used by this unit from the target "
        "instead of from this unit."
    )["range_bonus"]
    assert e.stat == "spell"


# --- analyseur v29 (revue « a-revoir » : DoT, CoS, SY, SG, IJ, MoN, HS, KO, SoB, DoK, ID, HoH, NT…) ---


@pytest.mark.parametrize(
    "text,kind,side",
    [
        ("Halve the target's Move characteristic until the start of your next turn.", "move_debuff", "enemy"),
        (
            "The target can immediately use a SPELL ability from the Lore of Change or the Lore of Fate.",
            "extra_use",
            "friendly",
        ),
        ("Change the casting roll for that spell to a value of 12 that cannot be modified.", "fixed_roll", "friendly"),
        (
            'Until the start of your next turn, ignore the effects of enemy SPELL abilities on units within 6" of the '
            "target.",
            "anti_magic",
            "friendly",
        ),
        (
            "If the roll equals or exceeds the banishment value, it is banished and removed from play.",
            "anti_magic",
            "friendly",
        ),
        ("This unit can use CHARGE abilities even if it is in combat.", "extra_move", "friendly"),
        ('Set up the substitute wholly within 6" of the target and not in combat.', "deep_strike", "friendly"),
        (
            "Remove the targets from the battlefield and set them up in reserve masked by illusion.",
            "deep_strike",
            "friendly",
        ),
        ("You control the target objective.", "control", "friendly"),
        (
            'Set up a Hand of Nagash wholly within 12" of and visible to the caster and more than 9" from all enemy units.',
            "summon",
            "friendly",
        ),
        (
            "Melee weapons used by friendly ZOGGROK'S IRONMONGERZ units have ANTI-WAR MACHINE (+1 REND).",
            "anti",
            "friendly",
        ),
        (
            "For the rest of the battle round, friendly BIG WAAAGH! units' melee weapons have CRIT (2 HITS).",
            "crit",
            "friendly",
        ),
        ("Enemy MONSTERS cannot use RAMPAGE abilities while they are in combat with this unit.", "lockout", "enemy"),
        ("For the rest of the turn, the target can only use CORE abilities.", "lockout", "enemy"),
        ('Enemy units cannot end a charge move within 1/2" of a friendly Argent Shard.', "restriction", "enemy"),
        (
            "On a 3+, the target's weapons cannot be affected by weapon abilities other than the Companion weapon ability.",
            "no_weapon_abilities",
            "enemy",
        ),
        ("Ignore all modifiers to save rolls for friendly units (positive and negative).", "damage_ignore", "friendly"),
        ("No command point is spent the second time that command is used.", "cp_gain", "friendly"),
        ("Pick a visible friendly FYRESLAYERS PRIEST. Give that PRIEST D3 ritual points.", "resource", "friendly"),
        (
            "Roll a dice. On a 3+, it can use the 'Shoot' ability as if it were your shooting phase.",
            "extra_shoot",
            "friendly",
        ),
        ("Inflict D3 damage on the target.", "mortal_damage", "enemy"),
        (
            "Each time this unit uses a FIGHT ability, pick either the Calamitous Sweep or Crushing Blow weapon "
            "characteristics for all the attacks it makes with its Menhir Club.",
            "profile_choice",
            "friendly",
        ),
        (
            "Instead of discarding that card, return it face down to the bottom of your battle tactic deck.",
            "tactic_cards",
            "friendly",
        ),
        ('This unit has a coherency range of 2".', "coherency", "friendly"),
    ],
)
def test_v29_generic_wordings(text, kind, side):
    k = _kinds28(
        text,
        declare="Pick a visible enemy unit to be the target."
        if "the target" in text and "friendly" not in text and kind not in ("deep_strike", "extra_use")
        else "",
    )
    assert kind in k and k[kind][0].side == side


@pytest.mark.parametrize(
    "text,declare,side",
    [
        # contrepartie sur sa propre unité après une téléportation (« They cannot use MOVE abilities »)
        (
            'Remove your general and set them up again more than 6" from all enemy units. They cannot use MOVE abilities '
            "in the following movement phase.",
            "",
            "friendly",
        ),
        # pronom dont l'antécédent ennemi est dans la phrase
        (
            "If the target is a friendly unit, it has STRIKE-FIRST. If the target is an enemy unit, it has STRIKE-LAST "
            "for the rest of the turn.",
            "Pick a visible unit to be the target.",
            "enemy",
        ),
        # pronom sous une cible ennemie déclarée
        (
            "While the target is tongue-tied:\n- It cannot use RUN abilities.",
            "Pick a visible enemy unit to be the target.",
            "enemy",
        ),
        # « The target » amie : contrepartie
        (
            "Until the start of your next turn:\n- The target has STRIKE-FIRST.\n- The target cannot use commands.",
            "Pick a visible friendly unit to be the target.",
            "friendly",
        ),
    ],
)
def test_v29_restriction_subject(text, declare, side):
    k = _kinds28(text, declare=declare)
    (e,) = [e for kind in ("restriction", "strike_last", "lockout") for e in k.get(kind, [])]
    assert e.side == side


def test_v29_dice_match_and_battle_round():
    (e,) = _kinds28("You can change the lowest D6 in the charge roll to match the highest D6.")["dice_count"]
    assert (e.stat, e.value, e.detail, e.side) == ("charge", 1.0, "max", "friendly")
    (e,) = _kinds28(
        "Each time your opponent makes a charge roll for the target, they must change the highest D6 to "
        "match the lowest D6."
    )["dice_count"]
    assert (e.stat, e.value, e.detail, e.side) == ("charge", -1.0, "min", "enemy")
    (e,) = _kinds28(
        "Add the current battle round number to the Move characteristic of friendly GRUNTA STAMPEDE units."
    )["stat_mod"]
    assert (e.stat, e.value) == ("move", 3.0)
    assert "untargetable" not in _kinds28(
        "Units in this Regiment of Renown cannot be picked to be the target of RAMPAGE abilities used by enemy units."
    )


# --- analyseur v30 (dernier passage « a-revoir », toutes factions) ---


def test_v30_rules_self_damage_summon_and_declare_only():
    assert "warscroll_rule" in _kinds28(
        "When a number of damage points equal to this MANIFESTATION's Health "
        "characteristic are allocated to it, this MANIFESTATION is destroyed and both "
        "its parts are removed from play."
    )
    assert "warscroll_rule" in _kinds28(
        "This unit's Klutcha-grot is a token. If it is removed from the battlefield, "
        "this unit cannot use the 'A Tough Grot to Swallow' ability."
    )
    # jeton posé par une aptitude active : v34 (validé par l'utilisateur 2026-11-22), règle de fonctionnement aussi,
    # la valeur est dans l'aptitude-sœur qui lit le jeton (tests/abilities/test_references.py)
    assert "warscroll_rule" in _kinds28(
        "Place this unit's Bomb Rat next to the target.",
        declare="This unit's Bomb Rats are tokens.",
        condition="Once Per Turn (Army), Any Combat Phase",
    )
    (e,) = _kinds28(
        "For each 5+, allocate 1 damage point to this unit (ward rolls cannot be made for those damage points)."
    )["mortal_damage"]
    assert e.side == "friendly" and e.detail == "auto-infligé"
    assert "summon" in _kinds28(
        "If there is already a friendly MANIFESTATION from the list above on the "
        "battlefield, it is immediately banished. Then,",
        declare="Pick a friendly WIZARD to cast this spell, pick 1 of the friendly "
        "MANIFESTATIONS below that is not on the battlefield, then make a casting "
        "roll of 2D6.",
    )
    # tout le texte sous « Declare » : lu comme l'effet
    ex, _ = extract(
        _raw(
            "",
            declare="For the rest of the phase:\n- Add 1 to hit rolls for this unit's attacks.",
            condition="Once Per Turn (Army), Reaction: You declared an Attack ability for this unit",
        )
    )
    assert any(e.kind == "stat_mod" and e.stat == "hit" and e.value == 1 for e in ex.effects)


def test_v31_strip_enhancement():
    (e,) = _kinds28(
        "Roll a dice. On a 3+, the target no longer has that artefact of power.",
        declare="Pick an enemy HERO in combat with this unit to be the target.",
    )["strip_enhancement"]
    assert e.side == "enemy"


# ----- analyseur v33 : défauts relevés par la couche 3 -----


def _mortals(ex):
    return [e for e in ex.effects if e.kind == "mortal_damage"]


def test_per_roll_mortals_fixed_count_is_an_expectation():
    ex, _ = extract(
        _raw("Roll 10 dice. For each 4+, inflict 1 mortal damage on the target.", condition="Your Hero Phase")
    )
    (e,) = _mortals(ex)  # plus de doublon à 1
    assert e.side == "enemy" and e.value == pytest.approx(5.0) and e.detail == ""


def test_per_roll_mortals_variable_count_is_per_die():
    ex, _ = extract(
        _raw("Roll a dice for each model in the target unit. For each 5+, inflict 1 mortal damage on the target.")
    )
    (e,) = _mortals(ex)
    assert e.detail == "par dé" and e.value == pytest.approx(1 / 3, abs=1e-3)


def test_mortals_equal_to_the_roll():
    ex, _ = extract(_raw("Roll a D3. On a 2+, inflict an amount of mortal damage on the target equal to the roll."))
    (e,) = _mortals(ex)
    assert e.value == pytest.approx(5 / 3, abs=1e-3)
    # seuil de D6 déjà compté en déclenchement : moyenne sachant le seuil passé
    ex, _ = extract(_raw("Roll a dice. On a 2+, inflict an amount of mortal damage on the target equal to the roll."))
    assert ex.activation_prob == pytest.approx(5 / 6, abs=1e-3)
    assert _mortals(ex)[0].value == pytest.approx(4.0)


def test_mortals_on_a_friendly_target_are_a_drawback():
    ex, _ = extract(
        _raw(
            "Roll a dice. On a 2+, add 1 to save rolls for the target for the rest of the turn. "
            "On a 1, inflict D3 mortal damage on the target.",
            declare='Pick a friendly KRULEBOYZ INFANTRY unit wholly within 12" of this unit to be the target.',
            condition="Your Hero Phase",
        )
    )
    (e,) = _mortals(ex)
    assert e.side == "friendly"


def test_ward_of_this_unit_goes_to_the_bearer():
    raw = _raw(
        'For the rest of the battle, while the royal retinue is wholly within 6" of this unit, add 1 to hit rolls '
        "for attacks made by the royal retinue and this unit has WARD (4+).",
        declare="Pick a friendly non-HERO FYRESLAYERS INFANTRY unit within this unit's combat range to be the "
        "royal retinue.",
        condition="Once Per Battle (Army), Deployment Phase",
    )
    from aospy.abilities.models import AbilityOwner

    raw = raw.__class__(**{**raw.__dict__, "owners": (AbilityOwner("f", "F", "warscroll", "Auric Runefather"),)})
    ex, _ = extract(raw)
    ward = next(e for e in ex.effects if e.kind == "ward")
    hit = next(e for e in ex.effects if e.kind == "stat_mod")
    assert ward.friendly_target == "Auric Runefather" and hit.friendly_target == ""


def test_exclusive_options_are_grouped():
    ex, _ = extract(
        _raw(
            "Apply the effect below that corresponds to the rune used:\n"
            "Rune of Fury: Add 1 to wound rolls for combat attacks made by friendly FYRESLAYERS units.\n"
            "Rune of Fiery Determination: Add 1 to save rolls for friendly FYRESLAYERS units.",
            condition="Your Hero Phase",
        )
    )
    groups = {e.stat: e.option_group for e in ex.effects if e.kind == "stat_mod"}
    assert groups == {"wound": "Rune of Fury", "save": "Rune of Fiery Determination"}


def test_sentenced_target_and_passed_across():
    ex, _ = extract(
        _raw(
            "Each time a friendly NIGHTHAUNT INFANTRY unit uses a FIGHT ability, if all of its attacks target the "
            "same SENTENCED enemy unit, that friendly unit's melee weapons have Crit (Mortal) for that FIGHT ability."
        )
    )
    assert "cible désignée" in next(e for e in ex.effects if e.kind == "crit").target_condition
    ex, _ = extract(
        _raw(
            "Roll 4 dice. For each 4+, inflict 1 mortal damage on the target.",
            declare="Pick an enemy unit that does not have FLY and that this unit passed across this phase to be the "
            "target.",
            condition="Your Movement Phase",
        )
    )
    assert not any(e.kind == "fly" for e in ex.effects)
    assert "a survolé la cible" in _mortals(ex)[0].requires and "doit survoler la cible" in ex.conditions


def test_strike_first_as_a_condition_is_not_a_gain():
    ex, _ = extract(
        _raw(
            "For the rest of the battle round, add 1 to wound rolls for combat attacks made by friendly FYRESLAYERS "
            "units while they have STRIKE-FIRST.",
            condition="Your Hero Phase",
        )
    )
    assert not any(e.kind == "strike_first" for e in ex.effects)
    assert "frappe en premier" in next(e for e in ex.effects if e.kind == "stat_mod").requires


# ----- analyseur v34 : fin de la couche 1 (D) -----


def test_ignoring_enemy_charge_weapon_ability_depends_on_an_enemy_charge():
    """Anticipated Strike / Protective Pike-Wall : neutraliser Charge (+1 Damage) ne sert que si l'ennemi a chargé ;
    « has not charged » reste la contrainte du porteur."""
    ex, _ = extract(
        _raw(
            "If this unit has not charged this turn, ignore the effect of the Charge (+1 Damage) ability for combat "
            "attacks made by enemy units that target this unit."
        )
    )
    reqs = next(e for e in ex.effects if e.kind == "no_buff").requires
    assert "charge ennemie" in reqs and "sans charge" in reqs and "a chargé" not in reqs
    assert "dépend d'une charge ennemie" in ex.conditions and "doit avoir chargé" not in ex.conditions


def test_our_charge_or_enemy_charge_is_one_condition():
    """Brutal Troof : deux charges en OU → une seule condition, la plus facile (0,5)."""
    from aospy.abilities.extract.conditions import CHARGE_EITHER

    ex, pen = extract(
        _raw(
            "Until the start of your next turn, add 1 to wound rolls for the target's attacks if it charged in the "
            "same turn or if it is in combat with an enemy unit that charged in the same turn.",
            declare="Pick a visible friendly IRONSUNZ unit wholly within 12\" of them to be the target, then make a "
            "casting roll of 2D6.",
            condition="Your Hero Phase",
            cost_type="Spell",
            cost_value="6",
        )
    )
    assert ex.conditions == [CHARGE_EITHER[0]] and pen == pytest.approx(0.5)
    assert next(e for e in ex.effects if e.kind == "stat_mod").requires.startswith("a chargé ou charge ennemie")


def test_once_per_battle_trigger_for_the_rest_of_the_battle():
    """Oath of Supremacy : les conditions du « If » se remplissent une fois (pénalités ÷ 2) et ne sont pas des
    conditions de chaque combat (prérequis « déclencheur unique », sans « a chargé »)."""
    text = (
        "If this unit is wholly within enemy territory and charged this phase, for the rest of the battle, add 1 to "
        "hit rolls for combat attacks made by friendly DARKOATH units while they are wholly within 12\" of this unit."
    )
    once, pen_once = extract(_raw(text, condition="Once Per Battle, Any Charge Phase"))
    each, pen_each = extract(_raw(text, condition="Any Charge Phase"))
    assert pen_once == pytest.approx(pen_each / 2)
    req = next(e for e in once.effects if e.kind == "stat_mod").requires
    assert req == "déclencheur unique (charge, en territoire)" and "a chargé" not in req
    assert "a chargé" in next(e for e in each.effects if e.kind == "stat_mod").requires


def test_random_table_rows_are_weighted_by_their_dice_range():
    """Prized Creations : 1-2 BM sur soi, 3-4 +1 Attaques, 5-6 « en plus de 3-4 » Protection (5+) → une option
    par plage de dé, puissance = espérance des lignes (pas leur somme, pas la meilleure)."""
    from aospy.abilities.scoring import power_of

    text = (
        "Roll a dice for each target and apply the corresponding effect:\n"
        "- 1-2 - Baneful Fury: Inflict D3 mortal damage on the target.\n"
        "- 3-4 - Adrenal Injection: Add 1 to the Attacks characteristic of the target's melee weapons until your "
        "next turn.\n"
        "- 5-6 - Blind Frenzy: In addition to the effect of 'Adrenal Injection', the target has WARD (5+) until the "
        "start of your next turn."
    )
    ex, _ = extract(_raw(text, declare="Pick up to 3 friendly non-HERO MOULDER units to be the targets.",
                         condition="Your Hero Phase"))
    groups = {e.kind: e.option_group for e in ex.effects}
    assert groups == {"mortal_damage": "dé 1-2", "stat_mod": "dé 3-4", "ward": "dé 5-6 +préc"}
    table, _ = power_of(ex, text)
    rows = {
        g: power_of(dataclasses.replace(ex, effects=[dataclasses.replace(e, option_group="") for e in effs]), text)[0]
        for g, effs in (
            ("3-4", [e for e in ex.effects if e.kind == "stat_mod"]),
            ("5-6", [e for e in ex.effects if e.kind in ("stat_mod", "ward")]),
        )
    }
    assert table == pytest.approx((rows["3-4"] + rows["5-6"]) / 3, abs=0.01)


def test_heat_token_costs_are_not_a_random_table():
    """Cogforts : « 1 Launch Countermeasures!: … » est un coût en jetons de chaleur, choisi, pas un jet."""
    ex, _ = extract(
        _raw(
            "Pick 1 or more of the following effects. For each effect you pick, give this unit a number of heat "
            "tokens equal to the number beside it.\n"
            "1 Launch Countermeasures!: Until the start of your next turn, subtract 1 from hit rolls for shooting "
            "attacks that target other friendly SIGMARITE units while they are wholly within 12\" of this unit.\n"
            "2 Full Throttle!: For the rest of the turn, this unit's Move characteristic is 10\".",
            condition="Your Hero Phase",
        )
    )
    assert not any(e.option_group.startswith("dé ") for e in ex.effects)


def test_roll_several_dice_and_pick_one_takes_the_best_row():
    from aospy.abilities.scoring import _picked_dice

    assert _picked_dice("Roll 2 dice, pick either result, then apply the corresponding effect") == 2
    assert _picked_dice("Roll 3 dice. You must pick 1 of those dice and apply the effect that corresponds") == 3
    assert _picked_dice("If X, you can roll 2 dice instead, pick either result") == 1


def test_would_heal_or_return_is_an_anti_heal_not_a_return():
    """Seething Blight / Plague Progenitor : « If an ability would heal or return any slain models to the target unit,
    that ability does not heal any damage points or return any slain models to it » = anti-soin, pas un retour."""
    ex, _ = extract(
        _raw(
            "For the rest of the battle:\n- If an ability would heal or return any slain models to the target unit, "
            "that ability does not heal any damage points or return any slain models to it.",
            declare="Pick an enemy unit within 13\" of this unit to be the target.",
            condition="Your Hero Phase",
        )
    )
    kinds = {e.kind for e in ex.effects}
    assert "anti_heal" in kinds and "return_models" not in kinds


# ----- analyseur v35 : conditions de l'Annonce sur les cibles ennemies, tirs du porteur, auras ennemies ------


def test_v35_coordinated_relative_charged_is_the_enemy_unit():
    """« an enemy unit in combat with this unit and that charged this turn » : c'est l'ennemi qui a chargé."""
    from aospy.abilities.perimeter import charge_subjects

    bulwark = "Pick an enemy unit in combat with this unit and that charged this turn to be the target."
    assert charge_subjects(bulwark, True) == {"ennemi"}
    grapple = (
        "If this unit did not charge this turn, pick an enemy unit in combat with this unit and that charged this "
        "turn to be the target."
    )
    assert charge_subjects(grapple, True) == {"ennemi"}
    horn = (
        "Pick an enemy unit that has no more than 1 model, that is in combat with this unit and that has charged "
        "this turn to be the target."
    )
    assert charge_subjects(horn, True) == {"ennemi"}
    # la mention la plus proche reste la règle sans « and that »
    gitmob = "Pick an enemy unit in combat with a friendly GITMOB unit that has charged this turn."
    assert charge_subjects(gitmob, True) == {"nous"}


def test_v35_declare_charge_conditions_reach_enemy_effects():
    """Chilling Onslaught / Dance of Death / Deafening Drone : la condition de charge de l'Annonce vaut pour
    l'effet posé sur la cible ennemie (avant v35 : seulement pour les effets amis)."""
    cond = "Once Per Turn (Army), Any Combat Phase"
    ex, _ = extract(
        _raw(
            "Roll a dice. On a 4+, for the rest of the turn, subtract 1 from hit rolls for the target's attacks.",
            declare="If this unit charged this turn, pick an enemy unit in combat with it to be the target.",
            condition=cond,
        )
    )
    assert [e.requires for e in ex.effects if e.side == "enemy"] == ["a chargé"]
    ex, _ = extract(
        _raw(
            "Subtract 1 from hit rolls and wound rolls for the target's combat attacks for the rest of the turn.",
            declare="Pick an enemy unit that charged this turn and is in combat with this unit to be the target.",
            condition=cond,
        )
    )
    assert {e.requires for e in ex.effects} == {"charge ennemie"}
    ex, _ = extract(
        _raw(
            "Subtract 1 from the Attacks characteristic of the target's melee weapons for the rest of the turn.",
            declare="If this unit did not charge this turn, pick an enemy unit in combat with it to be the target.",
            condition=cond,
        )
    )
    assert {e.requires for e in ex.effects} == {"sans charge"}


def test_v35_debuff_set_by_the_bearers_shooting():
    """Hurricane Winds : la cible est désignée par les tirs du porteur → prérequis « après tir du porteur »
    (la couche 3 en tire l'exposition) ; jamais sur des dégâts directs (lecture de realized.direct_damage)."""
    from aospy.abilities.perimeter import SHOT_BY_BEARER

    ex, _ = extract(
        _raw(
            "Roll a dice. On a 3+, the target has STRIKE-LAST for the rest of the turn.",
            declare="Pick an enemy unit that had any damage points allocated to it this turn by this unit's shooting "
            "attacks to be the target.",
            condition="Once Per Turn (Army), Any Shooting Phase",
        )
    )
    assert [e.requires for e in ex.effects] == [SHOT_BY_BEARER]
    ex, _ = extract(
        _raw(
            "Roll a dice. On a 2+, subtract 1 from wound rolls for the target's combat attacks "
            "for the rest of the turn.",
            declare="Pick an enemy unit that had any damage points allocated to it this turn by attacks made with this "
            "unit's Dartpipe to be the target.",
            condition="Any Shooting Phase",
        )
    )
    assert all(SHOT_BY_BEARER in e.requires for e in ex.effects)
    ex, _ = extract(
        _raw(
            "If any damage points are allocated to an enemy unit by a SHOOT ability used by this unit, inflict 1 "
            "mortal damage on that unit."
        )
    )
    assert all(SHOT_BY_BEARER not in (e.requires or "") for e in ex.effects if e.kind == "mortal_damage")


@pytest.mark.parametrize(
    "condition,declare,effect,expected",
    [
        ("Passive", "", 'Subtract 1 from charge rolls for enemy units within 9" of this unit.', 9),
        (
            'Reaction: Opponent declared a command for a unit within 12" of this unit',
            "",
            "Roll a dice. On a 5+, that command has no effect.",
            12,
        ),
        (
            "Your Hero Phase",
            'Pick a visible unit within 12" of the caster to be the target, then make a casting roll of 2D6.',
            "If the target is an enemy unit, it has STRIKE-LAST for the rest of the turn.",
            12,
        ),
    ],
)
def test_v35_enemy_aura_radius_written_around_the_bearer(condition, declare, effect, expected):
    """Atmospheric Isolation, Network of Spies, Aethershock : portée lue pour l'exposition (couche 3)."""
    ex, _ = extract(_raw(effect, declare=declare, condition=condition))
    assert ex.range_inches == expected


def test_v35_ward_lost_by_this_unit_is_a_drawback():
    """Elite Guardians : « this unit has STRIKE-FIRST but ward rolls cannot be made for it »."""
    from aospy.abilities.scoring import _effect_weight as effect_weight

    ex, _ = extract(
        _raw(
            "If this unit is in combat with any enemy units that charged this turn, roll a dice. On a 3+, for the "
            "rest of the turn, this unit has STRIKE-FIRST but ward rolls cannot be made for it.",
            condition="Once Per Turn (Army), Any Combat Phase",
        )
    )
    nw = [e for e in ex.effects if e.kind == "no_ward"]
    assert nw and all(e.side == "friendly" for e in nw)
    assert all(effect_weight(e)[0] == 0.0 for e in nw)


def test_v35_retaliation_and_own_attack_riders_are_labelled():
    """Riposte (Extremis Chamber, Squigs Gone Wild, Blood of Molten Varanite) / BM sur ses attaques
    (Cometstrike Sceptre, Outrageous Carnage) : libellés lus par la couche 3 (exposition et rôle)."""
    from aospy.abilities.perimeter import ON_OWN_ATTACKS, RETALIATION

    for text in (
        "Each time you make an unmodified save roll of 6 for a combat attack that targets this unit, inflict 1 "
        "mortal damage on the attacking unit after the FIGHT ability has been resolved.",
        "Each time a model in this unit is slain by a combat attack and that model was in combat with the attacking "
        "unit, roll a dice. On a 5+, inflict 1 mortal damage on the attacking unit after the FIGHT ability has been "
        "resolved.",
        "Roll a dice each time a damage point inflicted by a combat attack is allocated to this unit. On a 4+, inflict "
        "1 mortal damage on the attacking unit after the FIGHT ability has been resolved.",
    ):
        ex, _ = extract(_raw(text))
        assert [e.requires for e in ex.effects if e.kind == "mortal_damage"] == [RETALIATION]
    for text in (
        "Each time this unit attacks with its Cometstrike Sceptre, if the attack scores a hit, inflict D3 mortal "
        "damage on the target.",
        'Each time an attack made by this unit scores a critical hit, inflict D3 mortal damage on each enemy unit '
        'within 8" of it after the FIGHT ability has been resolved (and continue the attack sequence).',
    ):
        ex, _ = extract(_raw(text))
        assert [e.requires for e in ex.effects if e.kind == "mortal_damage"] == [ON_OWN_ATTACKS]


def test_v35_condition_heading_the_effect_applies_to_all_its_effects():
    """Soaring Terror : « If this unit charged this turn, roll a dice. On a 3+, … move 2D6" … Inflict D3 » ;
    un serment à déclencheur unique garde sa seule lecture v34."""
    ex, _ = extract(
        _raw(
            'If this unit charged this turn, roll a dice. On a 3+, this unit can move 2D6". It can pass through the '
            "combat ranges of enemy units but must end that move in combat. Then, pick an enemy unit that this unit "
            "passed across during that move. Inflict D3 mortal damage on that enemy unit.",
            condition="Once Per Turn (Army), Any Combat Phase",
        )
    )
    assert all("a chargé" in e.requires for e in ex.effects)
    ex, _ = extract(
        _raw(
            "If this unit charged this phase and the unmodified charge roll was 8+, add 1 to the Rend characteristic "
            "of this unit's weapons for the rest of the battle.",
            condition="Once Per Battle, Any Charge Phase",
        )
    )
    assert all("a chargé" not in e.requires.split(" | ") for e in ex.effects)


def test_v35_damage_allocated_to_a_friendly_target_is_a_cost():
    """Offering of Blood : « Allocate 3 damage points to the target » avec une cible amie ; Avatar of
    Destruction : « If this unit would be automatically destroyed, it is not » = protection du porteur."""
    ex, _ = extract(
        _raw(
            "Allocate 3 damage points to the target (ward rolls cannot be made for those damage points).",
            declare='Pick a friendly unit within 3" of this unit to be the target.',
            condition="Once Per Turn (Army), Your Hero Phase",
        )
    )
    assert [(e.side, e.detail) for e in ex.effects if e.kind == "mortal_damage"] == [("friendly", "auto-infligé")]
    ex, _ = extract(
        _raw(
            "If this unit would be automatically destroyed, it is not automatically destroyed. Instead, allocate 6 "
            "damage points to it (ward rolls cannot be made for those damage points)."
        )
    )
    assert all(e.side == "friendly" for e in ex.effects)


# ----- v36 : lectures relevées par la grille mobilité (couche 3) ------------------------------------------


def _effs(raw):
    return extract(raw)[0].effects


def test_v36_mortal_damage_on_a_target_redesignated_enemy():
    """Cible amie OU ennemie : « If the target is an enemy unit, inflict D3 mortal damage on it » vise l'ennemi
    (Invocation of Nagash, Gifts of Pain and Pleasure), pas une contrepartie auto-infligée."""
    raw = _raw(
        "If the target is an enemy unit, inflict D3 mortal damage on it. If the target is a friendly DEATH unit, "
        "it can move up to 3\".",
        declare="Pick a visible unit wholly within 18\" of this unit to be the target, then make a casting roll "
        "of 2D6.",
        condition="Your Hero Phase",
    )
    md = [e for e in _effs(raw) if e.kind == "mortal_damage"]
    assert md and all(e.side == "enemy" and e.detail != "auto-infligé" for e in md)
    jolly = _raw(
        "If you picked an enemy unit to be the target, roll a dice. If the roll equals or exceeds the target's Control "
        "characteristic, until the start of your next turn, inflict D3 mortal damage on the target:\n"
        "- Each time the target is removed from the battlefield and set up again further from this unit.",
        declare="Pick a visible friendly DAEMON unit wholly within 12\" of this unit or a visible enemy unit within "
        "12\" of this unit to be the target.",
        condition="Your Hero Phase",
    )
    effs = _effs(jolly)
    assert [e.side for e in effs if e.kind == "mortal_damage"] == ["enemy"]
    # « Each time the target is removed from the battlefield and set up again » : déclencheur, pas un mouvement
    assert not any(e.kind == "redeploy" for e in effs)


def test_v36_cannot_be_removed_is_a_restriction_not_a_teleport():
    """« The targets cannot be removed from the battlefield by an ability that would allow them to be set up
    elsewhere » (Fetters of Blood) : interdiction posée à l'ennemi ; sur « this unit », une contrepartie."""
    raw = _raw(
        "Until the start of your next turn:\n- The targets cannot use RETREAT or RUN abilities.\n"
        "- The targets cannot be removed from the battlefield by an ability that would allow them to be set up "
        "elsewhere on the battlefield or in reserve.",
        declare="Pick a visible enemy unit within 18\" of them to be the target.",
        condition="Your Hero Phase",
    )
    effs = _effs(raw)
    assert not any(e.kind in ("redeploy", "deep_strike") for e in effs)
    assert {e.side for e in effs if e.kind == "restriction"} == {"enemy"}
    mirror = _raw(
        "While the target is gazing into eternity, it must end all moves no further from this unit than it was at the "
        "start of the move and it cannot be removed from the battlefield by an ability that would allow it to be set "
        "up again on the battlefield.",
        declare="Pick a visible enemy unit within 18\" of this unit to be the target.",
        condition="Enemy Hero Phase",
    )
    effs = _effs(mirror)
    assert not any(e.kind == "redeploy" for e in effs)
    assert [e.side for e in effs if e.kind == "restriction"] == ["enemy"]
    own = _raw(
        "For the rest of the turn:\n- This unit cannot move or be removed from the battlefield by an ability that "
        "would allow it to be set up elsewhere on the battlefield or in reserve.",
        condition="Your Hero Phase",
    )
    assert not any(e.kind == "deep_strike" for e in _effs(own))


def test_v36_opponent_moves_its_own_target_is_a_debuff():
    """« Your opponent must remove the target from the battlefield and set it up again in combat with this unit »
    (Shadow Lariat) : c'est l'ennemi qu'on déplace."""
    raw = _raw(
        "If the target is more than 3\" from all other enemy units, apply the effect below.\n"
        "Your opponent must remove the target from the battlefield and set it up again in combat with this unit.",
        declare="Pick a visible enemy INFANTRY HERO within 12\" of this unit to be the target.",
        condition="End of Any Turn",
    )
    assert [e.side for e in _effs(raw) if e.kind == "redeploy"] == ["enemy"]


def test_v36_enemy_picked_on_an_option_line():
    """« Mesmerise: Pick a visible enemy unit within 12\" of this unit. Until …, that unit cannot use commands »."""
    raw = _raw(
        "Roll a dice. On a 3+, pick 1 of the following effects:\n"
        "Glareface Dance: Pick a friendly GLOOMSPITE GITZ unit within this unit's combat range. Add 1 to run rolls "
        "and charge rolls for that unit until the start of your next turn.\n"
        "Mesmerise: Pick a visible enemy unit within 12\" of this unit. Until the start of your next turn, that unit "
        "cannot use commands.",
        condition="Your Hero Phase",
    )
    assert [e.side for e in _effs(raw) if e.kind == "lockout"] == ["enemy"]


def test_v36_in_combat_or_charged_and_declare_in_combat():
    """« If this unit is in combat or charged this turn » : deux alternatives → « au combat » seul ; « If this unit
    is in combat, pick … » en tête de l'Annonce vaut pour tous les effets (Terminate Their Command)."""
    raw = _raw(
        "Resolve combat attacks against the target unit(s). Then, roll a dice. On a 3+, remove this unit from the "
        "battlefield and set it up again on the battlefield more than 3\" from all enemy units.",
        declare="If this unit is in combat or charged this turn, this unit can make a pile-in move. Then, if this unit "
        "is in combat, you must pick 1 or more enemy units to be the target(s) of this unit's attacks.",
        condition="Your Combat Phase",
    )
    for e in _effs(raw):
        reqs = (e.requires or "").split(" | ")
        assert "a chargé" not in reqs and "au combat" in reqs
    tele = _raw(
        "Remove this unit from the battlefield and set it up again within 1\" of the target.",
        declare="If this unit is in combat, pick a visible enemy HERO within 12\" of this unit to be the target.",
        condition="Once Per Turn (Army), Any Charge Phase",
    )
    assert all("au combat" in (e.requires or "") for e in _effs(tele))


# ----- v36 : lectures relevées par la grille soin (couche 3) ----------------------------------------------


def test_v36_heal_dice_are_read_before_integers():
    """« Heal (2D6) » valait 2 (l'alternative entière passait avant les dés) ; 3D3 manquait à la table."""
    heals = [e for e in _effs(_raw("Heal (2D6) this unit.", condition="Any Hero Phase")) if e.kind == "heal"]
    assert [e.value for e in heals] == [7.0]
    heals = [e for e in _effs(_raw("Heal (3D3) this unit.", condition="End of Any Turn")) if e.kind == "heal"]
    assert [e.value for e in heals] == [6.0]
    back = _effs(_raw("If the target is a Dryads unit, return up to D3 models to the target unit.",
                      declare="Pick a friendly SYLVANETH unit wholly within 12\" of this unit to be the target.",
                      condition="Your Hero Phase"))
    assert [e.value for e in back if e.kind == "return_models"] == [2.0]


def test_v36_heal_modifiers_are_not_heals():
    """Polluting Aura : « an ability that would heal 1 or more damage points » est un déclencheur ; « add 1 to the
    number of damage points healed » un bonus aux soins amis ; « subtract 1 … healed » un anti-soin ennemi."""
    effs = _effs(_raw(
        "While a friendly MAGGOTKIN OF NURGLE unit is wholly within 6\" of a POLLUTED terrain feature, each time that "
        "unit uses or is the target of an ability that would heal 1 or more damage points, add 1 to the number of "
        "damage points healed.\nWhile an enemy unit is within 6\" of a POLLUTED terrain feature, each time that unit "
        "uses or is the target of an ability that would heal 1 or more damage points, subtract 1 from the number of "
        "damage points healed, to a minimum of 0."
    ))
    heals = [e for e in effs if e.kind == "heal"]
    assert len(heals) == 1 and heals[0].detail == "bonus aux soins"
    assert any(e.kind == "anti_heal" and e.side == "enemy" for e in effs)
    assert not any(e.kind == "damage_redirect" for e in effs)


def test_v36_singular_friendly_aura_scope():
    """« If a friendly BLOODBOUND unit wholly within 12" of this unit uses the 'Rally' command » : bulle à 12", pas
    soi-même (17 bonus de Rally, quelques relais de magie)."""
    ex = extract(_raw("If a friendly BLOODBOUND unit wholly within 12\" of this unit uses the 'Rally' command, you can "
                      "make 3 additional rally rolls of D6."))[0]
    assert (ex.scope, ex.range_inches) == ("friendly_aura", 12)
    ex = extract(_raw("Each time a friendly NIGHTHAUNT unit wholly within 12\" of this unit uses the 'Rally' command, "
                      "you can make 3 additional rally rolls of D6."))[0]
    assert (ex.scope, ex.range_inches) == ("friendly_aura", 12)


def test_v36_drained_friendly_models_are_a_cost():
    """Father of Necromancy : « Up to 3 models in the drained unit are automatically slain » — l'unité drainée est
    AMIE : un coût, pas une élimination ennemie ; l'aptitude est un soin."""
    from aospy.abilities.families import effect_family, main_family

    raw = _raw(
        "Up to 3 models in the drained unit are automatically slain. Then, return a number of slain models to the "
        "target unit with a combined Health characteristic of up to the combined Health characteristic of models "
        "slain in the drained unit.",
        declare="Pick 2 visible friendly LEGIONS OF NAGASH units that are wholly within 18\" of this unit. Pick 1 of "
        "those units to be the target, then pick the other to be drained.",
        condition="Your Hero Phase",
    )
    ex = extract(raw)[0]
    slay = [e for e in ex.effects if e.kind == "slay"]
    assert slay and all(e.side == "friendly" and e.detail == "auto-infligé" for e in slay)
    assert main_family(effect_family(e, ex.scope) for e in ex.effects) == "soin"


def test_v36_heal_after_fighting_requires_combat_and_lists_the_kill():
    """Soin « slain by this unit's combat attacks » : « au combat » ; s'il faut détruire un HÉROS ennemi, la
    condition est listée en bon cas (`target_condition`), pas chiffrée (réponse utilisateur)."""
    raw = _raw(
        "If an enemy HERO had any damage points allocated to it by this unit's combat attacks this turn and that HERO "
        "was destroyed this turn, Heal (X) this unit, where X is the number of damage points this unit has.",
        condition="End of Any Turn",
    )
    heal = [e for e in _effs(raw) if e.kind == "heal"]
    assert heal and "au combat" in heal[0].requires and "élimine un HERO" in heal[0].target_condition
    plain = _raw("Each time this unit uses a FIGHT ability, after that FIGHT ability has been resolved, Heal (X) this "
                 "unit.")
    heal = [e for e in _effs(plain) if e.kind == "heal"]
    assert heal and "au combat" in heal[0].requires and not heal[0].target_condition


# ----- v36 : lectures relevées par la grille contrôle (couche 3) ------------------------------------------


def test_v36_enemy_control_is_a_debuff_and_own_cap_a_drawback():
    """« that enemy unit has a maximum control score of 1 » / « subtract … from the target's control score » sur une
    cible ennemie : débuff ; « This unit has a maximum control score of 1 » (Beast) : contrepartie à 0 ; « Add … to
    this unit's control score » après une cible ennemie (Light A Pyre) reste ami."""
    from aospy.abilities.families import effect_family

    spasms = extract(_raw(
        "After that SHOOT ability has been resolved, if all of this unit's attacks made as part of that SHOOT ability "
        "targeted the same enemy unit and any enemy models were slain by those attacks, roll a dice. On a 3+, that "
        "enemy unit has a maximum control score of 1 for the rest of the turn.",
        condition="Reaction: You declared a SHOOT ability for this unit",
    ))[0]
    ctl = [e for e in spasms.effects if e.kind == "control"]
    assert ctl and ctl[0].side == "enemy" and effect_family(ctl[0], spasms.scope) == "debuff"
    assert "après tir du porteur" in ctl[0].requires  # déclencheur de réaction lu (v36)
    from aospy.abilities.scoring import power_of

    text = "This unit has a maximum control score of 1."
    beast = extract(_raw(text))[0]
    assert beast.effects[0].detail == "contrepartie" and effect_family(beast.effects[0], beast.scope) == "autre"
    assert power_of(beast, text)[0] == 0
    pyre = extract(_raw(
        "Roll a D3. On a 2+:\n- Inflict an amount of mortal damage on the target equal to the roll.\n- Add a number "
        "equal to the roll to this unit's control score for the rest of the turn.",
        declare="If this unit is contesting an objective, pick a visible enemy unit within 6\" of this unit to be the "
        "target.",
        condition="Once Per Turn (Army)",
    ))[0]
    assert [e.side for e in pyre.effects if e.kind == "control"] == ["friendly"]


def test_v36_ignore_positive_modifiers_listed_rolls():
    """Grief-stricken : « Ignore positive modifiers to the target's control score and to hit rolls, wound rolls and
    save rolls for the target » est un anti-buff ennemi."""
    ex = extract(_raw(
        "Ignore positive modifiers to the target's control score and to hit rolls, wound rolls and save rolls for the "
        "target for the rest of the turn.",
        declare="Pick a visible enemy unit within 18\" of this unit to be the target, then make a casting roll of 2D6.",
        condition="Your Hero Phase",
    ))[0]
    assert any(e.kind == "no_buff" and e.side == "enemy" for e in ex.effects)


# ----- v37 : lectures relevées par la grille magie-ressource (couche 3) ------------------------------------


def test_v37_set_up_from_reserve_is_a_deep_strike_not_a_summon():
    """« Set up this unit anywhere on the battlefield more than 9" » (Emergence, Chameleon Ambush…), « Set up this
    unit within 6" of an enemy unit » (Sudden Ambush) et « set up the (other) units that were … with this unit » :
    sortie de réserve (`deep_strike`, mobilité) ; une unité de remplacement reste une convocation."""
    for eff in (
        "Set up this unit anywhere on the battlefield more than 9\" from all enemy units. Then, set up the other units "
        "that were set up underground with it (if any) wholly within 6\" of this unit and more than 9\" from all enemy "
        "units.",
        "Set up this unit within 6\" of an enemy unit and not in combat.",
    ):
        kinds = [e.kind for e in _effs(_raw(eff, condition="Your Movement Phase"))]
        assert kinds == ["deep_strike"]
    repl = _raw(
        "Set up a replacement unit with half the number of models from the target unit (rounding up) wholly "
        "within 12\" of this unit and more than 9\" from all enemy units.",
        declare="Pick a friendly SERAPHON unit that has been destroyed to be the target.",
        condition="Your Hero Phase",
    )
    assert [e.kind for e in _effs(repl)] == ["summon"]


def test_v37_power_level_malus_is_a_drawback():
    """« While this unit has 10 or more damage points, subtract 1 from its power level » : contrepartie, famille
    `autre`, pas de la magie."""
    from aospy.abilities.families import effect_family

    ex = extract(_raw("While this unit has 10 or more damage points, subtract 1 from its power level."))[0]
    mods = [e for e in ex.effects if e.kind == "stat_mod" and e.stat == "power_level"]
    assert mods and effect_family(mods[0], ex.scope) == "autre"


# ----- v38 : lectures relevées par les enchaînements (couche 4) --------------------------------------------


def test_v38_coordinated_keywords_and_conditions_on_allies():
    """« friendly SKAVEN INFANTRY and CAVALRY units » : règle d'armée ; « within 12" of any friendly X units » :
    une condition (le bénéficiaire reste l'unité) ; « While a friendly X is wholly within … : That non-HERO unit
    can … » : les receveurs sont X, pas un porteur ; sauf si le texte vise des unités ennemies."""
    ex = extract(_raw("No mortal damage is inflicted on friendly SKAVEN INFANTRY and CAVALRY units by RETREAT "
                      "abilities."))[0]
    assert ex.scope == "army"
    ex = extract(_raw("Add 1 to the Damage characteristic of this unit's melee weapons while this unit is wholly "
                      "within 12\" of any friendly SKINK INFANTRY or SKINK CAVALRY units in combat."))[0]
    assert ex.scope != "army"
    ex = extract(_raw("While a friendly non-HERO FLESH-EATER COURTS MONSTER or BEAST is wholly within 12\" of any "
                      "friendly FLESH-EATER COURTS HEROES:\n- That non-HERO unit can use a RAMPAGE ability."))[0]
    assert ex.scope == "army"
    ex = extract(_raw("In the third and subsequent battle rounds, while a friendly Cursed Sepulchre is on the "
                      "battlefield, subtract 1 from save rolls for enemy units."))[0]
    assert ex.scope != "army"

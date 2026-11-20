"""Notation des 4 axes, verdict, tags et corrections manuelles."""

from __future__ import annotations

import json

from aospy.abilities.overrides import apply_override, load_overrides
from aospy.abilities.pipeline import analyze_one
from aospy.abilities.tags import ALL_TAGS

from .test_extract import _raw


def test_reliable_strong_passive_is_a_plan():
    a = analyze_one(_raw("This unit has WARD (5+)."))
    assert a.score.verdict == "plan"
    assert {"fiable", "protection", "passif", "soi-meme", "plan"} <= set(a.tags)
    assert a.score.interaction == 0.0


def test_strong_but_random_is_a_gamble():
    a = analyze_one(_raw("Roll a dice. On a 4+, inflict D6 mortal damage on the target.",
                         declare="Pick a visible enemy unit within 12\" of this unit to be the target.",
                         condition="Your Hero Phase", cost_type="Spell", cost_value="7"))
    assert a.score.reliability < 2.25
    assert a.score.verdict == "pari"
    assert "aleatoire" in a.tags


def test_two_plus_vs_three_plus_gate():
    two = analyze_one(_raw("Roll a dice. On a 2+, this unit has STRIKE-FIRST for the rest of the turn.",
                           condition="Your Combat Phase"))
    three = analyze_one(_raw("Roll a dice. On a 3+, this unit has STRIKE-FIRST for the rest of the turn.",
                             condition="Your Combat Phase"))
    assert two.score.reliability > three.score.reliability
    assert two.score.verdict == "plan" and three.score.verdict == "pari"


def test_weak_effect_is_anecdotal():
    a = analyze_one(_raw("Add 1 to run rolls for this unit."))
    assert a.score.verdict == "anecdotique"


def test_unrecognized_is_flagged_for_review():
    a = analyze_one(_raw("You can measure the range from any point on the battlefield edge."))
    assert a.score.verdict == "a-revoir" and not a.understood


def test_army_wide_interaction_and_bubble_tags():
    army = analyze_one(_raw("Add 1 to hit rolls for combat attacks made by friendly SKAVEN units."))
    bubble = analyze_one(_raw("Add 1 to hit rolls for friendly SKAVEN units while they are wholly "
                              "within 12\" of this unit."))
    assert army.score.interaction == 3.0 and "armee" in army.tags
    assert 1.5 < bubble.score.interaction < 3.0 and "bulle-12" in bubble.tags


def test_once_per_battle_reduces_power():
    every = analyze_one(_raw("This unit has STRIKE-FIRST for the rest of the turn.", condition="Your Combat Phase"))
    once = analyze_one(_raw("This unit has STRIKE-FIRST for the rest of the turn.",
                            condition="Once Per Battle, Your Combat Phase"))
    assert once.score.power < every.score.power and "une-fois-par-bataille" in once.tags


def test_tags_stay_in_vocabulary():
    for text in ("This unit has WARD (4+).", "Heal (D3) this unit.", "Return 1 slain model to this unit.",
                 "Add 2\" to the Move characteristic of this unit.", "You gain 1 command point."):
        assert set(analyze_one(_raw(text)).tags) <= set(ALL_TAGS)


def test_override(tmp_path):
    path = tmp_path / "ov.json"
    path.write_text(json.dumps({"overrides": {"x": {"name": "Test", "verdict": "pari", "power": 2.5,
                                                    "add_tags": ["charge"], "note": "vu en partie"}}}))
    ov = load_overrides(path)
    a = apply_override(analyze_one(_raw("Add 1 to run rolls for this unit.")), ov["x"])
    assert a.score.verdict == "pari" and a.score.power == 2.5 and a.overridden
    assert "pari" in a.tags and "anecdotique" not in a.tags and "charge" in a.tags


def test_blood_tithe_chain_is_late_bonus_never_a_plan():
    from dataclasses import replace

    from aospy.abilities.extract import extract
    from aospy.abilities.models import AbilityOwner
    from aospy.abilities.pipeline import _finish, resolve_resource_costs

    bok = (AbilityOwner("BoK", "Blades of Khorne", "faction_rule", "Battle Traits"),)

    def tithe(name, cost, text):
        return replace(_raw(text), name=name, cost_type="Blood tithe", cost_value=str(cost), owners=bok)

    raws = [
        tithe("PUNISH THE PACIFIST", 1, "Subtract 1 from the control score of the target."),
        tithe("GLORIOUS COMBAT OR NAUGHT", 2, "You can only unlock this ability if you have unlocked "
              "'Divine Scorn' or 'Punish the Pacifist'. Add 1 to the Rend characteristic of melee weapons "
              "used by friendly BLADES OF KHORNE units."),
        tithe("CLEAVE WIDE THE GRIN OF KHORNE", 4, "You can only unlock this ability if you have unlocked "
              "already 'Revel in Battle' or 'Glorious Combat or Naught'. Add 1 to hit rolls for combat "
              "attacks made by friendly BLADES OF KHORNE units."),
    ]
    extracted = [extract(r) for r in raws]
    resolve_resource_costs(raws, [ex for ex, _ in extracted])
    cleave = _finish(raws[2], *extracted[2])
    assert cleave.extraction.resource_cost == 7          # 1 + 2 + 4
    assert cleave.extraction.available_round == 5        # 2 points/round
    assert cleave.score.verdict == "bonus"
    assert {"bonus", "tardive", "armee"} <= set(cleave.tags)


def test_reliable_but_modest_is_correct():
    a = analyze_one(_raw("Add 3 to the control scores of friendly SKAVEN units while they are wholly "
                         "within 12\" of this unit."))
    assert a.score.verdict == "correct"


def test_coordination_with_carrier_makes_a_situational_bonus():
    a = analyze_one(_raw("Pick a friendly non-HERO INFANTRY unit that has not used a FIGHT ability this turn "
                         "and is within this unit's combat range to be the target. The target can be picked "
                         "to use a FIGHT ability immediately after.", condition="Reaction: You declared a FIGHT "
                         "ability for this unit", is_reaction=True))
    assert "coordination" in a.tags
    assert a.score.verdict == "bonus"


def test_fragile_ward_token_is_anecdotal():
    a = analyze_one(_raw("This unit has WARD (5+) while its token is on the battlefield. If you make an "
                         "unmodified save roll of 1 for this unit, remove its token from the battlefield."))
    assert a.score.verdict == "anecdotique"


def test_crit_threshold_is_strong():
    a = analyze_one(_raw("Roll a dice. On a 2+, attacks made by that unit score critical hits on unmodified "
                         "hit rolls of 5+.", declare="Pick a friendly unit to be the target.",
                         condition="Once Per Turn (Army), Your Hero Phase"))
    assert a.score.power >= 2.5 and a.score.verdict == "plan"


def test_stacked_offense_debuffs_are_anti_deathstar():
    a = analyze_one(_raw("Until the start of your next turn:\n- Subtract 1 from hit rolls for the target's combat "
                         "attacks.\n- The target's combat attacks cannot score critical hits.",
                         declare="Pick a visible enemy unit within 18\" of this unit to be the target, then "
                                 "make a casting roll of 2D6.", cost_type="Spell", cost_value="6",
                         condition="Your Hero Phase"))
    assert "anti-deathstar" in a.tags and a.score.power >= 2.5
    assert a.score.verdict == "pari"


def test_manifestation_needs_summoning_and_melee():
    from dataclasses import replace

    from aospy.abilities.extract import extract
    from aospy.abilities.models import AbilityOwner
    from aospy.abilities.pipeline import _finish, resolve_manifestations

    viper = AbilityOwner("DoK", "Daughters of Khaine", "warscroll", "Bloodwrack Viper", "w", "Manifestation")
    coils = replace(_raw("Roll a dice. On a 3+, the target has STRIKE-LAST for the rest of the turn.",
                         declare="Pick an enemy HERO in combat with this MANIFESTATION to be the target.",
                         condition="Any Combat Phase"), owners=(viper,))
    summon = replace(_raw("Set up a Bloodwrack Viper wholly within 12\" of the caster."),
                     name="SUMMON BLOODWRACK VIPER", cost_type="Spell", cost_value="6")
    raws = [coils, summon]
    extracted = resolve_manifestations(raws, [extract(r) for r in raws])
    a = _finish(coils, *extracted[0])
    assert a.extraction.activation_prob < 0.67 * 0.9          # 3+ × facteur d'invocation
    assert "manifestation à amener au corps à corps" in a.extraction.conditions
    assert {"manifestation", "dissuasion", "pari"} <= set(a.tags)


def test_marked_enemy_target_is_an_offensive_bubble():
    a = analyze_one(_raw("Add 1 to the Rend characteristic of melee weapons used for attacks that target that unit.",
                         declare="Pick an enemy unit on the battlefield.", condition="Start of the First Battle Round"))
    e = next(e for e in a.extraction.effects if e.kind == "stat_mod")
    assert (e.stat, e.side, e.detail, e.weapon_scope) == ("rend", "friendly", "marquage", "melee")
    assert {"marquage", "buff-offensif"} <= set(a.tags) and a.score.interaction == 2.0


def test_v28_dice_count_weights():
    from aospy.abilities.models import Effect
    from aospy.abilities.scoring import DICE_ENEMY_WEIGHTS, REROLL_WEIGHTS, _effect_weight
    keep = _effect_weight(Effect("dice_count", "charge", 1.0, "", "friendly", "garder"))[0]
    summed = _effect_weight(Effect("dice_count", "charge", 1.0, "", "friendly", "somme"))[0]
    assert keep == REROLL_WEIGHTS["charge"]          # 3 dés, on en retire un ≈ une relance de charge
    assert summed > keep                              # 3D6 : 9" à 74 %
    assert _effect_weight(Effect("dice_count", "charge", -1.0, "", "enemy", "somme"))[0] == DICE_ENEMY_WEIGHTS["charge"]
    assert _effect_weight(Effect("dice_count", "charge", -1.0, "", "friendly", "somme"))[0] == 0.0   # contrepartie

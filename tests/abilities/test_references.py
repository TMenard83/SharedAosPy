"""Analyseur v34, chantier B : mécaniques de faction dont la valeur est dans d'autres aptitudes.

Une règle validée par l'utilisateur (2026-11-22) = un test.
"""

from __future__ import annotations

import dataclasses

import pytest

from aospy.abilities.extract import extract
from aospy.abilities.extract.references import DIRTY_TRICK_P, REF_FRACTIONS, TERRAIN_FRACTION
from aospy.abilities.models import AbilityOwner, RawAbility
from aospy.abilities.pipeline import _finish, analyze_one
from aospy.abilities.references import RESOLUTION_PASSES, pending_references, resolve_references
from aospy.abilities.text import fix_typos


def _raw(
    effect: str,
    declare: str = "",
    condition: str = "Passive",
    name: str = "Test",
    keywords: str = "",
    source_kind: str = "warscroll",
    owner: str = "Some Unit",
    owner_kind: str = "warscroll",
    faction: str = "XX",
    uid: str | None = None,
) -> RawAbility:
    return RawAbility(
        uid=uid or name,
        name=name,
        source_kind=source_kind,  # type: ignore[arg-type]
        group_name="",
        condition=condition,
        phase="",
        wahapedia_type="",
        is_reaction=False,
        keywords=keywords,
        cost_type="",
        cost_value="",
        declare=declare,
        effect=effect,
        owners=(AbilityOwner(faction, faction, owner_kind, owner),),  # type: ignore[arg-type]
    )


def _kinds(raw: RawAbility) -> dict[str, object]:
    ex, _ = extract(raw)
    return {e.kind: e for e in ex.effects}


def _resolve_all(raws: list[RawAbility]):
    """Pipeline réduit : 1re passe, puis résolution des renvois (comme `pipeline.analyze_all`)."""
    out = [analyze_one(r) for r in raws]
    pending = pending_references(out)
    for _ in range(RESOLUTION_PASSES):
        left = resolve_references(out, pending)
        for i in pending:
            ex, penalty = extract(raws[i])
            out[i] = _finish(raws[i], out[i].extraction, penalty)
        pending = left
    return {a.raw.name: a for a in out}


_PLUS1_HIT = "Add 1 to hit rolls for combat attacks made by this unit."  # ≈ puissance 1,5
_PLUS1_DMG = "Add 1 to the Damage characteristic of this unit's melee weapons."  # ≈ puissance 2,0


# ----- B1 : options choisies par l'adversaire, défi accepter/refuser -----


def test_opponent_picks_the_weakest_option():
    """Tentations HoS : « your opponent must pick 1 of the effects below » → l'option la plus faible."""
    text = (
        "If the unit using this ability is a PARAGON, pick 1 of the effects below. Otherwise, your opponent must "
        "pick 1 of the effects below.\n"
        "Rise to the Insults: For the rest of the turn, the target has a maximum control score of 1.\n"
        "Turn the Other Cheek: For the rest of the turn, add 1 to hit rolls for attacks made by friendly HEDONITES "
        "OF SLAANESH units that target the target."
    )
    a = analyze_one(_raw(text, declare="Pick an enemy unit in combat with that HERO to be the target.",
                         condition="Any Combat Phase"))
    groups = {e.option_group for e in a.extraction.effects}
    assert groups == {"Rise to the Insults", "Turn the Other Cheek"}
    assert "choisies par l'adversaire" in "\n".join(a.score.rationale)
    assert a.score.power < 1.0  # le contrôle max 1, pas le +1 touche


def test_challenge_accept_or_decline_are_exclusive_options():
    """You First, I Insist... : chaque réponse au défi est une option, ses puces comprises."""
    text = (
        "Your opponent must decide whether the target will accept or decline this unit's challenge:\n"
        "If they accept, for the rest of the turn, subtract 1 from hit rolls for the target's attacks and all of "
        "the target's attacks must target this unit.\n"
        "If they decline, for the rest of the turn:\n"
        "- The target has STRIKE-LAST.\n"
        "- Add 1 to the Damage characteristic of this unit's melee weapons for attacks that target the target."
    )
    ex, _ = extract(_raw(text, declare="Pick an enemy unit in combat with this unit to be the target.",
                         condition="Any Combat Phase"))
    assert {e.option_group for e in ex.effects} == {"accept", "decline"}


# ----- B3 : ligne « pick any other effect » d'une table aléatoire -----


def test_free_pick_row_is_worth_the_best_other_row():
    """Aura of Mutation : « 6 - Mutant Tide Pick any other effect » vaut la meilleure ligne, plus 0."""
    rows = (
        "Roll a dice and apply the corresponding effect below.\n"
        "1 - Untouched No effect.\n"
        "2-5 - Horrible Absorption Inflict D6 mortal damage on the target.\n"
    )
    declare = "Pick a visible enemy unit within 12\" of this unit to be the target."
    base = analyze_one(_raw(rows + "6 - Bad Luck No effect.", declare=declare, condition="Your Hero Phase"))
    pick = analyze_one(_raw(rows + "6 - Mutant Tide Pick any other effect.", declare=declare,
                            condition="Your Hero Phase"))
    assert pick.score.power == pytest.approx(base.score.power * 5 / 4, abs=0.02)  # 4/6 → 5/6 de lignes utiles


# ----- lectures génériques corrigées en chemin -----


def test_second_modifier_after_and_add_is_read():
    """Creepy Cantrips : « add 1 to rampage rolls for the target and add 1 to hit rolls … » : le +1 touche compte."""
    ex, _ = extract(_raw(
        "Until the start of your next turn, add 1 to rampage rolls for the target and add 1 to hit rolls for the "
        "target's combat attacks.",
        declare="Pick a visible friendly MONSTER unit wholly within 18\" of this unit to be the target.",
        condition="Your Hero Phase",
    ))
    assert any(e.kind == "stat_mod" and e.stat == "hit" and e.value == 1 for e in ex.effects)


def test_capitalised_lost_ligature_is_fixed():
    assert fix_typos("Inict D3 mortal damage on each target.") == "Inflict D3 mortal damage on each target."


# ----- moteurs de rotation et Sales Tours -----


@pytest.mark.parametrize("kw,factor", [("Delusion", 5 / 6), ("Cycle", 1 / 3)])
def test_rotation_engines_scale_power(kw, factor):
    """Délire cru seulement certains tours (×5/6), Cycle MoN mûr seulement certains rounds (×1/3)."""
    plain = analyze_one(_raw(_PLUS1_DMG))
    rotated = analyze_one(_raw(_PLUS1_DMG, keywords=kw))
    assert rotated.score.power == pytest.approx(plain.score.power * factor, abs=0.01)


def test_dirty_trick_needs_a_success_roll():
    plain = analyze_one(_raw(_PLUS1_DMG, condition="Your Hero Phase"))
    trick = analyze_one(_raw(_PLUS1_DMG, condition="Your Hero Phase", keywords="Dirty Trick"))
    assert trick.extraction.activation_prob == pytest.approx(plain.extraction.activation_prob * DIRTY_TRICK_P, abs=1e-3)
    assert trick.score.verdict == "pari"


# ----- règles-cadres et jetons posés : 0 -----


@pytest.mark.parametrize(
    "text,declare",
    [
        ("This unit can transport up to 2 friendly KHARADRON OVERLORDS INFANTRY units with a combined model count "
         "of up to 12 (see Battle Traits).", ""),
        ("On a delusion roll of 1-2, you must pick a different DELUSION. For the rest of the turn, you believe the "
         "DELUSION you picked.", ""),
        ("Place this unit's Grype next to the target.", "This unit's Grype is a token. Pick an enemy unit within 18\" "
         "of this unit to be the target."),
    ],
)
def test_frameworks_and_placed_tokens_are_warscroll_rules(text, declare):
    a = analyze_one(_raw(text, declare=declare, condition="Your Hero Phase"))
    assert {e.kind for e in a.extraction.effects} == {"warscroll_rule"}
    assert a.score.power == 0 and a.score.verdict == "anecdotique"


# ----- renvois résolus en seconde passe -----


def test_status_grant_is_worth_the_mean_of_its_readers():
    """Sous ordres : puissance = moyenne des aptitudes de la faction qui lisent le statut."""
    raws = [
        _raw("For the rest of the battle round, the targets are under orders.", name="FORM UP",
             declare="Pick 2 visible friendly units wholly within 12\" of it to be the targets.",
             condition="Start of Battle Round"),
        _raw("While this unit is under orders, " + _PLUS1_HIT[0].lower() + _PLUS1_HIT[1:], name="R1"),
        _raw("While this unit is under orders, " + _PLUS1_DMG[0].lower() + _PLUS1_DMG[1:], name="R2"),
    ]
    out = _resolve_all(raws)
    grant = next(e for e in out["FORM UP"].extraction.effects if e.kind == "status_grant")
    assert grant.detail == "sous ordres"
    assert grant.value == pytest.approx((out["R1"].score.power + out["R2"].score.power) / 2, abs=0.01)


@pytest.mark.parametrize(
    "text,how",
    [
        ("Add 1 to rolls for your general's 'Mighty Blow' ability.", "boost"),
        ("When using the 'Mighty Blow' ability, you can pick up to 2 eligible targets instead of 1.", "extend"),
        ("This unit can use the 'Mighty Blow' ability even if it has used it this turn.", "extend"),
        ("If this unit is anointed, the effects of the 'Mighty Blow' ability apply to this unit as if they were "
         "active.", "full"),
    ],
)
def test_meta_ability_is_a_graduated_fraction_of_the_cited_one(text, how):
    out = _resolve_all([_raw(text, name="META"), _raw(_PLUS1_DMG, name="Mighty Blow", condition="Your Hero Phase")])
    ref = next(e for e in out["META"].extraction.effects if e.kind == "ability_ref")
    assert ref.stat == how
    assert ref.value == pytest.approx(REF_FRACTIONS[how] * out["Mighty Blow"].score.power, abs=0.01)


def test_cited_name_after_a_possessive_and_with_an_apostrophe():
    """« this unit's 'Eat 'Em Alive' ability » : ni le possessif ni l'apostrophe du nom ne coupent la citation."""
    out = _resolve_all([
        _raw("More than 1 effect of this unit's 'Eat 'Em Alive' ability can apply to this unit at the same time.",
             name="META"),
        _raw(_PLUS1_DMG, name="Eat 'Em Alive", condition="End of Any Turn"),
    ])
    ref = next(e for e in out["META"].extraction.effects if e.kind == "ability_ref")
    assert ref.detail == "nom:Eat 'Em Alive" and ref.value > 0


def test_free_enhancement_is_the_table_mean_times_count():
    table = "Gorechosen Champions › Artefacts of Power"
    raws = [
        _raw("Give each target 1 artefact of power from the 'Gorechosen Champions' Army of Renown rules.",
             name="GIFTS", declare="Pick up to 2 friendly HEROES that do not have an artefact of power to be the "
             "targets.", condition="Once Per Battle, Deployment Phase", source_kind="battle_trait",
             owner="Gorechosen Champions › Battle Traits", owner_kind="faction_rule"),
        _raw(_PLUS1_HIT, name="A1", source_kind="artefact", owner=table, owner_kind="faction_rule"),
        _raw(_PLUS1_DMG, name="A2", source_kind="artefact", owner=table, owner_kind="faction_rule"),
    ]
    out = _resolve_all(raws)
    gift = next(e for e in out["GIFTS"].extraction.effects if e.kind == "free_enhancement")
    mean = (out["A1"].score.power + out["A2"].score.power) / 2
    assert gift.value == pytest.approx(min(3.0, 2 * mean), abs=0.01)
    # un seul héros : pas de plafond, et pas de malus « une fois par bataille » (l'artefact reste)
    # (au début du 1er round : « once_per_battle » ; au déploiement, déjà sans malus)
    one = _resolve_all([dataclasses.replace(raws[0], declare="Pick a friendly HERO to be the target.",
                                            condition="Once Per Battle, Start of the First Battle Round")] + raws[1:])
    assert one["GIFTS"].extraction.frequency == "once_per_battle"
    assert one["GIFTS"].score.power == pytest.approx(mean, abs=0.01)


def test_extra_faction_terrain_is_half_the_terrain_value():
    raws = [
        _raw("Set up a Feculent Gnarlmaw on the battlefield more than 3\" from all enemy units.", name="GROW",
             condition="Your Hero Phase"),
        _raw(_PLUS1_DMG, name="G1", owner="Feculent Gnarlmaw"),
    ]
    out = _resolve_all(raws)
    setup = next(e for e in out["GROW"].extraction.effects if e.kind == "terrain_setup")
    assert setup.value == pytest.approx(TERRAIN_FRACTION * out["G1"].score.power, abs=0.01)


def test_unresolved_reference_stays_a_revoir():
    """Renvoi vers une règle absente de la base (ordre de base, règle de saison) : jamais deviné."""
    out = _resolve_all([_raw("When this unit uses the 'Power Through' command, the target does not have to have a "
                             "lower Health characteristic.", name="META")])
    assert out["META"].score.verdict == "a-revoir" and not out["META"].extraction.effects


def test_chained_reference_is_resolved_on_the_second_pass():
    """HEAD GARDENER → 'Cultivating the Garden' (qui pose un Gnarlmaw) : résolu à la 2e passe."""
    raws = [
        _raw("The friendly gardener can use his 'Cultivating the Garden' ability this phase even if there are 1 or "
             "more friendly Feculent Gnarlmaws on the battlefield.", name="HEAD", condition="Your Movement Phase"),
        _raw("You can set up a Feculent Gnarlmaw wholly within 12\" of this unit.", name="Cultivating the Garden",
             condition="Your Movement Phase"),
        _raw(_PLUS1_DMG, name="G1", owner="Feculent Gnarlmaw"),
    ]
    out = _resolve_all(raws)
    assert out["Cultivating the Garden"].score.power > 0
    assert out["HEAD"].score.power > 0

"""Analyseur v42 : receveurs d'en-tête (Waaagh!) et effet qui suit une perte amie (Memories of the Fallen)."""

from __future__ import annotations

from aospy.abilities.extract import extract
from aospy.abilities.models import RawAbility
from aospy.abilities.perimeter import AFTER_FRIENDLY_LOSS


def _raw(effect: str, declare: str, condition: str) -> RawAbility:
    return RawAbility(
        uid="x", name="Test", source_kind="battle_trait", group_name="Battle Traits", condition=condition, phase="",
        wahapedia_type="", is_reaction=False, keywords="", cost_type="", cost_value="", declare=declare, effect=effect,
    )


def test_waaagh_header_receivers():
    ex, _ = extract(_raw(
        "For the rest of the turn, the following effects apply to friendly IRONJAWZ units while they are wholly "
        'within 18" of the target:\n- Add 1 to charge rolls for those units.\n'
        "- Add 1 to the Attacks characteristic of those units' melee weapons.",
        "Pick a friendly IRONJAWZ HERO to be the target. You cannot pick the same HERO to be the target of this "
        "ability more than once per battle.",
        "Once Per Turn (Army), Your Charge Phase",
    ))
    assert ex.friendly_target == "IRONJAWZ HERO"
    assert {e.friendly_target for e in ex.effects if e.stat in ("charge", "attacks")} == {"IRONJAWZ"}


def test_memories_after_friendly_loss():
    ex, _ = extract(_raw(
        "Add 1 to the Attacks characteristic of each target's melee weapons for the rest of the turn.",
        "For each friendly SYLVANETH unit or friendly Awakened Wyldwood that was destroyed in the previous turn, you "
        "can pick a friendly SYLVANETH unit to be a target.",
        "Once Per Turn (Army), Any Hero Phase",
    ))
    assert all(AFTER_FRIENDLY_LOSS in (e.requires or "") for e in ex.effects)

"""Couche 4 — aptitudes × armée (analysis/layers/listing.py), cœur pur."""

from __future__ import annotations

from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.listing import ListAbility, conflicts, magic_budget, marriages, wizard_level
from aospy.domain.models import Unit, Weapon

HAMMER = Weapon("Hammer", "melee", attacks=4, hit=4, wound=2, rend=2, damage=5)


def _unit(name, **kw):
    base = dict(
        name=name,
        army_id=1,
        move=6,
        save=3,
        health=14,
        control=5,
        models=1,
        points=300,
        keywords=frozenset({"MONSTER", "ALARITH"}),
        weapons=[HAMMER],
    )
    base.update(kw)
    return Unit(**base)


def _ab(name, scope="self", freq="passive", carriers=(), effects=(), **kw):
    base = dict(
        uid=name,
        name=name,
        source=f"charte : {carriers[0]}" if carriers else "formation : X",
        source_kind="warscroll" if carriers else "battle_formation",
        carriers=tuple(carriers),
        scope=scope,
        frequency=freq,
        turn_side="any",
        phase="",
        cost_type="",
        cost_value=None,
        activation_prob=1.0,
        available_round=None,
        friendly_target="",
        excludes_self=False,
        verdict="correct",
        power=1.5,
        reliability=3.0,
        ease=3.0,
        interaction=0.0,
        effects=tuple(effects),
    )
    base.update(kw)
    return ListAbility(**base)


def test_wards_do_not_stack_in_a_list():
    spirit = _unit("Spirit")
    warded = _unit("Sevireth", ward=5)
    shield = _ab(
        "Realmshield",
        scope="friendly_aura",
        freq="unlimited",
        effects=[EffectSpec("ward", value=5.0)],
        activation_prob=0.5,
    )
    got = {m.receiver: m for m in marriages([shield], [spirit, warded], frozenset({"MONSTER"}))}
    assert got["Spirit"].def_gain_pct > 49 and got["Spirit"].weight == 0.5
    assert got["Sevireth"].def_gain_pct == 0


def test_army_limited_ability_on_several_copies_is_a_conflict():
    rain = _ab("Rain of Stone", scope="one_enemy", freq="once_per_turn_army", carriers=("Spirit",))
    solo = _ab("Searing Winds", scope="enemy_aura", freq="once_per_turn_army", carriers=("Sevireth",))
    got = conflicts([rain, solo], {"Spirit": 3, "Sevireth": 1})
    assert [c.ability for c in got] == ["Rain of Stone"]


def test_magic_budget_counts_casters_and_spells():
    mage = _unit("Mage", keywords=frozenset({"HERO", "WIZARD"}))
    big = _unit("Arch", keywords=frozenset({"HERO", "WIZARD (2)"}))
    assert wizard_level(mage) == 1 and wizard_level(big) == 2 and wizard_level(_unit("S")) == 0
    spell = _ab("Push", scope="one_friendly", freq="unlimited", cost_type="Spell", cost_value=6.0, activation_prob=0.72)
    mb = magic_budget([spell], [mage, big, _unit("S")])
    assert mb.casts_per_turn == 3 and mb.spells[0][0] == "Push"


def test_ranged_buff_is_unprofitable_when_nobody_shoots():
    """Exemple de l'utilisateur : bannière « +1 touche au tir » en bulle, nulle si personne ne tire."""
    from aospy.analysis.layers.listing import unprofitable_buffs

    banner = _ab(
        "Banner",
        scope="friendly_aura",
        carriers=("Spirit",),
        effects=[EffectSpec("stat_mod", "hit", 1.0, weapon_scope="ranged")],
    )
    melee_only = [_unit("Spirit"), _unit("Sevireth")]
    got = unprofitable_buffs([banner], melee_only, frozenset({"MONSTER"}))
    assert [(a.name, r) for a, r in got] == [("Banner", "aucune unité de la liste ne tire")]
    bow = Weapon("Bow", "ranged", attacks=4, hit=4, wound=4, rend=1, damage=1, range_in=18)
    archer = _unit("Archer", weapons=[bow])
    assert unprofitable_buffs([banner], [*melee_only, archer], frozenset({"MONSTER"})) == []


def test_army_of_renown_categories_replace_base_ones():
    from types import SimpleNamespace

    from aospy.analysis.layers.listing import _rule_groups

    parsed = SimpleNamespace(
        allegiance="Thunderhead Host",
        spell_lore="Lore of the Storm",
        prayer_lore="Prayers of the Stormhosts",
        manifestation_lore=None,
    )
    base = dict(_rule_groups(parsed))
    assert "Battle Traits › *" in base and "Spell Lore › Lore of the Storm" in base
    aor = dict(_rule_groups(parsed, ("Ruination Brotherhood", frozenset({"Battle Traits", "Prayer Lore"}))))
    assert "Battle Traits › *" not in aor and "Ruination Brotherhood › Battle Traits" in aor
    assert "Ruination Brotherhood › Prayer Lore" in aor and "Prayer Lore › Prayers of the Stormhosts" not in aor
    assert "Spell Lore › Lore of the Storm" in aor  # catégorie que l'AoR ne porte pas : celle de base
    assert "Battle Formations › Thunderhead Host" in aor


def test_exclusive_options_keep_the_best_one_per_receiver():
    from aospy.analysis.layers.listing import Marriage, _best_options

    rows = [
        Marriage(
            "Master of the Runes",
            "Auric Runemaster",
            "Hearthguard",
            "allié",
            "stat_mod",
            10.0,
            None,
            1.0,
            "",
            "Rune of Fury",
        ),
        Marriage(
            "Master of the Runes",
            "Auric Runemaster",
            "Hearthguard",
            "allié",
            "stat_mod",
            None,
            25.0,
            1.0,
            "",
            "Rune of Fiery Determination",
        ),
        Marriage("Lodge Leader", "Auric Runefather", "Hearthguard", "allié", "stat_mod", 5.0, None, 1.0, ""),
    ]
    kept = _best_options(rows)
    assert {m.option for m in kept} == {"Rune of Fiery Determination", ""}

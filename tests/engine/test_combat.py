"""Tests Phase 4 : math de dégât espéré + simulation."""

from __future__ import annotations

import math

import pytest

from aospy.engine.combat import (
    CombatModifiers,
    _parse_crit,
    _prob_x_plus,
    damage_floor95,
    expected_unit_damage,
    expected_weapon_damage,
    unit_damage_moments,
    weapon_damage_moments,
)
from aospy.domain.models import Unit, Weapon


def _unit(save=4, health=2, ward=None, weapons=None, models=5, keywords=frozenset()):
    return Unit(
        name="T", army_id=1, move=5, save=save, health=health, control=1,
        models=models, points=100, ward=ward, keywords=keywords, weapons=weapons or [],
    )


def test_prob_x_plus_basic():
    assert _prob_x_plus(3) == pytest.approx(4 / 6)
    assert _prob_x_plus(6) == pytest.approx(1 / 6)
    assert _prob_x_plus(2) == pytest.approx(5 / 6)


def test_prob_x_plus_modifier_caps_at_2():
    # 3+ avec +1 → 2+ (5/6), 2+ avec +1 → reste 2+
    assert _prob_x_plus(3, 1) == pytest.approx(5 / 6)
    assert _prob_x_plus(2, 1) == pytest.approx(5 / 6)


def test_prob_x_plus_impossible_when_above_6():
    assert _prob_x_plus(7) == 0.0
    assert _prob_x_plus(8) == 0.0


def test_parse_crit_variants():
    assert _parse_crit("Crit (2 Hits)") == "2hits"
    assert _parse_crit("Crit (Mortal Wounds)") == "mortal"
    assert _parse_crit("Crit (Auto-Wound)") == "autowound"
    assert _parse_crit("rien") == "none"
    assert _parse_crit(None) == "none"


def test_expected_damage_simple_no_ward_no_rend():
    # 10 attaques, 4+ hit, 4+ wound, save 4+, rend 0, dmg 1, ward off
    # E = 10 * 1/2 * 1/2 * (1 - 1/2) * 1 = 1.25
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, rend=0, damage=1)
    defender = _unit(save=4, ward=None)
    mods = CombatModifiers()
    result = expected_weapon_damage(weapon, attacker_models=5, defender=defender, modifiers=mods)
    assert result == pytest.approx(1.25)


def test_expected_damage_with_rend_and_ward():
    # 10 atk, 3+ hit (4/6), 3+ wound (4/6), save 4+ rend 1 → save 5+ (2/6),
    # unsaved = 1 - 2/6 = 4/6 ; ward 5+ (2/6) → ward_mult = 4/6
    # dmg = 2 ; E = 10 * 4/6 * 4/6 * 4/6 * 2 * 4/6 ≈ 1.97...
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2)
    defender = _unit(save=4, ward=5)
    mods = CombatModifiers()
    result = expected_weapon_damage(weapon, 5, defender, mods)
    expected = 10 * (4/6) * (4/6) * (4/6) * 2 * (4/6)
    assert result == pytest.approx(expected)


def test_rend_makes_save_impossible_when_eff_above_6():
    # save 6+ + rend 2 → 8+ → P_save = 0
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=2, wound=2, rend=2, damage=1)
    defender = _unit(save=6, ward=None)
    # 5 atk, hit 5/6, wound 5/6, unsaved 1, ward 1, dmg 1
    expected = 5 * (5/6) * (5/6) * 1.0 * 1
    assert expected_weapon_damage(weapon, 5, defender, CombatModifiers()) == pytest.approx(expected)


def test_charge_without_ability_text_gives_no_bonus():
    # AoS4 : pas de bonus universel de charge. Sans texte "Charge (+N <Stat>)"
    # dans abilities, charger ne change rien, mêlée ou distance.
    melee = Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1)
    ranged = Weapon(name="r", kind="ranged", attacks=2, hit=4, wound=4, damage=1)
    defender = _unit(save=7)  # save impossible → P_unsaved = 1
    mods = CombatModifiers(attacker_charged=True)

    assert expected_weapon_damage(melee, 5, defender, mods) == pytest.approx(10 * 0.5 * 0.5)
    assert expected_weapon_damage(ranged, 5, defender, mods) == pytest.approx(10 * 0.5 * 0.5)


def test_all_out_attack_improves_hit():
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=4, wound=4, damage=1)
    defender = _unit(save=7)
    base = expected_weapon_damage(weapon, 5, defender, CombatModifiers())
    boosted = expected_weapon_damage(
        weapon, 5, defender, CombatModifiers(attacker_all_out_attack=True)
    )
    # base: 5 * 3/6 * 3/6 = 1.25 ; boosted: 5 * 4/6 * 3/6 ≈ 1.667
    assert base == pytest.approx(1.25)
    assert boosted == pytest.approx(5 * (4/6) * (3/6))


def test_all_out_defense_improves_save():
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=2, wound=2, rend=0, damage=1)
    defender = _unit(save=4)
    base = expected_weapon_damage(weapon, 5, defender, CombatModifiers())
    defended = expected_weapon_damage(
        weapon, 5, defender, CombatModifiers(defender_all_out_defense=True)
    )
    # base: save 4+ (3/6), unsaved 3/6. defended: save 3+ (4/6), unsaved 2/6.
    assert defended < base


def test_crit_2_hits():
    # 6 atk, 4+ hit, 4+ wound, save 7 (impossible), dmg 1, Crit (2 Hits)
    # P_normal_hit = 1/2 - 1/6 = 2/6 ; P_crit = 1/6
    # E[hits] = 6 * (2/6 + 2 * 1/6) = 6 * 4/6 = 4
    # E[unsaved] = 4 * 1/2 = 2
    weapon = Weapon(name="w", kind="melee", attacks=6, hit=4, wound=4, damage=1,
                    abilities="Crit (2 Hits)")
    defender = _unit(save=7)
    result = expected_weapon_damage(weapon, 1, defender, CombatModifiers())
    assert result == pytest.approx(2.0)


def test_crit_auto_wound_skips_wound_roll():
    # 6 atk, 4+ hit, 6+ wound, save 7. Normal: 6*1/2*1/6 = 0.5
    # Auto-wound: normal_hits=6*2/6=2, crit_hits=6*1/6=1
    # wounds = 2*1/6 + 1 = 1.333..., unsaved = wounds (no save), dmg 1
    weapon = Weapon(name="w", kind="melee", attacks=6, hit=4, wound=6, damage=1,
                    abilities="Crit (Auto-Wound)")
    defender = _unit(save=7)
    result = expected_weapon_damage(weapon, 1, defender, CombatModifiers())
    assert result == pytest.approx(2 * (1/6) + 1)


def test_crit_mortal_bypasses_wound_and_save():
    # crit dmg passe outre save & wound mais subit ward
    weapon = Weapon(name="w", kind="melee", attacks=6, hit=4, wound=6, damage=2,
                    abilities="Crit (Mortal Wounds)")
    defender = _unit(save=2, ward=5)  # save 2+ bloque presque tout, mortels passent
    result = expected_weapon_damage(weapon, 1, defender, CombatModifiers())
    # crit_hits = 1, mortels = 1 * 2 = 2 ; normal_hits = 2, wounds = 2*1/6, save 2+ (5/6) unsaved 1/6
    # normal damage = (2*1/6)*1/6 * 2 ≈ 0.111
    # ward = 5+ → 1 - 2/6 = 4/6 multiplier
    expected = ((2 * (1/6) * (1/6) * 2) + (1 * 2)) * (4/6)
    assert result == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# Moments (moyenne/variance/écart-type) — non-régression vs expected_weapon_damage
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "weapon,defender,mods",
    [
        (Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, rend=0, damage=1),
         _unit(save=4, ward=None), CombatModifiers()),
        (Weapon(name="w", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2),
         _unit(save=4, ward=5), CombatModifiers()),
        (Weapon(name="m", kind="melee", attacks=2, hit=4, wound=4, damage=1),
         _unit(save=7), CombatModifiers(attacker_charged=True)),
        (Weapon(name="w", kind="melee", attacks=1, hit=4, wound=4, damage=1),
         _unit(save=7), CombatModifiers(attacker_all_out_attack=True)),
        (Weapon(name="w", kind="melee", attacks=6, hit=4, wound=4, damage=1, abilities="Crit (2 Hits)"),
         _unit(save=7), CombatModifiers()),
        (Weapon(name="w", kind="melee", attacks=6, hit=4, wound=6, damage=1, abilities="Crit (Auto-Wound)"),
         _unit(save=7), CombatModifiers()),
        (Weapon(name="w", kind="melee", attacks=6, hit=4, wound=6, damage=2, abilities="Crit (Mortal Wounds)"),
         _unit(save=2, ward=5), CombatModifiers()),
    ],
)
def test_weapon_damage_moments_mean_matches_expected_weapon_damage(weapon, defender, mods):
    mean, _var = weapon_damage_moments(weapon, 5, defender, mods)
    assert mean == pytest.approx(expected_weapon_damage(weapon, 5, defender, mods))


def test_weapon_damage_moments_variance_zero_when_deterministic():
    # hit/wound/save tous à 2+ modifié à l'infini n'existe pas, mais un profil
    # "tout ou rien" impossible à rater n'existe pas non plus en 1d6 : on vérifie
    # plutôt la formule binomiale à la main sur un cas simple sans crit.
    # 4 attaques, hit 4+ (1/2), wound 4+ (1/2), save impossible (7+), dmg 3 :
    # p_land = 1/2 * 1/2 * 1 = 1/4 ; par attaque Bernoulli(1/4)*3
    # E[X] = 3/4 ; E[X²] = 9 * 1/4 = 2.25 ; Var(X) = 2.25 - 0.5625 = 1.6875
    # Unité (4 attaques i.i.d.) : mean = 3, var = 4 * 1.6875 = 6.75
    weapon = Weapon(name="w", kind="melee", attacks=4, hit=4, wound=4, damage=3)
    defender = _unit(save=7)
    mean, var = weapon_damage_moments(weapon, 1, defender, CombatModifiers())
    assert mean == pytest.approx(3.0)
    assert var == pytest.approx(6.75)


def test_weapon_damage_moments_2hits_variance():
    # 1 attaque, hit toujours (2+ = 5/6, mais on isole le crit) : ici hit 2+ pour
    # simplifier p_crit = 1/6 = p_hit_min, wound 2+ (5/6), save impossible, dmg 1,
    # Crit (2 Hits). Vérifié contre le calcul manuel E[Y²] = 2p + 2p² (Y = B1+B2).
    weapon = Weapon(name="w", kind="melee", attacks=1, hit=2, wound=2, damage=1,
                    abilities="Crit (2 Hits)")
    defender = _unit(save=7)
    p_hit = 5 / 6
    p_crit = 1 / 6
    p_normal = p_hit - p_crit
    p_land = (5 / 6) * 1.0 * 1.0  # p_wound * p_unsaved * ward_survive
    ex1 = p_normal * p_land + p_crit * 2 * p_land
    ex2 = p_normal * p_land + p_crit * (2 * p_land + 2 * p_land * p_land)
    expected_mean = ex1 * 1
    expected_var = ex2 * 1 - expected_mean ** 2
    mean, var = weapon_damage_moments(weapon, 1, defender, CombatModifiers())
    assert mean == pytest.approx(expected_mean)
    assert var == pytest.approx(expected_var)


def test_unit_damage_moments_sums_independent_weapon_variances():
    w1 = Weapon(name="a", kind="melee", attacks=4, hit=4, wound=4, damage=3, wielders=1)
    w2 = Weapon(name="b", kind="ranged", attacks=4, hit=4, wound=4, damage=3, wielders=1)
    attacker = Unit(
        name="A", army_id=1, move=5, save=4, health=2, control=1,
        models=1, points=100, weapons=[w1, w2],
    )
    defender = _unit(save=7)
    mean, var, std = unit_damage_moments(attacker, 1, defender, CombatModifiers())
    m1, v1 = weapon_damage_moments(w1, 1, defender, CombatModifiers())
    m2, v2 = weapon_damage_moments(w2, 1, defender, CombatModifiers())
    assert mean == pytest.approx(m1 + m2)
    assert var == pytest.approx(v1 + v2)
    assert std == pytest.approx(math.sqrt(v1 + v2))


def test_unit_damage_moments_mean_matches_expected_unit_damage():
    w1 = Weapon(name="a", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=2, wielders=3)
    w2 = Weapon(name="b", kind="ranged", attacks=1, hit=4, wound=4, damage=1, wielders=2)
    attacker = Unit(
        name="A", army_id=1, move=5, save=4, health=2, control=1,
        models=5, points=200, weapons=[w1, w2],
    )
    defender = _unit(save=4, ward=5)
    mods = CombatModifiers(attacker_charged=True)
    mean, _var, _std = unit_damage_moments(attacker, 5, defender, mods)
    assert mean == pytest.approx(expected_unit_damage(attacker, 5, defender, mods))


def test_damage_floor95_basic():
    assert damage_floor95(10.0, 2.0) == pytest.approx(10.0 - 1.6448536269514722 * 2.0)


def test_damage_floor95_clamped_at_zero():
    assert damage_floor95(1.0, 10.0) == 0.0


# --------------------------------------------------------------------------- #
# Bonus intrinsèques Anti-<MOT-CLÉ> / Charge (texte libre, Weapon.abilities)
# --------------------------------------------------------------------------- #

def test_anti_keyword_bonus_active_only_when_defender_has_keyword():
    # 10 atk, 4+ hit, 4+ wound, save 4+, dmg 1, Anti-MONSTER (+1 Rend)
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Anti-MONSTER (+1 Rend)")
    plain = _unit(save=4, keywords=frozenset())
    monster = _unit(save=4, keywords=frozenset({"MONSTER"}))
    dmg_plain = expected_weapon_damage(weapon, 5, plain, CombatModifiers())
    dmg_monster = expected_weapon_damage(weapon, 5, monster, CombatModifiers())
    # rend +1 → save 4+ devient 5+ (2/6 au lieu de 3/6) → plus de dégâts non sauvés
    assert dmg_monster > dmg_plain
    assert dmg_plain == pytest.approx(10 * (1/2) * (1/2) * (1/2))
    assert dmg_monster == pytest.approx(10 * (1/2) * (1/2) * (4/6))


def test_anti_keyword_bonus_absent_without_matching_keyword():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Anti-MONSTER (+1 Rend)")
    hero = _unit(save=4, keywords=frozenset({"HERO"}))  # mot-clé présent mais pas MONSTER
    result = expected_weapon_damage(weapon, 5, hero, CombatModifiers())
    assert result == pytest.approx(10 * (1/2) * (1/2) * (1/2))


def test_charge_ability_bonus_only_from_weapon_text():
    # Pas de bonus universel de charge en AoS4 : seul le texte d'arme compte
    # (ex. Charge (+1 Damage), typique des profils de cavalerie).
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Charge (+1 Damage)")
    defender = _unit(save=7)  # save impossible → tout passe
    base = expected_weapon_damage(weapon, 5, defender, CombatModifiers())
    charged = expected_weapon_damage(weapon, 5, defender, CombatModifiers(attacker_charged=True))
    # base : 10 atk * 1/2 * 1/2 * dmg 1 = 2.5
    # chargé : attaques inchangées (10), seul le dégât par coup augmente : dmg (1+1)=2 → 5.0
    assert base == pytest.approx(2.5)
    assert charged == pytest.approx(5.0)


def test_charge_ability_bonus_inactive_without_charge():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Charge (+1 Hit)")
    defender = _unit(save=7)
    result = expected_weapon_damage(weapon, 5, defender, CombatModifiers())
    assert result == pytest.approx(10 * (1/2) * (1/2) * 1)


def test_expected_unit_damage_uses_loadout_description_when_present():
    # 10 modèles, mais seuls 2 portent l'arme spéciale (description restreinte) :
    # sans description, wielders=0 ferait porter l'arme spéciale par les 10 modèles.
    base = Weapon(name="Warhammer", kind="melee", attacks=2, hit=4, wound=4, damage=1)
    special = Weapon(name="Grandhammer", kind="melee", attacks=2, hit=4, wound=4, damage=2)
    desc = ("<ul><li>Each model is armed with a Warhammer.</li>"
            "<li>2/10 models can replace their Warhammer with a Grandhammer.</li></ul>")
    attacker = Unit(
        name="A", army_id=1, move=5, save=4, health=1, control=1,
        models=10, points=100, description=desc, weapons=[base, special],
    )
    defender = _unit(save=7)
    mods = CombatModifiers()
    result = expected_unit_damage(attacker, 10, defender, mods)
    # 8 modèles Warhammer + 2 modèles Grandhammer (pas 10+10, ni 0 sur l'un des deux)
    expected = (
        expected_weapon_damage(base, 8, defender, mods)
        + expected_weapon_damage(special, 2, defender, mods)
    )
    assert result == pytest.approx(expected)


def test_expected_unit_damage_falls_back_to_wielders_without_description():
    # Sans description, comportement inchangé : wielders pilote l'allocation.
    w1 = Weapon(name="a", kind="melee", attacks=2, hit=4, wound=4, damage=1, wielders=3)
    attacker = Unit(
        name="A", army_id=1, move=5, save=4, health=1, control=1,
        models=10, points=100, weapons=[w1],
    )
    defender = _unit(save=7)
    mods = CombatModifiers()
    result = expected_unit_damage(attacker, 10, defender, mods)
    assert result == pytest.approx(expected_weapon_damage(w1, 3, defender, mods))


def test_anti_keyword_and_charge_moments_match_expected_weapon_damage():
    weapon = Weapon(name="w", kind="melee", attacks=2, hit=4, wound=4, damage=1,
                    abilities="Anti-MONSTER (+1 Rend), Charge (+1 Damage)")
    defender = _unit(save=4, keywords=frozenset({"MONSTER"}))
    mods = CombatModifiers(attacker_charged=True)
    mean, _var = weapon_damage_moments(weapon, 5, defender, mods)
    assert mean == pytest.approx(expected_weapon_damage(weapon, 5, defender, mods))

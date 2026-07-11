"""Calcul du dégât espéré (expected damage) pour AoS 4.

Mécaniques prises en compte :
- Hit / Wound / Save / Rend / Ward
- Critiques (sur jet de touche naturel de 6) : 'Crit (2 Hits)',
  'Crit (Mortal)', 'Crit (Auto-Wound)'
- Modificateurs : All-out Attack (+1 hit), All-out Defense (+1 save),
  Charge (+1 attaque en mêlée)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import Unit, Weapon


@dataclass
class CombatModifiers:
    """Modificateurs pour une direction d'attaque (attaquant vs défenseur)."""
    attacker_all_out_attack: bool = False
    attacker_charged: bool = False
    defender_all_out_defense: bool = False


def _prob_x_plus(x: int, modifier: int = 0) -> float:
    """Probabilité de réussir un X+ sur 1d6 avec modificateur (cap 2+ / impossible >6)."""
    target = max(2, x - modifier)
    if target > 6:
        return 0.0
    return (7 - target) / 6


def _parse_crit(abilities: Optional[str]) -> str:
    """Détecte le type de crit dans le champ abilities (insensible à la casse)."""
    if not abilities:
        return "none"
    s = abilities.lower()
    if "crit (2 hits)" in s or "crit (2hits)" in s:
        return "2hits"
    if "crit (mortal" in s:
        return "mortal"
    if "crit (auto" in s:
        return "autowound"
    return "none"


def expected_weapon_damage(
    weapon: Weapon,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> float:
    """Dégât espéré d'un profil d'arme sur un défenseur.

    `attacker_models` est ici le nombre de porteurs effectifs : seulement les
    modèles équipés de cette arme. Les appelants doivent fournir une valeur
    déjà scalée (voir `expected_unit_damage`).
    """
    bonus_attacks = 1 if (modifiers.attacker_charged and weapon.kind == "melee") else 0
    total_attacks = (weapon.attacks + bonus_attacks) * attacker_models
    if total_attacks <= 0:
        return 0.0

    hit_mod = 1 if modifiers.attacker_all_out_attack else 0
    p_hit = _prob_x_plus(weapon.hit, hit_mod)
    # un 6 naturel est toujours une touche et toujours un crit
    p_crit = min(p_hit, 1.0 / 6.0)
    p_normal_hit = max(0.0, p_hit - p_crit)

    p_wound = _prob_x_plus(weapon.wound)

    save_mod = 1 if modifiers.defender_all_out_defense else 0
    save_eff = defender.save + weapon.rend - save_mod
    if save_eff > 6:
        p_save = 0.0
    else:
        p_save = _prob_x_plus(save_eff)
    p_unsaved = 1.0 - p_save

    ward_mult = 1.0
    if defender.ward is not None:
        ward_mult = 1.0 - _prob_x_plus(defender.ward)

    crit_type = _parse_crit(weapon.abilities)

    if crit_type == "2hits":
        e_hits = total_attacks * (p_normal_hit + 2.0 * p_crit)
        e_wounds = e_hits * p_wound
        e_unsaved = e_wounds * p_unsaved
        return e_unsaved * weapon.damage * ward_mult

    if crit_type == "autowound":
        e_normal_hits = total_attacks * p_normal_hit
        e_crit_hits = total_attacks * p_crit
        e_wounds = e_normal_hits * p_wound + e_crit_hits
        e_unsaved = e_wounds * p_unsaved
        return e_unsaved * weapon.damage * ward_mult

    if crit_type == "mortal":
        e_normal_hits = total_attacks * p_normal_hit
        e_crit_hits = total_attacks * p_crit
        e_normal_unsaved = e_normal_hits * p_wound * p_unsaved
        e_damage_normal = e_normal_unsaved * weapon.damage
        e_damage_mortal = e_crit_hits * weapon.damage   # bypass wound + save
        return (e_damage_normal + e_damage_mortal) * ward_mult

    # standard
    e_hits = total_attacks * p_hit
    e_wounds = e_hits * p_wound
    e_unsaved = e_wounds * p_unsaved
    return e_unsaved * weapon.damage * ward_mult


def expected_unit_damage(
    attacker: Unit,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> float:
    """Dégât total espéré d'une unité attaquante (tous profils d'arme) en 1 round.

    Chaque arme n'est portée que par `weapon.wielders` modèles (taille de base).
    En cas de renforcement (`attacker_models > attacker.models`), le nombre de
    porteurs est scalé proportionnellement. Si `wielders` vaut 0 (legacy / tests),
    on retombe sur le nombre de modèles attaquant total.
    """
    base = max(attacker.models, 1)
    scale = attacker_models / base
    total = 0.0
    for w in attacker.weapons:
        if w.wielders > 0:
            effective = max(1, round(w.wielders * scale))
        else:
            effective = attacker_models
        total += expected_weapon_damage(w, effective, defender, modifiers)
    return total

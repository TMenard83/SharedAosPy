"""Calcul du dégât espéré (expected damage) pour AoS 4.

Mécaniques prises en compte :
- Hit / Wound / Save / Rend / Ward
- Critiques (sur jet de touche naturel de 6) : 'Crit (2 Hits)',
  'Crit (Mortal)', 'Crit (Auto-Wound)'
- Modificateurs : All-out Attack (+1 hit), All-out Defense (+1 save),
  Charge (+1 attaque en mêlée)
- Bonus intrinsèques lus dans le texte libre `Weapon.abilities` (même champ que
  le tag Crit) : `Anti-<MOT-CLÉ> (+N <Stat>)` (actif si le défenseur porte ce
  mot-clé) et `Charge (+N <Stat>)` (actif si l'attaquant a chargé, cumulatif
  avec le bonus universel +1 attaque en mêlée)
"""

from __future__ import annotations

import math
import re
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


_ANTI_RE = re.compile(r"Anti-([A-Za-z ]+?)\s*\(\s*\+(\d+)\s+(\w+)\s*\)", re.IGNORECASE)
_CHARGE_RE = re.compile(r"Charge\s*\(\s*\+(\d+)\s+(\w+)\s*\)", re.IGNORECASE)
_STAT_FIELD = {
    "attacks": "attacks", "atk": "attacks",
    "hit": "hit",
    "wound": "wound", "wounds": "wound",
    "rend": "rend",
    "damage": "damage", "dmg": "damage",
}


@dataclass
class _IntrinsicBonus:
    """Bonus additifs issus du texte d'aptitudes (Anti-<MOT-CLÉ> / Charge)."""

    attacks: int = 0
    hit: int = 0
    wound: int = 0
    rend: int = 0
    damage: int = 0


def _intrinsic_bonus(
    abilities: Optional[str], *, charged: bool, defender_keywords: frozenset[str],
) -> _IntrinsicBonus:
    """Résout les bonus Anti-<MOT-CLÉ>/Charge d'un texte d'aptitudes.

    `Anti-<MOT-CLÉ> (+N <Stat>)` n'est actif que si `defender_keywords` contient
    ce mot-clé ; `Charge (+N <Stat>)` seulement si `charged` (en plus du bonus
    universel +1 attaque en mêlée, géré séparément dans les fonctions de calcul).
    """
    bonus = _IntrinsicBonus()
    if not abilities:
        return bonus
    for keyword, amount, stat in _ANTI_RE.findall(abilities):
        field_name = _STAT_FIELD.get(stat.lower())
        if field_name and keyword.strip().upper() in defender_keywords:
            setattr(bonus, field_name, getattr(bonus, field_name) + int(amount))
    if charged:
        for amount, stat in _CHARGE_RE.findall(abilities):
            field_name = _STAT_FIELD.get(stat.lower())
            if field_name:
                setattr(bonus, field_name, getattr(bonus, field_name) + int(amount))
    return bonus


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
    bonus = _intrinsic_bonus(
        weapon.abilities, charged=modifiers.attacker_charged, defender_keywords=defender.keywords,
    )
    bonus_attacks = 1 if (modifiers.attacker_charged and weapon.kind == "melee") else 0
    total_attacks = (weapon.attacks + bonus_attacks + bonus.attacks) * attacker_models
    if total_attacks <= 0:
        return 0.0

    hit_mod = (1 if modifiers.attacker_all_out_attack else 0) + bonus.hit
    p_hit = _prob_x_plus(weapon.hit, hit_mod)
    # un 6 naturel est toujours une touche et toujours un crit
    p_crit = min(p_hit, 1.0 / 6.0)
    p_normal_hit = max(0.0, p_hit - p_crit)

    p_wound = _prob_x_plus(weapon.wound, bonus.wound)

    save_mod = 1 if modifiers.defender_all_out_defense else 0
    save_eff = defender.save + weapon.rend + bonus.rend - save_mod
    if save_eff > 6:
        p_save = 0.0
    else:
        p_save = _prob_x_plus(save_eff)
    p_unsaved = 1.0 - p_save

    ward_mult = 1.0
    if defender.ward is not None:
        ward_mult = 1.0 - _prob_x_plus(defender.ward)

    dmg = weapon.damage + bonus.damage
    crit_type = _parse_crit(weapon.abilities)

    if crit_type == "2hits":
        e_hits = total_attacks * (p_normal_hit + 2.0 * p_crit)
        e_wounds = e_hits * p_wound
        e_unsaved = e_wounds * p_unsaved
        return e_unsaved * dmg * ward_mult

    if crit_type == "autowound":
        e_normal_hits = total_attacks * p_normal_hit
        e_crit_hits = total_attacks * p_crit
        e_wounds = e_normal_hits * p_wound + e_crit_hits
        e_unsaved = e_wounds * p_unsaved
        return e_unsaved * dmg * ward_mult

    if crit_type == "mortal":
        e_normal_hits = total_attacks * p_normal_hit
        e_crit_hits = total_attacks * p_crit
        e_normal_unsaved = e_normal_hits * p_wound * p_unsaved
        e_damage_normal = e_normal_unsaved * dmg
        e_damage_mortal = e_crit_hits * dmg   # bypass wound + save
        return (e_damage_normal + e_damage_mortal) * ward_mult

    # standard
    e_hits = total_attacks * p_hit
    e_wounds = e_hits * p_wound
    e_unsaved = e_wounds * p_unsaved
    return e_unsaved * dmg * ward_mult


def _effective_counts(attacker: Unit, attacker_models: int) -> list[int]:
    """Nombre de modèles portant chaque profil d'arme, à la taille d'attaque donnée.

    Utilise `loadout.model_counts` (allocation depuis `Unit.description`, texte libre)
    quand `attacker.description` est renseigné — c'est le chemin le plus fidèle,
    typiquement peuplé par l'import Wahapedia (`wahapedia.py`). Sinon retombe sur
    `weapon.wielders` (contraintes BattleScribe, cf. `bsdata.py`), lui-même scalé à
    `attacker_models` si `wielders` vaut 0 (legacy / tests). Dans les deux cas, le
    scaling en cas de renforcement (`attacker_models > attacker.models`) est
    proportionnel, en préservant les comptes nuls (profil non retenu par un choix
    exclusif ou un remplacement).
    """
    base = max(attacker.models, 1)
    scale = attacker_models / base
    if attacker.description:
        from .loadout import model_counts  # import tardif : évite le cycle loadout↔combat

        counts, _notes = model_counts(attacker, attacker.weapons)
        return [max(1, round(c * scale)) if c > 0 else 0 for c in counts]
    result: list[int] = []
    for w in attacker.weapons:
        if w.wielders > 0:
            result.append(max(1, round(w.wielders * scale)))
        else:
            result.append(attacker_models)
    return result


def expected_unit_damage(
    attacker: Unit,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> float:
    """Dégât total espéré d'une unité attaquante (tous profils d'arme) en 1 round.

    Le nombre de porteurs par profil vient de `_effective_counts` (loadout par
    description, ou wielders BattleScribe à défaut).
    """
    counts = _effective_counts(attacker, attacker_models)
    return sum(
        expected_weapon_damage(w, c, defender, modifiers)
        for w, c in zip(attacker.weapons, counts, strict=True)
    )


def weapon_damage_moments(
    weapon: Weapon,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> tuple[float, float]:
    """Espérance et variance des dégâts d'un profil d'arme sur un défenseur.

    Même modèle probabiliste que `expected_weapon_damage` (voir son docstring),
    étendu à `E[D²]` par branche de touche (normale vs critique) pour en tirer
    `Var(D) = E[D²] - E[D]²`. `total_attacks` est un nombre fixe (non aléatoire
    dans ce modèle : `weapon.attacks` est un entier déjà résolu, pas un dé) :
    la variance de l'unité est donc `total_attacks` fois celle d'une attaque.
    """
    bonus = _intrinsic_bonus(
        weapon.abilities, charged=modifiers.attacker_charged, defender_keywords=defender.keywords,
    )
    bonus_attacks = 1 if (modifiers.attacker_charged and weapon.kind == "melee") else 0
    total_attacks = (weapon.attacks + bonus_attacks + bonus.attacks) * attacker_models
    if total_attacks <= 0:
        return 0.0, 0.0

    hit_mod = (1 if modifiers.attacker_all_out_attack else 0) + bonus.hit
    p_hit = _prob_x_plus(weapon.hit, hit_mod)
    p_crit = min(p_hit, 1.0 / 6.0)
    p_normal_hit = max(0.0, p_hit - p_crit)

    p_wound = _prob_x_plus(weapon.wound, bonus.wound)

    save_mod = 1 if modifiers.defender_all_out_defense else 0
    save_eff = defender.save + weapon.rend + bonus.rend - save_mod
    p_save = 0.0 if save_eff > 6 else _prob_x_plus(save_eff)
    p_unsaved = 1.0 - p_save

    ward_survive = 1.0
    if defender.ward is not None:
        ward_survive = 1.0 - _prob_x_plus(defender.ward)

    dmg = float(weapon.damage + bonus.damage)
    # probabilité qu'une touche normale se convertisse en dégâts encaissés (blessure + save + ward)
    p_land = p_wound * p_unsaved * ward_survive
    crit_type = _parse_crit(weapon.abilities)

    if crit_type == "2hits":
        # une touche crit vaut 2 essais indépendants Bernoulli(p_land) : E[Y²] = 2p + 2p² pour Y = B1+B2
        ex1 = p_normal_hit * p_land + p_crit * 2.0 * p_land
        ex2 = p_normal_hit * p_land + p_crit * (2.0 * p_land + 2.0 * p_land * p_land)
    elif crit_type == "autowound":
        p_land_autowound = p_unsaved * ward_survive  # le crit saute le jet de blessure
        ex1 = p_normal_hit * p_land + p_crit * p_land_autowound
        ex2 = ex1  # chaque branche reste un Bernoulli simple (0/1) : E[B²] = E[B]
    elif crit_type == "mortal":
        # le crit saute blessure ET save ; seul le ward peut encore l'arrêter
        ex1 = p_normal_hit * p_land + p_crit * ward_survive
        ex2 = ex1
    else:
        # le 6 non modifié touche normalement (déjà inclus dans p_hit)
        ex1 = p_hit * p_land
        ex2 = ex1

    mean_attack = ex1 * dmg
    var_attack = max(0.0, ex2 * dmg * dmg - mean_attack * mean_attack)

    return total_attacks * mean_attack, total_attacks * var_attack


def unit_damage_moments(
    attacker: Unit,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> tuple[float, float, float]:
    """Espérance, variance et écart-type des dégâts totaux d'une unité (1 round).

    Même `_effective_counts` (loadout ou wielders) que `expected_unit_damage`. Les
    profils d'arme sont des variables indépendantes : les variances s'additionnent.
    """
    counts = _effective_counts(attacker, attacker_models)
    mean_total = 0.0
    var_total = 0.0
    for w, c in zip(attacker.weapons, counts, strict=True):
        m, v = weapon_damage_moments(w, c, defender, modifiers)
        mean_total += m
        var_total += v
    return mean_total, var_total, math.sqrt(var_total)


#: Quantile de la loi normale centrée réduite pour le 20ᵉ centile (couverture 80 %).
_Z80 = 0.8416212335729143


def damage_floor80(mean: float, std: float) -> float:
    """Plancher de dégâts atteint 80 % du temps : `moyenne - z·σ` (≥ 0).

    Approximation normale (somme de nombreuses variables indépendantes ⇒
    raisonnable par le théorème central limite), même formule que StatHammer.
    """
    return max(0.0, mean - _Z80 * std)

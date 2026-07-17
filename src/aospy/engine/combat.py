"""Calcul du dégât espéré (expected damage) pour AoS 4.

Mécaniques prises en compte :
- Hit / Wound / Save / Rend / Ward
- Critiques (sur jet de touche naturel de 6) : 'Crit (2 Hits)',
  'Crit (Mortal)', 'Crit (Auto-Wound)'
- Modificateurs : All-out Attack (+1 hit), All-out Defense (+1 save)
- Bonus intrinsèques lus dans le texte libre `Weapon.abilities` (même champ que
  le tag Crit) : `Anti-<MOT-CLÉ> (+N <Stat>)` (actif si le défenseur porte ce
  mot-clé) et `Charge (+N <Stat>)` (actif si l'attaquant a chargé). En AoS 4 la
  charge ne donne aucun bonus universel : seuls certains profils d'arme
  (typiquement de la cavalerie) portent ce texte, le plus souvent
  `Charge (+1 Damage)` plutôt qu'un bonus d'attaques.
- Règle optionnelle "tir double" (`CombatModifiers.attacker_ranged_double`,
  cf. `orchestration/benchmark.py::DuelRules.double_shoot`) : multiplie par
  `RANGED_DOUBLE_MULT` le dégât espéré des profils `ranged` de l'attaquant,
  la mêlée n'est pas concernée.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from ..domain.models import Unit, Weapon

#: Multiplicateur de la règle optionnelle "tir double" (`CombatModifiers.
#: attacker_ranged_double`) — appliqué aux seuls profils `ranged` de
#: l'attaquant. Historiquement 2.0 (deux tirs), ramené à 1.5 : la règle reste
#: un simple multiplicateur du dégât espéré, plus littéralement "N tirs".
RANGED_DOUBLE_MULT = 1.5


@dataclass
class CombatModifiers:
    """Modificateurs pour une direction d'attaque (attaquant vs défenseur).

    `attacker_ranged_double` : règle optionnelle "tir double"
    (`orchestration/benchmark.py::DuelRules.double_shoot`) — multiplie par
    `RANGED_DOUBLE_MULT` le dégât espéré des profils d'arme `ranged` de
    l'attaquant (mêlée non affectée).
    """
    attacker_all_out_attack: bool = False
    attacker_charged: bool = False
    defender_all_out_defense: bool = False
    attacker_ranged_double: bool = False


def _prob_x_plus(x: int, modifier: int = 0) -> float:
    """Probabilité de réussir un X+ sur 1d6 avec modificateur (cap 2+ / impossible >6)."""
    target = max(2, x - modifier)
    if target > 6:
        return 0.0
    return (7 - target) / 6


#: BSData encode le texte d'aptitudes avec du markup de mise en forme
#: (`**gras**`, `^^exposant^^`, parfois un tiret insécable U+2011 dans "Anti‑X")
#: et Wahapedia avec du HTML (`<span class="kwb">MOT-CLÉ</span>`) : sans nettoyage,
#: `Anti-**^^Infantry^^** (+1 Rend)` ne matche aucune des deux regex ci-dessous
#: (constaté : 118 des 134 unités portant un Anti-X en base n'appliquaient aucun
#: bonus). Idempotent sur du texte déjà propre (tests unitaires).
_MARKUP_RE = re.compile(r"\*\*|\^\^|<[^>]+>")


def _normalize_abilities(abilities: str) -> str:
    """Retire le markup de mise en forme (gras/exposant/HTML) et les espaces/tirets
    insécables du texte libre `Weapon.abilities`, avant tout matching par regex."""
    text = _MARKUP_RE.sub("", abilities)
    return text.replace("‑", "-").replace("\xa0", " ")


def _parse_crit(abilities: Optional[str]) -> str:
    """Détecte le type de crit dans le champ abilities (insensible à la casse)."""
    if not abilities:
        return "none"
    s = _normalize_abilities(abilities).lower()
    if "crit (2 hits)" in s or "crit (2hits)" in s:
        return "2hits"
    if "crit (mortal" in s:
        return "mortal"
    if "crit (auto" in s:
        return "autowound"
    return "none"


def weapon_crit_type(abilities: Optional[str]) -> str:
    """Alias public de `_parse_crit`, pour un usage hors de ce module (ex. le
    vecteur de caractéristiques du modèle de coût, `analysis/features.py`)."""
    return _parse_crit(abilities)


def _has_no_wound_roll(abilities: Optional[str]) -> bool:
    """Détecte la règle spéciale « pas de jet pour blesser » dans `Weapon.abilities` :
    chaque touche inflige directement le dégât du profil en blessures mortelles —
    saute blessure ET save (le ward peut encore l'arrêter). Ex. Warp Lightning
    Cannon (« Each hit inflicts 1 mortal damage on the target and the attack
    sequence ends. ») : contrairement à `Crit (Mortal)`, qui ne s'applique qu'aux
    touches critiques (6 naturel), cette règle s'applique à *toutes* les touches
    — il n'y a jamais de jet pour blesser du tout sur ce profil."""
    if not abilities:
        return False
    return "no wound roll" in _normalize_abilities(abilities).lower()


_ANTI_RE = re.compile(r"Anti-([A-Za-z ]+?)\s*\(\s*\+(\d+)\s+(\w+)\s*\)", re.IGNORECASE)
#: Lookbehind négatif : exclut `Anti-charge (+N Rend)` (mot-clé "CHARGE", bonus vs
#: un défenseur qui a chargé — état non modélisé côté défenseur, cf. docstring de
#: `_intrinsic_bonus`) qui sinon matcherait comme le bonus de charge de l'attaquant
#: lui-même, alors que ce sont deux mécaniques distinctes.
_CHARGE_RE = re.compile(r"(?<!anti-)Charge\s*\(\s*\+(\d+)\s+(\w+)\s*\)", re.IGNORECASE)
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
    ce mot-clé ; `Charge (+N <Stat>)` seulement si `charged`. Il n'y a pas de
    bonus de charge universel en AoS 4 : c'est ce texte d'arme qui porte
    l'intégralité du bonus (souvent +1 dégât sur des profils de cavalerie).

    Cas particulier : `Anti-charge (+N <Stat>)` (mot-clé "CHARGE") vise un
    défenseur qui a chargé ce combat, un état que `CombatModifiers` ne modélise
    que côté attaquant (`attacker_charged`) — cette clause matche donc bien
    `_ANTI_RE` (elle ne se déclenche jamais, faute de mot-clé "CHARGE" dans
    `Unit.keywords`) mais n'applique aucun bonus, plutôt que de se faire
    absorber à tort par `_CHARGE_RE` comme le bonus de charge de l'attaquant.
    """
    bonus = _IntrinsicBonus()
    if not abilities:
        return bonus
    text = _normalize_abilities(abilities)
    for keyword, amount, stat in _ANTI_RE.findall(text):
        field_name = _STAT_FIELD.get(stat.lower())
        if field_name and keyword.strip().upper() in defender_keywords:
            setattr(bonus, field_name, getattr(bonus, field_name) + int(amount))
    if charged:
        for amount, stat in _CHARGE_RE.findall(text):
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
    total_attacks = (weapon.attacks + bonus.attacks) * attacker_models
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

    #: Règle optionnelle "tir double" (`DuelRules.double_shoot`) : ne
    #: multiplie que les profils `ranged`, la mêlée n'est pas concernée.
    ranged_mult = RANGED_DOUBLE_MULT if modifiers.attacker_ranged_double and weapon.kind == "ranged" else 1.0

    if _has_no_wound_roll(weapon.abilities):
        # pas de jet pour blesser : chaque touche saute blessure ET save (le ward peut encore l'arrêter)
        e_hits = total_attacks * p_hit
        return e_hits * dmg * ward_mult * ranged_mult

    if crit_type == "2hits":
        e_hits = total_attacks * (p_normal_hit + 2.0 * p_crit)
        e_wounds = e_hits * p_wound
        e_unsaved = e_wounds * p_unsaved
        return e_unsaved * dmg * ward_mult * ranged_mult

    if crit_type == "autowound":
        e_normal_hits = total_attacks * p_normal_hit
        e_crit_hits = total_attacks * p_crit
        e_wounds = e_normal_hits * p_wound + e_crit_hits
        e_unsaved = e_wounds * p_unsaved
        return e_unsaved * dmg * ward_mult * ranged_mult

    if crit_type == "mortal":
        e_normal_hits = total_attacks * p_normal_hit
        e_crit_hits = total_attacks * p_crit
        e_normal_unsaved = e_normal_hits * p_wound * p_unsaved
        e_damage_normal = e_normal_unsaved * dmg
        e_damage_mortal = e_crit_hits * dmg   # bypass wound + save
        return (e_damage_normal + e_damage_mortal) * ward_mult * ranged_mult

    # standard
    e_hits = total_attacks * p_hit
    e_wounds = e_hits * p_wound
    e_unsaved = e_wounds * p_unsaved
    return e_unsaved * dmg * ward_mult * ranged_mult


#: Cible de référence utilisée pour classer des profils d'arme entre eux (rend
#: modéré, comme le CV) — partagée par `loadout.py` (choix exclusifs décrits en
#: texte libre) et `importers/bsdata.py` (choix exclusifs portés par une
#: contrainte BSData sur un `selectionEntryGroup`).
REFERENCE_SAVE = 4


def reference_expected_damage(weapons: list[Weapon]) -> list[float]:
    """Dégâts attendus par profil (1 porteur) contre la cible de référence.

    Sert uniquement à départager des profils d'arme entre eux (choix exclusif),
    pas à produire un résultat de duel réel — d'où la cible fixe `REFERENCE_SAVE`
    plutôt qu'un vrai défenseur.
    """
    probe = Unit(
        name="_probe", army_id=0, move=0, save=REFERENCE_SAVE, health=1, control=0,
        models=1, points=0,
    )
    mods = CombatModifiers()
    out: list[float] = []
    for w in weapons:
        try:
            out.append(expected_weapon_damage(w, 1, probe, mods))
        except Exception:
            out.append(0.0)
    return out


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
    total_attacks = (weapon.attacks + bonus.attacks) * attacker_models
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

    if _has_no_wound_roll(weapon.abilities):
        # pas de jet pour blesser : chaque touche est un Bernoulli(ward_survive) direct
        ex1 = p_hit * ward_survive
        ex2 = ex1
    elif crit_type == "2hits":
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

    #: Règle optionnelle "tir double" (`DuelRules.double_shoot`), profils
    #: `ranged` uniquement : la moyenne ET la variance sont multipliées par
    #: `RANGED_DOUBLE_MULT` (pas la variance au carré qu'on aurait en mettant
    #: à l'échelle une seule variable aléatoire par une constante) — exact
    #: pour une somme de tirages i.i.d. (le cas historique ×2 = 2 tirs),
    #: traité ici comme un simple multiplicateur au-delà de ce cas entier.
    ranged_mult = RANGED_DOUBLE_MULT if modifiers.attacker_ranged_double and weapon.kind == "ranged" else 1.0

    return total_attacks * mean_attack * ranged_mult, total_attacks * var_attack * ranged_mult


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


#: Quantiles de la loi normale centrée réduite (couverture 66 %/80 %/95 %, borne inférieure).
#: NB : conservées uniquement pour comparaison avec `distribution_floor` (approximation
#: gaussienne historique) — la lecture des planchers en production passe désormais par
#: la distribution exacte ci-dessous (`orchestration/benchmark.py::_attack_damage`).
_Z66 = 0.41246312944140484
_Z80 = 0.8416212335729143
_Z95 = 1.6448536269514722


def _damage_floor(mean: float, std: float, z: float) -> float:
    """Plancher de dégâts `moyenne - z·σ` (≥ 0), approximation normale (somme de
    nombreuses variables indépendantes ⇒ raisonnable par le théorème central limite).

    Approximation : la vraie distribution des dégâts est discrète, bornée à 0 et
    souvent asymétrique (peu d'attaques à fort dégât, probabilités extrêmes) — voir
    `distribution_floor` pour la lecture exacte du même plancher, sans hypothèse de
    normalité.
    """
    return max(0.0, mean - z * std)


def damage_floor95(mean: float, std: float) -> float:
    """Plancher de dégâts atteint 95 % du temps, même formule que StatHammer.

    Approximation gaussienne, voir `_damage_floor`. Équivalent exact :
    `distribution_floor(unit_damage_distribution(...), 0.95)`.
    """
    return _damage_floor(mean, std, _Z95)


def damage_floor80(mean: float, std: float) -> float:
    """Plancher de dégâts atteint 80 % du temps : lecture pessimiste plus permissive
    que `damage_floor95` (z plus petit ⇒ plus proche de la moyenne).

    Approximation gaussienne, voir `_damage_floor`. Équivalent exact :
    `distribution_floor(unit_damage_distribution(...), 0.80)`.
    """
    return _damage_floor(mean, std, _Z80)


def damage_floor66(mean: float, std: float) -> float:
    """Plancher de dégâts atteint 66 % du temps : lecture pessimiste la plus permissive
    des trois planchers (z le plus petit ⇒ le plus proche de la moyenne).

    Approximation gaussienne, voir `_damage_floor`. Équivalent exact :
    `distribution_floor(unit_damage_distribution(...), 0.66)`.
    """
    return _damage_floor(mean, std, _Z66)


# ---------------------------------------------------------------------------
# Distribution exacte (convolution) — remplace l'approximation gaussienne
# ci-dessus pour la lecture des planchers de dégâts.
# ---------------------------------------------------------------------------
#
# Chaque attaque individuelle est un tirage indépendant sur un petit nombre
# d'issues discrètes (raté / touche normale / touche critique, cf. les branches
# de `weapon_damage_moments`), chacune valant 0, `dmg` ou `2×dmg` dégâts. Comme
# `total_attacks` est un entier fixe (pas un dé, `Weapon.attacks` est déjà résolu
# à l'import), la distribution exacte des dégâts d'un profil d'arme est la loi
# de la somme de `total_attacks` tirages i.i.d. de cette petite loi — calculable
# par auto-convolution, sans aucune hypothèse de normalité. Les profils d'arme
# étant indépendants (cf. `unit_damage_moments`), on convolue ensuite leurs PMF
# pour obtenir la distribution totale de l'unité.


def _convolve(a: list[float], b: list[float]) -> list[float]:
    """Produit de convolution discret de deux lois de probabilité (index = valeur
    entière, résultat de longueur `len(a) + len(b) - 1`)."""
    result = [0.0] * (len(a) + len(b) - 1)
    for i, pa in enumerate(a):
        if pa == 0.0:
            continue
        for j, pb in enumerate(b):
            if pb:
                result[i + j] += pa * pb
    return result


def weapon_damage_distribution(
    weapon: Weapon,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> list[float]:
    """PMF exacte des dégâts d'un profil d'arme sur un défenseur : `resultat[d]` =
    probabilité d'infliger exactement `d` dégâts avec ce profil.

    Même modèle probabiliste que `weapon_damage_moments` (voir sa docstring) —
    mêmes branches crit (`2hits`/`autowound`/`mortal`/`no wound roll`/standard) —
    mais construit toute la distribution par auto-convolution de la loi d'une
    attaque individuelle sur les `total_attacks` tirages i.i.d, plutôt que ses
    deux premiers moments seulement. Sert de brique à `distribution_floor`.
    """
    bonus = _intrinsic_bonus(
        weapon.abilities, charged=modifiers.attacker_charged, defender_keywords=defender.keywords,
    )
    total_attacks = (weapon.attacks + bonus.attacks) * attacker_models
    if total_attacks <= 0:
        return [1.0]

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

    dmg = weapon.damage + bonus.damage
    if dmg <= 0:
        return [1.0]

    p_land = p_wound * p_unsaved * ward_survive
    crit_type = _parse_crit(weapon.abilities)

    #: PMF d'une seule attaque, exprimée en « paliers de touche réussie »
    #: (1 palier = 1 touche qui passe blessure/save/ward, valant `dmg` dégâts ;
    #: 2 paliers pour la branche `2hits`, dont le crit vaut deux essais indépendants).
    if _has_no_wound_roll(weapon.abilities):
        p = p_hit * ward_survive
        per_attack = [1.0 - p, p]
    elif crit_type == "2hits":
        p0 = (1.0 - p_hit) + p_normal_hit * (1.0 - p_land) + p_crit * (1.0 - p_land) ** 2
        p1 = p_normal_hit * p_land + p_crit * 2.0 * p_land * (1.0 - p_land)
        p2 = p_crit * p_land * p_land
        per_attack = [p0, p1, p2]
    elif crit_type == "autowound":
        p_land_autowound = p_unsaved * ward_survive
        p = p_normal_hit * p_land + p_crit * p_land_autowound
        per_attack = [1.0 - p, p]
    elif crit_type == "mortal":
        p = p_normal_hit * p_land + p_crit * ward_survive
        per_attack = [1.0 - p, p]
    else:
        p = p_hit * p_land
        per_attack = [1.0 - p, p]

    #: Règle optionnelle "tir double" (`DuelRules.double_shoot`), profils `ranged`
    #: uniquement : contrairement à `weapon_damage_moments` (qui multiplie
    #: directement moyenne/variance — une approximation au-delà du cas entier ×2),
    #: la distribution exacte modélise le multiplicateur comme des tirages
    #: supplémentaires — exact pour ×2 (le cas historique : deux salves), extension
    #: raisonnable pour tout autre multiplicateur non entier.
    ranged_mult = RANGED_DOUBLE_MULT if modifiers.attacker_ranged_double and weapon.kind == "ranged" else 1.0
    attack_count = round(total_attacks * ranged_mult)

    result = [1.0]
    for _ in range(attack_count):
        result = _convolve(result, per_attack)

    #: Ré-espace le support de « nombre de paliers » (indices 0..len(result)-1)
    #: vers « dégâts réels » (multiples de `dmg`), pour pouvoir ensuite convoluer
    #: avec la PMF d'autres profils d'arme portant un `dmg` différent.
    damage_pmf = [0.0] * ((len(result) - 1) * dmg + 1)
    for k, prob in enumerate(result):
        damage_pmf[k * dmg] = prob
    return damage_pmf


def unit_damage_distribution(
    attacker: Unit,
    attacker_models: int,
    defender: Unit,
    modifiers: CombatModifiers,
) -> list[float]:
    """PMF exacte des dégâts totaux d'une unité (tous profils, 1 round) : convolution
    des PMF indépendantes de chaque profil d'arme (`weapon_damage_distribution`).

    Même `_effective_counts` (loadout ou wielders) que `unit_damage_moments`, mais
    lecture exacte de la distribution plutôt que ses deux premiers moments seulement.
    """
    counts = _effective_counts(attacker, attacker_models)
    total_pmf = [1.0]
    for w, c in zip(attacker.weapons, counts, strict=True):
        total_pmf = _convolve(total_pmf, weapon_damage_distribution(w, c, defender, modifiers))
    return total_pmf


def distribution_floor(pmf: list[float], coverage: float) -> float:
    """Plus grand dégât `d` tel que P(dégâts ≥ d) ≥ `coverage` : lecture *exacte*
    du quantile inverse sur la distribution complète — remplace l'approximation
    gaussienne `_damage_floor`/`mean - z·σ`, sans hypothèse de normalité.
    """
    survival = 0.0
    for d in range(len(pmf) - 1, -1, -1):
        survival += pmf[d]
        if survival >= coverage - 1e-9:
            return float(d)
    return 0.0

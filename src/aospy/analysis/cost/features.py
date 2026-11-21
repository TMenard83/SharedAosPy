"""Vecteur de caractéristiques par unité — socle du modèle de coût.

Port du principe de StatHammer (voir son `features.py`) sur le modèle de données
natif d'aospy : chaque unité est sondée offensivement contre trois défenseurs
synthétiques (save 2+, save 4+, save 6+) pour capter à la fois la magnitude
brute des dégâts et la sensibilité au rend, en réutilisant le moteur de
`combat.py` (`unit_damage_moments`) — aucun calcul de dés n'est réécrit ici.

Simplifications assumées par rapport à StatHammer, dues au schéma aospy :

* pas de dés dans les caractéristiques (`Weapon.attacks`/`damage` sont des
  entiers déjà résolus par l'import BSData) : `dmg_cv_vs_save4` ne capte que
  l'aléa hit/wound/save/ward, pas une éventuelle variabilité d'attaques/dégâts
  en dés (perdue à l'import) ;
* `move`/`control` sont déjà des entiers propres (pas de texte à parser) ;
* la répartition mêlée/distance vient directement de `Weapon.kind`, pas d'un
  parsing de texte (`Weapon.kind` distingue déjà "melee"/"ranged") ;
* pas d'axe « puissance d'aptitudes » général (aucun texte d'aptitude par unité en
  base) — sauf pour les profils sorciers/prêtres : `wizard_level`/`priest_level`
  extraient le `WIZARD (N)`/`PRIEST (N)` que BSData capture tel quel dans
  `Unit.keywords` (seule `WARD (N+)` y est traitée à part par l'import), un proxy
  ponctuel mais direct de cet axe pour ces deux mots-clés précis.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass

import duckdb

from ...domain.models import Unit
from ...engine.combat import (
    CombatModifiers,
    effective_counts,
    unit_damage_moments,
    weapon_crit_type,
    weapon_damage_moments,
)
from ...persistence.repository import load_all_units_with_weapons

#: Repère les mots-clés `WIZARD (N)`/`PRIEST (N)` (BSData les capture tels quels
#: dans `Unit.keywords` — seule `WARD (N+)` est traitée à part comme pseudo-catégorie).
_CASTER_RE = re.compile(r"^(WIZARD|PRIEST) \((\d+)\)$")

#: Catégories de "type d'unité" AoS4 — quasi mutuellement exclusives (une unité
#: porte normalement exactement l'une de ces cinq, cf. audit sur la base BSData :
#: INFANTRY+CAVALRY+MONSTER+WAR MACHINE+BEAST ≈ nombre total d'unités).
_UNIT_TYPE_KEYWORDS: tuple[str, ...] = ("INFANTRY", "CAVALRY", "MONSTER", "WAR MACHINE", "BEAST")


def _caster_level(keywords: frozenset[str], kind: str) -> int:
    """Niveau de lanceur (nombre de sorts/prières castables), 0 si absent.

    Proxy direct de la puissance d'aptitudes pour les seuls profils sorciers/prêtres
    (aospy ne stocke pas le texte des aptitudes en général — voir la note de module) :
    un `Wizard (2)` coûte structurellement plus cher qu'un profil de combat identique
    sans incantation, et le modèle de coût était jusqu'ici aveugle à ce facteur.
    """
    best = 0
    for kw in keywords:
        m = _CASTER_RE.match(kw)
        if m and m.group(1) == kind:
            best = max(best, int(m.group(2)))
    return best


def unit_type_of(keywords: frozenset[str]) -> str:
    """Type d'unité (INFANTRY/CAVALRY/MONSTER/WAR MACHINE/BEAST), "OTHER" si aucun ne matche."""
    for t in _UNIT_TYPE_KEYWORDS:
        if t in keywords:
            return t
    return "OTHER"

#: Héros porte-étendard / porte-icône : contrôle 5 quel que soit leur profil (reconnus par
#: le nom faute de mot-clé dédié en base — à compléter quand un nouveau battletome en ajoute).
_BANNER_NAME_RE = re.compile(r"Vexillor|secrator|Bannerblade|Astrolith|banna|Battlesmith")
#: Unités assimilées à un monstre pour le contrôle sans en porter le mot-clé (gabarit du socle).
_MONSTER_LIKE_NAMES: frozenset[str] = frozenset({"Loonboss on Giant Cave Squig"})


def expected_control(unit: Unit) -> int:
    """Contrôle « tacite » d'un profil, selon la règle de conception reconstruite de GW.

    Validée avec l'utilisateur (2026-11-19) puis par régression : ce contrôle attendu ne se
    paie PAS (non significatif), seul l'écart à cette règle se paie — cf.
    `UnitFeatures.control_bonus`/`control_deficit` et `analysis/cost/experiments/control_profile.py`.

    * plusieurs figurines : 1 sous 5 PV/figurine, 2 jusqu'à 6, 3 à 7, 5 au-delà ; Ogors : 2 dès
      4 PV ; équipe de héros : 2 au minimum (machines multi-figurines comprises, même règle) ;
    * une figurine : mot-clé BEAST → 1 (héros : 2) ; MONSTER (ou assimilé) → 5, Gargant non
      LITTLE et monstre Ogor → 10 ; porte-étendard → 5 ; héros Ogor à pied → 3 ; WAR MACHINE →
      2 sous 12 PV, 5 au-delà ; autre héros → 2 sous 10 PV, 5 au-delà ; autre → 2 sous 12 PV, 5.

    Les héros montés/sur char à 10-12 PV et contrôle 2 restent volontairement en *déficit*
    (meilleur ajustement qu'une exception dédiée). Bonus restants attendus : figurines
    épiques (10-15) et quelques personnages nommés « leaders » du lore.
    """
    kw, hp, hero = unit.keywords, unit.health, unit.is_hero
    ogor = "OGOR MAWTRIBES" in kw
    if unit.models > 1:
        if ogor and 4 <= hp < 7:
            ctl = 2
        else:
            ctl = 1 if hp < 5 else 2 if hp < 7 else 3 if hp < 8 else 5
        return max(ctl, 2) if hero else ctl
    if "BEAST" in kw:
        return 2 if hero else 1
    if "MONSTER" in kw or unit.name in _MONSTER_LIKE_NAMES:
        if ogor or ("SONS OF BEHEMAT" in kw and "LITTLE" not in kw):
            return 10
        return 5
    if hero and _BANNER_NAME_RE.search(unit.name):
        return 5
    if hero and ogor and "INFANTRY" in kw:
        return 3
    if "WAR MACHINE" in kw:
        return 2 if hp < 12 else 5
    if hero:
        return 2 if hp < 10 else 5
    return 2 if hp < 12 else 5


#: Défenseurs synthétiques pour la sonde offensive. Save 6+ = pire sauvegarde native
#: existant réellement en AoS4 — il n'y a pas de "aucune save" comme stat native du jeu
#: (le save 7 utilisé auparavant ici, convention empruntée à StatHammer, ne correspond à
#: aucune unité jouable) ; ward toujours absent : on veut mesurer l'attaquant, pas la défense.
_PROBE_SAVE2 = Unit(name="_probe", army_id=0, move=0, save=2, health=1, control=0, models=1, points=0)
_PROBE_SAVE4 = Unit(name="_probe", army_id=0, move=0, save=4, health=1, control=0, models=1, points=0)
_PROBE_SAVE6 = Unit(name="_probe", army_id=0, move=0, save=6, health=1, control=0, models=1, points=0)

_NO_MODS = CombatModifiers()
_CHARGED_MODS = CombatModifiers(attacker_charged=True)

#: Rend "représentatif" supposé par `compute_effective_wounds` pour dégrader la save nue avant de
#: calculer sa probabilité de succès. `combat.py` calcule toujours `save_eff = defender.save +
#: weapon.rend` face à un attaquant précis ; `effective_wounds` n'a pas d'attaquant (c'est une
#: caractéristique du seul défenseur) et supposait jusqu'ici Rend 0 — optimiste, puisque la
#: quasi-totalité des profils d'arme de la base portent du Rend (moyenne pondérée par profil :
#: 0,98 mêlée / 1,05 tir). Le Ward, lui, n'a besoin d'aucun ajustement analogue : contrairement
#: à la save, il n'est jamais modifié par le Rend (règle AoS core). Valeur choisie par balayage
#: entier 0-3 sur le modèle de coût complet (R² ajusté : 0,9175 / 0,9204 / 0,9199 / 0,9169) —
#: cf. `analysis/cost/experiments/effective_wounds_rend.py`.
_REPRESENTATIVE_REND = 1


@dataclass(frozen=True)
class UnitFeatures:
    """Vecteur de caractéristiques d'une unité, prêt pour la régression de coût."""

    unit_id: int | None
    army_id: int
    name: str
    points: int
    is_hero: bool

    dmg_vs_save2: float
    dmg_vs_save4: float
    dmg_vs_save6: float
    dmg_melee_vs_save6: float  # pool de dégâts bruts (avant save/ward) des seuls profils
    # de mêlée — cf. `dmg_ranged_vs_save6`, même sonde save6+ mais côté cac. Avec
    # `dmg_ranged_vs_save6`, permet de scinder `dmg_vs_save6` en deux pools tir/cac plutôt
    # que de traiter le tir comme un delta sur un total déjà mêlée+tir — cf.
    # `analysis/cost/experiments/melee_ranged_split.py`.
    dmg_ranged_vs_save6: float
    dmg_melee_vs_save2: float  # même scission tir/cac que ci-dessus, mais côté pool perçant
    # (sonde save2+) plutôt que pool brut (save6+) — cf. `dmg_ranged_vs_save2`.
    dmg_ranged_vs_save2: float
    dmg_pen: float  # dmg_vs_save2 / dmg_vs_save6 (0 si dmg_vs_save6 == 0)
    dmg_vs_save2_sq: float  # dmg_vs_save2² — terme quadratique : au-delà d'un certain seuil,
    # chaque dégât perçant supplémentaire vaut structurellement plus (rendements croissants,
    # pas décroissants) que ne le capte le terme linéaire seul. Cf.
    # `analysis/cost/experiments/durability_and_saturation.py`, gain R² ajusté +0.0040 seul.
    dmg_cv_vs_save4: float  # écart-type / moyenne contre save4 (fiabilité offensive)
    charge_bonus_save2: float  # supplément de dmg_vs_save2 apporté par un `Charge (+N <Stat>)`
    # (0 si l'unité n'a aucun profil d'arme avec ce texte) — sans ce champ, ce bonus était
    # invisible au modèle de coût (les sondes ci-dessous ne simulent jamais une charge).
    # Magnitude, pas simple indicateur de présence : cf. `analysis/cost/experiments/weapon_tags.py`,
    # même constat que `dmg_pen`→`dmg_vs_save2` (la magnitude explique le prix, pas la
    # présence — `has_charge` seul n'était pas significatif, p=0.150 vs p=0.001 en magnitude).
    # `Anti-<MOT-CLÉ>` a été testé dans le même essai et écarté : ni la présence
    # (`has_anti`, p=0.500) ni la magnitude (`anti_bonus_save2`, p=0.83-0.91) n'étaient
    # significatives, contre un défenseur sonde portant tous les mots-clés jamais visés
    # par un Anti-X dans la base — GW ne semble pas facturer ce tag séparément.

    wounds_total: int  # health * models
    save_num: int
    ward_num: int  # ward, ou 7 si aucun ward
    effective_wounds: float  # wounds_total / P(un coup passe la save ET le ward) — combine les
    # trois caractéristiques ci-dessus en un seul indice de durabilité "nombre de coups qu'il
    # faut effectivement porter pour tuer l'unité", au lieu de les traiter comme trois effets
    # additifs indépendants. Remplace wounds_total/save_num/ward_num dans
    # `cost_model.MODEL_FEATURES` (ils restent ici comme caractéristiques brutes, utiles
    # hors régression) — cf. `analysis/cost/experiments/durability_and_saturation.py`, gain R²
    # ajusté +0.0067 seul (+0.0105 combiné à `dmg_vs_save2_sq` et à l'interaction héros).
    # La probabilité de save est dégradée par `_REPRESENTATIVE_REND` avant ce calcul (le Ward
    # reste nu) — cf. `analysis/cost/experiments/effective_wounds_rend.py`, gain R² ajusté +0.0029.

    move: int
    control: int
    control_expected: int  # contrôle « tacite » du profil (`expected_control`) — ne se paie pas
    control_bonus: int     # max(0, control − attendu) : figurines épiques, leaders nommés — se paie
    control_deficit: int   # max(0, attendu − control) : héros montés/sur char, Celestant-Prime…
    unit_size: int  # models
    unit_size_sq: int  # unit_size² — terme quadratique : rendement croissant sur la taille
    # d'unité, symétrique de `dmg_vs_save2_sq` sur le pool perçant. Une fois ce terme ajouté,
    # le coefficient linéaire de `unit_size` devient franchement négatif (rabais de volume
    # marqué), compensé par le carré positif au-delà d'une dizaine de modèles — GW semble
    # facturer une prime sur les très grosses hordes (contrôle d'objectif, difficulté à les
    # effacer), pas seulement un rabais continu. Cf.
    # `analysis/cost/experiments/unit_size_saturation.py`, gain R² ajusté +0.0009, robuste au
    # retrait des unités à 20 modèles (les plus grosses de la base).

    grand_alliance: str  # résolu par `all_features` (nécessite la DB) ; gardé comme métadonnée,
    # mais absorbé par `army_name` dans `cost_model.CATEGORICAL_FEATURES` (armée ⊂ alliance,
    # les deux ensemble seraient colinéaires — cf. `analysis/cost/experiments/army_factor.py`)
    army_name: str  # facteur catégoriel plus fin que grand_alliance, résolu par `all_features`
    weapon_mix: str  # "melee" / "ranged" / "mixed" — facteur catégoriel dérivé des profils d'arme

    unit_type: str  # INFANTRY / CAVALRY / MONSTER / WAR MACHINE / BEAST / OTHER, cf. unit_type_of
    is_flying: bool  # mot-clé FLY
    wizard_level: int  # WIZARD (N), 0 si aucun
    priest_level: int  # PRIEST (N), 0 si aucun
    is_unique: bool  # mot-clé UNIQUE — proxy grossier de la prime "aptitudes/narratif" d'un
    # personnage nommé, qu'aospy ne modélise pas autrement (pas de texte d'aptitude en base) ;
    # cf. `analysis/cost/experiments/unique_factor.py`, +16.6 pts significatif (p<0.001)
    crit_type: str  # type de Crit (none/2hits/mortal/autowound) du profil d'arme qui contribue
    # le plus à dmg_vs_save2 (proxy du "crit dominant" d'une unité multi-profils) — significatif
    # au-delà de la magnitude de dégât déjà captée par dmg_vs_save2 : cf.
    # `analysis/cost/experiments/weapon_tags.py` (autowound +17.1 pts, mortal -15.9 pts vs 2hits, p<0.05)


def _ranged_only(unit: Unit) -> Unit:
    """Copie de `unit` ne conservant que ses profils d'arme à distance.

    Ne pas passer cette copie au moteur pour mesurer le tir d'une unité : ses choix
    exclusifs d'armement y seraient résolus sans les armes de mêlée — utiliser
    `weapon_damages`. Gardée pour les scripts d'expérience qui l'importent."""
    return dataclasses.replace(unit, weapons=[w for w in unit.weapons if w.kind == "ranged"])


def _melee_only(unit: Unit) -> Unit:
    """Copie de `unit` ne conservant que ses profils d'arme de mêlée (même réserve que `_ranged_only`)."""
    return dataclasses.replace(unit, weapons=[w for w in unit.weapons if w.kind == "melee"])


def weapon_damages(unit: Unit, probe: Unit, mods: CombatModifiers = _NO_MODS) -> list[float]:
    """Dégâts moyens d'un round de chaque profil d'arme, porteurs répartis sur l'unité ENTIÈRE.

    Ne pas mesurer un sous-ensemble d'armes en le passant seul au moteur : les choix exclusifs
    (« 1/3 models must be armed with 1 of the following ») y seraient résolus par sous-ensemble,
    chaque moitié prenant sa meilleure option — Stormfiends : mêlée + tir = 21,5 pour 14,2 au total."""
    counts = effective_counts(unit, unit.models)
    return [weapon_damage_moments(w, c, probe, mods)[0] for w, c in zip(unit.weapons, counts)]


def _damage_of_kind(unit: Unit, kind: str, probe: Unit) -> float:
    return sum(d for w, d in zip(unit.weapons, weapon_damages(unit, probe)) if w.kind == kind)


def dominant_crit_type(unit: Unit) -> str:
    """Type de Crit du profil d'arme qui contribue le plus à `dmg_vs_save2` — proxy du
    "crit dominant" d'une unité à profils d'arme multiples (chacun peut porter un Crit
    différent). "none" si l'unité n'a aucune arme ou aucun Crit. Un profil écarté par un
    choix exclusif (0 porteur) ne compte pas."""
    best_type = "none"
    best_dmg = -1.0
    for w, dmg in zip(unit.weapons, weapon_damages(unit, _PROBE_SAVE2)):
        if dmg > best_dmg:
            best_dmg = dmg
            best_type = weapon_crit_type(w.abilities)
    return best_type


def compute_effective_wounds(wounds_total: int, save_num: int, ward_num: int) -> float:
    """PV totaux normalisés par la probabilité qu'un coup passe la save ET le ward —
    "nombre de coups qu'il faut effectivement porter pour tuer l'unité", plutôt que
    trois effets additifs séparés (cf. note de `UnitFeatures.effective_wounds`). La save
    est dégradée par `_REPRESENTATIVE_REND` (le Ward, jamais modifié par le Rend, ne l'est
    pas)."""
    save_eff = min(save_num + _REPRESENTATIVE_REND, 7)
    p_save = max(0.0, (7 - save_eff) / 6.0)
    p_ward = max(0.0, (7 - ward_num) / 6.0) if ward_num <= 6 else 0.0
    p_fail = (1 - p_save) * (1 - p_ward)
    return wounds_total / p_fail if p_fail > 0 else wounds_total * 6.0


def compute_features(unit: Unit) -> UnitFeatures:
    """Calcule le vecteur de caractéristiques d'une unité (cœur pur, sans DB)."""
    mean2, _v2, _s2 = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, _NO_MODS)
    mean4, var4, _s4 = unit_damage_moments(unit, unit.models, _PROBE_SAVE4, _NO_MODS)
    mean6, _v6, _s6 = unit_damage_moments(unit, unit.models, _PROBE_SAVE6, _NO_MODS)
    mean2_charged, _v2c, _s2c = unit_damage_moments(unit, unit.models, _PROBE_SAVE2, _CHARGED_MODS)
    charge_bonus_save2 = max(0.0, mean2_charged - mean2)

    dmg_ranged_vs_save6 = _damage_of_kind(unit, "ranged", _PROBE_SAVE6)
    dmg_melee_vs_save6 = _damage_of_kind(unit, "melee", _PROBE_SAVE6)
    dmg_ranged_vs_save2 = _damage_of_kind(unit, "ranged", _PROBE_SAVE2)
    dmg_melee_vs_save2 = _damage_of_kind(unit, "melee", _PROBE_SAVE2)

    dmg_pen = (mean2 / mean6) if mean6 > 0 else 0.0
    dmg_cv_vs_save4 = (var4**0.5 / mean4) if mean4 > 0 else 0.0

    save_num = unit.save
    ward_num = unit.ward if unit.ward is not None else 7
    wounds_total = unit.health * unit.models

    kinds = {w.kind for w in unit.weapons}
    if kinds == {"melee"}:
        weapon_mix = "melee"
    elif kinds == {"ranged"}:
        weapon_mix = "ranged"
    elif kinds:
        weapon_mix = "mixed"
    else:
        weapon_mix = "melee"

    return UnitFeatures(
        unit_id=unit.id,
        army_id=unit.army_id,
        name=unit.name,
        points=unit.points,
        is_hero=unit.is_hero,
        dmg_vs_save2=mean2,
        dmg_vs_save4=mean4,
        dmg_vs_save6=mean6,
        dmg_melee_vs_save6=dmg_melee_vs_save6,
        dmg_ranged_vs_save6=dmg_ranged_vs_save6,
        dmg_melee_vs_save2=dmg_melee_vs_save2,
        dmg_ranged_vs_save2=dmg_ranged_vs_save2,
        dmg_pen=dmg_pen,
        dmg_vs_save2_sq=mean2**2,
        dmg_cv_vs_save4=dmg_cv_vs_save4,
        charge_bonus_save2=charge_bonus_save2,
        wounds_total=wounds_total,
        save_num=save_num,
        ward_num=ward_num,
        effective_wounds=compute_effective_wounds(wounds_total, save_num, ward_num),
        move=unit.move,
        control=unit.control,
        control_expected=(ctl_exp := expected_control(unit)),
        control_bonus=max(0, unit.control - ctl_exp),
        control_deficit=max(0, ctl_exp - unit.control),
        unit_size=unit.models,
        unit_size_sq=unit.models**2,
        grand_alliance="",
        army_name="",
        weapon_mix=weapon_mix,
        unit_type=unit_type_of(unit.keywords),
        is_flying="FLY" in unit.keywords,
        wizard_level=_caster_level(unit.keywords, "WIZARD"),
        priest_level=_caster_level(unit.keywords, "PRIEST"),
        is_unique="UNIQUE" in unit.keywords,
        crit_type=dominant_crit_type(unit),
    )


def all_features(con: duckdb.DuckDBPyConnection) -> list[UnitFeatures]:
    """Calcule le vecteur de caractéristiques de toutes les unités de la base."""
    from ...persistence.repository import list_armies

    armies = list_armies(con)
    alliance_by_army = {a.id: a.grand_alliance for a in armies}
    name_by_army = {a.id: a.name for a in armies}
    by_army = load_all_units_with_weapons(con)
    return [
        dataclasses.replace(
            compute_features(unit),
            grand_alliance=alliance_by_army.get(unit.army_id, "Order"),
            army_name=name_by_army.get(unit.army_id, "?"),
        )
        for units in by_army.values()
        for unit in units
    ]

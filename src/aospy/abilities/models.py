"""Dataclasses de l'analyse d'aptitudes. Aucune logique ni accès aux données."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

#: Origine de l'aptitude dans le jeu (colonne `ability.source_kind`).
SourceKind = Literal[
    "warscroll",  # aptitude imprimée sur une warscroll
    "battle_trait",  # trait de bataille de faction
    "formation",  # formation de bataille
    "heroic_trait",  # trait héroïque
    "artefact",  # artefact de pouvoir
    "spell",  # domaine de sorts
    "prayer",  # domaine de prières
    "manifestation",  # domaine de manifestations (sort d'invocation)
    "monstrous_trait",  # trait monstrueux
    "enhancement",  # autre amélioration achetée (bannière, mutation, titre…)
    "other",  # autre règle de faction (Armée de Renom, quête, etc.)
]

#: Fréquence d'utilisation, de la plus rare à la plus fréquente.
Frequency = Literal[
    "once_per_battle_army",
    "once_per_battle",
    "once_per_round_army",
    "once_per_round",
    "once_per_turn_army",
    "once_per_turn",
    "once_per_phase_army",
    "unlimited",
    "passive",
]

#: Tour où l'aptitude peut servir.
TurnSide = Literal["yours", "enemy", "any", "deployment", "round_start"]

#: Portée de l'effet (qui en profite / qui le subit).
Scope = Literal[
    "self",
    "one_friendly",
    "friendly_aura",
    "army",
    "one_enemy",
    "enemy_aura",
    "all_enemies",
    "battlefield",
    "unknown",
]

#: « bonus » : forte et gratuite mais tardive/non maîtrisée (ressource qui s'accumule) —
#: on en profite quand elle arrive, on ne construit jamais de plan dessus.
#: « a-revoir » : aucun effet reconnu par les règles, verdict non calculable.
Verdict = Literal["plan", "correct", "pari", "bonus", "anecdotique", "a-revoir"]


@dataclass(frozen=True)
class AbilityOwner:
    """Un porteur de l'aptitude (warscroll, ou groupe de règle de faction)."""

    faction_id: str
    faction_name: str
    owner_kind: Literal["warscroll", "faction_rule"]
    owner_name: str  # nom de warscroll, ou « type › sous-type » de la règle
    warscroll_id: Optional[str] = None
    role: str = ""  # rôle Wahapedia de la warscroll (Infantry, Manifestation…)
    #: Origine (`abilities.source.origin_of`) : warscroll / regiment_of_renown / base / army_of_renown /
    #: spearhead / path_to_glory. Spearhead et Path to Glory sont hors jeu égal (couches 3-4 les écartent).
    origin_kind: str = ""
    origin_name: str = ""  # nom de l'Armée de Renom / de l'armée Spearhead, '' sinon
    #: catégorie de CE porteur (battle_trait, formation, spell…) : `RawAbility.source_kind` ne garde que
    #: celle du premier porteur.
    category: str = ""


@dataclass(frozen=True)
class RawAbility:
    """Aptitude telle que lue dans Wahapedia, texte nettoyé, avant analyse."""

    uid: str  # empreinte stable (nom + condition + texte)
    name: str
    source_kind: SourceKind
    group_name: str  # formation / domaine / sous-type ; '' pour une warscroll
    condition: str  # timing nettoyé (« Once Per Turn (Army), Any Combat Phase »)
    phase: str  # `ability_phase` Wahapedia
    wahapedia_type: str  # `ability_type` Wahapedia (Offensive, Movement…)
    is_reaction: bool
    keywords: str  # mots-clés d'aptitude (« Rampage », « Unlimited »…)
    cost_type: str  # Spell / Prayer / Command / Blood tithe / Fate / ''
    cost_value: str  # valeur brute (« 7 », « 1+ »…)
    declare: str  # texte « Declare: » nettoyé
    effect: str  # texte « Effect: » nettoyé (sans note de concepteur)
    owners: tuple[AbilityOwner, ...] = ()
    #: Optimisations : à qui elle peut être donnée, tel qu'écrit dans l'export (« HERO only », « can be given
    #: to non-Hero Slaves to Darkness Infantry units »…) ; '' sinon. Résolu en couche 3 (`analysis/layers/bearers.py`).
    bearer_restriction: str = ""


@dataclass(frozen=True)
class Effect:
    """Un effet chiffré reconnu dans le texte (colonne de `ability_effect`)."""

    kind: str  # stat_mod, mortal_damage, ward, heal, return_models…
    stat: str = ""  # hit, wound, save, attacks, rend, damage, charge…
    value: float = 0.0  # valeur moyenne (D3 → 2, D6 → 3,5)
    dice: str = ""  # expression brute (« D3 », « 2D6 »), '' si fixe
    side: Literal["friendly", "enemy", ""] = ""  # qui le subit/en profite
    detail: str = ""
    # --- périmètre (`perimeter.py`) : ce qu'il faut savoir pour appliquer l'effet à un châssis ---
    weapon_scope: str = ""  # melee / ranged / named / chosen / all ; '' si sans objet
    weapon_name: str = ""  # arme nommée (« Almighty Stomp »), si weapon_scope == named
    includes_companion: bool = False  # « including … Companion weapons » (exclues par défaut)
    target_keywords: str = ""  # cible exigée par mot-clé, ex. « HERO,MONSTER »
    target_condition: str = ""  # autre condition sur la cible (« ≥10 figurines », « sur objectif »…)
    requires: str = ""  # prérequis propre à l'effet (« a chargé », « sans mouvement »…)
    duration: str = ""  # permanent / tour / phase / jusqu'au prochain tour / round / bataille / immédiat
    # restriction de cible amie lue dans la phrase de l'effet (aptitude à options : chaque option vise ses
    # propres unités) ; '' = celle de l'aptitude (`Extraction.friendly_target`) s'applique (analyseur v26)
    friendly_target: str = ""


@dataclass
class Extraction:
    """Caractéristiques extraites par règles (paquet `extract/`)."""

    frequency: Frequency = "unlimited"
    turn: TurnSide = "any"
    scope: Scope = "unknown"
    range_inches: Optional[int] = None  # portée principale (cible/aura)
    wholly_within: bool = False
    activation_prob: float = 1.0  # P(l'aptitude se déclenche vraiment)
    activation_notes: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)  # prérequis de mise en place
    effects: list[Effect] = field(default_factory=list)
    variance: Literal["fixe", "des", "binomial"] = "fixe"  # aléa de l'effet lui-même
    target_keywords: list[str] = field(default_factory=list)  # Anti-X : cible MONSTER/HERO…
    scales_with_size: bool = False  # « for each model in this unit »
    excludes_self: bool = False  # « another/other friendly » : pas le porteur
    friendly_target: str = ""  # restriction de cible amie (« non-HERO WARRIORS OF CHAOS INFANTRY »)
    unlock_prereqs: list[str] = field(default_factory=list)  # « unlocked 'X' or 'Y' » (l'un suffit)
    resource_cost: Optional[int] = None  # coût cumulé en ressource de faction (chaîne incluse)
    available_round: Optional[int] = None  # round estimé où elle devient disponible


@dataclass
class Score:
    """Quatre axes notés de 0 à 3 (3 = facile / fort / fiable / profite à l'armée) + verdict.

    `interaction` mesure le rayonnement sur le reste de l'armée : 0 = l'unité
    porteuse seule, 1 = une autre unité, 2 = bulle (selon son rayon), 3 = armée.
    Une aptitude offensive contre l'ennemi (dégâts, debuff) n'est pas pénalisée
    par cet axe : il ne compte pas dans le verdict, il sert aux combos.
    """

    ease: float
    power: float
    reliability: float
    interaction: float
    verdict: Verdict
    rationale: list[str] = field(default_factory=list)


@dataclass
class AbilityAnalysis:
    """Résultat complet pour une aptitude, prêt à persister."""

    raw: RawAbility
    extraction: Extraction
    score: Score
    tags: list[str]
    understood: bool  # au moins un effet reconnu
    overridden: bool = False

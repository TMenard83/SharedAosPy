"""Dataclasses du domaine AoSPy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

GrandAlliance = Literal["Order", "Chaos", "Death", "Destruction"]
WeaponKind = Literal["melee", "ranged"]
CompositionKind = Literal["tournament", "custom"]


@dataclass(frozen=True)
class Army:
    name: str
    grand_alliance: GrandAlliance
    id: Optional[int] = None


@dataclass(frozen=True)
class Weapon:
    name: str
    kind: WeaponKind
    attacks: int
    hit: int            # X+
    wound: int          # X+
    damage: int
    rend: int = 0       # valeur positive, appliquée en -X
    range_in: int = 1   # pouces
    abilities: Optional[str] = None
    wielders: int = 0   # nb de modèles porteurs (taille de base) ; 0 = tous
    id: Optional[int] = None
    unit_id: Optional[int] = None


@dataclass
class Unit:
    name: str
    army_id: int
    move: int
    save: int            # X+
    health: int          # par modèle
    control: int         # par modèle
    models: int          # taille d'unité de base
    points: int
    is_hero: bool = False
    ward: Optional[int] = None  # X+
    weapons: list[Weapon] = field(default_factory=list)
    id: Optional[int] = None


@dataclass(frozen=True)
class HeroicTrait:
    army_id: int
    name: str
    description: Optional[str] = None
    id: Optional[int] = None


@dataclass(frozen=True)
class Artefact:
    army_id: int
    name: str
    description: Optional[str] = None
    id: Optional[int] = None


@dataclass
class CompositionUnit:
    unit_id: int
    reinforced: bool = False
    is_general: bool = False
    heroic_trait_id: Optional[int] = None
    artefact_id: Optional[int] = None
    id: Optional[int] = None
    composition_id: Optional[int] = None


@dataclass
class Composition:
    army_id: int
    name: str
    kind: CompositionKind
    format_points: int           # ex: 2000
    total_points: int = 0        # recalculé à la sauvegarde
    source: Optional[str] = None
    notes: Optional[str] = None
    entries: list[CompositionUnit] = field(default_factory=list)
    id: Optional[int] = None
    created_at: Optional[datetime] = None

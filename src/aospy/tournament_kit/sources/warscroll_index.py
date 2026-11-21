"""Charge `data/json/warscroll_index.json` — index curé manuellement (voir le
fichier lui-même) reliant :

- chaque nom d'unité canonique (celui de l'App/BSData, identique à
  `unit.name` dans la DB aospy) à ses pages dans le PDF de battletome de sa
  faction ;
- par faction, les pages de règles générales du battletome (traits de
  bataille, formation choisie, traits héroïques/artefacts de pouvoir,
  domaines de sorts/manifestations — un domaine par nom, une faction peut en
  avoir plusieurs) ;
- les cartes de tactique de bataille (indépendantes de la faction), dans
  `data/Manuel du général/MdG26-27 Tactiques.pdf` ;
- les domaines de manifestations **génériques** (partagés entre factions,
  ex. « Twilit Sorceries »), dans
  `data/Manuel du général/sorts persistants - manifestations.pdf` : pour
  chacun, la page de règles de convocation (« domain_pages ») **et** la/les
  page(s) de charte (warscroll) de chaque manifestation invocable par ce
  domaine — un domaine de sorts choisi donne accès à toutes ses
  manifestations, pas une seule, donc toutes leurs pages sont incluses.

Chargé « à froid » à chaque appel, comme `bonus_simulator/army_rules.py` —
aucune écriture en DB. À étendre à la main (curation visuelle) pour chaque
nouveau battletome ajouté ou nouvelle carte de tactique."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from ...text import fold_name

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_INDEX_PATH = _REPO_ROOT / "data" / "json" / "warscroll_index.json"
DEFAULT_BATTLETOME_DIR = _REPO_ROOT / "data" / "Battle tome" / "Done"
DEFAULT_MANUEL_DIR = _REPO_ROOT / "data" / "Manuel du général"


@dataclass(frozen=True)
class FactionRules:
    battle_traits: list[int]
    formations: list[int]
    heroic_traits_artefacts: list[int]
    spell_lores: dict[str, list[int]]
    manifestation_lores: dict[str, list[int]]


@dataclass(frozen=True)
class UnitEntry:
    pages: list[int]
    file: str


@dataclass(frozen=True)
class FactionIndex:
    file: str
    units: dict[str, UnitEntry]
    rules: FactionRules


@dataclass(frozen=True)
class TacticCardsIndex:
    dir: str
    file: str
    cards: dict[str, list[int]]


@dataclass(frozen=True)
class GenericManifestationLore:
    domain_pages: list[int]
    manifestations: dict[str, list[int]]

    def all_pages(self) -> list[int]:
        pages = list(self.domain_pages)
        for manif_pages in self.manifestations.values():
            pages.extend(manif_pages)
        return pages


@dataclass(frozen=True)
class GenericManifestationLoresIndex:
    dir: str
    file: str
    lores: dict[str, GenericManifestationLore]


@dataclass(frozen=True)
class WarscrollIndex:
    factions: dict[str, FactionIndex]
    tactic_cards: TacticCardsIndex | None
    generic_manifestation_lores: GenericManifestationLoresIndex | None = None


_T = TypeVar("_T")


def _lookup_normalized(entries: dict[str, _T], name: str) -> _T | None:
    if name in entries:
        return entries[name]
    target = fold_name(name)
    for key, value in entries.items():
        if fold_name(key) == target:
            return value
    return None


def _parse_faction_rules(raw: dict) -> FactionRules:
    return FactionRules(
        battle_traits=raw.get("battle_traits", []),
        formations=raw.get("formations", []),
        heroic_traits_artefacts=raw.get("heroic_traits_artefacts", []),
        spell_lores={e["name"]: e["pages"] for e in raw.get("spell_lores", [])},
        manifestation_lores={e["name"]: e["pages"] for e in raw.get("manifestation_lores", [])},
    )


def load_index(path: str | Path = DEFAULT_INDEX_PATH) -> WarscrollIndex:
    path = Path(path)
    if not path.exists():
        return WarscrollIndex(factions={}, tactic_cards=None)
    raw = json.loads(path.read_text(encoding="utf-8"))

    factions: dict[str, FactionIndex] = {}
    for faction, data in raw.get("factions", {}).items():
        units = {
            entry["name"]: UnitEntry(pages=entry["pages"], file=entry.get("file", data["file"]))
            for entry in data.get("units", [])
        }
        factions[faction] = FactionIndex(
            file=data["file"], units=units, rules=_parse_faction_rules(data.get("rules", {})),
        )

    tactic_cards = None
    raw_cards = raw.get("battle_tactic_cards")
    if raw_cards is not None:
        tactic_cards = TacticCardsIndex(
            dir=raw_cards["dir"],
            file=raw_cards["file"],
            cards={e["name"]: e["pages"] for e in raw_cards.get("cards", [])},
        )

    generic_manifestation_lores = None
    raw_generic = raw.get("generic_manifestation_lores")
    if raw_generic is not None:
        lores = {
            name: GenericManifestationLore(
                domain_pages=data.get("domain_pages", []),
                manifestations={e["name"]: e["pages"] for e in data.get("manifestations", [])},
            )
            for name, data in raw_generic.get("lores", {}).items()
        }
        generic_manifestation_lores = GenericManifestationLoresIndex(
            dir=raw_generic["dir"], file=raw_generic["file"], lores=lores,
        )

    return WarscrollIndex(
        factions=factions, tactic_cards=tactic_cards, generic_manifestation_lores=generic_manifestation_lores,
    )


def find_pages(index: WarscrollIndex, faction: str, unit_name: str) -> list[int] | None:
    """Pages (0-indexées) du profil `unit_name` pour `faction`, ou `None` si
    la faction n'est pas indexée ou que l'unité n'y est pas trouvée. Essaie
    une correspondance exacte, puis normalisée (accents/casse)."""
    entry = _find_unit_entry(index, faction, unit_name)
    return entry.pages if entry is not None else None


def _find_unit_entry(index: WarscrollIndex, faction: str, unit_name: str) -> UnitEntry | None:
    faction_index = index.factions.get(faction)
    if faction_index is None:
        return None
    return _lookup_normalized(faction_index.units, unit_name)


def unit_pdf_path(
    index: WarscrollIndex, faction: str, unit_name: str, battletome_dir: str | Path = DEFAULT_BATTLETOME_DIR,
) -> Path | None:
    """Chemin du PDF où trouver les pages de `unit_name` pour `faction` — le
    battletome principal de la faction, sauf si l'unité vient d'un supplément
    indexé avec son propre `"file"` (ex. une variante Scourge of Aqshy dont la
    charte est dans un PDF séparé plutôt que le battletome de base)."""
    entry = _find_unit_entry(index, faction, unit_name)
    if entry is None:
        return None
    return Path(battletome_dir) / entry.file


def find_lore_pages(faction_index: FactionIndex, lores: dict[str, list[int]], lore_name: str) -> list[int] | None:
    """Résout un domaine de sorts/manifestations (`lores` = `rules.spell_lores`
    ou `rules.manifestation_lores` de `faction_index`) par nom, normalisé.
    Le nom d'un domaine dans un export de liste porte parfois un suffixe de
    coût (« Morbid Conjuration (20 Points) ») absent de l'index : on retente
    sans tout ce qui suit une parenthèse ouvrante avant d'abandonner."""
    pages = _lookup_normalized(lores, lore_name)
    if pages is not None:
        return pages
    base_name = lore_name.split("(", 1)[0].strip()
    if base_name != lore_name:
        return _lookup_normalized(lores, base_name)
    return None


def find_tactic_card_pages(index: WarscrollIndex, card_name: str) -> list[int] | None:
    if index.tactic_cards is None:
        return None
    return _lookup_normalized(index.tactic_cards.cards, card_name)


def find_generic_manifestation_lore(index: WarscrollIndex, lore_name: str) -> GenericManifestationLore | None:
    """Résout un domaine de manifestations générique (partagé entre factions,
    absent du battletome) par nom, normalisé, avec le même repli sur suffixe
    de coût que `find_lore_pages`."""
    if index.generic_manifestation_lores is None:
        return None
    lores = index.generic_manifestation_lores.lores
    if lore_name in lores:
        return lores[lore_name]
    target = fold_name(lore_name)
    for key, lore in lores.items():
        if fold_name(key) == target:
            return lore
    base_name = lore_name.split("(", 1)[0].strip()
    if base_name != lore_name:
        return find_generic_manifestation_lore(index, base_name)
    return None


def battletome_path(index: WarscrollIndex, faction: str, battletome_dir: str | Path = DEFAULT_BATTLETOME_DIR) -> Path | None:
    faction_index = index.factions.get(faction)
    if faction_index is None:
        return None
    return Path(battletome_dir) / faction_index.file


def tactic_cards_path(index: WarscrollIndex, manuel_dir: str | Path | None = None) -> Path | None:
    if index.tactic_cards is None:
        return None
    base_dir = Path(manuel_dir) if manuel_dir is not None else _REPO_ROOT / "data" / index.tactic_cards.dir
    return base_dir / index.tactic_cards.file


def generic_manifestation_lores_path(index: WarscrollIndex, manuel_dir: str | Path | None = None) -> Path | None:
    if index.generic_manifestation_lores is None:
        return None
    base_dir = Path(manuel_dir) if manuel_dir is not None else _REPO_ROOT / "data" / index.generic_manifestation_lores.dir
    return base_dir / index.generic_manifestation_lores.file

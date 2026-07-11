"""Chargement des données initiales depuis JSON (armées, compositions)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import repository
from .models import (
    Army,
    Artefact,
    Composition,
    CompositionUnit,
    HeroicTrait,
    Unit,
    Weapon,
)

DEFAULT_DATA_FILE = Path("data") / "armies.json"
DEFAULT_COMPOSITIONS_FILE = Path("data") / "compositions.json"


def load_armies_from_json(
    con: duckdb.DuckDBPyConnection,
    path: str | Path = DEFAULT_DATA_FILE,
) -> dict[str, int]:
    """Charge un fichier JSON d'armées et insère les données.

    Retourne un mapping `{nom_armée: army_id}`. Les armées déjà présentes
    (par nom) ne sont pas dupliquées ni mises à jour.
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    army_ids: dict[str, int] = {}
    for entry in payload:
        existing = repository.get_army_by_name(con, entry["name"])
        if existing is not None:
            army_ids[entry["name"]] = existing.id  # type: ignore[assignment]
            continue

        army = Army(name=entry["name"], grand_alliance=entry["grand_alliance"])
        army_id = repository.add_army(con, army)
        army_ids[entry["name"]] = army_id

        for t in entry.get("heroic_traits", []):
            repository.add_heroic_trait(
                con, HeroicTrait(army_id=army_id, name=t["name"], description=t.get("description"))
            )
        for a in entry.get("artefacts", []):
            repository.add_artefact(
                con, Artefact(army_id=army_id, name=a["name"], description=a.get("description"))
            )

        for u in entry.get("units", []):
            weapons = [
                Weapon(
                    name=w["name"], kind=w["kind"], range_in=w.get("range_in", 1),
                    attacks=w["attacks"], hit=w["hit"], wound=w["wound"],
                    rend=w.get("rend", 0), damage=w["damage"],
                    abilities=w.get("abilities"),
                )
                for w in u.get("weapons", [])
            ]
            unit = Unit(
                name=u["name"], army_id=army_id,
                move=u["move"], save=u["save"], health=u["health"],
                control=u["control"], models=u["models"], points=u["points"],
                is_hero=u.get("is_hero", False), ward=u.get("ward"),
                weapons=weapons,
            )
            repository.add_unit(con, unit)

    return army_ids



def load_compositions_from_json(
    con: duckdb.DuckDBPyConnection,
    path: str | Path = DEFAULT_COMPOSITIONS_FILE,
) -> dict[str, int]:
    """Charge un fichier JSON de compositions et insère les données.

    Format attendu (par entrée) :
        - army        : nom d'armée (doit exister)
        - name        : nom de la composition
        - kind        : 'tournament' ou 'custom'
        - format_points
        - source / notes  (optionnels)
        - entries     : liste d'objets {unit, reinforced?, is_general?,
                                        heroic_trait?, artefact?}

    Retourne `{nom_composition: composition_id}`. Idempotent par (army, name).
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    comp_ids: dict[str, int] = {}
    for entry in payload:
        army = repository.get_army_by_name(con, entry["army"])
        if army is None or army.id is None:
            raise ValueError(f"Armée inconnue: {entry['army']}")

        existing = repository.get_composition_by_name(con, army.id, entry["name"])
        if existing is not None and existing.id is not None:
            comp_ids[entry["name"]] = existing.id
            continue

        units_by_name = {u.name: u for u in repository.list_units_for_army(con, army.id)}
        comp_entries: list[CompositionUnit] = []
        for raw in entry.get("entries", []):
            unit = units_by_name.get(raw["unit"])
            if unit is None or unit.id is None:
                raise ValueError(f"Unité inconnue '{raw['unit']}' pour {army.name}")
            trait_id = None
            if raw.get("heroic_trait"):
                t = repository.get_heroic_trait_by_name(con, army.id, raw["heroic_trait"])
                if t is None:
                    raise ValueError(f"Trait héroïque inconnu: {raw['heroic_trait']}")
                trait_id = t.id
            artefact_id = None
            if raw.get("artefact"):
                a = repository.get_artefact_by_name(con, army.id, raw["artefact"])
                if a is None:
                    raise ValueError(f"Artefact inconnu: {raw['artefact']}")
                artefact_id = a.id
            comp_entries.append(CompositionUnit(
                unit_id=unit.id,
                reinforced=raw.get("reinforced", False),
                is_general=raw.get("is_general", False),
                heroic_trait_id=trait_id,
                artefact_id=artefact_id,
            ))

        composition = Composition(
            army_id=army.id, name=entry["name"], kind=entry["kind"],
            format_points=entry["format_points"], source=entry.get("source"),
            notes=entry.get("notes"), entries=comp_entries,
        )
        comp_ids[entry["name"]] = repository.add_composition(con, composition)

    return comp_ids

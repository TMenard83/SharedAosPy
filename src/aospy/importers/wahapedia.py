"""Importeur Wahapedia : lit les CSV publics et alimente le même schéma que `bsdata.py`.

Deuxième mécanique d'import (aux côtés de BSData) : les deux alimentent le même
schéma DuckDB (`Army`/`Unit`/`Weapon`), au choix de la source de données. Les
CSV Wahapedia (séparateur `|`, BOM UTF-8) sont la source utilisée par le projet
StatHammer ; ce module les rend disponibles ici sans dupliquer le moteur de
calcul (qui reste celui d'aospy, `combat.py`).

Limitations connues (périmètre volontairement restreint, voir importers/README.md) :

* seuls les rôles « unité de combat classique » sont importés (`INGESTIBLE_ROLES`)
  — Endless Spells, Manifestations, Regiments of Renown et Faction Terrain sont
  ignorés (`Unit` n'a pas de colonne `role` pour les distinguer après import) ;
* `Weapon.wielders` vaut toujours `0` (« tous les modèles »): Wahapedia ne fournit
  pas l'équivalent des contraintes BattleScribe qu'utilise `bsdata.py` pour
  inférer qui porte quelle arme ;
* les doublons de warscrolls homonymes sont dédupliqués par un algorithme fidèle
  à celui de StatHammer (`ingest/dedupe.py`), mais sans fichier d'overrides
  manuel : une ambiguïté résiduelle retient le premier candidat et imprime un
  avertissement plutôt que de bloquer un import non interactif.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..domain.models import Army, Unit, Weapon
from ..persistence import repository
from ..sources.wahapedia_csv import DEFAULT_DATA_DIR, canonical_ids, is_expired_variant, legends_warscroll_ids, read_csv
from .bsdata import KNOWN_ARMIES, ImportSummary, parse_dice, parse_target

#: Alliance de grande faction, dérivée du mapping déjà tenu par `bsdata.py`
#: (les noms d'armée correspondent exactement aux noms de faction Wahapedia).
FACTION_GRAND_ALLIANCE: dict[str, str] = {name: alliance for name, (_main, _lib, alliance) in KNOWN_ARMIES.items()}

#: Rôles représentant une unité de combat classique (placée sur table, achetée
#: en points) — cf. limitations en tête de module.
INGESTIBLE_ROLES: frozenset[str] = frozenset(
    {
        "Infantry",
        "Infantry Hero",
        "Cavalry",
        "Cavalry Hero",
        "Beast",
        "Beast Hero",
        "Monster",
        "Monster Hero",
        "War Machine",
        "War Machine Hero",
        "Hero",
    }
)


def keyword_variants(row: dict[str, str]) -> set[str]:
    """Mot-clé d'une ligne `Warscrolls_keywords.csv`, plus sa forme paramétrée pour les lanceurs.

    Wahapedia range le niveau d'un sorcier/prêtre dans la colonne `parameter` (`WIZARD` + `2`) : on
    garde `WIZARD` (ciblages « friendly WIZARD ») **et** `WIZARD (2)`, la forme que BSData capture et
    que lit `analysis.cost.features._CASTER_RE`. Sans elle, tous les niveaux de lanceur étaient perdus."""
    kw = (row.get("keyword") or "").upper()
    out = {kw}
    param = (row.get("parameter") or "").strip()
    if kw in ("WIZARD", "PRIEST") and param.isdigit():
        out.add(f"{kw} ({param})")
    return out


def _parse_unit(
    row: dict[str, str],
    army_id: int,
    weapon_rows: list[dict[str, str]],
    keywords: set[str],
) -> Unit:
    ward_raw = (row.get("Ward") or "").strip()
    ward = parse_target(ward_raw) if ward_raw and ward_raw != "-" else None
    return Unit(
        name=row["name"],
        army_id=army_id,
        move=parse_dice(row.get("Move") or ""),
        save=parse_target(row.get("Save") or ""),
        health=int(row["Health"]),
        control=parse_dice(row.get("Control") or ""),
        models=int(row["UnitSize"]) if (row.get("UnitSize") or "").strip() else 1,
        points=int(row["Cost"]),
        is_hero="HERO" in keywords,
        ward=ward,
        keywords=frozenset(keywords),
        description=row.get("description") or None,
        weapons=[_parse_weapon(w) for w in weapon_rows],
    )


def _parse_weapon(row: dict[str, str]) -> Weapon:
    kind = "ranged" if (row.get("type") or "").upper() == "RANGED" else "melee"
    rng_raw = (row.get("Rng") or "").strip()
    return Weapon(
        name=row.get("name") or "?",
        kind=kind,  # type: ignore[arg-type]
        range_in=parse_dice(rng_raw) if rng_raw else 1,
        attacks=parse_dice(row.get("Atk") or ""),
        hit=parse_target(row.get("Hit") or ""),
        wound=parse_target(row.get("Wnd") or ""),
        rend=parse_dice(row.get("Rnd") or ""),
        damage=parse_dice(row.get("Dmg") or ""),
        abilities=row.get("abilities") or None,
        wielders=0,  # cf. limitation en tête de module : pas d'inférence de porteurs
    )


def import_faction(
    con: duckdb.DuckDBPyConnection,
    faction_name: str,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> ImportSummary:
    """Importe une faction depuis les CSV Wahapedia. Remplace les unités existantes (par nom)."""
    if faction_name not in FACTION_GRAND_ALLIANCE:
        raise ValueError(f"faction inconnue '{faction_name}'. Connues : {', '.join(FACTION_GRAND_ALLIANCE)}")

    factions = read_csv(data_dir / "Factions.csv")
    faction_id = next((f["id"] for f in factions if f.get("name") == faction_name), None)
    if faction_id is None:
        raise ValueError(f"faction '{faction_name}' absente de {data_dir / 'Factions.csv'}")

    warscrolls = read_csv(data_dir / "Warscrolls.csv")
    exclude_legends = legends_warscroll_ids(data_dir)
    canonical = canonical_ids(warscrolls)

    keywords_by_id: dict[str, set[str]] = {}
    for k in read_csv(data_dir / "Warscrolls_keywords.csv"):
        keywords_by_id.setdefault(k["warscroll_id"], set()).update(keyword_variants(k))

    weapons_by_id: dict[str, list[dict[str, str]]] = {}
    for w in read_csv(data_dir / "Warscrolls_weapons.csv"):
        weapons_by_id.setdefault(w["warscroll_id"], []).append(w)

    alliance = FACTION_GRAND_ALLIANCE[faction_name]
    existing = repository.get_army_by_name(con, faction_name)
    if existing is None or existing.id is None:
        army_id = repository.add_army(con, Army(name=faction_name, grand_alliance=alliance))  # type: ignore[arg-type]
    else:
        army_id = existing.id

    summary = ImportSummary(army=faction_name)
    for w in warscrolls:
        wid = w["id"]
        if w.get("faction_id") != faction_id:
            continue
        if wid in exclude_legends or wid not in canonical:
            continue
        if (w.get("role") or "") not in INGESTIBLE_ROLES:
            continue
        if is_expired_variant(w.get("name") or ""):
            summary.skipped_legends += 1
            continue
        if not (w.get("Cost") or "").strip():
            summary.skipped_no_points += 1
            continue
        try:
            unit = _parse_unit(w, army_id, weapons_by_id.get(wid, []), keywords_by_id.get(wid, set()))
        except (ValueError, KeyError):
            summary.skipped_no_profile += 1
            continue
        was_update = repository.replace_unit(con, unit)
        if was_update:
            summary.updated += 1
        else:
            summary.inserted += 1
    return summary

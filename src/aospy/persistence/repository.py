"""CRUD pour les armées, unités, armes, traits, artefacts et compositions."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import duckdb

from ..domain.models import (
    Army,
    Artefact,
    Composition,
    CompositionUnit,
    HeroicTrait,
    Unit,
    Weapon,
)


def _keywords_to_db(keywords: frozenset[str]) -> str:
    return ",".join(sorted(keywords))


def _keywords_from_db(raw: Optional[str]) -> frozenset[str]:
    return frozenset(raw.split(",")) if raw else frozenset()


# ----- Army -----------------------------------------------------------------

def add_army(con: duckdb.DuckDBPyConnection, army: Army) -> int:
    row = con.execute(
        "INSERT INTO army(name, grand_alliance) VALUES (?, ?) RETURNING id",
        [army.name, army.grand_alliance],
    ).fetchone()
    return int(row[0])


def get_army_by_name(con: duckdb.DuckDBPyConnection, name: str) -> Optional[Army]:
    row = con.execute(
        "SELECT id, name, grand_alliance FROM army WHERE name = ?",
        [name],
    ).fetchone()
    if row is None:
        return None
    return Army(id=row[0], name=row[1], grand_alliance=row[2])


def list_armies(con: duckdb.DuckDBPyConnection) -> list[Army]:
    rows = con.execute(
        "SELECT id, name, grand_alliance FROM army ORDER BY name"
    ).fetchall()
    return [Army(id=r[0], name=r[1], grand_alliance=r[2]) for r in rows]


# ----- Unit -----------------------------------------------------------------

def add_unit(con: duckdb.DuckDBPyConnection, unit: Unit) -> int:
    row = con.execute(
        """
        INSERT INTO unit(army_id, name, move, save, health, control,
                         models, points, is_hero, ward, keywords, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            unit.army_id, unit.name, unit.move, unit.save, unit.health,
            unit.control, unit.models, unit.points, unit.is_hero, unit.ward,
            _keywords_to_db(unit.keywords), unit.description,
        ],
    ).fetchone()
    unit_id = int(row[0])
    for w in unit.weapons:
        add_weapon(con, unit_id, w)
    return unit_id


def add_weapon(con: duckdb.DuckDBPyConnection, unit_id: int, weapon: Weapon) -> int:
    row = con.execute(
        """
        INSERT INTO weapon(unit_id, name, kind, range_in, attacks, hit,
                           wound, rend, damage, abilities, wielders, is_companion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            unit_id, weapon.name, weapon.kind, weapon.range_in, weapon.attacks,
            weapon.hit, weapon.wound, weapon.rend, weapon.damage, weapon.abilities,
            weapon.wielders, weapon.is_companion,
        ],
    ).fetchone()
    return int(row[0])


def get_unit(con: duckdb.DuckDBPyConnection, unit_id: int) -> Optional[Unit]:
    row = con.execute(
        """
        SELECT id, army_id, name, move, save, health, control,
               models, points, is_hero, ward, keywords, description
        FROM unit WHERE id = ?
        """,
        [unit_id],
    ).fetchone()
    if row is None:
        return None
    weapons = _list_weapons(con, unit_id)
    return Unit(
        id=row[0], army_id=row[1], name=row[2], move=row[3], save=row[4],
        health=row[5], control=row[6], models=row[7], points=row[8],
        is_hero=bool(row[9]), ward=row[10], keywords=_keywords_from_db(row[11]),
        description=row[12], weapons=weapons,
    )


def list_units_for_army(con: duckdb.DuckDBPyConnection, army_id: int) -> list[Unit]:
    rows = con.execute(
        """
        SELECT id, army_id, name, move, save, health, control,
               models, points, is_hero, ward, keywords, description
        FROM unit WHERE army_id = ? ORDER BY name
        """,
        [army_id],
    ).fetchall()
    units: list[Unit] = []
    for r in rows:
        units.append(Unit(
            id=r[0], army_id=r[1], name=r[2], move=r[3], save=r[4],
            health=r[5], control=r[6], models=r[7], points=r[8],
            is_hero=bool(r[9]), ward=r[10], keywords=_keywords_from_db(r[11]),
            description=r[12], weapons=_list_weapons(con, r[0]),
        ))
    return units


def _list_weapons(con: duckdb.DuckDBPyConnection, unit_id: int) -> list[Weapon]:
    rows = con.execute(
        """
        SELECT id, unit_id, name, kind, range_in, attacks, hit, wound,
               rend, damage, abilities, wielders, is_companion
        FROM weapon WHERE unit_id = ? ORDER BY kind, name
        """,
        [unit_id],
    ).fetchall()
    return [
        Weapon(
            id=r[0], unit_id=r[1], name=r[2], kind=r[3], range_in=r[4],
            attacks=r[5], hit=r[6], wound=r[7], rend=r[8], damage=r[9],
            abilities=r[10], wielders=r[11], is_companion=bool(r[12]),
        )
        for r in rows
    ]


def bulk_add_armies(con: duckdb.DuckDBPyConnection, armies: Iterable[Army]) -> None:
    for a in armies:
        if get_army_by_name(con, a.name) is None:
            add_army(con, a)


def load_all_units_with_weapons(
    con: duckdb.DuckDBPyConnection,
) -> dict[int, list[Unit]]:
    """Charge toutes les unités et leurs armes en deux requêtes globales.

    Retourne un dict army_id -> list[Unit] (armes incluses, triées comme list_units_for_army).
    Évite les N+1 dans les boucles type benchmark global.
    """
    unit_rows = con.execute(
        """
        SELECT id, army_id, name, move, save, health, control,
               models, points, is_hero, ward, keywords, description
        FROM unit ORDER BY army_id, name
        """,
    ).fetchall()
    weapon_rows = con.execute(
        """
        SELECT id, unit_id, name, kind, range_in, attacks, hit, wound,
               rend, damage, abilities, wielders, is_companion
        FROM weapon ORDER BY unit_id, kind, name
        """,
    ).fetchall()
    weapons_by_unit: dict[int, list[Weapon]] = {}
    for r in weapon_rows:
        weapons_by_unit.setdefault(int(r[1]), []).append(Weapon(
            id=r[0], unit_id=r[1], name=r[2], kind=r[3], range_in=r[4],
            attacks=r[5], hit=r[6], wound=r[7], rend=r[8], damage=r[9],
            abilities=r[10], wielders=r[11], is_companion=bool(r[12]),
        ))
    by_army: dict[int, list[Unit]] = {}
    for r in unit_rows:
        unit = Unit(
            id=r[0], army_id=r[1], name=r[2], move=r[3], save=r[4],
            health=r[5], control=r[6], models=r[7], points=r[8],
            is_hero=bool(r[9]), ward=r[10], keywords=_keywords_from_db(r[11]),
            description=r[12],
            weapons=weapons_by_unit.get(int(r[0]), []),
        )
        by_army.setdefault(int(r[1]), []).append(unit)
    return by_army


def get_unit_by_name(
    con: duckdb.DuckDBPyConnection, army_id: int, name: str,
) -> Optional[Unit]:
    row = con.execute(
        "SELECT id FROM unit WHERE army_id = ? AND name = ?",
        [army_id, name],
    ).fetchone()
    return get_unit(con, int(row[0])) if row else None


def replace_unit(con: duckdb.DuckDBPyConnection, unit: Unit) -> bool:
    """Insère ou remplace une unité (par army_id+name) et ses armes.

    Retourne True si l'unité existait déjà (mise à jour), False si insertion.
    Les compositions qui référencent l'unité voient leur total_points rafraîchi.
    """
    existing = get_unit_by_name(con, unit.army_id, unit.name)
    if existing is None or existing.id is None:
        add_unit(con, unit)
        return False
    unit_id = existing.id
    con.execute(
        """
        UPDATE unit SET move = ?, save = ?, health = ?, control = ?,
                        models = ?, points = ?, is_hero = ?, ward = ?,
                        keywords = ?, description = ?, imported_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [
            unit.move, unit.save, unit.health, unit.control,
            unit.models, unit.points, unit.is_hero, unit.ward,
            _keywords_to_db(unit.keywords), unit.description, unit_id,
        ],
    )
    con.execute("DELETE FROM weapon WHERE unit_id = ?", [unit_id])
    for w in unit.weapons:
        add_weapon(con, unit_id, w)
    rows = con.execute(
        "SELECT DISTINCT composition_id FROM composition_unit WHERE unit_id = ?",
        [unit_id],
    ).fetchall()
    for (cid,) in rows:
        _refresh_total_points(con, int(cid))
    return True


def delete_units_imported_before(
    con: duckdb.DuckDBPyConnection, cutoff: datetime, *, army_id: Optional[int] = None,
) -> int:
    """Purge les unités dont `imported_at` précède `cutoff` (plus touchées par le dernier import).

    Nettoie aussi leurs armes, leurs entrées de composition et leurs résultats de
    benchmark avant de supprimer la ligne `unit` elle-même (pas de ON DELETE
    CASCADE dans le schéma). Restreint à `army_id` si fourni, sinon global.
    `cutoff` s'obtient typiquement en notant `datetime.now()` juste avant de
    relancer un import complet : tout ce qui n'a pas été rafraîchi depuis a
    disparu de la source (ou a été filtré, ex. Legends/Scourge of Ghyran).
    """
    where = "imported_at < ?" + (" AND army_id = ?" if army_id is not None else "")
    params: list[object] = [cutoff] + ([army_id] if army_id is not None else [])
    stale_ids = [int(r[0]) for r in con.execute(f"SELECT id FROM unit WHERE {where}", params).fetchall()]
    if not stale_ids:
        return 0
    placeholders = ",".join("?" for _ in stale_ids)
    con.execute(f"DELETE FROM weapon WHERE unit_id IN ({placeholders})", stale_ids)
    con.execute(f"DELETE FROM composition_unit WHERE unit_id IN ({placeholders})", stale_ids)
    con.execute(
        f"DELETE FROM unit_benchmark WHERE attacker_id IN ({placeholders}) OR defender_id IN ({placeholders})",
        stale_ids + stale_ids,
    )
    con.execute(f"DELETE FROM unit WHERE id IN ({placeholders})", stale_ids)
    return len(stale_ids)


# ----- Heroic traits / Artefacts --------------------------------------------

def add_heroic_trait(con: duckdb.DuckDBPyConnection, trait: HeroicTrait) -> int:
    row = con.execute(
        "INSERT INTO heroic_trait(army_id, name, description) VALUES (?, ?, ?) RETURNING id",
        [trait.army_id, trait.name, trait.description],
    ).fetchone()
    return int(row[0])


def get_heroic_trait_by_name(
    con: duckdb.DuckDBPyConnection, army_id: int, name: str
) -> Optional[HeroicTrait]:
    row = con.execute(
        "SELECT id, army_id, name, description FROM heroic_trait WHERE army_id = ? AND name = ?",
        [army_id, name],
    ).fetchone()
    if row is None:
        return None
    return HeroicTrait(id=row[0], army_id=row[1], name=row[2], description=row[3])


def list_heroic_traits(con: duckdb.DuckDBPyConnection, army_id: int) -> list[HeroicTrait]:
    rows = con.execute(
        "SELECT id, army_id, name, description FROM heroic_trait WHERE army_id = ? ORDER BY name",
        [army_id],
    ).fetchall()
    return [HeroicTrait(id=r[0], army_id=r[1], name=r[2], description=r[3]) for r in rows]


def add_artefact(con: duckdb.DuckDBPyConnection, artefact: Artefact) -> int:
    row = con.execute(
        "INSERT INTO artefact(army_id, name, description) VALUES (?, ?, ?) RETURNING id",
        [artefact.army_id, artefact.name, artefact.description],
    ).fetchone()
    return int(row[0])


def get_artefact_by_name(
    con: duckdb.DuckDBPyConnection, army_id: int, name: str
) -> Optional[Artefact]:
    row = con.execute(
        "SELECT id, army_id, name, description FROM artefact WHERE army_id = ? AND name = ?",
        [army_id, name],
    ).fetchone()
    if row is None:
        return None
    return Artefact(id=row[0], army_id=row[1], name=row[2], description=row[3])


def list_artefacts(con: duckdb.DuckDBPyConnection, army_id: int) -> list[Artefact]:
    rows = con.execute(
        "SELECT id, army_id, name, description FROM artefact WHERE army_id = ? ORDER BY name",
        [army_id],
    ).fetchall()
    return [Artefact(id=r[0], army_id=r[1], name=r[2], description=r[3]) for r in rows]


# ----- Compositions ---------------------------------------------------------

def _unit_points(con: duckdb.DuckDBPyConnection, unit_id: int) -> int:
    row = con.execute("SELECT points FROM unit WHERE id = ?", [unit_id]).fetchone()
    if row is None:
        raise ValueError(f"unit_id introuvable: {unit_id}")
    return int(row[0])


def compute_total_points(con: duckdb.DuckDBPyConnection, entries: Iterable[CompositionUnit]) -> int:
    total = 0
    for e in entries:
        pts = _unit_points(con, e.unit_id)
        total += pts * (2 if e.reinforced else 1)
    return total


def add_composition(con: duckdb.DuckDBPyConnection, composition: Composition) -> int:
    """Insère une composition et ses entrées. total_points est recalculé."""
    composition.total_points = compute_total_points(con, composition.entries)
    row = con.execute(
        """
        INSERT INTO composition(army_id, name, kind, format_points, total_points,
                                source, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            composition.army_id, composition.name, composition.kind,
            composition.format_points, composition.total_points,
            composition.source, composition.notes,
        ],
    ).fetchone()
    comp_id = int(row[0])
    for e in composition.entries:
        con.execute(
            """
            INSERT INTO composition_unit(composition_id, unit_id, reinforced,
                                          is_general, heroic_trait_id, artefact_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [comp_id, e.unit_id, e.reinforced, e.is_general,
             e.heroic_trait_id, e.artefact_id],
        )
    return comp_id


def get_composition(con: duckdb.DuckDBPyConnection, composition_id: int) -> Optional[Composition]:
    row = con.execute(
        """
        SELECT id, army_id, name, kind, format_points, total_points,
               source, notes, created_at
        FROM composition WHERE id = ?
        """,
        [composition_id],
    ).fetchone()
    if row is None:
        return None
    entries = _list_composition_entries(con, composition_id)
    return Composition(
        id=row[0], army_id=row[1], name=row[2], kind=row[3],
        format_points=row[4], total_points=row[5], source=row[6],
        notes=row[7], created_at=row[8], entries=entries,
    )


def get_composition_by_name(
    con: duckdb.DuckDBPyConnection, army_id: int, name: str
) -> Optional[Composition]:
    row = con.execute(
        "SELECT id FROM composition WHERE army_id = ? AND name = ?",
        [army_id, name],
    ).fetchone()
    return get_composition(con, int(row[0])) if row else None


def list_compositions(
    con: duckdb.DuckDBPyConnection,
    army_id: Optional[int] = None,
    kind: Optional[str] = None,
) -> list[Composition]:
    sql = "SELECT id FROM composition WHERE 1=1"
    params: list = []
    if army_id is not None:
        sql += " AND army_id = ?"
        params.append(army_id)
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY army_id, name"
    rows = con.execute(sql, params).fetchall()
    return [c for c in (get_composition(con, int(r[0])) for r in rows) if c is not None]


def _list_composition_entries(
    con: duckdb.DuckDBPyConnection, composition_id: int
) -> list[CompositionUnit]:
    rows = con.execute(
        """
        SELECT id, composition_id, unit_id, reinforced, is_general,
               heroic_trait_id, artefact_id
        FROM composition_unit WHERE composition_id = ? ORDER BY id
        """,
        [composition_id],
    ).fetchall()
    return [
        CompositionUnit(
            id=r[0], composition_id=r[1], unit_id=r[2], reinforced=bool(r[3]),
            is_general=bool(r[4]), heroic_trait_id=r[5], artefact_id=r[6],
        )
        for r in rows
    ]



def add_composition_entry(
    con: duckdb.DuckDBPyConnection,
    composition_id: int,
    entry: CompositionUnit,
) -> int:
    """Ajoute une entrée à une composition existante et met à jour le total."""
    row = con.execute(
        """
        INSERT INTO composition_unit(composition_id, unit_id, reinforced,
                                      is_general, heroic_trait_id, artefact_id)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [composition_id, entry.unit_id, entry.reinforced, entry.is_general,
         entry.heroic_trait_id, entry.artefact_id],
    ).fetchone()
    _refresh_total_points(con, composition_id)
    return int(row[0])


def remove_composition_entry(con: duckdb.DuckDBPyConnection, entry_id: int) -> bool:
    """Supprime une entrée de composition. Retourne True si une ligne a été supprimée."""
    row = con.execute(
        "SELECT composition_id FROM composition_unit WHERE id = ?", [entry_id]
    ).fetchone()
    if row is None:
        return False
    composition_id = int(row[0])
    con.execute("DELETE FROM composition_unit WHERE id = ?", [entry_id])
    _refresh_total_points(con, composition_id)
    return True


def delete_composition(con: duckdb.DuckDBPyConnection, composition_id: int) -> bool:
    """Supprime une composition et toutes ses entrées."""
    row = con.execute("SELECT id FROM composition WHERE id = ?", [composition_id]).fetchone()
    if row is None:
        return False
    con.execute("DELETE FROM composition_unit WHERE composition_id = ?", [composition_id])
    con.execute("DELETE FROM composition WHERE id = ?", [composition_id])
    return True


def clone_composition(
    con: duckdb.DuckDBPyConnection,
    source_id: int,
    new_name: str,
    kind: str = "custom",
) -> int:
    """Duplique une composition (par défaut en 'custom')."""
    source = get_composition(con, source_id)
    if source is None:
        raise ValueError(f"composition introuvable: {source_id}")
    clone = Composition(
        army_id=source.army_id, name=new_name, kind=kind,  # type: ignore[arg-type]
        format_points=source.format_points,
        source=f"clone of #{source_id} ({source.name})",
        notes=source.notes,
        entries=[
            CompositionUnit(
                unit_id=e.unit_id, reinforced=e.reinforced, is_general=e.is_general,
                heroic_trait_id=e.heroic_trait_id, artefact_id=e.artefact_id,
            )
            for e in source.entries
        ],
    )
    return add_composition(con, clone)


def _refresh_total_points(con: duckdb.DuckDBPyConnection, composition_id: int) -> None:
    entries = _list_composition_entries(con, composition_id)
    total = compute_total_points(con, entries)
    con.execute(
        "UPDATE composition SET total_points = ? WHERE id = ?",
        [total, composition_id],
    )



# ----- Benchmarks -----------------------------------------------------------

def save_benchmark_result(
    con: duckdb.DuckDBPyConnection,
    *,
    attacker_id: int,
    defender_id: int,
    attacker_reinforced: bool,
    defender_reinforced: bool,
    attacker_charged: bool,
    defender_charged: bool,
    attacker_mode: str,
    defender_mode: str,
    raw_a_to_b: float,
    expected_a_to_b: float,
    raw_b_to_a: float,
    expected_b_to_a: float,
    pts_destroyed: float,
    pts_lost: float,
    pts_net: float,
    roi: float,
) -> None:
    """Upsert d'un résultat de duel (clé : attacker × defender × options × modes)."""
    now = datetime.now()
    con.execute(
        """
        INSERT INTO unit_benchmark (
            attacker_id, defender_id,
            attacker_reinforced, defender_reinforced,
            attacker_charged, defender_charged, attacker_mode, defender_mode,
            raw_a_to_b, expected_a_to_b, raw_b_to_a, expected_b_to_a,
            pts_destroyed, pts_lost, pts_net, roi, computed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (attacker_id, defender_id,
                     attacker_reinforced, defender_reinforced,
                     attacker_charged, defender_charged, attacker_mode, defender_mode)
        DO UPDATE SET
            raw_a_to_b      = EXCLUDED.raw_a_to_b,
            expected_a_to_b = EXCLUDED.expected_a_to_b,
            raw_b_to_a      = EXCLUDED.raw_b_to_a,
            expected_b_to_a = EXCLUDED.expected_b_to_a,
            pts_destroyed   = EXCLUDED.pts_destroyed,
            pts_lost        = EXCLUDED.pts_lost,
            pts_net         = EXCLUDED.pts_net,
            roi             = EXCLUDED.roi,
            computed_at     = EXCLUDED.computed_at
        """,
        [
            attacker_id, defender_id,
            attacker_reinforced, defender_reinforced,
            attacker_charged, defender_charged, attacker_mode, defender_mode,
            raw_a_to_b, expected_a_to_b, raw_b_to_a, expected_b_to_a,
            pts_destroyed, pts_lost, pts_net, roi, now,
        ],
    )


_BENCH_COLS = (
    "attacker_id, defender_id, attacker_reinforced, defender_reinforced, "
    "attacker_charged, defender_charged, attacker_mode, defender_mode, "
    "raw_a_to_b, expected_a_to_b, raw_b_to_a, expected_b_to_a, pts_destroyed, "
    "pts_lost, pts_net, roi, computed_at"
)


def _fmt_bench_value(v: object) -> str:
    """Sérialise un Python value en littéral SQL pour les colonnes de unit_benchmark."""
    if v is True:
        return "TRUE"
    if v is False:
        return "FALSE"
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ', timespec='microseconds')}'"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def save_benchmark_results_many(
    con: duckdb.DuckDBPyConnection,
    rows: list[tuple],
) -> None:
    """Upsert batch des résultats de duel (mêmes colonnes que save_benchmark_result).

    Stratégie : INSERT VALUES inlinés vers une TEMP table sans contraintes, puis
    une seule INSERT-SELECT … ON CONFLICT vers `unit_benchmark`. `executemany`
    DuckDB facture ~150 ms/ligne, l'INSERT inliné < 2 ms/ligne.
    """
    if not rows:
        return
    values_sql = ",".join(
        "(" + ",".join(_fmt_bench_value(v) for v in row) + ")" for row in rows
    )
    con.execute("DROP TABLE IF EXISTS _unit_benchmark_stg")
    con.execute(
        "CREATE TEMP TABLE _unit_benchmark_stg AS "
        "SELECT * FROM unit_benchmark LIMIT 0"
    )
    con.execute(
        f"INSERT INTO _unit_benchmark_stg ({_BENCH_COLS}) VALUES {values_sql}"
    )
    con.execute(
        f"""
        INSERT INTO unit_benchmark ({_BENCH_COLS})
        SELECT {_BENCH_COLS} FROM _unit_benchmark_stg
        ON CONFLICT (attacker_id, defender_id,
                     attacker_reinforced, defender_reinforced,
                     attacker_charged, defender_charged, attacker_mode, defender_mode)
        DO UPDATE SET
            raw_a_to_b      = EXCLUDED.raw_a_to_b,
            expected_a_to_b = EXCLUDED.expected_a_to_b,
            raw_b_to_a      = EXCLUDED.raw_b_to_a,
            expected_b_to_a = EXCLUDED.expected_b_to_a,
            pts_destroyed   = EXCLUDED.pts_destroyed,
            pts_lost        = EXCLUDED.pts_lost,
            pts_net         = EXCLUDED.pts_net,
            roi             = EXCLUDED.roi,
            computed_at     = EXCLUDED.computed_at
        """
    )
    con.execute("DROP TABLE _unit_benchmark_stg")


def clear_benchmark_results(con: duckdb.DuckDBPyConnection) -> int:
    """Vide la table des benchmarks. Retourne le nombre de lignes supprimées."""
    row = con.execute(
        "SELECT COUNT(*) FROM unit_benchmark"
    ).fetchone()
    count = int(row[0]) if row else 0
    con.execute("DELETE FROM unit_benchmark")
    return count


#: Même agrégation que `reports/aggregate.py::QUERY` (scénario sans charge
#: déclarée, attaquant lu au plancher pessimiste 66%, défenseur à l'espérance),
#: mais lue *live* depuis `unit_benchmark` plutôt que depuis son export JSON
#: (`scratch/per_unit_nocharge_floor66_TM.json`) — utilisée par
#: `orchestration/whatif.py` pour situer une unité hypothétique dans le même
#: pool que `reports/best_unites.py`/`best_heros.py::compute_ranked()` sans
#: dépendre d'un fichier généré séparément.
_RANKING_POOL_QUERY = """
with agg as (
    select
        u.id as unit_id,
        u.name as name,
        a.name as army,
        a.grand_alliance as grand_alliance,
        u.points as points,
        u.is_hero as is_hero,
        avg(b.roi) * 100.0 as avg_roi_pct,
        avg(b.pts_net) as avg_pts_net,
        quantile_cont(b.roi, 0.05) * 100.0 as roi_floor95_pct,
        quantile_cont(b.roi, 0.34) * 100.0 as roi_floor66_pct,
        quantile_cont(b.roi, 0.80) * 100.0 as roi_floor20_pct
    from unit_benchmark b
    join unit u on u.id = b.attacker_id
    join army a on a.id = u.army_id
    where b.attacker_charged = false and b.defender_charged = false
      and b.attacker_mode = 'floor66' and b.defender_mode = 'mean'
    group by u.id, u.name, a.name, a.grand_alliance, u.points, u.is_hero
)
select *, (roi_floor95_pct + roi_floor66_pct + roi_floor20_pct) / 3.0 as avg_floor_roi_pct
from agg
"""


def get_ranking_pool(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Une ligne par unité attaquante déjà benchmarkée (`unit_benchmark`), avec
    les mêmes colonnes que `reports/aggregate.py`'s export JSON — dont
    `avg_floor_roi_pct`, moyenne des quantiles 5e/34e/80e du ROI entre duels.
    Nécessite `aospy unit benchmark-all --charge none --attacker-mode floor66
    --defender-mode mean --include-heroes` (ou équivalent) pour être peuplée.
    """
    cols = [
        "unit_id", "name", "army", "grand_alliance", "points", "is_hero",
        "avg_roi_pct", "avg_pts_net",
        "roi_floor95_pct", "roi_floor66_pct", "roi_floor20_pct", "avg_floor_roi_pct",
    ]
    rows = con.execute(_RANKING_POOL_QUERY).fetchall()
    return [dict(zip(cols, r)) for r in rows]


# ----- Analyse des aptitudes (src/aospy/abilities/) ---------------------------

ABILITY_COLS = (
    "uid", "name", "source_kind", "group_name", "faction_id", "faction_name", "condition_text",
    "phase", "wahapedia_type", "is_reaction", "ability_keywords", "cost_type", "cost_value",
    "declare_text", "effect_text", "frequency", "turn_side", "scope", "range_inches",
    "wholly_within", "activation_prob", "variance", "scales_with_size", "target_keywords",
    "conditions", "ease", "power", "reliability", "interaction", "verdict", "rationale",
    "understood", "overridden", "analyzer_version", "analyzed_at",
    "resource_cost", "available_round", "friendly_target", "excludes_self",
)
ABILITY_OWNER_COLS = ("ability_uid", "faction_id", "faction_name", "owner_kind", "owner_name", "warscroll_id")
ABILITY_TAG_COLS = ("ability_uid", "tag")
ABILITY_EFFECT_COLS = ("ability_uid", "seq", "kind", "stat", "value", "dice", "side", "detail",
                       "weapon_scope", "weapon_name", "includes_companion", "target_keywords",
                       "target_condition", "requires", "duration")
_ABILITY_TABLES = ("ability_effect", "ability_tag", "ability_owner", "ability")


def _sql_literal(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    return "'" + str(v).replace("'", "''") + "'"


def _insert_rows(con: duckdb.DuckDBPyConnection, table: str, cols: tuple[str, ...],
                 rows: list[tuple], chunk: int = 500) -> None:
    """INSERT VALUES inliné par paquets (cf. save_benchmark_results_many : executemany est lent)."""
    for i in range(0, len(rows), chunk):
        values = ",".join(
            "(" + ",".join(_sql_literal(v) for v in row) + ")" for row in rows[i:i + chunk]
        )
        con.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES {values}")


def replace_ability_analyses(
    con: duckdb.DuckDBPyConnection,
    abilities: list[tuple],
    owners: list[tuple],
    tags: list[tuple],
    effects: list[tuple],
) -> None:
    """Remplace tout le contenu des tables `ability*` (une transaction).

    Les tuples suivent `ABILITY_COLS`/`ABILITY_OWNER_COLS`/`ABILITY_TAG_COLS`/
    `ABILITY_EFFECT_COLS` ; la conversion depuis `AbilityAnalysis` vit dans
    `abilities/pipeline.py::to_rows` (la persistance ne connaît pas ce modèle).
    """
    con.execute("BEGIN TRANSACTION")
    try:
        for table in _ABILITY_TABLES:
            con.execute(f"DELETE FROM {table}")
        _insert_rows(con, "ability", ABILITY_COLS, abilities)
        _insert_rows(con, "ability_owner", ABILITY_OWNER_COLS, owners)
        _insert_rows(con, "ability_tag", ABILITY_TAG_COLS, tags)
        _insert_rows(con, "ability_effect", ABILITY_EFFECT_COLS, effects)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def search_abilities(
    con: duckdb.DuckDBPyConnection,
    *,
    name: Optional[str] = None,
    faction: Optional[str] = None,
    owner: Optional[str] = None,
    tags: Iterable[str] = (),
    verdict: Optional[str] = None,
    source_kind: Optional[str] = None,
    order_by: str = "power",
    limit: int = 50,
) -> list[dict]:
    """Aptitudes filtrées (tous les tags demandés doivent être présents), triées décroissant.

    `faction`/`owner`/`name` : sous-chaîne insensible à la casse ; `faction` et
    `owner` portent sur n'importe quel porteur (une aptitude partagée apparaît une fois).
    """
    if order_by not in ("power", "ease", "reliability", "interaction", "name"):
        raise ValueError(f"tri inconnu : {order_by}")
    where, params = ["TRUE"], []
    if name:
        where.append("lower(a.name) LIKE ?")
        params.append(f"%{name.lower()}%")
    if verdict:
        where.append("a.verdict = ?")
        params.append(verdict)
    if source_kind:
        where.append("a.source_kind = ?")
        params.append(source_kind)
    if faction or owner:
        sub, sp = ["o.ability_uid = a.uid"], []
        if faction:
            sub.append("(lower(o.faction_name) LIKE ? OR lower(o.faction_id) = ?)")
            sp += [f"%{faction.lower()}%", faction.lower()]
        if owner:
            sub.append("lower(o.owner_name) LIKE ?")
            sp.append(f"%{owner.lower()}%")
        where.append(f"EXISTS (SELECT 1 FROM ability_owner o WHERE {' AND '.join(sub)})")
        params += sp
    for tag in tags:
        where.append("EXISTS (SELECT 1 FROM ability_tag t WHERE t.ability_uid = a.uid AND t.tag = ?)")
        params.append(tag)
    order = "a.name" if order_by == "name" else f"a.{order_by} DESC, a.name"
    rows = con.execute(
        f"""
        SELECT a.*,
               (SELECT string_agg(tag, ',' ORDER BY tag) FROM ability_tag t WHERE t.ability_uid = a.uid) AS tags,
               (SELECT string_agg(DISTINCT owner_name, ' ; ') FROM ability_owner o WHERE o.ability_uid = a.uid) AS owners
        FROM ability a
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT ?
        """,
        params + [limit],
    )
    cols = [d[0] for d in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def ability_stats(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple]]:
    """Décomptes pour piloter la qualité de l'analyse (verdicts, origines, tags)."""
    q = {
        "verdict": "SELECT verdict, count(*) FROM ability GROUP BY 1 ORDER BY 2 DESC",
        "source_kind": "SELECT source_kind, count(*), count(*) FILTER (WHERE NOT understood) "
                       "FROM ability GROUP BY 1 ORDER BY 2 DESC",
        "tag": "SELECT tag, count(*) FROM ability_tag GROUP BY 1 ORDER BY 2 DESC",
        "version": "SELECT analyzer_version, max(analyzed_at), count(*) FROM ability GROUP BY 1",
    }
    return {k: con.execute(sql).fetchall() for k, sql in q.items()}


def get_ability_effects(con: duckdb.DuckDBPyConnection, ability_uid: str) -> list[dict]:
    """Effets chiffrés d'une aptitude, avec leur périmètre, dans l'ordre d'extraction."""
    rows = con.execute(
        f"SELECT {','.join(ABILITY_EFFECT_COLS)} FROM ability_effect WHERE ability_uid = ? ORDER BY seq",
        [ability_uid],
    ).fetchall()
    return [dict(zip(ABILITY_EFFECT_COLS, r)) for r in rows]


#: Familles de cas suspects à revoir avec l'utilisateur (`aospy ability review`) : clé →
#: (libellé, condition SQL sur `a` = ability). L'ordre est celui de la revue.
ABILITY_REVIEW_CATEGORIES: dict[str, tuple[str, str]] = {
    "contresens": ("effet ami sur une cible ennemie (sens mal lu ?)",
                   "a.scope = 'one_enemy' AND EXISTS (SELECT 1 FROM ability_effect e WHERE e.ability_uid = a.uid "
                   # un buff offensif de « this unit » contre la cible qu'elle désigne est le cas normal
                   "AND e.kind = 'stat_mod' AND e.side = 'friendly' "
                   "AND coalesce(e.detail, '') NOT IN ('marquage', 'offensif'))"),
    "malus": ("malus détecté (vraie contrepartie ou contresens ?)",
              "EXISTS (SELECT 1 FROM ability_effect e WHERE e.ability_uid = a.uid AND e.detail = 'malus')"),
    "duree": ("buff ami dont la durée n'est pas écrite",
              "EXISTS (SELECT 1 FROM ability_effect e WHERE e.ability_uid = a.uid AND e.kind = 'stat_mod' "
              "AND e.side = 'friendly' AND e.duration = 'non précisée')"),
    "portee": ("effet reconnu mais portée inconnue", "a.scope = 'unknown' AND a.understood"),
    "a-revoir": ("aucun effet reconnu", "a.verdict = 'a-revoir'"),
}


def ability_review_queue(con: duckdb.DuckDBPyConnection, category: str,
                         exclude_uids: Iterable[str] = (), limit: int = 15) -> tuple[int, list[dict]]:
    """(nombre restant, lot d'aptitudes) d'une famille de cas suspects, hors uids déjà revus."""
    if category not in ABILITY_REVIEW_CATEGORIES:
        raise ValueError(f"famille inconnue : {category} ({', '.join(ABILITY_REVIEW_CATEGORIES)})")
    where = ABILITY_REVIEW_CATEGORIES[category][1]
    excluded = list(exclude_uids)
    not_in = f" AND a.uid NOT IN (SELECT unnest(?::VARCHAR[]))" if excluded else ""
    params = [excluded] if excluded else []
    total = con.execute(f"SELECT count(*) FROM ability a WHERE {where}{not_in}", params).fetchone()[0]
    rows = con.execute(
        f"SELECT a.uid, a.name, a.faction_id, a.verdict, a.condition_text, a.declare_text, a.effect_text "
        f"FROM ability a WHERE {where}{not_in} ORDER BY a.faction_id, a.name LIMIT ?", params + [limit])
    cols = [d[0] for d in rows.description]
    return total, [dict(zip(cols, r)) for r in rows.fetchall()]


# ----- Châssis (analysis/chassis.py) -------------------------------------------

CHASSIS_COLS = (
    "unit_id", "name", "army_id", "points", "is_hero", "unit_type", "models", "health", "save", "ward",
    "move", "is_flying", "dmg_melee", "dmg_ranged", "effective_wounds", "dmg_per_100", "ewounds_per_100",
    "attacks_total", "share_melee", "share_damage1", "share_companion", "crit_type", "dmg_pct_rank",
    "ewounds_pct_rank", "cost_residual_pct", "duel_roi_pct", "built_at",
)


def duel_roi_by_unit(con: duckdb.DuckDBPyConnection) -> dict[int, float]:
    """avg_floor_roi_pct par unité attaquante (même lecture que reports/aggregate.py)."""
    rows = con.execute(
        """
        SELECT attacker_id,
               100.0 * (quantile_cont(roi, 0.05) + quantile_cont(roi, 0.34) + quantile_cont(roi, 0.80)) / 3.0
        FROM unit_benchmark
        WHERE NOT attacker_charged AND NOT defender_charged
          AND attacker_mode = 'floor66' AND defender_mode = 'mean'
        GROUP BY attacker_id
        """
    ).fetchall()
    return {int(uid): float(v) for uid, v in rows}


def replace_chassis(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `unit_chassis` (tuples dans l'ordre de `CHASSIS_COLS`)."""
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM unit_chassis")
        _insert_rows(con, "unit_chassis", CHASSIS_COLS, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def list_chassis(
    con: duckdb.DuckDBPyConnection, *, army: Optional[str] = None, hero: Optional[bool] = None,
    name: Optional[str] = None, order_by: str = "dmg_per_100", ascending: bool = False, limit: int = 30,
) -> list[dict]:
    """Châssis filtrés (armée = sous-chaîne, héros/troupes) et triés."""
    allowed = {"dmg_per_100", "ewounds_per_100", "dmg_pct_rank", "ewounds_pct_rank", "cost_residual_pct",
               "duel_roi_pct", "points", "share_damage1", "share_companion", "name"}
    if order_by not in allowed:
        raise ValueError(f"tri inconnu : {order_by} ({', '.join(sorted(allowed))})")
    where, params = ["TRUE"], []
    if army:
        where.append("lower(ar.name) LIKE ?")
        params.append(f"%{army.lower()}%")
    if hero is not None:
        where.append("c.is_hero = ?")
        params.append(hero)
    if name:
        where.append("lower(c.name) LIKE ?")
        params.append(f"%{name.lower()}%")
    direction = "ASC" if ascending else "DESC"
    rows = con.execute(
        f"""SELECT c.*, ar.name AS army_name FROM unit_chassis c JOIN army ar ON ar.id = c.army_id
            WHERE {' AND '.join(where)} ORDER BY c.{order_by} {direction} NULLS LAST, c.name LIMIT ?""",
        params + [limit],
    )
    cols = [d[0] for d in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


# ----- Couche 3 : rencontre aptitude × châssis (analysis/encounter.py) ----------

def replace_encounters(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `ability_encounter` (tuples dans l'ordre de `encounter.ENCOUNTER_COLS`)."""
    from ..analysis.encounter import ENCOUNTER_COLS

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM ability_encounter")
        _insert_rows(con, "ability_encounter", ENCOUNTER_COLS, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def list_encounters(
    con: duckdb.DuckDBPyConnection, *, unit: Optional[str] = None, ability: Optional[str] = None,
    relation: Optional[str] = None, order_by: str = "gain", limit: int = 30,
) -> list[dict]:
    """Rencontres filtrées (unité / aptitude = sous-chaîne), triées par gain décroissant.

    `gain` = le plus grand des deux gains en % (offense, défense)."""
    where, params = ["TRUE"], []
    if unit:
        where.append("lower(u.name) LIKE ?")
        params.append(f"%{unit.lower()}%")
    if ability:
        where.append("lower(a.name) LIKE ?")
        params.append(f"%{ability.lower()}%")
    if relation:
        where.append("e.relation = ?")
        params.append(relation)
    order = {"gain": "greatest(coalesce(e.off_gain_pct, 0), coalesce(e.def_gain_pct, 0))",
             "off_per_100": "e.off_gain_per_100", "def_per_100": "e.def_gain_per_100"}[order_by]
    cur = con.execute(
        f"""SELECT e.*, a.name AS ability_name, a.verdict, a.activation_prob, a.frequency,
                   ef.kind, ef.stat, ef.value, ef.weapon_scope, ef.weapon_name,
                   u.name AS unit_name, u.points, ar.name AS army_name
            FROM ability_encounter e
            JOIN ability a ON a.uid = e.ability_uid
            JOIN ability_effect ef ON ef.ability_uid = e.ability_uid AND ef.seq = e.seq
            JOIN unit u ON u.id = e.unit_id JOIN army ar ON ar.id = u.army_id
            WHERE {' AND '.join(where)}
            ORDER BY {order} DESC NULLS LAST, a.name, u.name LIMIT ?""",
        [*params, limit],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def replace_realized(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `unit_realized` (tuples dans l'ordre de `realized.REALIZED_COLS`)."""
    from ..analysis.realized import REALIZED_COLS

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM unit_realized")
        _insert_rows(con, "unit_realized", REALIZED_COLS, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def list_realized(
    con: duckdb.DuckDBPyConnection, *, army: Optional[str] = None, hero: Optional[bool] = None,
    name: Optional[str] = None, order_by: str = "off_realized_per_100", limit: int = 30,
) -> list[dict]:
    """Valeur réalisée par unité, filtrée (armée/nom = sous-chaîne, héros/troupes) et triée décroissante."""
    allowed = {"off_realized_per_100", "def_realized_per_100", "off_good_per_100", "def_good_per_100",
               "off_gain", "def_gain"}
    if order_by not in allowed:
        raise ValueError(f"tri inconnu : {order_by}")
    order = {"off_gain": "r.off_realized / nullif(r.off_chassis, 0)",
             "def_gain": "r.def_realized / nullif(r.def_chassis, 0)"}.get(order_by, f"r.{order_by}")
    where, params = ["TRUE"], []
    if army:
        where.append("lower(ar.name) LIKE ?")
        params.append(f"%{army.lower()}%")
    if hero is not None:
        where.append("u.is_hero = ?")
        params.append(hero)
    if name:
        where.append("lower(u.name) LIKE ?")
        params.append(f"%{name.lower()}%")
    cur = con.execute(
        f"""SELECT r.*, u.name, u.points, u.is_hero, ar.name AS army_name
            FROM unit_realized r JOIN unit u ON u.id = r.unit_id JOIN army ar ON ar.id = u.army_id
            WHERE {' AND '.join(where)} ORDER BY {order} DESC NULLS LAST, u.name LIMIT ?""",
        [*params, limit],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

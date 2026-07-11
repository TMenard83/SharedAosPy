"""CRUD pour les armées, unités, armes, traits, artefacts et compositions."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import duckdb

from .models import (
    Army,
    Artefact,
    Composition,
    CompositionUnit,
    HeroicTrait,
    Unit,
    Weapon,
)


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
                         models, points, is_hero, ward)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            unit.army_id, unit.name, unit.move, unit.save, unit.health,
            unit.control, unit.models, unit.points, unit.is_hero, unit.ward,
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
                           wound, rend, damage, abilities, wielders)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            unit_id, weapon.name, weapon.kind, weapon.range_in, weapon.attacks,
            weapon.hit, weapon.wound, weapon.rend, weapon.damage, weapon.abilities,
            weapon.wielders,
        ],
    ).fetchone()
    return int(row[0])


def get_unit(con: duckdb.DuckDBPyConnection, unit_id: int) -> Optional[Unit]:
    row = con.execute(
        """
        SELECT id, army_id, name, move, save, health, control,
               models, points, is_hero, ward
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
        is_hero=bool(row[9]), ward=row[10], weapons=weapons,
    )


def list_units_for_army(con: duckdb.DuckDBPyConnection, army_id: int) -> list[Unit]:
    rows = con.execute(
        """
        SELECT id, army_id, name, move, save, health, control,
               models, points, is_hero, ward
        FROM unit WHERE army_id = ? ORDER BY name
        """,
        [army_id],
    ).fetchall()
    units: list[Unit] = []
    for r in rows:
        units.append(Unit(
            id=r[0], army_id=r[1], name=r[2], move=r[3], save=r[4],
            health=r[5], control=r[6], models=r[7], points=r[8],
            is_hero=bool(r[9]), ward=r[10], weapons=_list_weapons(con, r[0]),
        ))
    return units


def _list_weapons(con: duckdb.DuckDBPyConnection, unit_id: int) -> list[Weapon]:
    rows = con.execute(
        """
        SELECT id, unit_id, name, kind, range_in, attacks, hit, wound,
               rend, damage, abilities, wielders
        FROM weapon WHERE unit_id = ? ORDER BY kind, name
        """,
        [unit_id],
    ).fetchall()
    return [
        Weapon(
            id=r[0], unit_id=r[1], name=r[2], kind=r[3], range_in=r[4],
            attacks=r[5], hit=r[6], wound=r[7], rend=r[8], damage=r[9],
            abilities=r[10], wielders=r[11],
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
               models, points, is_hero, ward
        FROM unit ORDER BY army_id, name
        """,
    ).fetchall()
    weapon_rows = con.execute(
        """
        SELECT id, unit_id, name, kind, range_in, attacks, hit, wound,
               rend, damage, abilities, wielders
        FROM weapon ORDER BY unit_id, kind, name
        """,
    ).fetchall()
    weapons_by_unit: dict[int, list[Weapon]] = {}
    for r in weapon_rows:
        weapons_by_unit.setdefault(int(r[1]), []).append(Weapon(
            id=r[0], unit_id=r[1], name=r[2], kind=r[3], range_in=r[4],
            attacks=r[5], hit=r[6], wound=r[7], rend=r[8], damage=r[9],
            abilities=r[10], wielders=r[11],
        ))
    by_army: dict[int, list[Unit]] = {}
    for r in unit_rows:
        unit = Unit(
            id=r[0], army_id=r[1], name=r[2], move=r[3], save=r[4],
            health=r[5], control=r[6], models=r[7], points=r[8],
            is_hero=bool(r[9]), ward=r[10],
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
                        models = ?, points = ?, is_hero = ?, ward = ?
        WHERE id = ?
        """,
        [
            unit.move, unit.save, unit.health, unit.control,
            unit.models, unit.points, unit.is_hero, unit.ward, unit_id,
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
    raw_a_to_b: float,
    expected_a_to_b: float,
    raw_b_to_a: float,
    expected_b_to_a: float,
    pts_destroyed: float,
    pts_lost: float,
    pts_net: float,
    roi: float,
) -> None:
    """Upsert d'un résultat de duel (clé : attacker × defender × options)."""
    now = datetime.now()
    con.execute(
        """
        INSERT INTO unit_benchmark (
            attacker_id, defender_id,
            attacker_reinforced, defender_reinforced,
            attacker_charged, defender_charged,
            raw_a_to_b, expected_a_to_b, raw_b_to_a, expected_b_to_a,
            pts_destroyed, pts_lost, pts_net, roi, computed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (attacker_id, defender_id,
                     attacker_reinforced, defender_reinforced,
                     attacker_charged, defender_charged)
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
            attacker_charged, defender_charged,
            raw_a_to_b, expected_a_to_b, raw_b_to_a, expected_b_to_a,
            pts_destroyed, pts_lost, pts_net, roi, now,
        ],
    )


_BENCH_COLS = (
    "attacker_id, defender_id, attacker_reinforced, defender_reinforced, "
    "attacker_charged, defender_charged, raw_a_to_b, expected_a_to_b, "
    "raw_b_to_a, expected_b_to_a, pts_destroyed, pts_lost, pts_net, roi, "
    "computed_at"
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
                     attacker_charged, defender_charged)
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

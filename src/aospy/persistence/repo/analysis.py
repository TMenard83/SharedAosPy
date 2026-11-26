"""Tables de résultats des couches 2 à 4 (`unit_chassis`, `ability_encounter`, `unit_realized`,
`ability_marriage`, `enhancement_bearer`)."""

from __future__ import annotations

from typing import Optional

import duckdb

from ..analysis_tables import BEARER_COLS, ENCOUNTER_COLS, MARRIAGE_COLS, REALIZED_COLS
from ._sql import _insert_rows

# ----- Châssis (analysis/layers/chassis.py) -------------------------------------------

CHASSIS_COLS = (
    "unit_id",
    "name",
    "army_id",
    "points",
    "is_hero",
    "unit_type",
    "models",
    "health",
    "save",
    "ward",
    "move",
    "is_flying",
    "dmg_melee",
    "dmg_ranged",
    "effective_wounds",
    "dmg_per_100",
    "ewounds_per_100",
    "attacks_total",
    "share_melee",
    "share_damage1",
    "share_companion",
    "crit_type",
    "dmg_pct_rank",
    "ewounds_pct_rank",
    "cost_residual_pct",
    "duel_roi_pct",
    "built_at",
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
    con: duckdb.DuckDBPyConnection,
    *,
    army: Optional[str] = None,
    hero: Optional[bool] = None,
    name: Optional[str] = None,
    order_by: str = "dmg_per_100",
    ascending: bool = False,
    limit: int = 30,
) -> list[dict]:
    """Châssis filtrés (armée = sous-chaîne, héros/troupes) et triés."""
    allowed = {
        "dmg_per_100",
        "ewounds_per_100",
        "dmg_pct_rank",
        "ewounds_pct_rank",
        "cost_residual_pct",
        "duel_roi_pct",
        "points",
        "share_damage1",
        "share_companion",
        "name",
    }
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
            WHERE {" AND ".join(where)} ORDER BY c.{order_by} {direction} NULLS LAST, c.name LIMIT ?""",
        params + [limit],
    )
    cols = [d[0] for d in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


# ----- Couche 3 : rencontre aptitude × châssis (analysis/layers/encounter.py) ----------


def replace_encounters(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `ability_encounter` (tuples dans l'ordre de `encounter.ENCOUNTER_COLS`)."""

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM ability_encounter")
        _insert_rows(con, "ability_encounter", ENCOUNTER_COLS, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def list_encounters(
    con: duckdb.DuckDBPyConnection,
    *,
    unit: Optional[str] = None,
    ability: Optional[str] = None,
    relation: Optional[str] = None,
    order_by: str = "gain",
    limit: int = 30,
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
    order = {
        "gain": "greatest(coalesce(e.off_gain_pct, 0), coalesce(e.def_gain_pct, 0))",
        "off_per_100": "e.off_gain_per_100",
        "def_per_100": "e.def_gain_per_100",
    }[order_by]
    cur = con.execute(
        f"""SELECT e.*, a.name AS ability_name, a.verdict, a.activation_prob, a.frequency,
                   ef.kind, ef.stat, ef.value, ef.weapon_scope, ef.weapon_name,
                   u.name AS unit_name, u.points, ar.name AS army_name
            FROM ability_encounter e
            JOIN ability a ON a.uid = e.ability_uid
            JOIN ability_effect ef ON ef.ability_uid = e.ability_uid AND ef.seq = e.seq
            JOIN unit u ON u.id = e.unit_id JOIN army ar ON ar.id = u.army_id
            WHERE {" AND ".join(where)}
            ORDER BY {order} DESC NULLS LAST, a.name, u.name LIMIT ?""",
        [*params, limit],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def replace_realized(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `unit_realized` (tuples dans l'ordre de `realized.REALIZED_COLS`)."""

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM unit_realized")
        _insert_rows(con, "unit_realized", REALIZED_COLS, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def replace_ability_marriage(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `ability_marriage` (tuples dans l'ordre de `marriage.MARRIAGE_COLS`)."""

    con.execute("DELETE FROM ability_marriage")
    _insert_rows(con, "ability_marriage", MARRIAGE_COLS, rows)


def list_marriage(
    con: duckdb.DuckDBPyConnection,
    *,
    ability: Optional[str] = None,
    unit: Optional[str] = None,
    family: Optional[str] = None,
    worst: bool = False,
    limit: int = 30,
) -> list[dict]:
    """Mariages aptitude × porteur, filtrés (sous-chaînes), triés par mariage décroissant (ou croissant)."""
    where, params = ["TRUE"], []
    if ability:
        where.append("lower(m.ability_name) LIKE ?")
        params.append(f"%{ability.lower()}%")
    if unit:
        where.append("lower(u.name) LIKE ?")
        params.append(f"%{unit.lower()}%")
    if family:
        where.append("m.family = ?")
        params.append(family)
    cur = con.execute(
        f"""SELECT m.*, u.name AS unit_name, u.points, u.move, u.health * u.models AS hp, u.save, u.ward,
                   ar.name AS army_name
            FROM ability_marriage m JOIN unit u ON u.id = m.unit_id JOIN army ar ON ar.id = u.army_id
            WHERE {" AND ".join(where)}
            ORDER BY m.marriage {"ASC" if worst else "DESC"}, m.power DESC NULLS LAST, u.name LIMIT ?""",
        [*params, limit],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def replace_enhancement_bearers(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Remplace tout le contenu de `enhancement_bearer` (tuples dans l'ordre de `bearers.BEARER_COLS`)."""

    con.execute("DELETE FROM enhancement_bearer")
    _insert_rows(con, "enhancement_bearer", BEARER_COLS, rows)


def list_enhancement_bearers(
    con: duckdb.DuckDBPyConnection,
    *,
    ability: Optional[str] = None,
    unit: Optional[str] = None,
    army: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 40,
) -> list[dict]:
    """Optimisation × porteur éligible, triés par optimisation puis valeur (sinon mariage, puis porteur)."""
    where, params = ["TRUE"], []
    if ability:
        where.append("lower(b.ability_name) LIKE ?")
        params.append(f"%{ability.lower()}%")
    if unit:
        where.append("lower(u.name) LIKE ?")
        params.append(f"%{unit.lower()}%")
    if army:
        where.append("lower(b.faction_name) LIKE ?")
        params.append(f"%{army.lower()}%")
    if kind:
        where.append("b.source_kind = ?")
        params.append(kind)
    cur = con.execute(
        f"""SELECT b.*, u.name AS unit_name, u.points, u.move, u.health * u.models AS hp, u.save, u.ward,
                   a.group_name
            FROM enhancement_bearer b JOIN unit u ON u.id = b.unit_id JOIN ability a ON a.uid = b.ability_uid
            WHERE {" AND ".join(where)}
            ORDER BY b.ability_name, a.group_name, b.ability_uid, b.value DESC NULLS LAST, b.marriage DESC,
                     b.bearer_combined DESC
            LIMIT ?""",
        [*params, limit],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_realized(
    con: duckdb.DuckDBPyConnection,
    *,
    army: Optional[str] = None,
    hero: Optional[bool] = None,
    name: Optional[str] = None,
    order_by: str = "score_per_100",
    limit: int = 30,
) -> list[dict]:
    """Valeur réalisée par unité, filtrée (armée/nom = sous-chaîne, héros/troupes) et triée décroissante."""
    allowed = {
        "score_per_100",
        "score_fit_per_100",
        "reach_in",
        "combined_per_100",
        "off_realized_per_100",
        "def_realized_per_100",
        "off_good_per_100",
        "def_good_per_100",
        "off_gain",
        "def_gain",
        "combined_fit_per_100",
        "off_fit_per_100",
        "def_fit_per_100",
    }
    if order_by not in allowed:
        raise ValueError(f"tri inconnu : {order_by}")
    order = {
        "off_gain": "r.off_realized / nullif(r.off_chassis, 0)",
        "def_gain": "r.def_realized / nullif(r.def_chassis, 0)",
    }.get(order_by, f"r.{order_by}")
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
            WHERE {" AND ".join(where)} ORDER BY {order} DESC NULLS LAST, u.name LIMIT ?""",
        [*params, limit],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ----- cascade des couches (analysis/layers/cascade.py) -------------------------------------------


def mark_layer_built(con: duckdb.DuckDBPyConnection, layer: int, fingerprint: str) -> None:
    """Enregistre le build de la couche `layer` avec l'empreinte de ses entrées."""
    con.execute(
        "INSERT OR REPLACE INTO layer_build VALUES (?, CURRENT_TIMESTAMP, ?)", [layer, fingerprint]
    )


def layer_builds(con: duckdb.DuckDBPyConnection) -> dict[int, tuple[str, str]]:
    """{couche: (built_at, empreinte)} ; vide si la table manque (base ouverte en lecture seule, ancienne)."""
    try:
        rows = con.execute("SELECT layer, CAST(built_at AS VARCHAR), fingerprint FROM layer_build").fetchall()
    except duckdb.CatalogException:
        return {}
    return {int(layer): (built, fp) for layer, built, fp in rows}


def unit_data_stamp(con: duckdb.DuckDBPyConnection) -> str:
    """Empreinte des données d'unités lues par la couche 2 : imports (unit, weapon) et duels (unit_benchmark)."""
    row = con.execute(
        """
        SELECT (SELECT COUNT(*) FROM unit), (SELECT CAST(MAX(imported_at) AS VARCHAR) FROM unit),
               (SELECT COUNT(*) FROM weapon),
               (SELECT COUNT(*) FROM unit_benchmark), (SELECT CAST(MAX(computed_at) AS VARCHAR) FROM unit_benchmark)
        """
    ).fetchone()
    return "|".join(str(v) for v in row)

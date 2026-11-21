"""Cache des duels `unit_benchmark` et pool de classement lu en direct."""

from __future__ import annotations

from datetime import datetime

import duckdb

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


#: Pool de classement « édition TM » (scénario sans charge déclarée, attaquant
#: lu au plancher pessimiste 66%, défenseur à l'espérance ; méthode détaillée
#: dans la docstring de `reports/aggregate.py`), lu *live* depuis
#: `unit_benchmark` — source unique des registres `reports/combat_*`/`best_*`
#: (`combat_report.build`, `best_report.compute_ranked`), du simulateur de bonus
#: (`bonus_simulator/whatif.py`) et de l'export JSON facultatif
#: `reports/aggregate.py`.
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
        100.0 * avg(case when b.roi > 0 then 1.0 else 0.0 end) as pct_positive,
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
    les colonnes de l'export JSON de `reports/aggregate.py` — dont
    `avg_floor_roi_pct`, moyenne des quantiles 5e/34e/80e du ROI entre duels.
    Nécessite `aospy unit benchmark-all --charge none --attacker-mode floor66
    --defender-mode mean --include-heroes` (ou équivalent) pour être peuplée.
    """
    cols = [
        "unit_id", "name", "army", "grand_alliance", "points", "is_hero",
        "avg_roi_pct", "avg_pts_net", "pct_positive",
        "roi_floor95_pct", "roi_floor66_pct", "roi_floor20_pct", "avg_floor_roi_pct",
    ]
    rows = con.execute(_RANKING_POOL_QUERY).fetchall()
    return [dict(zip(cols, r)) for r in rows]

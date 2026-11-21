"""Helpers d'insertion SQL en lot, partagés par les sous-modules de `repo/`."""

from __future__ import annotations

from datetime import datetime

import duckdb


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

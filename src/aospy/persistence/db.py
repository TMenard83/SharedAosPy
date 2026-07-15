"""Connexion DuckDB et initialisation du schéma."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data") / "aospy.duckdb"


def _read_schema() -> str:
    return resources.files("aospy.persistence").joinpath("schema.sql").read_text(encoding="utf-8")


def _migrate_floor95(con: duckdb.DuckDBPyConnection) -> None:
    """Renomme `unit_benchmark.floor80` -> `floor95` (v0.8416 -> v1.6449 sigma).

    Ne s'exécute qu'une fois (le rename fait disparaître `floor80`, donc le check
    `col_names` échoue ensuite). Les lignes `floor95=TRUE` héritées de l'ancien
    plancher 80% ne correspondent plus au 95% annoncé par leur nouveau nom : on
    les purge plutôt que de les exposer sous une étiquette fausse — elles seront
    recalculées par un prochain `benchmark-all --floor95`.
    """
    tables = con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    if ("unit_benchmark",) not in tables:
        return
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'unit_benchmark'"
    ).fetchall()}
    if "floor80" not in cols or "floor95" in cols:
        return
    con.execute("ALTER TABLE unit_benchmark RENAME COLUMN floor80 TO floor95")
    con.execute("DELETE FROM unit_benchmark WHERE floor95")


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Ouvre (ou crée) la base DuckDB et applique le schéma."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    _migrate_floor95(con)
    con.execute(_read_schema())
    return con


def reset(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Supprime la base existante (utile en dev/tests)."""
    path = Path(db_path)
    if path.exists():
        path.unlink()
    wal = path.with_suffix(path.suffix + ".wal")
    if wal.exists():
        wal.unlink()

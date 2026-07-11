"""Connexion DuckDB et initialisation du schéma."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data") / "aospy.duckdb"


def _read_schema() -> str:
    return resources.files("aospy").joinpath("schema.sql").read_text(encoding="utf-8")


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Ouvre (ou crée) la base DuckDB et applique le schéma."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
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

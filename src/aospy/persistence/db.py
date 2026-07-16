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


def _migrate_damage_mode(con: duckdb.DuckDBPyConnection) -> None:
    """Remplace la colonne unique `unit_benchmark.floor95` (BOOLEAN) par deux
    colonnes indépendantes `attacker_mode`/`defender_mode` ('mean'/'floor80'/
    'floor95'), pour permettre une lecture de dégât différente par sens de duel
    (cf. `orchestration/benchmark.py::DamageMode`). `floor95=TRUE` -> les deux
    valent 'floor95' ; `floor95=FALSE` -> 'mean' (seul mode utilisé jusqu'ici par
    cette colonne). Traduction 1:1, aucune donnée perdue. DuckDB ne permettant pas
    de modifier une clé primaire en place, la table est reconstruite.
    """
    tables = con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    if ("unit_benchmark",) not in tables:
        return
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'unit_benchmark'"
    ).fetchall()}
    if "floor95" not in cols or "attacker_mode" in cols:
        return
    con.execute("""
        CREATE TABLE unit_benchmark_new (
            attacker_id         INTEGER NOT NULL REFERENCES unit(id),
            defender_id         INTEGER NOT NULL REFERENCES unit(id),
            attacker_reinforced BOOLEAN NOT NULL DEFAULT FALSE,
            defender_reinforced BOOLEAN NOT NULL DEFAULT FALSE,
            attacker_charged    BOOLEAN NOT NULL DEFAULT FALSE,
            defender_charged    BOOLEAN NOT NULL DEFAULT FALSE,
            attacker_mode       VARCHAR NOT NULL DEFAULT 'mean',
            defender_mode       VARCHAR NOT NULL DEFAULT 'mean',
            raw_a_to_b          DOUBLE NOT NULL,
            expected_a_to_b     DOUBLE NOT NULL,
            raw_b_to_a          DOUBLE NOT NULL,
            expected_b_to_a     DOUBLE NOT NULL,
            pts_destroyed       DOUBLE NOT NULL,
            pts_lost            DOUBLE NOT NULL,
            pts_net             DOUBLE NOT NULL,
            roi                 DOUBLE NOT NULL,
            computed_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (attacker_id, defender_id,
                         attacker_reinforced, defender_reinforced,
                         attacker_charged, defender_charged,
                         attacker_mode, defender_mode)
        )
    """)
    con.execute("""
        INSERT INTO unit_benchmark_new
        SELECT attacker_id, defender_id, attacker_reinforced, defender_reinforced,
               attacker_charged, defender_charged,
               CASE WHEN floor95 THEN 'floor95' ELSE 'mean' END,
               CASE WHEN floor95 THEN 'floor95' ELSE 'mean' END,
               raw_a_to_b, expected_a_to_b, raw_b_to_a, expected_b_to_a,
               pts_destroyed, pts_lost, pts_net, roi, computed_at
        FROM unit_benchmark
    """)
    con.execute("DROP TABLE unit_benchmark")
    con.execute("ALTER TABLE unit_benchmark_new RENAME TO unit_benchmark")


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Ouvre (ou crée) la base DuckDB et applique le schéma."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    _migrate_floor95(con)
    _migrate_damage_mode(con)
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

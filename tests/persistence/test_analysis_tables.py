"""Les colonnes déclarées dans `persistence/analysis_tables.py` correspondent aux tables du schéma, et les
`replace_*` de `repository` les trouvent (régression : import manquant après leur déplacement, lot 3)."""

from __future__ import annotations

import pytest

from aospy.persistence import analysis_tables, db, repository

CASES = [
    ("ability_encounter", analysis_tables.ENCOUNTER_COLS, repository.replace_encounters),
    ("unit_realized", analysis_tables.REALIZED_COLS, repository.replace_realized),
    ("ability_marriage", analysis_tables.MARRIAGE_COLS, repository.replace_ability_marriage),
    ("enhancement_bearer", analysis_tables.BEARER_COLS, repository.replace_enhancement_bearers),
    ("unit_chassis", repository.CHASSIS_COLS, repository.replace_chassis),
]


@pytest.mark.parametrize("table, cols, replace", CASES, ids=[c[0] for c in CASES])
def test_analysis_table_columns_match_schema(tmp_path, table, cols, replace):
    con = db.connect(tmp_path / "t.duckdb")
    try:
        schema_cols = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
        assert set(cols) <= schema_cols
        replace(con, [])
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    finally:
        con.close()

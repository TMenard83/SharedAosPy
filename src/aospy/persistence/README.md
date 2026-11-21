# persistence — DuckDB, schéma, seul endroit où vit le SQL

Lire avant de modifier ce paquet (CLAUDE.md ne garde que la carte des couches).

## Modules

- **`persistence/db.py`** — opens a DuckDB connection at `DEFAULT_DB_PATH` (`data/aospy.duckdb`) and applies `persistence/schema.sql` on every `connect()` (idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations). Schema changes go in `schema.sql`, not in Python.
- **`persistence/repository.py`** — façade: re-exports every name (private ones included) of `persistence/repo/`, so callers keep `from ..persistence import repository` / `repository.x`. Add new queries to the matching `repo/` module, then to the façade's import list.
- **`persistence/repo/`** — all SQL lives here; nothing above this layer writes raw SQL. `units.py` (armies, units/weapons, heroic traits, artefacts, compositions — `Unit.keywords` (`frozenset[str]`) round-trips through one comma-joined `VARCHAR` column), `benchmarks.py` (`unit_benchmark` cache, live ranking pool), `abilities.py` (`ability*` tables), `analysis.py` (layers 2-4 result tables), `_sql.py` (`_sql_literal`/`_insert_rows`, inlined multi-row `INSERT` batches).
- **`persistence/analysis_tables.py`** — column tuples of the layer 3-4 result tables (`ENCOUNTER_COLS`, `REALIZED_COLS`, `MARRIAGE_COLS`, `BEARER_COLS`), defined here so `persistence/` never imports `analysis/`; `analysis/` builds its row tuples in that order. `CHASSIS_COLS` stays in `repo/analysis.py`. `tests/persistence/test_analysis_tables.py` checks them against `schema.sql`.
- **`persistence/seed.py`** — one-time JSON loaders (`data/json/armies.json`, `data/json/compositions.json`), idempotent by name.

## Tables et migrations

- **`unit_benchmark` table**: persisted duel-result cache keyed by `(attacker_id, defender_id, attacker_reinforced, defender_reinforced, attacker_charged, defender_charged, attacker_mode, defender_mode)`, populated via `benchmark-all`. `attacker_mode`/`defender_mode` (`"mean"`/`"floor66"`/`"floor80"`/`"floor95"`) let different confidence levels coexist per duel direction — see `orchestration/benchmark.py::DamageMode`. `repository.save_benchmark_results_many` batches upserts through a staged temp table (DuckDB `executemany` is ~150ms/row vs <2ms/row for an inlined multi-row `INSERT`).
- **Why `imported_at`/`unit_benchmark.attacker_mode`/`defender_mode` are declared directly in `CREATE TABLE`** rather than via the usual `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration: DuckDB silently resets a column's value to its `DEFAULT` if that statement re-runs on a column that already exists — which would wipe `imported_at` (or mislabel old mode rows) on every `connect()`. This column pair has been through two migrations, both one-shot table rewrites in `db.py::connect()`: `floor80` (BOOLEAN) → `floor95` (BOOLEAN, confidence level moved 80%→95%, `_migrate_floor95` purges leftover `floor95=TRUE` rows from the old formula) → `attacker_mode`/`defender_mode` (VARCHAR, `_migrate_damage_mode` rebuilds the table so each duel direction can read a different confidence level, translating old `floor95` values 1:1 with no data loss).

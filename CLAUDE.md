# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AoSPy computes expected-damage combat statistics for Age of Sigmar 4th edition armies. It stores armies/units/weapons/compositions in a local DuckDB file and exposes a French-language CLI (`aospy`) for querying duels, benchmarks, and full-army battle simulations. Domain text (docstrings, CLI help, output) is in French; keep new docstrings/help text in French for consistency.

## Setup & commands

```bash
pip install -e ".[dev]"        # editable install with pytest
python -m aospy <command>      # or `aospy <command>` once installed
```

Run tests:

```bash
pytest                         # full suite
pytest tests/test_combat.py    # single file
pytest tests/test_combat.py::test_prob_x_plus_basic   # single test
```

There is no configured linter; there is no `pytest.ini`/`tool.pytest.ini_options` in `pyproject.toml`, so pytest defaults apply (run from repo root).

Common CLI flows (all take `--db path/to.duckdb`, default `data/aospy.duckdb`):

```bash
aospy init                                  # create schema + seed data/armies.json (+ compositions.json)
aospy reset                                 # delete the DB file
aospy import bsdata --army "Stormcast Eternals"   # pull a live army from BSData (GitHub)
aospy import bsdata --all                   # import every known army
aospy unit duel --attacker X --defender Y
aospy unit benchmark --attacker X --charge a --detail
aospy unit benchmark-all --charge both -v   # persists all attacker×defender pairs to unit_benchmark
aospy battle simulate --a <comp_id> --b <comp_id> --charge both
```

## Architecture

Layers, bottom to top — each module only calls downward:

1. **`models.py`** — frozen/plain dataclasses for the domain (`Army`, `Weapon`, `Unit`, `HeroicTrait`, `Artefact`, `CompositionUnit`, `Composition`). No DB or logic.
2. **`db.py`** — opens a DuckDB connection at `DEFAULT_DB_PATH` (`data/aospy.duckdb`) and applies `schema.sql` on every `connect()` (idempotent `CREATE TABLE IF NOT EXISTS` + one `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration for `weapon.wielders`). Schema changes go in `schema.sql`, not in Python.
3. **`repository.py`** — all SQL lives here (CRUD for army/unit/weapon/heroic_trait/artefact/composition/composition_unit, plus `unit_benchmark` upsert helpers). Nothing above this layer writes raw SQL.
4. **`combat.py`** — pure math, no DB access. `expected_weapon_damage` computes expected damage for one weapon profile (hit → wound → save/rend → ward, with crit variants parsed from the free-text `abilities` field: `Crit (2 Hits)`, `Crit (Mortal)`, `Crit (Auto-Wound)`). `expected_unit_damage` sums across a unit's weapon profiles, scaling each weapon's wielder count by reinforcement.
5. **`benchmark.py`** / **`simulation.py`** — orchestration on top of `combat.py` + `repository.py`. `benchmark.py` does single-attacker-vs-many-defenders duels (`unit_duel`, `benchmark_attacker`, `run_all_benchmarks`) and persists results. `simulation.py` does full composition-vs-composition (`simulate_battle`, all-entries-vs-all-entries).
6. **`report.py`** — pure text formatting of `DuelResult`/`BattleReport` objects for terminal output. No computation.
7. **`cli.py`** / **`cli_commands.py`** — argparse wiring (`cli.py`) dispatching to one `cmd_*` function per subcommand (`cli_commands.py`). Each `cmd_*` opens its own DB connection via `_connect(args)` and closes it before returning.
8. **`bsdata.py`** — standalone importer: downloads `.cat` XML files from the `BSData/age-of-sigmar-4th` GitHub repo, parses BattleScribe profiles into `Unit`/`Weapon`, and upserts via `repository.replace_unit`. `KNOWN_ARMIES` maps army name → (main catalogue file, library file, grand alliance).
9. **`seed.py`** — one-time JSON loaders (`data/armies.json`, `data/compositions.json`) for hand-authored seed data, idempotent by name.

### Key domain concepts

- **Points economy**: every `DuelResult` computes `pts_destroyed`/`pts_lost`/`pts_net`/`roi` by scaling expected damage against the defender's/attacker's total points — this is how units are compared across point costs, not just raw damage.
- **Reinforcement**: doubles model count and points; `combat.py` scales each weapon's `wielders` count proportionally rather than assuming all models carry all weapons (matters for units with limited special-weapon loadouts).
- **Side modifiers**: charge (+1 melee attack), All-out Attack (+1 hit), All-out Defense (+1 save) are represented as `CombatModifiers`/`SideOptions` and threaded through as directional flags (attacker vs defender), configurable per-side via CLI flags (`--charge {a,b,both,none}`, `--aoa`, `--aod`).
- **`unit_benchmark` table**: a persisted cache of duel results keyed by `(attacker_id, defender_id, attacker_reinforced, defender_reinforced, attacker_charged, defender_charged)`, populated via `benchmark-all`. `repository.save_benchmark_results_many` batches upserts through a staged temp table because DuckDB's `executemany` is ~150ms/row vs <2ms/row for an inlined multi-row `INSERT`.
- **BSData import**: `wielders` (how many models in a unit actually carry a given weapon) is inferred from BattleScribe `constraints` on `selections` (min/max, scoped to `parent` or the unit itself) — see `_weapon_wielders`/`_entry_minmax` in `bsdata.py`. This is the trickiest part of the importer; if imported weapon counts look wrong, check constraint scope handling there first.

### Data files vs generated files

`data/armies.json` and `data/compositions.json` are hand-authored seed data (loaded by `seed.py` / `aospy init`). `data/aospy.duckdb` (default DB path) and the `bench_*.log`/`bench_*.txt`/`*_ranking_*.csv` files at repo root are generated/exploratory outputs, not source.

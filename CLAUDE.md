# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AoSPy computes expected-damage combat statistics for Age of Sigmar 4th edition armies. It stores armies/units/weapons/compositions in a local DuckDB file and exposes a French-language CLI (`aospy`) for querying duels, benchmarks, full-army battle simulations, ability analysis and tournament roster PDFs. Domain text (docstrings, CLI help, output) is in French; keep new docstrings/help text in French for consistency.

## Setup & commands

```bash
pip install -e ".[dev]"        # editable install with pytest, ruff, import-linter
pip install -e ".[analysis]"   # + pandas/statsmodels, only needed for `aospy cost ...`
pip install -e ".[gui]"        # + streamlit (implies [analysis]), only needed for the bonus simulator
pip install -e ".[roster]"     # + reportlab/pypdf, only needed for `aospy roster pdf`
python -m aospy <command>      # or `aospy <command>` once installed
streamlit run src/aospy/bonus_simulator/app.py   # bonus "what-if" simulator — see src/aospy/bonus_simulator/README.md
```

Run tests and checks (from repo root):

```bash
pytest                                       # full suite (golden PDF test included, ~100 s)
pytest -k "not golden"                       # fast run
pytest tests/engine/test_combat.py::test_prob_x_plus_basic   # single test
pytest tests/tournament_kit/test_pdf_golden.py --update-golden   # regenerate PDF references (= a behaviour change)
lint-imports                                 # layer contract (pyproject.toml)
ruff check                                   # E, F, I — existing warnings not fixed yet
```

`tests/` mirrors the `src/aospy/` sub-package layout. The golden test skips itself when the copyrighted sources (`data/Battle tome/`, `data/Manuel du général/`) are absent.

Common CLI flows (all take `--db path/to.duckdb`, default `data/aospy.duckdb`):

```bash
aospy init                                  # create schema + seed data/json/armies.json (+ compositions.json)
aospy reset                                 # delete the DB file
aospy import bsdata --army "Stormcast Eternals"   # pull a live army from BSData (GitHub)
aospy import bsdata --all                   # import every known army
aospy import wahapedia --faction "Stormcast Eternals"   # import from Wahapedia CSV instead
aospy import wahapedia --all                # import every known faction (data/wahapedia/*.csv)
aospy import bsdata --all --clean-stale     # also purges units an import no longer touched (see `imported_at`)
aospy import wahapedia --all --clean-stale  # same, for the Wahapedia importer
aospy import verify --faction X             # diff Wahapedia (DB) vs a local BSData .cat
aospy unit duel --attacker X --defender Y
aospy unit benchmark --attacker X --charge a --detail
aospy unit benchmark-all --charge both -v   # persists all attacker×defender pairs to unit_benchmark
aospy unit benchmark-all --charge both --attacker-mode floor95 --defender-mode floor95   # same, but persists the 95%-confidence floor instead of the mean
aospy unit benchmark-all --charge both --attacker-mode floor80 --defender-mode mean      # asymmetric: A→B at the 80%-confidence floor, B→A at the mean
aospy unit stats --attacker X [--charge]    # mean / std / 95%-confidence damage floor vs 3 standard targets
aospy battle simulate --a <comp_id> --b <comp_id> --charge both
aospy cost fit [--segmented]                # OLS points ~ features (needs `[analysis]`)
aospy cost residuals --top 20 --direction under   # most under/over-costed units by residual
aospy roster pdf --list "data/Proposition de listes/LRL L3 Avengers Wardens.txt"   # tournament PDF (needs `[roster]`)
aospy roster pdf --list "data/Proposition de listes/LRL L3 Avengers Wardens.txt" --mode fr   # same, French-verbatim mode (see tournament_kit/MODES.md)
aospy roster analyze --list <file> [--out x.md]   # layer 4: the numbers behind a list analysis
aospy ability analyze                       # (re)build the ability* tables from data/wahapedia/*.csv (~1.5 s)
aospy ability search --tag bulle-12 --tag buff-offensif --verdict plan --faction SE   # query by tag/faction/verdict
aospy ability show "Sow Confusion"          # full card: text, 4 axes, rationale, tags, effects + perimeter
aospy ability review [contresens|malus|duree|portee|a-revoir]   # suspicious cases to settle with the user
aospy chassis build                          # layer 2: bare-warscroll profiles → unit_chassis
aospy chassis list --troops --sort cost_residual_pct --asc      # cheapest chassis for their profile
aospy encounter build                        # layer 3: friendly ability effects × receivers' chassis → ability_encounter
aospy encounter list --unit "Liberators" [--own] [--sort off_per_100]   # what each buff really yields on that chassis
aospy encounter best | marriage | bearers --ability X   # best units, chassis × ability marriage, enhancement bearers
aospy l3 matchups | listes | diag | compare | scenarios | export-lists   # L3 league tools (options forwarded: `aospy l3 diag --help`)
```

`cost_model.fit_cost_model_factorial` is a library call, not wired to the CLI (see `analysis/README.md`).

## Architecture

`src/aospy/` is one sub-package per layer, bottom to top — each layer only calls downward (contract enforced by `lint-imports`; known violations are listed in `pyproject.toml`'s `ignore_imports`). **Read a package's `README.md` before modifying it** — it holds the design decisions, pitfalls and data conventions of that package.

| Package | Role | Details |
|---|---|---|
| `text.py` | shared text normalisation (`fold_name`), only for functions strictly identical across packages | module docstring |
| `sources/` | raw-data readers shared by importers, abilities and tournament kit: `wahapedia_csv.py` (pipe/BOM CSV reader, Legends, canonical dedup, expired variants) | [importers README](src/aospy/importers/README.md) |
| `domain/` | frozen/plain dataclasses (`Army`, `Weapon`, `Unit`, `HeroicTrait`, `Artefact`, `CompositionUnit`, `Composition`), no DB or logic | `models.py` |
| `persistence/` | DuckDB connection, `schema.sql` (applied on every `connect()`), **all SQL** in `repo/` (re-exported by `repository.py`), analysis-table columns in `analysis_tables.py`, JSON seed loaders | [README](src/aospy/persistence/README.md) |
| `engine/` | pure math: expected damage, exact damage distribution / floors, `Anti-X`/`Charge`, loadout parsing | [README](src/aospy/engine/README.md) |
| `orchestration/` | duels, benchmarks (`DamageMode` per direction), composition-vs-composition battles | [README](src/aospy/orchestration/README.md) |
| `importers/` | BSData and Wahapedia → same schema; source corrections, Legends filtering, companion merging, wielders | [README](src/aospy/importers/README.md) |
| `abilities/` | layer 1: context-free analysis of every ability (tables `ability*`) | [README](src/aospy/abilities/README.md) |
| `analysis/` | `cost/`: cost model (`[analysis]`), features, ranking score, adopted experiments; `layers/`: ability layers 2-4 (chassis, encounter, realized value, marriage, bearers, list analysis) — `layers` may import `cost`, never the reverse | [README](src/aospy/analysis/README.md) |
| `reports/` | PDF "best units/heroes"/duel/cost reports, read live from `unit_benchmark` via `repository.get_ranking_pool` | module docstrings |
| `bonus_simulator/` | Streamlit "what-if" bonus simulator (`[gui]`), no DB writes | [README](src/aospy/bonus_simulator/README.md) |
| `tournament_kit/` | tournament roster PDF (`[roster]`), no DB; roster modes | [README](src/aospy/tournament_kit/README.md) (+ `render/`, `sources/`, `MODES.md`) |
| `l3/` | L3 Centre 2026-27 league tools (matchup grids, diagnostics, list analysis, scenarios, list export), run by `aospy l3 …`; reads `data/aospy.duckdb` read-only | module docstring, skill `l3-matchups` |
| `cli/` | one module per command group (`db`, `unit`, `comp`, `battle`, `import_`, `cost`, `roster`, `ability`, `chassis`, `encounter`, `l3`), each with `register(sub)` and its `cmd_*` (each opens/closes its own DB connection via `common._connect(args)`); `__init__.py` only assembles them and exposes `main`; pure text formatting (`report.py`) | — |

## Cross-cutting rules

- French for docstrings, CLI help and output.
- Schema changes go in `persistence/schema.sql`, not in Python. Never re-run `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on a column holding real data (DuckDB resets it to its `DEFAULT` — see `persistence/README.md`).
- SQL lives only in `persistence/` (`repo/*.py`, imported through `repository.py`); nothing above that layer writes raw SQL.
- `engine/combat.py` ships in the base install (`duckdb` only): no numpy/pandas there; those stay behind `[analysis]`.
- Optional extras are checked at command time with an "install this extra" message (`cmd_cost_fit`, `cmd_roster_pdf`).
- Source precedence for warscroll data: `data/json/source_corrections.json` > latest rules update > scan > Wahapedia/BSData (`importers/README.md`).
- Hand-curated JSON (`data/json/`) is loaded fresh at each run, extended incrementally, never generated. Bump `abilities.pipeline.ANALYZER_VERSION` when ability extraction/scoring rules change.
- The roster PDF golden test (`tests/tournament_kit/test_pdf_golden.py`) is the judge of PDF behaviour: changing a reference is a behaviour change, to validate with the user.

## Data files vs generated files

Hand-authored / hand-curated (source, versioned):

- `data/json/armies.json`, `data/json/compositions.json` — seed data (`persistence/seed.py`, `aospy init`).
- `data/json/army_rules.json` — bonus simulator named army rules (`bonus_simulator/army_rules.py`, never touches the DB).
- `data/json/source_corrections.json` — verified warscroll/ability-text fixes, win over every source (`importers/corrections.py`).
- `data/json/ability_overrides.json` — manual ability-analysis corrections keyed by `uid` (`abilities/overrides.py`).
- `data/json/warscroll_index.json` — unit/rule/generic-manifestation-lore name → PDF page (`tournament_kit/sources/warscroll_index.py`, `warscroll-index` skill).
- `data/json/battle_tactic_cards.json` — the 6 Battle Tactic Cards, verbatim French (`tournament_kit/sources/tactic_cards.py`).
- `data/json/faction_rules_fr.json` — per-faction French verbatim/errata/season content for the French roster modes (`tournament_kit/sources/faction_rules_fr.py`, `faction-rules-fr` skill).
- `data/json/season_rules.json`, `data/json/generic_core_abilities.json` (+ `_en.json`) — season rules and the complete `MdG26-27 Aptitudes.pdf` (`tournament_kit/sources/{season_rules,generic_core_abilities}.py`).
- `data/json/roster_simplifications.json` — `*-split-simple` per-list simplifications (`tournament_kit/sources/roster_simplifications.py`; principles in `data/roster_simplifications.md`).

Sources read, not generated: `data/Battle tome/*.pdf` and `data/Manuel du général/*.pdf` (copyrighted, no text layer, not versioned — `MdG26-27 Tactiques.pdf` stays the source of truth for `battle_tactic_cards.json`; `sorts persistants - manifestations.pdf` is a user-supplied French scan), `data/Proposition de listes/*.txt` (App list exports), `data/wahapedia/*.csv` (same files as the StatHammer project; re-download to refresh — no network in the shell, ask the user), `data/bsdata/*.cat` (local BSData libraries for `import verify`, to be dropped there by hand when needed).

Generated / exploratory: `data/aospy.duckdb` (default DB path) and everything under `scratch/` (ad hoc scripts; their PDF/JSON outputs land in `scratch/output/`, roster PDFs in `scratch/output/roster/<équipe>/<liste>/`).

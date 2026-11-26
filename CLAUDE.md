# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

 
## Reduction de la consomation
   
  Think before acting. Read existing files before writing code.  
- Be concise in output.  
- Prefer editing over rewriting whole files.  
- Do not re-read files you have already read.  
- Test your code before declaring done.  
- No sycophantic openers or closing fluff.  
- Keep solutions simple and direct.  
- User instructions always override this file.  
   
## Langue
 - Reponse en francais


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

Common CLI flows (all take `--db path/to.duckdb`, default `data/aospy.duckdb`; options of each command: `aospy <group> <cmd> --help`):

```bash
aospy init | reset                          # schema + seed data/json/armies.json / delete the DB file
aospy import wahapedia|bsdata --all [--clean-stale]   # or --faction/--army X ; `import verify --faction X` = diff vs local .cat
aospy unit duel|benchmark|benchmark-all|stats     # benchmark-all persists unit_benchmark (--attacker-mode/--defender-mode mean|floorNN)
aospy battle simulate --a <comp_id> --b <comp_id> --charge both
aospy cost fit [--segmented] | residuals    # needs `[analysis]`
aospy roster pdf --list <file.txt> [--mode fr]    # needs `[roster]`, modes in tournament_kit/MODES.md
aospy roster analyze --list <file> [--out x.md]   # layer 4 numbers
aospy roster dossier --list <file> [--out dir]    # layer 4 + full texts/profiles (skill list-analysis)
aospy ability analyze | search | show | review    # layer 1 (ability* tables)
aospy chassis build|list ; aospy encounter build|list|best|marriage|bearers   # layers 2-3
aospy cascade [--status|--all|--start N] [--list <file> --out-root dir]   # rebuild stale layers 1 → 2 → 3, then layer 4
aospy l3 matchups|listes|diag|compare|scenarios|scenario-match|export-lists|plan-note|qui-tue-qui   # L3 league tools
```

`cost_model.fit_cost_model_factorial` is a library call, not wired to the CLI (see `analysis/README.md`).

## Architecture

`src/aospy/` is one sub-package per layer, bottom to top — each layer only calls downward (contract enforced by `lint-imports`; known violations are listed in `pyproject.toml`'s `ignore_imports`). **Read a package's `README.md` before modifying it** — it holds the design decisions, pitfalls and data conventions of that package. Some packages (`analysis/`, `abilities/`) keep a short README and put per-module detail in their `docs/`: read only the docs file of the module you touch, and add new notes there (not to the README).

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
| `cli/` | one module per command group (`db`, `unit`, `comp`, `battle`, `import_`, `cost`, `roster`, `ability`, `chassis`, `encounter`, `cascade`, `l3`), each with `register(sub)` and its `cmd_*` (each opens/closes its own DB connection via `common._connect(args)`); `__init__.py` only assembles them and exposes `main`; pure text formatting (`report.py`) | — |

## Cross-cutting rules

- **Layer cascade** (`analysis/layers/cascade.py`, table `layer_build`): each build of layers 1-3 stores a fingerprint of its inputs; a layer refuses to build/run (layer 4: `roster analyze|dossier`, `l3/layer4.indices`, `l3 plan-note`) while a layer below is stale. Fix with `aospy cascade`, never by bypassing the guard.
- Schema changes go in `persistence/schema.sql`, not in Python. Never re-run `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on a column holding real data (DuckDB resets it to its `DEFAULT` — see `persistence/README.md`).
- SQL lives only in `persistence/` (`repo/*.py`, imported through `repository.py`); nothing above that layer writes raw SQL.
- `engine/combat.py` ships in the base install (`duckdb` only): no numpy/pandas there; those stay behind `[analysis]`.
- Optional extras are checked at command time with an "install this extra" message (`cmd_cost_fit`, `cmd_roster_pdf`).
- Source precedence for warscroll data: `data/json/source_corrections.json` > latest rules update > scan > Wahapedia/BSData (`importers/README.md`).
- **Token economy**: never `Read` a whole `data/json/*.json` (`faction_rules_fr.json` is 2.7 MB, lines up to 4 000 chars) nor `tests/abilities/test_extract.py` (105 KB): query them with `jq`/`python -c` or `grep -n` + `Read` with `offset`/`limit`. Same for long command outputs: pipe through `head`/`cut -c`.
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

## Agents

- **Five agents at most at a time**, each in its own copy of the repo (`isolation: "worktree"`), without network, commit or push. Merging, validation (tests, `lint-imports`, golden test), commits and anything external stay in the main loop.
- **Model per task**: **Opus** for complex lots (engine maths, ability extraction/scoring rules, layers 2-4, tricky merges, roster PDF rendering); **Sonnet** for bounded code (CLI wiring, formatting, scripts, JSON curation from a given source, tests) and for research/search. No Haiku agents.
- Announce the model of each lot when a wave is launched.

## Quota and continuous work

- **Check the quota**: at the start of a session, and after each Claude Code restart, read it (`claude -p "/usage" --output-format text`: 5-hour session, week) and re-read it before launching any agents.
- **Thresholds**: at 95 % of the 5-hour session, launch nothing new and switch to economy mode (let in-flight agents finish, integrate their work). The week can go up to 98 %. Warn early, with the expected time, when a gauge is about to block. Resets are triggered by the user, never by Claude.
- **Long conversations cost the most** (context > 150k tokens dominates usage): when a conversation gets long, write the current state in memory (or the relevant README / `docs/`) and suggest restarting from a fresh session rather than going on.

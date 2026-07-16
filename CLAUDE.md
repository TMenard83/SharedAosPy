# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AoSPy computes expected-damage combat statistics for Age of Sigmar 4th edition armies. It stores armies/units/weapons/compositions in a local DuckDB file and exposes a French-language CLI (`aospy`) for querying duels, benchmarks, and full-army battle simulations. Domain text (docstrings, CLI help, output) is in French; keep new docstrings/help text in French for consistency.

## Setup & commands

```bash
pip install -e ".[dev]"        # editable install with pytest
pip install -e ".[analysis]"   # + pandas/statsmodels, only needed for `aospy cost ...`
python -m aospy <command>      # or `aospy <command>` once installed
```

Run tests:

```bash
pytest                                       # full suite
pytest tests/engine/test_combat.py           # single file
pytest tests/engine/test_combat.py::test_prob_x_plus_basic   # single test
```

There is no configured linter; there is no `pytest.ini`/`tool.pytest.ini_options` in `pyproject.toml`, so pytest defaults apply (run from repo root). `tests/` mirrors the `src/aospy/` sub-package layout below.

Common CLI flows (all take `--db path/to.duckdb`, default `data/aospy.duckdb`):

```bash
aospy init                                  # create schema + seed data/armies.json (+ compositions.json)
aospy reset                                 # delete the DB file
aospy import bsdata --army "Stormcast Eternals"   # pull a live army from BSData (GitHub)
aospy import bsdata --all                   # import every known army
aospy import wahapedia --faction "Stormcast Eternals"   # import from Wahapedia CSV instead
aospy import wahapedia --all                # import every known faction (data/wahapedia/*.csv)
aospy unit duel --attacker X --defender Y
aospy unit benchmark --attacker X --charge a --detail
aospy unit benchmark-all --charge both -v   # persists all attacker×defender pairs to unit_benchmark
aospy unit benchmark-all --charge both --attacker-mode floor95 --defender-mode floor95   # same, but persists the 95%-confidence floor instead of the mean
aospy unit benchmark-all --charge both --attacker-mode floor80 --defender-mode mean      # asymmetric: A→B at the 80%-confidence floor, B→A at the mean
aospy unit stats --attacker X [--charge]    # mean / std / 95%-confidence damage floor vs 3 standard targets
aospy battle simulate --a <comp_id> --b <comp_id> --charge both
aospy import bsdata --all --clean-stale     # also purges units an import no longer touched (see `imported_at`)
aospy import wahapedia --all --clean-stale  # same, for the Wahapedia importer
aospy cost fit [--segmented]                # OLS points ~ features (needs `[analysis]`)
aospy cost residuals --top 20 --direction under   # most under/over-costed units by residual
```

`cost_model.fit_cost_model_factorial` (single OLS with categorical factors + hero/troupe interaction terms) is available as a library call but not yet wired to the CLI — see "Cost model" below.

## Architecture

`src/aospy/` is one sub-package per layer, bottom to top — each layer only calls downward. Each sub-package's own docstring (`__init__.py`) gives the one-line summary; this list adds the cross-file wiring:

1. **`domain/models.py`** — frozen/plain dataclasses (`Army`, `Weapon`, `Unit`, `HeroicTrait`, `Artefact`, `CompositionUnit`, `Composition`). No DB or logic.
2. **`persistence/db.py`** — opens a DuckDB connection at `DEFAULT_DB_PATH` (`data/aospy.duckdb`) and applies `persistence/schema.sql` on every `connect()` (idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations). Schema changes go in `schema.sql`, not in Python.
3. **`persistence/repository.py`** — all SQL lives here; nothing above this layer writes raw SQL. `Unit.keywords` (`frozenset[str]`) round-trips through one comma-joined `VARCHAR` column.
4. **`engine/combat.py`** — pure math, no DB access. `expected_weapon_damage` (hit → wound → save/rend → ward, crit variants + intrinsic `Anti-X`/`Charge` bonuses parsed from `Weapon.abilities` — see "Intrinsic Anti-X/Charge bonuses" below) and its `E[D²]` twin `weapon_damage_moments` (→ `unit_damage_moments`, `damage_floor80`/`damage_floor95`). **Caveat**: `Weapon.attacks`/`damage` are integers resolved at import time (no dice notation kept), so variance only captures hit/wound/save/ward/crit randomness, not dice-valued attacks/damage.
5. **`engine/loadout.py`** — ported from StatHammer's `loadout.py`: parses `Unit.description` (free text) into per-weapon-profile model counts (`model_counts`). Best-effort, unrecognized clauses fall back to "every model carries every profile" (logged in the returned notes). Used by `combat.py::_effective_counts`.
6. **`orchestration/benchmark.py`** / **`orchestration/simulation.py`** — orchestration on `combat.py` + `repository.py`. `benchmark.py`: single-attacker-vs-many-defenders duels (`unit_duel`, `benchmark_attacker`, `run_all_benchmarks`), with independent `mode_a`/`mode_b: DamageMode` (`"mean"`/`"floor80"`/`"floor95"`) per duel direction — a duel need not read both sides at the same confidence level. `simulation.py`: full composition-vs-composition (`simulate_battle`, all-entries-vs-all-entries).
7. **`cli/report.py`** — pure text formatting of `DuelResult`/`BattleReport`/unit-stats rows. No computation.
8. **`cli/__init__.py`** (argparse wiring, exposes `main`) / **`cli/commands.py`** (one `cmd_*` per subcommand, each opens its own DB connection via `_connect(args)` and closes it before returning).
9. **`importers/bsdata.py`** — downloads `.cat` XML from `BSData/age-of-sigmar-4th` (GitHub), parses BattleScribe profiles, upserts via `repository.replace_unit`. `KNOWN_ARMIES` maps army name → (catalogue, library, grand alliance). `Unit.description` is left `None` (no BattleScribe equivalent found yet — BSData units keep the `wielders`-based allocation instead). Filters Legends/expired content and merges free companion units into their paid parent — see the two dedicated sections below.
10. **`importers/wahapedia.py`** — second importer, reading `data/wahapedia/*.csv` into the *same* schema via the same `repository.replace_unit`. Reuses `bsdata.parse_dice`/`parse_target`/`KNOWN_ARMIES`. See "Wahapedia import" below.
11. **`analysis/features.py`** / **`analysis/cost_model.py`** (needs `[analysis]`: pandas + statsmodels). `features.py::compute_features` probes a unit against three synthetic defenders (save 2+/4+/none) via `combat.py`'s moments engine → `UnitFeatures`. `cost_model.py` regresses `points ~ features` (OLS) three ways (`fit_cost_model`, `fit_segmented`, `fit_cost_model_factorial`) for coefficients + per-unit residuals. See "Cost model" below.
12. **`persistence/seed.py`** — one-time JSON loaders (`data/armies.json`, `data/compositions.json`), idempotent by name.

### Key domain concepts

- **Points economy**: every `DuelResult` computes `pts_destroyed`/`pts_lost`/`pts_net`/`roi` by scaling expected damage against the defender's/attacker's total points — units are compared across point costs, not just raw damage.
- **Reinforcement**: doubles model count and points; `combat.py::_effective_counts` scales per-profile model counts (from `loadout.model_counts` or `weapon.wielders`) proportionally rather than assuming all models carry all weapons.
- **Side modifiers**: All-out Attack (+1 hit) / All-out Defense (+1 save) are `CombatModifiers`/`SideOptions`, threaded as directional flags (`--aoa`/`--aod`). Charge (`--charge {a,b,both,none}`) carries **no universal bonus** in AoS4 — only a weapon's own `Charge (+N <Stat>)` ability text does (see "Intrinsic Anti-X/Charge bonuses" below).
- **`unit_benchmark` table**: persisted duel-result cache keyed by `(attacker_id, defender_id, attacker_reinforced, defender_reinforced, attacker_charged, defender_charged, attacker_mode, defender_mode)`, populated via `benchmark-all`. `attacker_mode`/`defender_mode` (`"mean"`/`"floor80"`/`"floor95"`) let different confidence levels coexist per duel direction — see `orchestration/benchmark.py::DamageMode`. `repository.save_benchmark_results_many` batches upserts through a staged temp table (DuckDB `executemany` is ~150ms/row vs <2ms/row for an inlined multi-row `INSERT`).
- **BSData `wielders`**: inferred from BattleScribe `constraints` on `selections` (min/max, scoped to `parent` or the unit), with parent-resolved counts for nested weapon bundles, replaced-base-weapon reduction, and group-level exclusive choices — see "BSData wielders resolution" below. Trickiest part of that importer; check there first if imported weapon counts look wrong.

### Wahapedia import — second import mechanism, same schema

`data/wahapedia/*.csv` (pipe-separated, UTF-8 BOM) is an alternative to BSData; both write into the identical schema, so downstream code doesn't care which importer populated a given army. Deliberate simplifications:

- **`Weapon.wielders` is always `0`** ("all models carry it"). Instead, `Unit.description` (the warscroll's free-text restriction) is captured and resolved at combat-time by `loadout.model_counts`.
- **`Unit.keywords`** captured in full (not just `HERO`) so weapon-level `Anti-<KEYWORD>` clauses can be evaluated against a defender's keyword set.
- **Only "regular battlefield unit" roles** are imported (`INGESTIBLE_ROLES`: Infantry/Cavalry/Beast/Monster/War Machine, plain or `* Hero`); `Endless Spell`/`Manifestation`/`Regiment of Renown`/`Faction Terrain` are skipped (`Unit` has no `role` column to store them distinctly).
- **Canonical dedup** (`_canonical_ids`, ported from StatHammer's `mark_canonical`): a warscroll "shell" dominated by a sibling (`virtual='false'` version, or a non-RoR version) is dropped. No manual overrides file — a residual ambiguity just picks the first candidate and warns, so `--all` never blocks.
- **Grand alliance mapping** (`FACTION_GRAND_ALLIANCE`) is derived from `bsdata.KNOWN_ARMIES` (faction names match) since Wahapedia CSVs carry no alliance info.

### Legends & stale-unit filtering (both importers)

- **Legends detection**: `bsdata._is_legends_catalogue` skips a whole catalogue named `... [Legends]`. For individually-retired units in an otherwise-current army, `bsdata._wahapedia_legends_names` cross-references `data/wahapedia/Source.csv`+`Warscrolls.csv` by name (read-only; `bsdata.py` never imports `wahapedia.py`, keeping the one-way dependency above) — same "legend" substring match `wahapedia._legends_warscroll_ids` uses for its own importer.
- **Expired narrative packs**: `bsdata._is_expired_variant` matches the name suffix "Scourge of Ghyran" (current seasonal narrative pack, absent from matched-play rules); shared by both importers. Both count these on `ImportSummary.skipped_legends`, reported separately from `skipped_no_profile`/`skipped_no_points`. "Scourge of Aqshy" (an earlier pack) is deliberately *not* filtered — those BSData entries target a distinct `targetId`/points cost from the base unit, so they're standalone valid units, not duplicates.
- **`--clean-stale`** (`cmd_import_bsdata`/`cmd_import_wahapedia`): records `datetime.now()` as `cutoff` before importing, then `repository.delete_units_imported_before(con, cutoff, army_id=...)` deletes any unit (+ weapons/composition entries/`unit_benchmark` rows) whose `unit.imported_at` predates it — i.e. units the run didn't touch. Scoped to the current army/faction, unscoped for `--all`.
- **Why `imported_at`/`unit_benchmark.attacker_mode`/`defender_mode` are declared directly in `CREATE TABLE`** rather than via the usual `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration: DuckDB silently resets a column's value to its `DEFAULT` if that statement re-runs on a column that already exists — which would wipe `imported_at` (or mislabel old mode rows) on every `connect()`. This column pair has been through two migrations, both one-shot table rewrites in `db.py::connect()`: `floor80` (BOOLEAN) → `floor95` (BOOLEAN, confidence level moved 80%→95%, `_migrate_floor95` purges leftover `floor95=TRUE` rows from the old formula) → `attacker_mode`/`defender_mode` (VARCHAR, `_migrate_damage_mode` rebuilds the table so each duel direction can read a different confidence level, translating old `floor95` values 1:1 with no data loss).

### Composite/companion unit merging (`bsdata.py` only)

Some warscrolls are split across several free BattleScribe entries that only exist because a paid entry was taken (e.g. "Neave Blacktalon" + Neave's Companions, "Morathi-Khaine" + The Shadow Queen, "Freeguild Command Corps" = paid Adjutants + free Auxiliaries). `_detect_composite_units` finds these by following the BSData `entryLink`/`condition` graph itself (a free entry's condition referencing another, paid `entryLink`) rather than a hardcoded name list — verified against all 27 known catalogues (7 sub-entries across 4 armies). `_merge_composite_units` then folds the free entry's models/weapons/keywords into its paid parent in-place. **Simplification**: if the two differ in `save`, the parent's value wins (aospy's `Unit` has one `save` per unit).

Wahapedia's importer has no equivalent merge — companion warscrolls there still land as separate `points <= 0` rows, which is why `analysis/features.py::feature_frame` unconditionally excludes `points <= 0` units from training/scoring (mechanically ≈ -100% residual otherwise, not a meaningful signal).

### BSData wielders resolution (`_extract_weapons`/`_weapon_wielders` in `bsdata.py`)

`_extract_weapons`'s `walk` resolves `model_count` **top-down**: each parent computes how many times *its own* children are actually picked (via `_raw_wielders`) before recursing, rather than threading the top-level unit size unchanged all the way down. This matters for three BattleScribe patterns that a flat "min/max scope=parent" read gets wrong:

- **Nested weapon bundles** (e.g. Kharadron Overlords' Endrinriggers "Skyrigger Heavy Weapon and Gun Butt", capped 1/3 models at the unit): the wrapper's own unit-wide cap must be resolved and passed down as the new `model_count` for its two sub-weapons, or they'd inherit the full unit size instead of the wrapper's cap.
- **Base weapon replaced by an upgrade** (`_replaced_by`): BattleScribe encodes "N models can replace their base weapon(s) with X" as a modifier that sets the base weapon's own min/max constraint to 0, conditioned on the replacement's selection. `_replaced_by` reads that modifier back off the base weapon entry and subtracts the replacement(s)' resolved count from the naive `model_count` read — otherwise the base weapon is counted on every model even when some replaced it (e.g. Arkanaut Company's Privateer Pistol/Arkanaut Hand Weapon).
- **Group-level exclusive choice** (`_group_cap`/`_option_damage_score`): a `selectionEntryGroup` can itself carry the "pick N of the following" cap (rather than a per-sibling modifier) — e.g. Seraphon's Stegadon "Wargear Options" group caps Skystreak Bow *or* Sunfire Throwers to 1, not both. When a group's own cap is below its number of weapon options, only the top-`cap` options (ranked by `_option_damage_score`, via the same `engine.combat.reference_expected_damage` "N best by expected damage vs a save-4+ reference" helper `loadout.py::_apply_exclusive_choices` uses for its own free-text exclusive choices) get walked; the rest are dropped entirely rather than counted.

`_unit_wide_max` deliberately accepts *any* non-`"parent"` scope as a unit-wide cap rather than requiring an exact match to the current unit's own id — at least one catalogue entry (Kharadron Overlords' "Endrinriggers (Scourge of Aqshy)") has a copy-paste bug where the wrapper's unit-scope constraint references the *base* unit's id instead of its own, which an exact match would silently miss. Missing it would fall through to `_weapon_wielders`'s uncapped default (`max(1, model_count)`), so the wrapper's sub-weapons would inherit the *full* unit size instead of its cap — the same over-count "Nested weapon bundles" above exists to prevent.

### Intrinsic `Anti-X`/`Charge` bonuses

Ported from StatHammer's `stats.py::_intrinsic_clauses`, benefiting **both** importers: `combat.py::_intrinsic_bonus` detects `Anti-<KEYWORD> (+N <Stat>)` and `Charge (+N <Stat>)` in `Weapon.abilities` (same free-text field as the Crit tag) and folds the bonus into `attacks`/`hit`/`wound`/`rend`/`damage` before the hit/wound/save chain. `Charge` is the *only* source of a charge bonus in AoS4 (typically `Charge (+1 Damage)` on cavalry). `Anti-X` needs `Unit.keywords`; both importers populate it.

**Deliberately out of scope** (candidate for a separate, larger PR): StatHammer's Stage/Modifier/Context engine (`detect_ability_modifiers` for self-conditional unit abilities, `build_army_catalog`/`compatible_army_buffs` for cross-unit buffs, `--enable`/`--on-objective`/`--army-buff` CLI flags) — needs a full per-unit abilities table (name + description) neither aospy's schema nor either importer has today.

### Cost model (`analysis/features.py` / `analysis/cost_model.py`) — scope vs StatHammer

Ported from StatHammer's own modules, adapted to aospy's already-typed schema (no text parsing needed for `move`/`save`/`control`). `MODEL_FEATURES`/`CATEGORICAL_FEATURES` in `cost_model.py` document, inline, the rationale behind each predictor choice — read those comments before adding/removing a feature. The A/B experiments backing each choice are runnable code: `analysis/experiments/*.py` holds the ones that were adopted (each derives its "before" baseline from the current, already-adopted `MODEL_FEATURES`/`CATEGORICAL_FEATURES` rather than hardcoding a snapshot, so the comparison stays valid as those constants evolve); `scratch/experiment_*.py` keeps the ones that were tried and rejected. Three fitting strategies share `feature_frame`: `fit_cost_model` (single OLS), `fit_segmented` (separate hero/troupe regressions), `fit_cost_model_factorial` (one OLS with categorical factors + `C(is_hero):...` interaction terms — only the first two are wired to `aospy cost fit`).

Deliberately **not** ported: an ability-power axis (StatHammer's LLM-scored `ability_scores.py`) and a tactical-role ranking (`roles.py`) — aospy stores no per-unit ability text, only a free-text Crit tag per weapon. `wizard_level`/`priest_level` (from the `WIZARD (N)`/`PRIEST (N)` keywords) are the one exception, giving casters a direct — if narrow — ability-power proxy.

### Data files vs generated files

`data/armies.json` and `data/compositions.json` are hand-authored seed data (loaded by `seed.py`/`aospy init`). `data/wahapedia/*.csv` is the Wahapedia data source (same files as the StatHammer project; re-download to refresh). `data/aospy.duckdb` (default DB path) and everything under `scratch/` (ad hoc aggregation/PDF-report scripts, e.g. `scratch/build_pdf.py`) are generated/exploratory, not source — PDF/JSON outputs from those scripts land in `scratch/output/`, kept out of the scripts themselves.

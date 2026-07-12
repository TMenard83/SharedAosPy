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
aospy import wahapedia --faction "Stormcast Eternals"   # import from Wahapedia CSV instead
aospy import wahapedia --all                # import every known faction (data/wahapedia/*.csv)
aospy unit duel --attacker X --defender Y
aospy unit benchmark --attacker X --charge a --detail
aospy unit benchmark-all --charge both -v   # persists all attacker×defender pairs to unit_benchmark
aospy unit benchmark-all --charge both --floor80   # same, but persists the 80%-confidence floor instead of the mean
aospy unit stats --attacker X [--charge]    # mean / std / 80%-confidence damage floor vs 3 standard targets
aospy battle simulate --a <comp_id> --b <comp_id> --charge both
aospy import bsdata --all --clean-stale     # also purges units an import no longer touched (see `imported_at`)
aospy import wahapedia --all --clean-stale  # same, for the Wahapedia importer
aospy cost fit [--segmented]                # OLS points ~ features (needs `[analysis]`)
aospy cost residuals --top 20 --direction under   # most under/over-costed units by residual
```

## Architecture

Layers, bottom to top — each module only calls downward:

1. **`models.py`** — frozen/plain dataclasses for the domain (`Army`, `Weapon`, `Unit`, `HeroicTrait`, `Artefact`, `CompositionUnit`, `Composition`). No DB or logic.
2. **`db.py`** — opens a DuckDB connection at `DEFAULT_DB_PATH` (`data/aospy.duckdb`) and applies `schema.sql` on every `connect()` (idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations for `weapon.wielders` and `unit.keywords`/`unit.description`). Schema changes go in `schema.sql`, not in Python.
3. **`repository.py`** — all SQL lives here (CRUD for army/unit/weapon/heroic_trait/artefact/composition/composition_unit, plus `unit_benchmark` upsert helpers). Nothing above this layer writes raw SQL. `Unit.keywords` (a `frozenset[str]`) round-trips through a single comma-joined `VARCHAR` column (`_keywords_to_db`/`_keywords_from_db`).
4. **`combat.py`** — pure math, no DB access. `expected_weapon_damage` computes expected damage for one weapon profile (hit → wound → save/rend → ward, with crit variants **and** intrinsic bonuses parsed from the free-text `abilities` field: `Crit (2 Hits/Mortal/Auto-Wound)`, `Anti-<KEYWORD> (+N <Stat>)` — active only if the defender has that keyword — and `Charge (+N <Stat>)` — active only if the attacker charged, on top of the universal +1 melee attack). `expected_unit_damage` sums across a unit's weapon profiles, using `_effective_counts` to resolve how many models carry each profile: `loadout.model_counts` (from `Unit.description`, free text) when present, else `weapon.wielders`-based scaling (BattleScribe constraints). `weapon_damage_moments`/`unit_damage_moments` extend the same branch-by-branch model to `E[D²]` to get variance/std (`Var(D) = E[D²] − E[D]²`); `damage_floor80` turns `(mean, std)` into a normal-approximation 80%-confidence damage floor (`mean − 0.8416·σ`). **Caveat**: `Weapon.attacks`/`damage` are integers already resolved at import time (no dice notation kept), so this variance only captures hit/wound/save/ward/crit randomness, not dice-valued attacks/damage — a known simplification (see `wahapedia.py` for why).
5. **`loadout.py`** — ported from StatHammer's own `loadout.py`: parses `Unit.description` (free text: "*n/m models can replace X with Y*", "*N of the following options*", named rosters…) into per-weapon-profile model counts (`model_counts`). Best-effort: unrecognized clauses fall back to "every model carries every profile", logged in the returned notes. Used by `combat.py::_effective_counts`, not called directly by callers.
6. **`benchmark.py`** / **`simulation.py`** — orchestration on top of `combat.py` + `repository.py`. `benchmark.py` does single-attacker-vs-many-defenders duels (`unit_duel`, `benchmark_attacker`, `run_all_benchmarks`) and persists results; all three take `use_floor80: bool = False` — when `True`, `_attack_damage` substitutes `damage_floor80(mean, std)` (via `unit_damage_moments`) for the raw `expected_unit_damage` mean, so the persisted/reported figures become a pessimistic 80%-confidence floor instead of the expectation (`--floor80` on `unit benchmark-all`). `simulation.py` does full composition-vs-composition (`simulate_battle`, all-entries-vs-all-entries).
7. **`report.py`** — pure text formatting of `DuelResult`/`BattleReport`/unit-stats rows for terminal output. No computation.
8. **`cli.py`** / **`cli_commands.py`** — argparse wiring (`cli.py`) dispatching to one `cmd_*` function per subcommand (`cli_commands.py`). Each `cmd_*` opens its own DB connection via `_connect(args)` and closes it before returning.
9. **`bsdata.py`** — standalone importer: downloads `.cat` XML files from the `BSData/age-of-sigmar-4th` GitHub repo, parses BattleScribe profiles into `Unit`/`Weapon`, and upserts via `repository.replace_unit`. `KNOWN_ARMIES` maps army name → (main catalogue file, library file, grand alliance). `_keywords(entry)` collects category-link names (excluding the `WARD (N+)` pseudo-category, handled separately by `_ward_from_categories`) into `Unit.keywords`; `Unit.description` is left `None` (no BattleScribe XML field identified yet as an equivalent free-text restriction — units imported via BSData keep the `wielders`-based allocation in `combat.py`, unaffected). Also filters out expired/Legends content — see "Legends & stale-unit filtering" below.
10. **`wahapedia.py`** — second importer, reading `data/wahapedia/*.csv` (same format as the StatHammer project) instead of BSData, upserting into the *same* `Army`/`Unit`/`Weapon` schema via the same `repository.replace_unit`. Reuses `bsdata.parse_dice`/`parse_target` and `bsdata.KNOWN_ARMIES` (for the grand-alliance mapping — absent from the Wahapedia CSVs themselves). See "Wahapedia import" below for its documented simplifications.
11. **`features.py`** / **`cost_model.py`** — analysis layer (needs the `[analysis]` extra: pandas + statsmodels). `features.py::compute_features` probes a unit's offense against three synthetic defenders (save 2+/4+/none) via `combat.py`'s moments engine to build a numeric feature vector (`UnitFeatures`); `cost_model.py::fit_cost_model`/`fit_segmented` regress `points ~ features` (OLS) to get interpretable coefficients and per-unit residuals, `CostModelResult.undercosted()`/`.overcosted()` surface the biggest relative residuals. See "Cost model" below for scope/limitations.
12. **`seed.py`** — one-time JSON loaders (`data/armies.json`, `data/compositions.json`) for hand-authored seed data, idempotent by name.

### Key domain concepts

- **Points economy**: every `DuelResult` computes `pts_destroyed`/`pts_lost`/`pts_net`/`roi` by scaling expected damage against the defender's/attacker's total points — this is how units are compared across point costs, not just raw damage.
- **Reinforcement**: doubles model count and points; `combat.py::_effective_counts` scales per-profile model counts (from `loadout.model_counts` or `weapon.wielders`) proportionally rather than assuming all models carry all weapons (matters for units with limited special-weapon loadouts).
- **Side modifiers**: charge (+1 melee attack, universal AoS4 rule), All-out Attack (+1 hit), All-out Defense (+1 save) are represented as `CombatModifiers`/`SideOptions` and threaded through as directional flags (attacker vs defender), configurable per-side via CLI flags (`--charge {a,b,both,none}`, `--aoa`, `--aod`). On top of this universal bonus, a weapon's own `abilities` text can carry an *additional*, cumulative `Charge (+N <Stat>)` clause (see `combat.py`).
- **`unit_benchmark` table**: a persisted cache of duel results keyed by `(attacker_id, defender_id, attacker_reinforced, defender_reinforced, attacker_charged, defender_charged, floor80)`, populated via `benchmark-all`. The `floor80` key column lets the mean-damage rows and the `--floor80` pessimistic-floor rows (see `benchmark.py` above) coexist without clobbering each other. `repository.save_benchmark_results_many` batches upserts through a staged temp table because DuckDB's `executemany` is ~150ms/row vs <2ms/row for an inlined multi-row `INSERT`.
- **BSData import**: `wielders` (how many models in a unit actually carry a given weapon) is inferred from BattleScribe `constraints` on `selections` (min/max, scoped to `parent` or the unit itself) — see `_weapon_wielders`/`_entry_minmax` in `bsdata.py`. This is the trickiest part of the importer; if imported weapon counts look wrong, check constraint scope handling there first.
- **Legends & stale-unit filtering**: both importers skip retired/narrative-pack content and can purge units a re-import no longer touches — see "Legends & stale-unit filtering" below.

### Wahapedia import (`wahapedia.py`) — second import mechanism, same schema

`data/wahapedia/*.csv` (pipe-separated, UTF-8 BOM — same files as the StatHammer project) is an
alternative to BSData for populating the DB. Both write into the identical `Army`/`Unit`/`Weapon`
schema, so downstream code (`combat.py`, `benchmark.py`, `cost_model.py`…) doesn't care which importer
populated a given army. Known, deliberate simplifications (kept small/additive rather than changing the
schema):

- **`Weapon.wielders` is always `0`** ("all models carry it by default") — Wahapedia has no
  BattleScribe-style constraint data to infer per-model weapon loadouts from directly on the weapon
  row. Instead, `Unit.description` (the warscroll's free-text restriction, e.g. Arkanaut Company's
  "*2/10 models can replace their Privateer Pistol with…*") is captured and resolved at combat-time by
  `loadout.model_counts` (see `combat.py::_effective_counts`) — this is the faithful per-model
  allocation, just computed downstream instead of stored back into `wielders`.
- **`Unit.keywords`** is captured in full (not just a `HERO` check) so that weapon-level
  `Anti-<KEYWORD> (+N <Stat>)` clauses (in `Weapon.abilities`) can be evaluated against a defender's
  actual keyword set in `combat.py`.
- **Only "regular battlefield unit" roles are imported** (`INGESTIBLE_ROLES`: Infantry/Cavalry/Beast/
  Monster/War Machine, each plain or `* Hero`). `Endless Spell`, `Manifestation`, `Regiment of Renown`,
  `Faction Terrain` and a few other special roles are skipped — `Unit` has no `role` column to store
  them distinctly after import; adding one is a possible follow-up if a need arises.
- **Canonical dedup** (`_canonical_ids`, ported from StatHammer's `ingest/dedupe.py::mark_canonical`):
  a warscroll is a "shell" dominated by a sibling if a `virtual='false'` version exists, or if a
  non-`Regiment of Renown` version exists for what would otherwise be a RoR reference. Unlike
  StatHammer, there's no manual overrides file here — a residual ambiguity (rare) just picks the first
  candidate and prints a warning, so an unattended `--all` import never blocks.
- **Grand alliance mapping** (`FACTION_GRAND_ALLIANCE`) is derived from `bsdata.KNOWN_ARMIES` (Wahapedia
  faction names match BSData army names) since the Wahapedia CSVs don't carry alliance info themselves.

### Legends & stale-unit filtering (both importers)

Both importers now skip content that's no longer legal/current, and can purge units that a
re-import stops touching:

- **Legends detection**: `bsdata.py::_is_legends_catalogue` skips an entire catalogue whose
  BattleScribe root is named `... [Legends]` (e.g. Beasts of Chaos, Bonesplitterz — armies pulled
  wholesale). For individually-retired units within an otherwise-current army (e.g. Terrorgheist in
  Soulblight Gravelords), `bsdata.py::_wahapedia_legends_names` cross-references `data/wahapedia/
  Source.csv` + `Warscrolls.csv` by name (the two data sources share no common ID) — same signal
  `wahapedia.py::_legends_warscroll_ids` already used for its own importer, now broadened from
  matching only `"warhammer legends"` in the notes field to matching `"legend"` (catches more
  variants of the note text). `bsdata.py` reads the Wahapedia CSVs read-only for this cross-check
  only (`WAHAPEDIA_DATA_DIR`); it does not import `wahapedia.py` itself, to keep the dependency
  direction documented above (Wahapedia importer may reuse BSData helpers, not the reverse).
- **Expired narrative packs**: `bsdata._is_expired_variant`/`_EXPIRED_VARIANT_MARKERS` matches name
  fragments like "Scourge of Aqshy"/"Scourge of Ghyran" (seasonal narrative-pack variants BSData
  still exposes as a name suffix, absent or excluded from the Wahapedia CSVs). Shared by both
  importers (`wahapedia.py` imports the same helper) so a warscroll named e.g. "Bonesplitterz
  (Scourge of Ghyran)" is skipped identically either way. Both importers count these skips on
  `ImportSummary.skipped_legends`, reported separately from `skipped_no_profile`/`skipped_no_points`
  in the CLI summary (`aospy import bsdata|wahapedia [--faction/--army] / --all`).
- **`--clean-stale`** (`cmd_import_bsdata`/`cmd_import_wahapedia` in `cli_commands.py`): records
  `datetime.now()` as `cutoff` before importing, then calls
  `repository.delete_units_imported_before(con, cutoff, army_id=...)` — deletes any unit (and its
  weapons/composition entries/`unit_benchmark` rows) whose `unit.imported_at` is older than the
  cutoff, i.e. units the just-run import didn't touch (removed from source, or now filtered as
  Legends/expired above). Restricted to the current army/faction for a single import, unscoped for
  `--all`. `unit.imported_at` (new column, `DEFAULT CURRENT_TIMESTAMP`, refreshed on every
  `repository.replace_unit` update) is declared directly in `CREATE TABLE` rather than via the usual
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration pattern — DuckDB silently resets a column's
  values to its `DEFAULT` if that `ALTER ADD COLUMN IF NOT EXISTS` runs again on a column that
  already exists, which would wipe `imported_at` on every `connect()`. Same reasoning applies to the
  `unit_benchmark.floor80` column above.

### Intrinsic Anti-X / Charge bonuses and per-model weapon allocation

Ported from StatHammer's `stats.py::_intrinsic_clauses` (regex-driven ability text) and
`loadout.py` (`model_counts`), onto aospy's own combat engine — this benefits **both** importers
(BSData and Wahapedia), not just one:

- `combat.py::_intrinsic_bonus` detects `Anti-<KEYWORD> (+N <Stat>)` and `Charge (+N <Stat>)` in
  `Weapon.abilities` (the same free-text field already used for the Crit tag) and folds the bonus into
  `attacks`/`hit`/`wound`/`rend`/`damage` before the hit/wound/save chain. Anti-X requires
  `Unit.keywords` (see above); Charge requires no schema addition (`CombatModifiers.attacker_charged`
  already existed).
- `loadout.py::model_counts` requires `Unit.description` — currently populated by `wahapedia.py` (the
  Wahapedia CSVs carry it), **not** by `bsdata.py` (no equivalent BattleScribe field identified yet).
  BSData-imported units therefore keep the `wielders`-based allocation, which is already faithful for
  that import path (BattleScribe constraints resolve `wielders` directly) — this is a documented
  difference between the two import paths, not a regression on either one.

**Deliberately out of scope** (proposed as a separate, larger follow-up PR): StatHammer's full
Stage/Modifier/Context engine (`stats.py:670-1066+` — `detect_ability_modifiers` for self-conditional
unit abilities, `build_army_catalog`/`compatible_army_buffs` for buffs one unit grants to *other* units,
and the CLI flags `--enable`/`--on-objective`/`--army-buff`). That needs a full per-unit abilities table
(name + description, one row per ability) that neither aospy's schema nor either importer has today —
a materially bigger change (new table, both importers, multi-unit context threading) than the additive,
same-`abilities`-field bonuses above.

### Cost model (`features.py` / `cost_model.py`) — scope vs StatHammer

Ported from StatHammer's own `features.py`/`cost_model.py`, adapted to aospy's already-typed schema
(no text parsing needed for `move`/`save`/`control` — they're plain ints already). Deliberately **not**
ported: an ability-power axis (StatHammer's `ability_scores.py`, LLM-scored) and a tactical-role ranking
(`roles.py`) — aospy stores no per-unit ability text or keyword table, only a single free-text Crit tag
per weapon (`Weapon.abilities`). Also not ported: free-companion aggregation (StatHammer's `bundles.py`,
e.g. Neave's Companions bundled into Neave's own profile) — instead, `feature_frame` simply **excludes
`points <= 0` units** from training/scoring (a `points=0` companion has no independent price, so its
residual would be a mechanical ≈-100% rather than a meaningful signal).

### Data files vs generated files

`data/armies.json` and `data/compositions.json` are hand-authored seed data (loaded by `seed.py` / `aospy init`). `data/wahapedia/*.csv` is the Wahapedia data source for `wahapedia.py` (same files as the StatHammer project; re-download to refresh). `data/aospy.duckdb` (default DB path), the `bench_*.log`/`bench_*.txt`/`*_ranking_*.csv`/`*.pdf` files at repo root, and everything under `scratch/` (ad hoc aggregation/PDF-report scripts and their JSON/PDF outputs, e.g. `scratch/build_pdf.py`) are generated/exploratory outputs, not source.

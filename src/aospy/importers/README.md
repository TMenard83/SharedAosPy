# importers — BSData et Wahapedia vers le même schéma

Lire avant de modifier ce paquet (CLAUDE.md ne garde que la carte des couches).

## Modules

- **`importers/bsdata.py`** — downloads `.cat` XML from `BSData/age-of-sigmar-4th` (GitHub), parses BattleScribe profiles, upserts via `repository.replace_unit`. `KNOWN_ARMIES` maps army name → (catalogue, library, grand alliance). `Unit.description` is left `None` (no BattleScribe equivalent found yet — BSData units keep the `wielders`-based allocation instead). Filters Legends/expired content and merges free companion units into their paid parent — see the two dedicated sections below.
- **`importers/wahapedia.py`** — second importer, reading `data/wahapedia/*.csv` into the *same* schema via the same `repository.replace_unit`. Reuses `bsdata.parse_dice`/`parse_target`/`KNOWN_ARMIES`. See "Wahapedia import" below.

- **BSData `wielders`**: inferred from BattleScribe `constraints` on `selections` (min/max, scoped to `parent` or the unit), with parent-resolved counts for nested weapon bundles, replaced-base-weapon reduction, and group-level exclusive choices — see "BSData wielders resolution" below. Trickiest part of that importer; check there first if imported weapon counts look wrong.

## Wahapedia import — second import mechanism, same schema

`data/wahapedia/*.csv` (pipe-separated, UTF-8 BOM) is an alternative to BSData; both write into the identical schema, so downstream code doesn't care which importer populated a given army. Deliberate simplifications:

- **`Weapon.wielders` is always `0`** ("all models carry it"). Instead, `Unit.description` (the warscroll's free-text restriction) is captured and resolved at combat-time by `loadout.model_counts`.
- **`Unit.keywords`** captured in full (not just `HERO`) so weapon-level `Anti-<KEYWORD>` clauses can be evaluated against a defender's keyword set.
- **Only "regular battlefield unit" roles** are imported (`INGESTIBLE_ROLES`: Infantry/Cavalry/Beast/Monster/War Machine, plain or `* Hero`); `Endless Spell`/`Manifestation`/`Regiment of Renown`/`Faction Terrain` are skipped (`Unit` has no `role` column to store them distinctly).
- **Canonical dedup** (`_canonical_ids`, ported from StatHammer's `mark_canonical`): a warscroll "shell" dominated by a sibling (`virtual='false'` version, or a non-RoR version) is dropped. No manual overrides file — a residual ambiguity just picks the first candidate and warns, so `--all` never blocks.
- **Grand alliance mapping** (`FACTION_GRAND_ALLIANCE`) is derived from `bsdata.KNOWN_ARMIES` (faction names match) since Wahapedia CSVs carry no alliance info.

## Source corrections and cross-checking (`importers/corrections.py`, `importers/verify.py`)

Three sources describe a warscroll: Wahapedia, BSData and the battletome scans. Precedence: **latest rules update > scan > Wahapedia/BSData** (a scan alone can be outdated: Skreech is Wizard (1) in the French battletome, Wizard (2) per the French rules update p. 33, which Wahapedia already had). `data/json/source_corrections.json` records verified fixes and **wins over everything**: unit fixes (keywords, stats, weapon profiles) are re-applied after every `aospy import bsdata|wahapedia`; ability text fixes (condition/declare/effect, English — the extractor reads English) are applied in `abilities.source.load_raw_abilities` before the uid is computed (a fixed text changes the uid). First entry: LRL's `DEPICT RUNE`, whose 5 runes Wahapedia truncates. `aospy import verify --faction X` diffs Wahapedia (in DB) against a local BSData library `.cat` (`data/bsdata/`, no network in the shell); each diff is settled on the scan/rules update. Wahapedia's `Warscrolls_keywords.csv` keeps caster levels in its `parameter` column: `wahapedia.keyword_variants` stores both `WIZARD` and `WIZARD (N)`. The `faction-rules-fr` skill has the verification step.

## Legends & stale-unit filtering (both importers)

- **Legends detection**: `bsdata._is_legends_catalogue` skips a whole catalogue named `... [Legends]`. For individually-retired units in an otherwise-current army, `bsdata._wahapedia_legends_names` cross-references `data/wahapedia/Source.csv`+`Warscrolls.csv` by name (read-only; `bsdata.py` never imports `wahapedia.py`, keeping the one-way dependency above) — same "legend" substring match `wahapedia._legends_warscroll_ids` uses for its own importer.
- **Expired narrative packs**: `bsdata._is_expired_variant` matches the name suffix "Scourge of Ghyran" (current seasonal narrative pack, absent from matched-play rules); shared by both importers. Both count these on `ImportSummary.skipped_legends`, reported separately from `skipped_no_profile`/`skipped_no_points`. "Scourge of Aqshy" (an earlier pack) is deliberately *not* filtered — those BSData entries target a distinct `targetId`/points cost from the base unit, so they're standalone valid units, not duplicates.
- **`--clean-stale`** (`cmd_import_bsdata`/`cmd_import_wahapedia`): records `datetime.now()` as `cutoff` before importing, then `repository.delete_units_imported_before(con, cutoff, army_id=...)` deletes any unit (+ weapons/composition entries/`unit_benchmark` rows) whose `unit.imported_at` predates it — i.e. units the run didn't touch. Scoped to the current army/faction, unscoped for `--all`.

## Composite/companion unit merging (`bsdata.py` only)

Some warscrolls are split across several free BattleScribe entries that only exist because a paid entry was taken (e.g. "Neave Blacktalon" + Neave's Companions, "Morathi-Khaine" + The Shadow Queen, "Freeguild Command Corps" = paid Adjutants + free Auxiliaries). `_detect_composite_units` finds these by following the BSData `entryLink`/`condition` graph itself (a free entry's condition referencing another, paid `entryLink`) rather than a hardcoded name list — verified against all 27 known catalogues (7 sub-entries across 4 armies). `_merge_composite_units` then folds the free entry's models/weapons/keywords into its paid parent in-place. **Simplification**: if the two differ in `save`, the parent's value wins (aospy's `Unit` has one `save` per unit).

Wahapedia's importer has no equivalent merge — companion warscrolls there still land as separate `points <= 0` rows, which is why `analysis/features.py::feature_frame` unconditionally excludes `points <= 0` units from training/scoring (mechanically ≈ -100% residual otherwise, not a meaningful signal).

## BSData wielders resolution (`_extract_weapons`/`_weapon_wielders` in `bsdata.py`)

`_extract_weapons`'s `walk` resolves `model_count` **top-down**: each parent computes how many times *its own* children are actually picked (via `_raw_wielders`) before recursing, rather than threading the top-level unit size unchanged all the way down. This matters for three BattleScribe patterns that a flat "min/max scope=parent" read gets wrong:

- **Nested weapon bundles** (e.g. Kharadron Overlords' Endrinriggers "Skyrigger Heavy Weapon and Gun Butt", capped 1/3 models at the unit): the wrapper's own unit-wide cap must be resolved and passed down as the new `model_count` for its two sub-weapons, or they'd inherit the full unit size instead of the wrapper's cap.
- **Base weapon replaced by an upgrade** (`_replaced_by`): BattleScribe encodes "N models can replace their base weapon(s) with X" as a modifier that sets the base weapon's own min/max constraint to 0, conditioned on the replacement's selection. `_replaced_by` reads that modifier back off the base weapon entry and subtracts the replacement(s)' resolved count from the naive `model_count` read — otherwise the base weapon is counted on every model even when some replaced it (e.g. Arkanaut Company's Privateer Pistol/Arkanaut Hand Weapon).
- **Group-level exclusive choice** (`_group_cap`/`_option_damage_score`): a `selectionEntryGroup` can itself carry the "pick N of the following" cap (rather than a per-sibling modifier) — e.g. Seraphon's Stegadon "Wargear Options" group caps Skystreak Bow *or* Sunfire Throwers to 1, not both. When a group's own cap is below its number of weapon options, only the top-`cap` options (ranked by `_option_damage_score`, via the same `engine.combat.reference_expected_damage` "N best by expected damage vs a save-4+ reference" helper `loadout.py::_apply_exclusive_choices` uses for its own free-text exclusive choices) get walked; the rest are dropped entirely rather than counted.

`_unit_wide_max` deliberately accepts *any* non-`"parent"` scope as a unit-wide cap rather than requiring an exact match to the current unit's own id — at least one catalogue entry (Kharadron Overlords' "Endrinriggers (Scourge of Aqshy)") has a copy-paste bug where the wrapper's unit-scope constraint references the *base* unit's id instead of its own, which an exact match would silently miss. Missing it would fall through to `_weapon_wielders`'s uncapped default (`max(1, model_count)`), so the wrapper's sub-weapons would inherit the *full* unit size instead of its cap — the same over-count "Nested weapon bundles" above exists to prevent.

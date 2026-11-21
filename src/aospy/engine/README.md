# engine — calcul pur (pas de DB)

Lire avant de modifier ce paquet (CLAUDE.md ne garde que la carte des couches).

## Modules

- **`engine/combat.py`** — pure math, no DB access. `expected_weapon_damage` (hit → wound → save/rend → ward, crit variants + intrinsic `Anti-X`/`Charge` bonuses parsed from `Weapon.abilities` — see "Intrinsic Anti-X/Charge bonuses" below) and its `E[D²]` twin `weapon_damage_moments` (→ `unit_damage_moments`). Damage-floor reads go through the *exact* discrete distribution (`weapon_damage_distribution` → `unit_damage_distribution` → `distribution_floor`), not a Gaussian approximation — see "Damage floor: exact distribution vs Gaussian approximation" below; `damage_floor66`/`80`/`95` (`mean − z·σ`) survive only as a comparison baseline. **Caveat**: `Weapon.attacks`/`damage` are integers resolved at import time (no dice notation kept), so variance only captures hit/wound/save/ward/crit randomness, not dice-valued attacks/damage.
- **`engine/loadout.py`** — ported from StatHammer's `loadout.py`: parses `Unit.description` (free text) into per-weapon-profile model counts (`model_counts`). Best-effort, unrecognized clauses fall back to "every model carries every profile" (logged in the returned notes). Used by `combat.py::effective_counts`.
- **Reinforcement**: doubles model count and points; `combat.py::effective_counts` scales per-profile model counts (from `loadout.model_counts` or `weapon.wielders`) proportionally rather than assuming all models carry all weapons.

## Intrinsic `Anti-X`/`Charge` bonuses

Ported from StatHammer's `stats.py::_intrinsic_clauses`, benefiting **both** importers: `combat.py::_intrinsic_bonus` detects `Anti-<KEYWORD> (+N <Stat>)` and `Charge (+N <Stat>)` in `Weapon.abilities` (same free-text field as the Crit tag) and folds the bonus into `attacks`/`hit`/`wound`/`rend`/`damage` before the hit/wound/save chain. `Charge` is the *only* source of a charge bonus in AoS4 (typically `Charge (+1 Damage)` on cavalry). `Anti-X` needs `Unit.keywords`; both importers populate it.

**Deliberately out of scope** (candidate for a separate, larger PR): StatHammer's Stage/Modifier/Context engine (`detect_ability_modifiers` for self-conditional unit abilities, `build_army_catalog`/`compatible_army_buffs` for cross-unit buffs, `--enable`/`--on-objective`/`--army-buff` CLI flags) — needs a full per-unit abilities table (name + description) neither aospy's schema nor either importer has today.

## Damage floor: exact distribution vs Gaussian approximation

`damage_floor66`/`damage_floor80`/`damage_floor95` (`mean − z·σ`, `_Z66`/`_Z80`/`_Z95` = inverse-normal quantiles) was
the original implementation, ported unchanged from StatHammer: it assumes the sum of hit/wound/save/ward outcomes is
approximately Gaussian, which the central limit theorem supports for many i.i.d. attacks but breaks down for the
low-attack/high-damage profiles common in AoS (monsters, single big war-machine models) — the true distribution is
discrete, bounded at 0, and often asymmetric. Concretely, a 2-attack/8-damage profile reads ~2.5 "guaranteed" damage
at 95% confidence under the Gaussian formula, but the real chance of both attacks missing exceeds 5%, so the true
95%-floor is 0 — the approximation isn't just imprecise there, it's actively optimistic.

`weapon_damage_distribution` → `unit_damage_distribution` → `distribution_floor` replace it with the *exact* discrete
distribution, no normality assumption. Since `total_attacks` is a fixed integer (not a die — see the caveat on
`engine/combat.py` above) and each attack is an independent categorical draw (miss / normal hit / crit hit, same
branches as `weapon_damage_moments`), the total-damage PMF of one weapon profile is the auto-convolution of a single
attack's outcome distribution over `total_attacks` draws; weapon profiles are independent, so a unit's PMF is the
convolution of its profiles' PMFs (mirrors `unit_damage_moments`'s variance-additivity). `distribution_floor` then
reads the quantile directly: the largest `d` with `P(damage ≥ d) ≥ coverage`. Convolution is plain Python (`list`,
no numpy) by design — `engine/combat.py` ships in the base install (`pyproject.toml` core deps = `duckdb` only;
numpy/pandas stay behind `[analysis]`) — and stays fast because PMF supports remain in the low hundreds of entries
for realistic attack counts (benchmarked ~0.6 ms/duel across the full unit database).

`orchestration/benchmark.py::_attack_damage` reads `floor66`/`floor80`/`floor95` off this exact PMF for production
use (`unit_duel`, `benchmark_attacker`, `run_all_benchmarks`, `unit_benchmark` persistence, `aospy unit stats`).
`damage_floor66`/`80`/`95` and their Gaussian machinery are kept, unchanged, purely as a comparison baseline (see
`tests/engine/test_combat.py`'s divergence/convergence tests) — nothing in the codebase still reads a floor through
them.

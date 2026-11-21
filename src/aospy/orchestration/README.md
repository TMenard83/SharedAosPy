# orchestration — duels et batailles

Lire avant de modifier ce paquet (CLAUDE.md ne garde que la carte des couches).

## Modules

- **`orchestration/benchmark.py`** / **`orchestration/simulation.py`** — orchestration on `combat.py` + `repository.py`. `benchmark.py`: single-attacker-vs-many-defenders duels (`unit_duel`, `benchmark_attacker`, `run_all_benchmarks`), with independent `mode_a`/`mode_b: DamageMode` (`"mean"`/`"floor66"`/`"floor80"`/`"floor95"`) per duel direction — a duel need not read both sides at the same confidence level. `_attack_damage` reads `floorNN` modes off `combat.py::unit_damage_distribution`'s exact PMF (`distribution_floor`), not a Gaussian approximation. `simulation.py`: full composition-vs-composition (`simulate_battle`, all-entries-vs-all-entries).

## Concepts

- **Points economy**: every `DuelResult` computes `pts_destroyed`/`pts_lost`/`pts_net`/`roi` by scaling expected damage against the defender's/attacker's total points — units are compared across point costs, not just raw damage.
- **Side modifiers**: All-out Attack (+1 hit) / All-out Defense (+1 save) are `CombatModifiers`/`SideOptions`, threaded as directional flags (`--aoa`/`--aod`). Charge (`--charge {a,b,both,none}`) carries **no universal bonus** in AoS4 — only a weapon's own `Charge (+N <Stat>)` ability text does (see `engine/README.md`, "Intrinsic Anti-X/Charge bonuses").

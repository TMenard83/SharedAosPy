# analysis — modèle de coût et couches 2 à 4

Lire avant de modifier ce paquet (CLAUDE.md ne garde que la carte des couches). Ce README reste court : le détail de chaque module est dans `docs/` — ne lire que le fichier du module touché, et y ajouter les nouvelles notes (pas ici).

## Modules

Two sub-packages, with an import-linter contract (`pyproject.toml`): `layers` may import `cost`, never the reverse.

- **`analysis/cost/`** — the cost model: `features.py`, `cost_model.py`, `scoring.py` (`combined_score`, the composite score shared by `reports/best_report.py` and `bonus_simulator/whatif.py`), `experiments/` (adopted A/B experiments).
- **`analysis/layers/`** — ability layers 2-4 (see "Architecture en quatre couches" below): `chassis`, `approach`, `timeline`, `encounter`, `realized`, `mobility`, `marriage`, `bearers`, `listing`, `assault`.

- **`analysis/cost/features.py`** / **`analysis/cost/cost_model.py`** (needs `[analysis]`: pandas + statsmodels). `features.py::compute_features` probes a unit against three synthetic defenders (save 2+/4+/none) via `combat.py`'s moments engine → `UnitFeatures`. `cost_model.py` regresses `points ~ features` (OLS) three ways (`fit_cost_model`, `fit_segmented`, `fit_cost_model_factorial`) for coefficients + per-unit residuals. See "Cost model" below.

## Cost model (`analysis/cost/features.py` / `analysis/cost/cost_model.py`) — scope vs StatHammer

Détail (portage StatHammer, contrôle comme écart à la règle tacite de GW, ce qui n'est pas porté, `CostModelResult.model`) : [docs/cost-model.md](docs/cost-model.md).

## Architecture en quatre couches

La couche 1 (aptitude hors contexte) est décrite dans `../abilities/README.md`.

**Four-layer architecture (user's design) — keep the layers separate:**

**Cascade imposée** (`analysis/layers/cascade.py`, table `layer_build`, `aospy cascade`) : chaque build de couche 1-3 enregistre l'empreinte de ses entrées (couche 1 : version de l'analyseur + date des CSV/`source_corrections.json`/`ability_overrides.json` ; couche 2 : build de la couche 1 + imports/duels ; couche 3 : build de la couche 2). `chassis build`, `encounter build`, `roster analyze|dossier`, `l3/layer4.indices` et `l3 plan-note` refusent de tourner (`require_fresh`, ValueError → code 2) tant qu'une couche du dessous est périmée. Tout nouveau point d'entrée de couche 2-4 appelle `require_fresh(con, <couche>)`.

1. **Ability, ex nihilo** (this package, done): judged without knowing who carries or receives it. A warscroll *stat* is given; an ability *bonus* has to be played/triggered — never value an ability by applying it to a "median unit" (rejected proposal: that sneaks context into layer 1). Power stays a qualitative, user-calibrated grid; quantified effects only record their raw magnitude plus their **perimeter** (below). Manifestations are the known hard case (summon spell → manifestation → its own abilities), approximated as a chain.
2. **Chassis** (`analysis/layers/chassis.py`, table `unit_chassis`, `aospy chassis build|list|show`): the bare warscroll — HP, save, weapon profiles. Two complementary tools: the combat engine measures what the chassis *does* (`dmg_vs_save4`, `effective_wounds`), the cost model measures what GW *charges* for it. Measured on every unit with `bonus_simulator.apply_bonus`: GW prices defence at ≈½ of its mechanical gain (ward 5+ = +50 % durability, +25-30 % points) but offence at ≈⅛ (+1 hit = +28 % damage, +4 % points; damage coefficients are weak, p≈0.12) — so offensive chassis may be structurally cheap, to be confirmed. `ChassisProfile` stores performance (melee/ranged damage per round vs save 4+, effective wounds, both per 100 pts with a centile rank within heroes/troops) plus the **compatibility descriptors** layer 3 reads to know whether an ability "takes" on a warscroll: `share_damage1` (share of damage from 1-damage weapons — what "+1 Damage" doubles), `share_companion` (Companion weapons, insensitive to most buffs), `share_melee`, `attacks_total`, dominant `crit_type`. The cost-model residual and duel efficiency (`unit_benchmark`, same reading as `reports/aggregate.py`) are joined when available. No composite chassis score yet (the offence/defence weighting is still open).
3. **Ability × chassis encounter** (`analysis/layers/encounter.py`, table `ability_encounter`, `aospy encounter build|list`): what a *friendly* effect really yields on *this* warscroll, via the engine (each effect = a profile rewrite). Détail : [docs/encounter.md](docs/encounter.md).
   **Time axis** (`analysis/layers/timeline.py`): 10 half-turns crossing all layers. Détail : [docs/encounter.md](docs/encounter.md).
   **Chassis × ability marriage** (`analysis/layers/marriage.py`, table `ability_marriage`, `aospy encounter marriage`): mariage = D × S × F × A × R, une grille par famille d'aptitude. Détail : [docs/marriage.md](docs/marriage.md).
4. **Abilities × army** (`analysis/layers/listing.py` + `listgrid`, `stacking`, `givers`, `chains`, `buildup`, `aospy roster analyze --list <file>`): the *numbers* a human list analysis builds on, never the analysis itself. Détail : [docs/listing.md](docs/listing.md).

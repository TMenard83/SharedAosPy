# Simulateur de bonus

IHM Streamlit pour tester en direct l'effet d'un bonus (règle d'armée ou libre)
sur une unité : profil avant/après, impact sur un duel de référence, et
position dans les classements combat×coût — sans jamais écrire en base ni
régénérer de PDF. Inspiré de [aos-statshammer](https://aos-statshammer.herokuapp.com/).

## Installation

```bash
pip install -e ".[gui]"   # installe streamlit + l'extra [analysis] (pandas/statsmodels)
```

## Lancement

```bash
streamlit run src/aospy/bonus_simulator/app.py
```

Streamlit affiche une URL locale (par défaut `http://localhost:8501`) et tente
d'ouvrir le navigateur automatiquement.

**Premier lancement** : Streamlit demande une adresse e-mail (onboarding). Pour
répondre en une fois et ne plus être interrompu (utile en lancement
non-interactif, ex. arrière-plan) :

```bash
mkdir -p ~/.streamlit
printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
```

**Prérequis pour la section « Classement »** : elle lit la table `unit_benchmark`
(via `whatif.rank_against_pool`), donc il faut l'avoir peuplée au moins une
fois, avec les mêmes modes que ceux attendus par `whatif.py` :

```bash
aospy unit benchmark-all --charge none --attacker-mode floor66 --defender-mode mean --include-heroes
```

Sans ça, l'IHM reste utilisable (profil et impact duel fonctionnent toujours)
mais affiche un avertissement à la place du classement.

## Utilisation

1. **Armée** puis **Unité** (barre latérale, deux menus déroulants en cascade).
2. **Bonus d'armée** : coche une ou plusieurs règles listées pour l'armée
   sélectionnée (curatées dans `data/json/army_rules.json` — voir plus bas).
3. **Bonus libre** : ajuste toucher/blesser/rend/save/ward/dégât/attaques à la
   main (cumulable avec les règles cochées).
4. **Profil avant/après** : tableau des profils d'arme + save/ward, avant et
   après application du bonus net.
5. **Impact en duel** : ROI moyen (plancher 66%) et points nets moyens contre
   toutes les unités des autres armées, avant vs après.
6. **Classement combat × coût** : rang de l'unité (avec/sans bonus) dans le
   même pool que le « Panthéon des Champions » (`reports/best_unites.py`/
   `best_heros.py`), troupes et héros séparés, avec les rangs voisins.

## Ajouter une règle d'armée

Éditer `data/json/army_rules.json` (liste plate, un objet par règle) :

```json
{
  "army": "Nom exact de l'armée (colonne `army.name`)",
  "name": "Nom de la règle",
  "description": "Texte affiché à côté de la case à cocher",
  "delta": {"wound": 1, "save": 1}
}
```

`delta` accepte n'importe quel sous-ensemble des champs de `bonus.StatDelta` :
`hit`, `wound`, `rend`, `save`, `ward`, `damage`, `attacks` (tous par défaut à
0). Rechargé à chaque lancement de l'IHM — pas de redémarrage de la base
nécessaire.

## Voir aussi

la section « Architecture interne » plus bas pour le détail d'architecture — quel
module fait quoi, pourquoi `DuelRules` est fixé explicitement, comment
`cost_model.predict_one` évite de ré-implémenter l'encodage catégoriel à la
main, etc.

## Architecture interne

**`bonus_simulator/`** (needs `[gui]`: streamlit, implies `[analysis]`) — self-contained: engine (`bonus.py`), orchestration (`whatif.py`) and Streamlit UI (`app.py`/`army_rules.py`) for this one feature all live together here rather than split across `engine/`/`orchestration/`/a UI package, since none of it is reused elsewhere. Live "what-if" bonus simulator; the user guide is the first part of this README.

A Streamlit IHM (`streamlit run src/aospy/bonus_simulator/app.py`, needs `[gui]`) lets you pick an army then a unit (two cascading dropdowns), apply a bonus — either a named army rule from `data/json/army_rules.json` (e.g. Stormcast Eternals' "Heure de Gloire", +1 to wound/+1 to save) or a free-form stat delta — and see the impact on that unit's profile, a live duel benchmark, and its position in the same combat×cost "best units/heroes" pantheon as `reports/best_unites.py`/`best_heros.py`, all recomputed on the fly. Nothing is written to the DB and no PDF is touched. The first part of this README is the user-facing guide (launch, Streamlit's first-run e-mail prompt gotcha, how to add a rule); this section covers the internals. The whole feature — engine, orchestration and UI — lives in this one package rather than split across `engine/`/`orchestration/`/a UI package, since none of `bonus.py`/`whatif.py` is reused outside it (unlike `combat.py`/`benchmark.py`, which the rest of the codebase depends on).

- **`bonus_simulator/bonus.py`**: `StatDelta` (additive hit/wound/rend/save/ward/damage/attacks deltas) and `apply_bonus(unit, delta)` build a modified *copy* of a `Unit`/its `Weapon`s via `dataclasses.replace` — no change to `engine/combat.py` itself, since it already reads `weapon.attacks/hit/wound/rend/damage`/`defender.save/ward` directly with no intermediate "resolved profile" layer. `hit`/`wound`/`save` clamp at 2+ (best possible roll); a ward bonus on a unit with no ward grants a 6+ ward (internal convention: absent ward reads as target 7, same as `features.py::UnitFeatures.ward_num`); `weapon.name` is never touched, since `loadout.py::model_counts` matches profiles by name. `Bonus` (name + description + `StatDelta`) is the named-rule shape loaded from JSON.
- **`data/json/army_rules.json`** / **`bonus_simulator/army_rules.py::load_army_rules`**: hand-curated list of named army rules, same JSON-seed convention as `data/json/armies.json` (see CLAUDE.md, "Data files") but loaded fresh on every IHM run rather than into the DB — this list isn't fleshed out yet (only the one example above), left for incremental curation. `data/wahapedia/Faction_abilities.csv` (`type_name == "Battle Traits"`) already carries this text for every Wahapedia faction and is a natural future auto-import source, not wired up.
- **`bonus_simulator/whatif.py`**: `live_combat_row(con, unit)` duels an in-memory `Unit` against every unit in the other armies and aggregates exactly like `reports/aggregate.py` (`avg_floor_roi_pct` = mean of the 5th/34th/80th percentile of ROI across duels) — but live, via `repository.get_ranking_pool` (a DB-backed twin of `aggregate.py`'s JSON export) instead of a static snapshot file, so a hypothetical unit can be compared against the real pool without needing `scratch/per_unit_nocharge_floor66_TM.json` to exist. `rank_against_pool(con, unit)` combines that with `cost_model.predict_one` (see `analysis/README.md`, "Cost model") and `analysis/cost/scoring.combined_score` (same weights as `best_unites.py`/`best_heros.py`) to insert the unit into the troupe/hero pool and return its rank + neighboring rows. Both require the **same `DuelRules`** the CLI defaults to (`double_shoot=True, charge_move_threshold=True` — `cli/common.py::_duel_rules`'s argparse defaults, not `DuelRules`' own dataclass defaults of `False`/`False`) to stay comparable to the persisted `unit_benchmark` pool; `whatif.RANKING_DUEL_RULES` pins this explicitly rather than relying on either default. `rank_against_pool` raises `ValueError` if `unit_benchmark` hasn't been populated yet (`aospy unit benchmark-all --charge none --attacker-mode floor66 --defender-mode mean --include-heroes`).
- **`bonus_simulator/app.py`**: uses absolute imports (`from aospy.bonus_simulator...`), not the relative imports (`from ..x`) used everywhere else in the codebase — `streamlit run` execs this file as a standalone script with no package context, so relative imports fail at runtime there specifically.

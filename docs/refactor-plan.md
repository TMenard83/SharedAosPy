# Plan de refactorisation aospy (2026-11-21)

Une session Claude Code **par lot**. Chaque session part d'un contexte vide (nouvelle session ou `/clear`),
lit ce fichier, fait **un seul lot**, puis met à jour la section « Journal » en bas.

## Règles communes à tous les lots

- **Aucun changement de comportement** (sauf lot 6b, explicitement à part). Un lot = refactor pur.
- Référence avant le lot : `pytest` → **648 passed** (2026-11-21, ~30 s). Le lot se termine tests verts,
  même nombre de tests ou plus.
- À partir du lot 0 : le test de non-régression PDF (`tests/tournament_kit/test_pdf_golden.py`) doit rester vert.
  Si une référence doit changer, c'est un changement de comportement : s'arrêter et demander.
- Travailler sur une branche `refactor/lot-N` créée depuis la branche courante une fois le lot 0 fait.
  Proposer le commit à l'utilisateur en fin de lot (ne pas committer sans son accord).
- **Coordination** : d'autres sessions (ex. `aospy-81`) peuvent travailler en parallèle dans `engine/` ou
  `analysis/`. Avant de toucher un fichier, vérifier `git status` ; si des modifs non committées existent dans
  le périmètre du lot, envoyer un message aux autres sessions (`ListAgents` puis `SendMessage`) avant d'y toucher.
  Si deux lots doivent tourner en parallèle, utiliser un worktree git.
- Garder les docstrings / messages CLI en français (convention du projet).
- Après un déplacement de module : mettre à jour les imports dans `src/`, `tests/`, `scripts/`, `pour_demarrer/`,
  les skills `.claude/skills/*/SKILL.md` et CLAUDE.md (`grep -rn "ancien.chemin"`).
- Fin de lot : compléter le Journal (ce qui a été fait, décisions prises, pièges pour la suite).

## Prompt à coller pour lancer un lot

> Fais le lot N de docs/refactor-plan.md. Lis d'abord tout le fichier (règles communes + journal).

---

## Lot 0 — Préalables et filet de sécurité

**Objectif** : pouvoir refactorer sans risque.

1. Vérifier `git status` : le travail en cours (`analysis/{bearers,chassis,encounter,realized}.py`,
   `tournament_kit/pdf_builder.py`, `tests/analysis/test_encounter.py`, CLAUDE.md au 2026-11-21) doit être
   committé par son auteur avant de commencer. Sinon, demander à l'utilisateur.
2. Outillage dans `pyproject.toml` :
   - `[tool.pytest.ini_options]` : `testpaths = ["tests"]`, filtre des `RuntimeWarning` de statsmodels.
   - `ruff` dans l'extra `dev` + `[tool.ruff]` minimal (règles `E`, `F`, `I`) ; **ne pas** reformater tout le
     code dans ce lot, juste le configurer et noter le nombre d'avertissements dans le Journal.
   - `import-linter` dans `dev` + un contrat `layers` qui reflète l'ordre **visé** :
     `cli > tournament_kit | bonus_simulator | reports > analysis > abilities > orchestration > importers > engine > persistence > domain`.
     Les violations actuelles (voir lot 3) sont listées en `ignore_imports` avec un commentaire « lot 3 ».
3. **Test de non-régression PDF** `tests/tournament_kit/test_pdf_golden.py` :
   - pour chaque liste de `tests/fixtures/lists/` × chaque mode (`hybrid`, `en`, `fr`, `fr-extended`, `fr-split`,
     `fr-split-simple`, `en-split-simple`) : `build_roster_pdf` dans `tmp_path`, extraction du texte page par
     page avec pypdf, comparaison à `tests/fixtures/golden/<liste>__<mode>.txt` ;
   - comparer aussi `RosterPdfResult` (unmatched, wahapedia_used) et le nombre de pages ;
   - `pytest.skip` si les sources locales sous droits (`data/Battle tome/`, `data/Manuel du général/`) sont
     absentes ;
   - option `--update-golden` (via `conftest.py`) pour régénérer les références ;
   - les références sont générées **sur le code actuel**, avant tout refactor.
4. Vérifier : `pytest` vert, `lint-imports` vert, `ruff check` tourne.

**Fini quand** : tout ça est en place et le Journal donne le nombre de tests et la durée.

## Lot 1 — Rangement de la racine (sans risque)

1. Retirer du suivi git (et déplacer dans `scratch/output/archives/`, ignoré par git) : `bench_*.log`,
   `bench_*.txt`, `army_ranking_*.csv`, `_inspect_arkanaut.py`.
2. `scratch/` : les `experiment_*.py` sont les expériences **rejetées** du modèle de coût (CLAUDE.md, « Cost
   model »). Les déplacer dans `src/aospy/analysis/experiments/rejected/` **ou** les supprimer — **demander à
   l'utilisateur**. Les `scratch/*.json` (instantanés de duels) restent tant que `reports/` en dépend (lot 6).
3. `scripts/l3_*.py` : **demander à l'utilisateur** s'ils restent des scripts ou deviennent une sous-commande
   `aospy l3` (dans ce cas, seulement noter la décision ; la migration se fera au lot 5). Vérifier les alias
   `tm-aospy-*` de `~/.bash_aliases` qui pointent dessus.
4. Ajouter à `.gitignore` ce qui doit l'être.

## Lot 2 — Alléger CLAUDE.md (94 Ko → 10-15 Ko)

**Pourquoi** : CLAUDE.md (~25 000 tokens) est rechargé à chaque session.

1. Créer un `README.md` par sous-paquet de `src/aospy/` (ou enrichir la docstring de `__init__.py`) et y
   **déplacer**, sans perte, les sections détaillées de CLAUDE.md : Wahapedia import, corrections, Legends,
   composites BSData, wielders, Anti-X/Charge, damage floor, cost model, bonus simulator, tournament kit (+ modes),
   ability analysis (4 couches).
2. CLAUDE.md garde : présentation, setup et commandes, carte des couches (une ligne par paquet + lien vers son
   README), règles transverses (français, schéma dans `schema.sql`, SQL uniquement dans `persistence/`,
   conventions des JSON curés, sources sous droits non versionnées), et une ligne « lire le README du paquet
   avant de le modifier ».
3. Retirer l'historique (dates, « caught once already », expériences) : il est dans git et dans la mémoire.
4. Mettre à jour les skills `.claude/skills/*` qui citent des sections de CLAUDE.md.
5. Vérifier qu'aucune information n'est perdue : liste des sections avant/après dans le Journal.

## Lot 3 — Remettre les couches en ordre

1. `persistence/repository.py:967-1065` importe `ENCOUNTER_COLS`/`REALIZED_COLS`/`MARRIAGE_COLS`/`BEARER_COLS`
   depuis `analysis/` → déplacer ces définitions dans `persistence/` (ex. `persistence/analysis_tables.py`),
   `analysis/` les importe de là.
2. Lecteur commun des CSV Wahapedia : aujourd'hui 9 modules lisent `data/wahapedia/*.csv` eux-mêmes
   (`importers/{bsdata,wahapedia}.py`, `abilities/source.py`, `bonus_simulator/army_rules.py`,
   `tournament_kit/{pdf_builder,warscroll_card}.py`, `tournament_kit/translation/{wahapedia_lookup,rules_resolution,absent_references}.py`).
   Créer une couche basse (ex. `aospy/sources/wahapedia_csv.py`) : lecture (pipe, BOM), filtres canoniques
   (`_canonical_ids`), Legends (`_legends_warscroll_ids`), contenus expirés (`_is_expired_variant`). Supprime les
   imports privés de `abilities/source.py:21-24`.
3. Normalisation de noms : ~8 fonctions `_norm`/`_normalize` (`wahapedia_lookup`, `warscroll_index`,
   `tactic_cards`, `encounter`, `loadout`, `verify`, `bsdata`…). Les regrouper dans `aospy/text.py` **seulement
   quand elles font exactement la même chose** (vérifier chacune, sinon garder et documenter la différence).
4. Rendre publiques (sans `_`) les 9 fonctions privées importées d'un module à l'autre
   (`grep -rnE "^from \.+[a-z_.]+ import .*\b_[a-z]" src`).
5. Découper `repository.py` (1 132 lignes) en `persistence/repo/{units,benchmarks,abilities,analysis}.py`, avec
   `repository.py` qui réexporte tout (pas de changement d'API pour les appelants dans ce lot).
6. Retirer les `ignore_imports` correspondants du contrat import-linter.

## Lot 4 — `tournament_kit` (le plus gros, peut se faire en 4a/4b/4c)

Le test golden du lot 0 est le juge. Le relancer après chaque étape.

- **4a. État global → options explicites.** `warscroll_card.py` a 9 drapeaux de module (`_HIDE_TURN_QUALIFIER`,
  `_SECTIONED`, `_BASE_LAST`, `_FRENCH_KEYWORDS`, `_BOLD_SET_UP`, `_FRENCH_WEAPON_TAGS`, `_ENGLISH_LABELS`,
  `_FACTION_KEYWORDS`…) modifiés via `set_*`/`global`, plus `_DRAWN_BADGE_SHAPES`/`_DRAWN_PILL_COLORS`. Les
  remplacer par un dataclass `RenderOptions` (gelé) passé explicitement, et un `RenderTracker` (pastilles
  dessinées) porté par le build. Si le passage explicite est trop invasif, un `contextvars.ContextVar` est
  acceptable — le noter dans le Journal.
- **4b. Modes.** Remplacer les tuples `FR_MODES`/`SPLIT_MODES`/`SIMPLE_MODES`/`FR_NAME_MODES` (17 tests `in …`
  dans `pdf_builder.py`) par un `ModeSpec` (langue, split, simple, patch FR, copie de pages, noms FR) construit
  depuis `RosterMode`. La CLI et `build_roster_pdf(..., mode="fr-split")` restent inchangées.
- **4c. Découpage des modules.**
  - `warscroll_card.py` (3 633 l.) → paquet `render/` : `pills.py` (pastilles, badges, `_CastBadge`, légende),
    `phases.py` (classement, rail, ordres, côtés du tour), `text.py` (flavor, gras « Placer », coupure de noms,
    `tr()`/libellés EN, tags d'armes FR), `cards.py` (carte d'unité/règles/tactique), `layout.py` (deux colonnes,
    `_chunk_group`, shrink-to-fit). `warscroll_card.py` réexporte l'API publique le temps de la transition.
  - `pdf_builder.py` (2 067 l.) → `split_pool.py` (pool d'aptitudes split, clusters de choix, alias, drops),
    `assembly.py` (pypdf, numéros de page, scénarios), `cover.py`, `pdf_builder.py` = orchestration.
  - `translation/` (mal nommé) → `sources/` (chargeurs : `wahapedia_lookup`, `warscroll_index`, `tactic_cards`,
    `faction_rules_fr`, `generic_core_abilities`, `season_rules`, `roster_simplifications`) et `resolution/`
    (`rules_resolution`, `absent_references`).
  - Découper `tests/tournament_kit/test_pdf_builder.py` (59 Ko) en suivant.
  - Mettre à jour les skills `roster-pdf`, `faction-rules-fr`, `warscroll-index`.

## Lot 5 — CLI

1. `cli/commands.py` (942 l., 39 `cmd_*`) + `cli/__init__.py` (426 l., 49 sous-parseurs) → un module par groupe
   (`cli/{db,import_,unit,battle,cost,roster,ability,chassis,encounter}.py`), chacun avec une fonction
   `register(subparsers)` et ses `cmd_*`. `cli/__init__.py` ne fait que les assembler. `_connect` dans
   `cli/common.py`.
2. Vérifier que `aospy --help` et l'aide de chaque sous-commande sont identiques avant/après (diff de la sortie).
3. Si le lot 1 a décidé `aospy l3` : migrer `scripts/l3_*.py` ici et mettre à jour les alias `tm-aospy-*`.

## Lot 6 — `analysis/` et `reports/`

- **6a (refactor pur).** Séparer `analysis/` en `cost/` (`features`, `cost_model`, `experiments/`) et
  `layers/` ou un paquet par couche (`chassis`, `encounter`, `realized`, `marriage`, `bearers`, `timeline`,
  `listing`, `assault`). Brancher `reports/` sur `repository.get_ranking_pool` au lieu de
  `scratch/per_unit_nocharge_floor66_TM.json` ; ensuite les `scratch/*.json` peuvent partir. **Coordonner avec
  les autres sessions : `analysis/` est la zone la plus active.**
- **6b (changement de comportement, à valider avec l'utilisateur, commit séparé).** Bug noté dans CLAUDE.md :
  les variables mêlée/tir de `features.py` recalculent les choix « 1 parmi » par sous-ensemble d'armes →
  passer par `chassis.weapon_damages`, refitter le modèle de coût, comparer R² et résidus avant/après.

## Plus tard (non planifié)

- `abilities/extract.py` (1 116 l. de règles regex) : découper par famille de règles si ça devient gênant.
- Appliquer `ruff format` à tout le code (un commit dédié, sans rien d'autre).

---

## Journal

| Lot | État | Date | Notes pour la suite |
|---|---|---|---|
| 0 | fait | 2026-11-21 | Branche `refactor/lot-0`, partie du commit WIP de `feature/cost-model-and-stats` (travail d'aospy-81 committé avec l'accord de l'utilisateur). **`pytest` : 707 passed, ~105 s** (658 + 49 golden ; le golden seul ≈ 73 s, `-k "not golden"` pour aller vite). Golden : 7 listes × 7 modes, `tests/fixtures/golden/*.txt` (1,9 Mo), texte par page + pages (+ variante scénarios) + champs de `RosterPdfResult` ; horodatage de couverture neutralisé par regex. **Piège** : `build_roster_pdf` laisse les drapeaux de module de `warscroll_card` positionnés → le test golden les sauvegarde/restaure (fixture autouse) ; sans ça, 3 tests de `test_warscroll_card.py` cassaient. Le lot 4a peut supprimer cette fixture. `lint-imports` : contrat vert avec 5 `ignore_imports` (4 `persistence.repository → analysis.*` pour le lot 3, **+1 non prévue** : `bonus_simulator.whatif → reports.cost_common` (`combined_score`), notée « lot 6 »). `ruff check` (E, F, I, ligne 120) : **359 avertissements** sur tout le dépôt (211 dans `src/`) — 277 E501, 46 I001, 18 F401, 5 E402, 4 E731… non corrigés. ruff/import-linter installés dans `.venv` via `uv pip install`. |
| 1 | fait | 2026-11-21 | Branche `refactor/lot-1` (depuis `refactor/lot-0`). `bench_*.log/txt`, `army_ranking_*.csv`, `_inspect_arkanaut.py` retirés de git → `scratch/output/archives/` ; motifs racine ajoutés à `.gitignore`. **Décision utilisateur** : les 7 `scratch/experiment_*.py` (rejetées) **supprimés** (historique git) ; commentaires mis à jour dans `cost_model.py` et CLAUDE.md (« Cost model » : « the rejected ones were deleted »), et 4 chemins périmés `scratch/experiment_*` de `features.py` corrigés vers `analysis/experiments/*.py` (expériences adoptées, déjà déplacées). **Décision utilisateur** : `scripts/l3_*.py` deviendront une sous-commande **`aospy l3`** au lot 5 — 5 alias à migrer dans `~/.bash_aliases` (`tm-aospy-l3-{matchups,listes,diag,compare,scenarios}`) ; `l3_aptitudes.py`/`l3_export_lists.py` n'ont pas d'alias. `scratch/*.json` laissés (lot 6). `pytest` 707 passed (~102 s), `lint-imports` vert. |
| 2 | fait | 2026-11-21 | Branche `refactor/lot-2` (depuis `refactor/lot-1`). CLAUDE.md **98 Ko → 10,6 Ko** : présentation, commandes (+ `lint-imports`/`ruff`/golden, phrase « pas de linter » périmée corrigée), tableau des paquets avec lien vers leur README, règles transverses, fichiers de données (liste à puces, + `source_corrections`/`ability_overrides`/`season_rules`/`roster_simplifications` qui manquaient). **Sections déplacées** (découpage par script, contenu verbatim, titres rétrogradés d'un niveau ; contrôle : toute ligne non vide de l'ancienne Architecture → Ability analysis se retrouve dans un README, sauf carte domain/cli et titres) : `engine/README.md` (combat, loadout, renforts, Anti-X/Charge, plancher exact), `orchestration/README.md` (benchmark/simulation, économie de points, modificateurs), `persistence/README.md` (db, repository, seed, `unit_benchmark`, migrations `imported_at`/modes), `importers/README.md` (bsdata, wahapedia, wielders BSData, import Wahapedia, corrections, Legends/`--clean-stale`, composites, résolution des wielders), `analysis/README.md` (features/cost_model, Cost model, 4 couches — couches 2-4 en détail), `abilities/README.md` (couche 1, pipeline, grille, tags, périmètre, overrides, limites), `bonus_simulator/README.md` (+ section « Architecture interne »), `tournament_kit/README.md` (Tournament kit, Wahapedia fallback, Roster modes, faction_rules_fr). **Retiré** : dates, « caught once already », « found via a user report », « Earlier plan » (doublon couche 4), « before 2026-11-20 every level was lost » ; mentions périmées corrigées (`faction_rules_fr.json`/`generic_core_abilities.json` « vides » → 21 factions / 31 entrées ; chemins `translation/`). Renvois « cf. CLAUDE.md » du code/tests (14) et de `pour_demarrer/README.md` repointés vers le README concerné ; renvois inter-sections devenus inter-fichiers corrigés. Skills : aucun ne citait une section de CLAUDE.md. `pytest` 707 passed, `lint-imports` vert. **Pour la suite** : le README de `tournament_kit` (44 Ko) est le prochain à alléger au lot 4c (un README par sous-module) ; les README restent en anglais (texte déplacé, non traduit). |
| 3 | fait | 2026-11-21 | Branche `refactor/lot-3` (depuis `refactor/lot-2`). **`pytest` : 712 passed (~100 s)** (+5 : `tests/persistence/test_analysis_tables.py`). `lint-imports` vert, **1 seul `ignore_imports`** (celui du lot 6) ; couches ajoutées sous `persistence` : `aospy.sources` puis `aospy.text`. `ruff` 359 → 340 (seuls les imports des fichiers touchés réordonnés/nettoyés). **1.** `persistence/analysis_tables.py` (`ENCOUNTER/REALIZED/MARRIAGE/BEARER_COLS`) ; `analysis/` ne les importait que pour ses docstrings → plus d'import. **Piège évité de justesse** : le retrait des imports locaux dans `repository.py` laissait des `NameError` dans les `replace_*` que *aucun test n'exerçait* ; trouvé par `ruff --select F821`, d'où le nouveau test. Lancer `ruff check --select F821` après tout déplacement. **2.** `aospy/sources/wahapedia_csv.py` : `read_csv`, `legends_warscrolls`/`legends_warscroll_ids`, `canonical_ids`, `is_expired_variant`, `ROR_ROLE`, `DEFAULT_DATA_DIR`. Seuls **5** modules lisaient vraiment les CSV (les 4 autres cités par le plan ne les mentionnent qu'en docstring) : les 2 importeurs, `abilities/source.py` (imports privés supprimés), `wahapedia_lookup` (garde son nettoyage de glyphes) et `absent_references` (garde son cache tuple). `bsdata._wahapedia_legends_names` réutilise `legends_warscrolls`. Tests de dédoublonnage laissés dans `tests/importers/test_wahapedia.py`, imports repointés. **3.** Une seule paire strictement identique : `tactic_cards._normalize` = `warscroll_index._normalize` → `aospy/text.py::fold_name`. Les 6 autres diffèrent et restent en place, différences documentées dans la docstring de `text.py` (`loadout`, `encounter`, `bsdata._normalize_name`, `verify._norm`, `wahapedia_lookup.normalize_name` ; `bearers._norm_kw`/`combat._normalize_abilities` font autre chose). **4.** 19 fonctions privées importées d'un module à l'autre (pas 9), renommées : `probe_for_effect`, `plan_offense`, `unit_durability`, `parse_keywords` (encounter) ; `dominant_crit_type`, `compute_effective_wounds`, `unit_type_of` (features) ; `convolve`, `effective_counts` (combat) ; `pct_rank` (chassis) ; `collapse_modes`, `normalize_weapon_name` (ex-`loadout._norm`) ; `resolve_rules`, `find_pledge_battle_trait` (rules_resolution) ; `classify_phase`, `strip_flavor` (warscroll_card) ; `normalize_name`, `sanitize_glyphs` (wahapedia_lookup) ; `clean_html` (pdf_builder). Noms choisis pour ne heurter aucun nom existant (`offense`/`defense`/`probe`/`effective_wounds`/`unit_type` sont des colonnes/variables). **Piège** : le remplacement mot entier avait aussi changé les chaînes `Unit(name="_probe")` (4 sondes) → rétablies. **Restent privées** (constantes, hors périmètre) : `_NO_MODS`, `_PROBE_SAVE4`, `_PLURALS`, `_BANNER_PLEDGED_GOD`, `_PLEDGE_OPTION_RE`, `_FULL_PAGE_HEIGHT`, `_ENHANCEMENT_CATEGORY_LABELS`, et `_ANTI_RE`/`_CHARGE_RE`/`_normalize_abilities`/`_parse_crit` importés par `analysis/experiments/weapon_tags.py`. **5.** `persistence/repo/{units,benchmarks,abilities,analysis,_sql}.py` (découpage par section, code inchangé, imports relatifs décalés d'un niveau) ; `repository.py` = façade qui réexporte tous les noms, privés compris (`# ruff: noqa: F401`). Aucun test ne monkeypatche `repository` (vérifié), donc la façade ne change rien. **6.** `ignore_imports` du lot 3 retirés. Docs : `persistence/README.md`, `importers/README.md` (section « Shared Wahapedia CSV reader »), tableau des paquets de CLAUDE.md (`sources/`, `text.py`), renvois de noms dans les README et 2 skills. **Pour le lot 4** : `pdf_builder.clean_html`, `warscroll_card.classify_phase`/`strip_flavor`, `rules_resolution.resolve_rules` sont maintenant publics, à placer dans les nouveaux modules sous ces noms. |
| 4 | à faire | | |
| 5 | à faire | | |
| 6 | à faire | | |

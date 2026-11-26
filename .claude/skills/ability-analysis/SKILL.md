---
name: ability-analysis
description: Base d'analyse hors contexte de toutes les aptitudes AoS4 (tables DuckDB ability*, CLI `aospy ability`) — axes puissance/fiabilité/mise en place/interaction, verdict plan/pari/anecdotique, tags d'utilité. Utiliser pour juger une aptitude, chercher des aptitudes par effet/portée/faction, analyser les interactions unité–aptitudes, les combos d'une liste, ou corriger une analyse (overrides).
---

# Analyse des aptitudes

**Architecture en 4 couches (à respecter)** : 1) aptitude *ex-nihilo* (cette base) — notée sans savoir
sur qui elle tombe ; 2) *châssis* — la charte nue (PV, sauvegarde, profils d'arme : moteur de combat +
modèle de coût) ; 3) *rencontre aptitude × châssis* — gain réel sur une charte via le moteur (+1 dégâts
sur armes à 1 dégât = énorme, +N attaques sur une arme Compagnon = nul) → refonte des « meilleures
unités » ; 4) *aptitudes × armée* — combos et mariages d'une liste. Ne jamais chiffrer une aptitude
en l'appliquant à une « unité médiane » : c'est de la couche 3, pas de la 1.

Fondation commune des analyses « meilleures unités », « combos de liste », « scoring » et « matchups ».
Interroger la base, **ne pas relire les textes Wahapedia** (c'est tout l'intérêt : peu de tokens).

**Cascade imposée** : après tout changement d'analyseur, d'override, de correction ou d'import, `aospy cascade`
(reconstruit 1 → 2 → 3 dans l'ordre) ; `aospy cascade --status` dit ce qui est périmé. Chaque couche refuse de
tourner sur une couche du dessous périmée.

## Châssis (couche 2)

```bash
aospy chassis build                 # après un import ou un benchmark-all
aospy chassis show "Chaos Warriors" # attaque, défense, centiles, %D1, %Compagnon, résidu de coût, duel
aospy chassis list --army Khorne --sort share_damage1
```
Table `unit_chassis` : la charte nue (aucune aptitude), avec les descripteurs de compatibilité que la
couche 3 lira (`share_damage1`, `share_companion`, `share_melee`, `attacks_total`, `crit_type`).

## Rencontre aptitude × châssis (couche 3)

```bash
aospy encounter build                                  # après `ability analyze` + `chassis build` (~1 s)
aospy encounter list --unit "Chaos Warriors"           # ce que chaque buff ami rapporte sur CETTE charte
aospy encounter list --own --sort off_per_100          # aptitudes propres des chartes, dégâts gagnés / 100 pts
aospy encounter list --ability "Bless Weapons"         # même effet, receveur par receveur
```
Table `ability_encounter` : gain **conditionnel** (« si l'effet s'applique ») en dégâts d'un round vs save 4+
(`off_*`) et en coups à porter (`def_*`), relation porteur/allié, `source` (charte, formation, domaine, AoR…),
conditions/durée. Receveurs filtrés par `ability.friendly_target` (restriction de cible amie, analyseur v6).
`fight_twice` (« can use 2 FIGHT abilities », vrai double combat) = mêlée ×2. Non traduits : `extra_fight` (= combattre juste après, tempo), débuffs ennemis, relances.
Meilleures unités (`unit_realized`) : `aospy encounter best [--troops|--heroes] [--sort off_gain] [--detail]` —
indicateur combiné √(dég/100 × dur/100), troupes et héros classés séparément ;
châssis + aptitudes propres qui boostent l'unité. Poids validés : rounds 2-3 = 1, 1/4/5 = 1/3 ; passif ou
réutilisable chaque tour = 1 (« 1/tour armée » = anti-spam, compte en liste) ; 1/bataille courte = 1/2 (kairos),
1/bataille pour le reste de la bataille = 8/9 ; × P(déclenchement) (prières : points rituels stockés) ;
conditions = aucun poids → colonne « bon cas ». Manque connu : coûts en ressource de faction non pondérés.

## Mettre à jour la base

```bash
.venv/bin/python -m aospy ability analyze      # ~1,5 s, reconstruit tout ; à relancer après refresh Wahapedia
.venv/bin/python -m aospy ability stats        # verdicts, « à revoir » par origine, tags
```

## Interroger

```bash
aospy ability search --faction SE --tag bulle-12 --tag buff-offensif --verdict plan   # verdicts : plan, correct, pari, bonus, anecdotique, a-revoir
aospy ability search --owner "Chaos Legionnaires" --text
aospy ability search --tag blessures-mortelles --tag fiable --sort power --limit 20
aospy ability show "Sow Confusion"             # texte, 4 axes avec justification, tags
aospy ability tags                             # vocabulaire complet
```

SQL direct (DuckDB `data/aospy.duckdb`) pour les analyses composées :

```sql
-- interactions unité–aptitudes (unités importées en base)
SELECT unit_name, name, verdict, power, interaction FROM unit_ability WHERE army_name = 'Stormcast Eternals';
-- bulles amies d'une faction, par rayon
SELECT a.name, a.range_inches, a.power FROM ability a JOIN ability_tag t ON t.ability_uid = a.uid
WHERE t.tag LIKE 'bulle-%' AND a.faction_id = 'SE' ORDER BY a.power DESC;
-- effets chiffrés (ex. tous les +1 à la blessure amis)
SELECT a.name, e.* FROM ability_effect e JOIN ability a ON a.uid = e.ability_uid
WHERE e.kind = 'stat_mod' AND e.stat = 'wound' AND e.side = 'friendly';
```

Tables : `ability` (texte, timing, coût, `scope`, `range_inches`, `activation_prob`, `variance`, 4 axes, `verdict`,
`rationale`), `ability_owner` (porteurs), `ability_tag`, `ability_effect` (kind/stat/value/dice/side + **périmètre** :
`weapon_scope` melee/ranged/named/chosen/all, `weapon_name`, `includes_companion`, `target_keywords`,
`target_condition`, `requires`, `duration`), vue `unit_ability`.

```sql
-- effets applicables à un châssis : tous les +dégâts de mêlée amis, avec leurs conditions
SELECT a.name, a.faction_id, e.value, e.target_keywords, e.requires, e.duration
FROM ability_effect e JOIN ability a ON a.uid = e.ability_uid
WHERE e.kind = 'stat_mod' AND e.stat = 'damage' AND e.side = 'friendly' AND e.weapon_scope = 'melee';
```

## Lire un résultat

- Axes 0-3 : **P**uissance, **F**iabilité (déclenchement × variance de l'effet), **M**ise en place, **I**nteraction
  (0 soi-même, 1 une unité, 1,5-2,5 bulle selon rayon, 3 armée).
- Verdict : **plan** (fiable ≥ 2,25 ≈ 2+, facile, forte) et **correct** (idem mais moyenne) se *construisent* ;
  **pari** se *tente* (jet de déclenchement aléatoire) ; **bonus** *arrive* (forte et gratuite mais tardive —
  Dîme de Sang — ou situationnelle — coordination porteur/unité) ; **anecdotique** s'oublie ;
  **a-revoir** = aucun effet reconnu (lire le texte et corriger).
- Vocabulaire joueur : *Death-Star* = unité ennemie surboostée qui efface tout ; tag `anti-deathstar` = débuffs
  cumulés sur une cible (−1 touche + pas de critique…).
- L'analyse est **hors contexte** : la valeur de l'unité porteuse, les combos et le matchup se jugent au-dessus.
- Probabilités : sorts sans dissipation, prières sans points rituels, tests 2D6 contre PV à 50 %.

## Revoir les cas suspects avec l'utilisateur

```bash
aospy ability review               # familles et décomptes (contresens, malus, duree, portee, a-revoir)
aospy ability review contresens    # un lot de 15, texte compris ; --limit N
```
Présenter un lot, laisser l'utilisateur trancher cas par cas, puis écrire ses décisions dans
`data/json/ability_overrides.json` (un cas tranché sort de la file, même sans modification : mettre au
moins une `note`). Si plusieurs cas partagent la même erreur de lecture, corriger plutôt la règle
dans `extract/`/`perimeter.py` (+ test).

## Corriger une analyse

Ne pas modifier les poids pour un cas isolé : ajouter une entrée dans `data/json/ability_overrides.json`
(clé = `uid` affiché par `show`) puis relancer `analyze`.

```json
{"overrides": {"<uid>": {"name": "Sow Confusion", "verdict": "plan", "power": 2.0,
  "add_tags": ["restriction"], "remove_tags": [], "note": "raison, validée par l'utilisateur"}}}
```

Un motif d'extraction raté sur **plusieurs** aptitudes se corrige dans `src/aospy/abilities/extract/` (module de la famille concernée)
(+ un test dans `tests/abilities/`, + `ANALYZER_VERSION` incrémenté).

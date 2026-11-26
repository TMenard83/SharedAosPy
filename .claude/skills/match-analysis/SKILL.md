---
name: match-analysis
description: Méthode et outils pour analyser UN match entre deux listes AoS4 (score attendu et sa décomposition, qui frappe qui, tempo et menaces, plan de match par scénario, PC, tactiques des deux camps, plan B). Deuxième maillon de la chaîne list-analysis → match → pairing-analysis. Utiliser quand on demande « comment jouer contre X », « qui gagne A contre B », un plan de match, ou pour corriger une case de grille de matchups.
---

# Analyse de match (maillon 2/3)

Entrée = **deux fiches liste** (`list-analysis`). Sans elles, les faire d'abord (au minimum §0-§1 et §4 de
`list-analysis` pour l'adversaire), donc la cascade couche 1 → 2 → 3 → 4 à jour (`aospy cascade --status`,
sinon `aospy cascade`) et lue dans l'ordre pour les deux listes. Sortie = la **fiche match**, dont le score alimente `pairing-analysis`.
Répondre en français.

## 1. Le score attendu (point de départ, pas la conclusion)

- L3 : `aospy l3 diag --match A B` → écart de pts de victoire borné ±20 (±3 équilibré, ±8 net) décomposé en
  combat ±6 / scénario ±7 / aptitudes et plan ±7,6 / ajustements nommés. Méthode v2 : skill `l3-matchups`.
- Hors L3 : pas d'équivalent direct (voir « Manques »). À la main : `aospy roster analyze` des deux listes +
  duels d'unités.
- **Contrôle d'intuition** : la décomposition est-elle cohérente avec les deux fiches ? Un écart fort qui vient
  d'un seul terme (souvent aptitudes/indice) est suspect.

## 2. Qui frappe qui (combat)

- L3 : `aospy l3 qui-tue-qui --match A B` → matrice des deux camps, activations pour retirer chaque unité
  (dégâts d'`attrition`, buffs de liste « tout en place » de la couche 4, `--nu` sans) + meilleures réponses
  par cible. `--team <équipe> [--ronde N]` : les 36 paires de chaque ronde dans `Matchups/Qui tue qui <équipe>/`.
- Duels clés : `aospy unit duel --attacker X --defender Y [--charge a] [--attacker-mode floor66]` — moyenne ET
  plancher « 2 fois sur 3 » (la fiabilité compte). Profils défensifs : Ward, Anti-X adverse avant de choisir
  d'encaisser.
- Pour chaque camp : **cibles prioritaires** (pièces centrales fragiles, donneurs de buffs, chargeurs qui
  contre-chargent), **réponses** (quelle unité à moi traite quelle unité à lui, en combien d'activations),
  ce qui ne se traite pas (à éviter/écranter).
- Croiser avec les buffs réellement en place (fiche couche 4 « tout en place »), pas les profils nus.

## 3. Tempo et menaces

- Allonges de menace (mouvement + course/charge, vol, set-up) : `assault.Threat` / `approach.py` donnent
  l'ordre de grandeur ; au-delà, le raisonner par round sur la géométrie (18" d'écart au départ, `marriage.ENGAGE_GAP_ROUND1`).
- Qui engage en premier, avec quoi ; premier/second joueur et double tour ; set-up au tour adverse (menace
  fiable, l'adversaire la voit venir) vs charge à 9" (pari) ; redondance des charges (`assault.py`).
- Contre-charge : engager tous ses chargeurs crédibles la supprime (en a-t-on assez ?).
- Composantes : une aile seule devant = 1000 pts contre 2000 ; renforts par sédimentation.

## 4. Scénario × matchup

- Par carte jouable (ronde L3 : maps dans `Données/scenarios.json`) : composante scénario de la paire,
  `aospy l3 scenario-match A B --ronde N` (aisance des deux listes, note à la main ou du modèle, correction
  centrée) ou `aospy l3 diag --match A B --ronde N` (score complet par carte), puis lecture concrète : qui prend quoi au R1, qui peut
  reprendre (mobilité, vol), qui tue ce qui conteste (contrôle après les combats).
- Tactiques des deux camps (fiches liste §2) : lesquelles l'adversaire peut-il **refuser** (écran, cordon,
  Avalanche/Rogne contre l'empilement…) ; lesquelles de ses tactiques on peut lui refuser.

## 5. PC et ressources face à face

Budget 4 PC/round (5 en outsider) des deux côtés : ce que chacun veut payer à chaque round, et comment le
forcer à dépenser ailleurs (menacer deux choses à la fois, provoquer la relance de charge, forcer le Ralliement).
Dissipation/bannissement contre sa magie, et l'inverse.

## Sortie : fiche match

`scratch/output/match_analyse/<nous>-vs-<eux>/<map ou "général">.md` ; L3 : les fichiers joueur générés par
`aospy l3 matchups` (ne jamais éditer les `.md` générés). Sections :
1. Verdict : score attendu, fourchette (bon jour / mauvais jour), et **pourquoi** en 2-3 lignes ·
2. Leurs menaces et nos réponses (table unité → réponse) · 3. Nos cibles prioritaires ·
4. Déploiement et R1-R2 (qui va où, ce qu'on refuse) · 5. Par scénario : plan de scoring, tactiques ·
6. PC par round · 7. Pièges et plan B (si la charge clé rate, si on perd le roll-off) ·
8. Correction de grille proposée (`ajustements_matchups.json`, `{bonus, raison}` + « proposé par Claude, à valider »).

## Manques (2026-11-25)

- Score de match hors des 54 listes L3 : `evaluate()` exige des `ArmyList` L3 et des z-scores sur la ligue.
  **Élargissement hors L3 prévu à partir du 2026-11-30** (décision de l'utilisateur relayée par la session
  aospy-54) : il faudra une population de référence pour les z-scores.
- Matrice unité × unité d'un match (qui tue qui, en combien d'activations) : calculée dans `attrition()` mais
  pas exposée ; `unit duel` se fait une paire à la fois, sans les buffs de la liste. **En cours dans une
  autre session** (2026-11-25) : s'y coordonner avant de toucher à `attrition()`.
- Simulation de tempo round par round des deux listes face à face (qui atteint qui, quand).
- Géométrie des cartes (déploiement, positions d'objectifs, décors).

Toute correction de la grille : `aospy l3 compare snapshot <nom>` avant, `diff` après, puis régénérer
(`aospy l3 matchups`, `aospy l3 scenarios`). Leviers et pièges : `l3-matchups/leviers.md`.

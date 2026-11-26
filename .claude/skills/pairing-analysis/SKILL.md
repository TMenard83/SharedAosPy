---
name: pairing-analysis
description: Méthode et outils pour l'appariement en tournoi par équipes AoS4 (solveur AOSFF, plan d'appariement avant la ronde, coup suivant pendant l'appariement, analyse a posteriori d'un appariement joué, robustesse aux erreurs de grille). Troisième maillon de la chaîne list-analysis → match-analysis → appariement. Utiliser dès qu'on parle d'appariement, de pairing, de défenseur/attaquants, de plan de ronde ou de « qui joue contre qui ».
---

# Appariement (maillon 3/3)

Entrée = une **grille de scores** nous × eux × map (une case = une fiche match, `match-analysis`). Le solveur
ne vaut que ce que vaut la grille : relire d'abord les cases qui décident (§3). Répondre en français.

## Règles (AOSFF §7.3, équipes de 6) — mémoire `aosff-pairing-defender-chooses`

Le **défenseur choisit** son adversaire parmi les 2 attaquants proposés ; le défenseur conseillé n'est pas notre
meilleure liste mais celle dont le **2e meilleur contre adverse** est le plus haut ; score de ronde = somme des
pts de victoire des 6 parties. Révélations simultanées → jeu à somme nulle à chaque étape.

## 0. D'où vient une case — où lire, comment corriger (L3)

`score(nous, eux, map)` = **grille** + **notes scénario** + **tactiques** (somme faite par
`pairing_scores.build_input`, détail par case dans `PairingInput.detail`). Dossier : `data/2026-27 L3 Aller/`.

| Terme | Valeur | Lire | Données (à corriger ici) | Régénérer |
|---|---|---|---|---|
| Grille du moteur (indép. de la carte, ±20) | combat ±6, scénario ±7, aptitudes/plan ±7,6 | `aospy l3 diag --match A B` (décomposition), `Matchups/Matchups <équipe>/Ronde N — contre X/00 Grille et profils.md`, `aospy l3 qui-tue-qui` | `Données/ajustements_matchups.json` (par paire, avec `raison`), `note_plan` dans `Données/combos/<équipe>.json`, `BT_RULES` (`l3/matchups.py`) — voir `l3-matchups/leviers.md` | `aospy l3 matchups` |
| Notes scénario | 2 pts × (notre note − la leur) sur la carte | `Scénarios/Scénarios <équipe>.md`, `aospy l3 scenario-model --player P` (note calculée) | `Données/notes_scenarios.json` (`equipes.<é>.joueurs.<j>.notes.<carte>`) | `aospy l3 scenarios` |
| Tactiques de bataille | 0,5 × (nos pts de tactique attendus − les leurs), selon les 2 cartes, la carte jouée et l'adversaire | `aospy l3 tactiques --ronde N` (correction par paire et par carte), `--player P` (niveau et p/tour de chaque tactique, source main/modèle), sans option = nos listes, écart main − modèle | niveaux à la main : `tactiques.niveaux` des combos (nos 12) ou `Données/auto/<équipe>/<joueur>.json` (adversaires) ; sinon modèle : `Données/modele_scenarios.json` (`tactiques` : `poids`, `difficulte`, `par_scenario`, `contre`) ; lecture qualitative : `Données/tactiques.json` ; cartes de chaque liste : ligne `Battle Tactic Cards:` de `Listes texte/<équipe>/<joueur>.txt` | rien (lu à chaque appel) ; `aospy l3 tactiques --rafraichir` après un changement de liste ou de base (cache `Données/indicateurs_listes.json`) |

Rondes, cartes jouées et adversaire : `Données/scenarios.json` (`rondes`, `calendrier`). Profils qualitatifs des
listes (plan, combos, forces, limites) : `Données/combos/<équipe>.json` et `Listes/Listes <équipe>.md`.
Avant de changer un terme : `aospy l3 compare snapshot <nom>`, puis relancer le solveur pour voir si le défenseur
change. Hypothèses du terme tactiques (à valider) : docstring de `src/aospy/l3/tactics.py`.

## Méthode prioritaire (utilisateur, 2026-11-25) — à appliquer avant le solveur complet

But : réduire les commutations explorées. **Périmètre** : seulement les rondes que jouent réellement Melusior et
Vae Victis (`Données/scenarios.json` → `calendrier`), pas toutes les paires de la L3. À lancer quand les
analyses prérequises (listes, fiches match, grille de la ronde) sont prêtes.

**Contre** = liste adverse qui nous bat **au combat** : terme combat de la grille (`aospy l3 diag --match A B`)
≤ −3 pts pour nous. Une case à peine négative n'est pas un contre (bruit de grille).

1. **Premier défenseur** : candidates = nos listes favorables sur le scénario de la 1re étape, **classées** par
   leur 2e meilleur adversaire (le moins défavorable d'abord : le défenseur choisit). Pour la première, compter
   ses contres dans l'équipe adverse ; avec **moins de 2 contres**, elle est retenue (elle échappe au seul
   contre en choisissant).
2. **Vérifier la réserve** : avant de valider ce défenseur, s'assurer que nos listes restantes ont encore de
   bonnes cases comme attaquants contre leur défenseur probable (ne pas brûler un attaquant dont on a besoin).
3. **Reste de l'appariement** : dérouler les autres commutations. Si la valeur de ronde est **négative**,
   revenir à l'étape 1 avec la candidate suivante.
4. **Arrêt** : toutes les candidates essayées et ronde toujours négative → garder celle qui perd le moins.
5. **Aucune liste ne passe l'étape 1** : défenseur sacrifié.
   - **Vae Victis** : **Sylvaneth** si le scénario demande de la mobilité, sinon **Ossiarch** ou **Khorne**.
   - **Melusior** : une liste polyvalente, **Martoni** ou **Hibou**, ou le joueur expérimenté **SoDarkSnow**.

**Contrôle** : comparer au solveur (§1, dont `--mode prudent`) et passer `aospy l3 robustesse` (§3) ; si le
choix du défenseur repose sur une case pivot, le signaler au capitaine. Expliquer tout écart avec le solveur.

## 1. Avant la ronde : plan d'appariement

1. Grille à jour : `aospy l3 matchups` puis `aospy l3 scenarios` (défenseurs conseillés par map).
2. Solveur : `aospy l3 pairing --team <équipe> --ronde N` (`--mode mixte` = valeur exacte + probabilités ;
   `--mode prudent` = plancher si l'adversaire voyait notre choix ; `--sans-notes` sans les notes scénario,
   `--sans-tactiques` sans les tactiques de bataille, les deux = grille seule). Score = grille + 2 pts par cran
   de note scénario + 0,5 × écart des pts de tactique attendus (`aospy l3 tactiques --ronde N` pour la
   correction tactiques seule, `--player P` pour le détail d'une liste).
3. Lire : valeur de la ronde, notre défenseur (plancher et proba), leur défenseur attendu, les étapes où le
   choix est serré (écart < 1 pt de victoire entre deux options = indifférent, décider sur le confort des joueurs).
4. Plan écrit pour le capitaine : défenseur par étape, paires d'attaquants à proposer selon leur défenseur,
   listes à ne jamais laisser choisir (nos pires cases), et leurs coups attendus.

## 2. Pendant l'appariement : coup suivant

Renseigner ce qui est révélé et relancer : `--joue NOUS:EUX` (parties fixées), `--def NOUS:EUX` (défenseurs de
l'étape), `--att A,B:C,D` (nos 2 attaquants : leurs 2). Donner une réponse courte : le coup, et la raison.

## 3. Robustesse (à faire avant de croire le solveur)

- **Cases pivot** : `aospy l3 robustesse --team <équipe> --ronde N [--delta 3] [--seuil 0.5]` (~20 s,
  `tm-aospy-l3-robustesse`). Chaque paire (3 maps) bougée de ±δ ; **regret** = ce que coûte le mélange de
  défenseurs actuel si la case est fausse de δ. Pivot = regret > seuil. Le « nouveau défenseur » seul ne dit rien
  (en mixte, le défenseur en tête bascule pour presque toute case) : lire le regret.
- **Fourchette** : `--tirages 200` (~1 min) bruite toute la grille à la fois, σ par paire selon la relecture des
  deux listes (`pairing_noise.SIGMA`, à valider) → valeur de la ronde en centiles 10/50/90, regret du plan de
  référence (moyen, part > seuil), part des tirages où chaque défenseur est en tête. La médiane est souvent
  au-dessus de la référence : le solveur profite du bruit (il choisit après), ce n'est pas un gain réel.
- Compléter par `mixte` / `prudent` / `--sans-notes` / `--sans-tactiques` (les tactiques adverses sont estimées
  par le modèle tant que leurs niveaux ne sont pas écrits) ; corriger une case via `ajustements_matchups.json`
  (snapshot `aospy l3 compare` avant).
- Revoir ces cases avec `match-analysis` (fiche match complète), pas seulement `diag --match`.
- Notes de plan et ajustements non validés par les joueurs = incertitude : le dire dans le plan.

## 4. Après la ronde : analyse a posteriori

Appariement réel vs plan : écart de valeur dû à nos choix, aux leurs, ou à la grille (résultats réels vs scores
attendus par partie). Corriger la grille seulement par ajustements nommés et validés.

## Manques (2026-11-25)

- Cases pivot : faites (`aospy l3 robustesse`, 2026-11-25), une case à la fois seulement. Fourchette faite aussi
  (`--tirages 200`, `l3/pairing_noise.py`) ; ses σ (`SIGMA` : grille 2, liste validée 1, brouillon 1,5, Claude
  seul 2, tactiques non écrites +0,5) sont proposés par Claude, **à valider** par l'utilisateur.
- Grille d'incertitude (fourchette par case) prise en compte par le solveur.
- Solveur câblé L3 seulement (équipes de 6, `Rondes.md`) : pas d'entrée pour un autre événement ni un autre
  format. L'utilisateur ne joue qu'à 6 par équipe pour l'instant : le format à 8 joueurs existe, à faire
  seulement s'il en joue un (note du 2026-11-25).
- Analyse a posteriori (§4) : pas de saisie des résultats réels.

## Sortie

`scratch/output/appariement/<événement>/ronde N - contre <équipe>.md` (L3 : `Fiches/` pour les fiches d'équipe
à la main). Sections : valeur de la ronde · maps · défenseur par étape (+ alternatives) · arbre des réponses
(leurs attaquants → notre choix) · cases pivot et confiance · consignes aux joueurs (une ligne par partie,
renvoi à la fiche match).

Code : `src/aospy/l3/pairing.py` (solveur), `pairing_scores.py` (contrat d'entrée `PairingInput` : le solveur
ne lit que ça ; un autre modèle de scores s'y branche sans toucher au solveur).

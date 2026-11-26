---
name: list-analysis
description: Méthode et outils pour analyser UNE liste d'armée AoS4 (concept, rôles, plan round par round, ressources PC/saison, scoring des tactiques de bataille, lecture par scénario, forces et faiblesses). Premier maillon de la chaîne liste → match (match-analysis) → appariement (pairing-analysis). Utiliser dès qu'on demande d'analyser, juger, comprendre ou préparer une liste (la nôtre ou une adverse).
---

# Analyse de liste (maillon 1/3)

Sortie = la **fiche liste**, entrée obligatoire de `match-analysis`. Répondre en français. Une liste se joue
dans les détails : concept et plan d'abord, chiffres ensuite (mémoire `list-building-concept`, 13 leçons — la
relire avant chaque analyse).

## 0. Données d'abord (bloquant)

1. Export App (`.txt`, ligne `Battle Tactic Cards:` comprise). L3 : `data/2026-27 L3 Aller/Listes texte/<équipe>/<joueur>.txt`.
2. Dossier : `aospy roster dossier --list "<liste.txt>" --out <dossier>` (`tm-aospy-roster-dossier`) → `<stem> -
   couche 4.md` + `<stem> - textes.md` + `liste.txt`. Code de sortie 2 et liste en clair si des unités ne sont pas
   reconnues : vérifier **chaque unité** (renforts, `Scourge of Aqshy:`). `scratch/list_dossier.py` = même chose.
   Une unité manquante fausse tout : la signaler avant tout chiffre.
3. Textes FR : aide de jeu `fr-split-simple` (skill `roster-pdf` ; L3 : `aospy l3 export-lists --pdf`, JSON
   `Aides de jeu/<équipe>/<joueur> (fr-split-simple).json`, cartes `deploy`/`any`/`mine`/`enemy`). L'aide de jeu fait foi.
4. Écart Wahapedia / `faction_rules_fr.json` / scan : le signaler, ne pas trancher seul (mémoire `source-precedence`).

## 1. Concept, rôles, plan

- **Règles constructrices** : l'aptitude ou la tactique qui explique la liste ; éliminer les règles mortes
  (mais un doublon partiel est un complément). Lire les **règles d'armée**, pas seulement les chartes.
- **Rôle de chaque unité** (marteau/deathstar, enclume, cordon, scoring, support, mobilité, ajustement) : partir
  des rôles suggérés de la fiche couche 4 (`analysis/layers/roles.py`), les confirmer ou corriger avec ce que
  l'unité *reçoit* dans la liste. **Composantes** (château lent + aile rapide…) : le tempo d'une aile seule.
- **Croiser les règles** : chaque aptitude à cible unique sur chaque receveur avec ce qu'il a déjà (section
  « sur qui les poser »). Les effets indépendants se multiplient ; plafond ±1 toucher/blessure/sauvegarde.
- **Plan round par round** (R1 → R5), une fois/bataille au round où elle paie le plus, enchaînements
  (dégagement → Ralliement, set-up au tour adverse = menace fiable, charge à 9" = pari, redondance = plan).
- **Ressources** — obligatoire : budget **4 PC/round (5 en outsider)** ; ce que la liste veut payer chaque round,
  la concurrence, premier/second joueur, comment l'adversaire la force à dépenser ailleurs. Saison (Furie, dés de
  rage MdG 26-27), manifestations (unités gratuites, lancées en Intervention Magique), sites, runes.

## 2. Scoring : tactiques de bataille

Mémoires `aos-battle-tactics-rules` (une tentative par famille et par tour), leçon 12 de `list-building-concept`.
- Les **2 cartes de l'export** (les vérifier), textes verbatim `data/json/battle_tactic_cards.json`.
- Par sous-tactique : niveau absolu `facile | moyen-facile | moyen | difficile | abandon`, **avec quelles unités et
  règles**, à quel round ; ordre conseillé ; ce que la liste sacrifie de son plan pour scorer.
- Bilan sur les **4 réalistes** (Échauffourées + Frappes) ; la Domination seulement avec un moyen concret.
- Aide chiffrée (L3 seulement) : `aospy l3 scenario-model --player P --tactiques`.

## 3. Scénarios

Mémoire `aos-objectives-control-reading` : objectif acquis tant que non repris ; contrôle compté **après les
combats** (une liste qui tue reprend) ; écrire « pts de victoire », jamais « PV ».
- Cartes : `data/2026-27 L3 Aller/Données/scenarios.json` (12 cartes MdG 26-27 : objectifs, score, aptitudes, ce qui gagne).
- Note `++ … −−` par carte avec une raison (mobilité/vol, nombre d'activations, contrôle, tir, encaisse).
- Aide chiffrée (L3) : `aospy l3 scenario-model --player P` ; notes curées : `Données/notes_scenarios.json`.
- Le modèle ne lit **ni déploiement ni décors** : les lire sur la carte pour les 2-3 scénarios notables.

## 4. Forces et faiblesses

- Chiffres : `aospy roster analyze --list <liste.txt>` (couche 4, section « Forces et faiblesses » = suggestion de départ) ; L3 : `aospy l3 diag --player P` (combat,
  scénario, indices, rang /54) et la ligne de la grille (`aospy l3 diag --team …`).
- Forces = ce qui gagne la partie (plan, combos, scoring facile). Faiblesses = **ce qui la punit**, en termes
  actionnables pour `match-analysis` : profils adverses qui la battent (anti-monstre, Anti-X, mortelles, tir à
  longue portée, dissipation, nombre d'objectifs…), pièces centrales fragiles, dépendances (condition fournie par
  un allié = sa propre fiabilité), PC sous tension.

## Sortie : fiche liste

Rangement (leçon 13) : `scratch/output/liste_analyse/<équipe>/<joueur>-<faction>/<liste>/` (`analyse.md`,
`fiche joueur.md`, `couche 4.md`, `textes.md`, `liste.txt`). L3 : JSON `Données/combos/<équipe>.json` (nos listes,
schéma `l3-matchups/plan_agent.md`) ou `Données/auto/<équipe>/<joueur>.json` (adverses, `strategie_agent.md`).

Sections de `analyse.md` (le document est un tout : pas de comparaison à une analyse précédente, pas de défauts
du moteur dedans) :
1. Concept et règles constructrices · 2. Rôles et composantes · 3. Plan R1-R5 · 4. PC et ressources ·
5. Tactiques (niveaux, ordre) · 6. Scénarios (notes et raisons) · 7. Forces · 8. Faiblesses / comment la battre ·
9. Questions fermées au joueur (2-4) · `note_plan` proposée (0-3, **à valider**, non calculable : `plan_agent.md`).

## Manques (2026-11-25)

- Tactiques et scénarios chiffrés seulement pour les 54 listes L3 (z-scores sur la ligue) : rien pour une
  liste hors ligue ; aucune faisabilité d'une tactique calculée par unité (distance, mouvement, round).
- Synthèse forces/faiblesses automatique (fiche couche 4, `analysis/layers/strengths.py`) : profils seulement, ni plan,
  ni décors, ni scénario — point de départ du §4, à confirmer.

Analyse **indépendante** : ne lire l'analyse existante du joueur qu'après avoir écrit la sienne. Liste adverse en
série : agent Opus par liste, consigne `l3-matchups/strategie_agent.md`, intégration dans la boucle principale.

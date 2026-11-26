# Consigne de l'agent « brouillon stratégique » (analyse stratégique + tactiques d'une liste)

Un agent par liste (Opus : lecture de règles), sans réseau, sans commit, base DuckDB en lecture seule. Il remplace
le travail manuel des regards 3 (analyse stratégique) et tactiques de bataille pour les listes **adverses** qui n'en
ont pas. Méthode générale : skill `.claude/skills/list-analysis/SKILL.md` (à lire) ; cette consigne en fixe la sortie.
Il écrit **un seul fichier**, dans le dossier temporaire que lui donne la boucle principale (un agent en worktree ne
peut pas écrire dans le dépôt principal) ; la boucle principale le copie vers
`data/2026-27 L3 Aller/Données/auto/<fichier d'équipe sans .json>/<joueur>.json` puis lance `python -m aospy.l3.drafts`.
Il ne touche ni à `combos/*.json`, ni à `notes_scenarios.json`, ni au code.

## Entrées (chemins depuis la racine du dépôt `/home/tmenard/Dev/Python/aospy`)

1. Dossier : `.venv/bin/python -m aospy roster dossier --list "data/2026-27 L3 Aller/Listes texte/<équipe>/<joueur>.txt" --out <scratch>`
   → `couche 4.md` (rôles suggérés, empilement, sur qui poser, assaut, montée en puissance, enchaînements,
   règles mortes) et `textes.md` (profils et textes Wahapedia complets). Lire les deux en entier.
2. Aide de jeu FR : `data/2026-27 L3 Aller/Aides de jeu/<équipe>/<joueur> (fr-split-simple).json` (règles d'armée,
   cartes `deploy`/`any`/`mine`/`enemy`) — à interroger avec `jq`/`python -c`, pas en entier si gros.
3. Cartes de tactique : ligne `Battle Tactic Cards:` de l'export ; textes verbatim FR
   `data/json/battle_tactic_cards.json` ; règles de lecture `data/2026-27 L3 Aller/Données/tactiques.json` (clé `regles`).
4. Scénarios : `data/2026-27 L3 Aller/Données/scenarios.json` (12 cartes).
5. Chiffres : `.venv/bin/python -m aospy l3 diag --player <joueur>` (combat, scénario, indices).
6. Méthode (à lire avant d'écrire), dans `/home/tmenard/.claude/projects/-home-tmenard-Dev-Python-aospy/memory/` :
   `list-building-concept.md` (13 leçons), `aos-set-up-rules.md`, `charge-9-is-a-gamble.md`,
   `aos-battle-tactics-rules.md`, `aos-objectives-control-reading.md`, `player-jargon.md`, `ability-weighting-rules.md` ;
   et `.claude/skills/l3-matchups/SKILL.md`, sections « Principes stratégiques » et « Règles de jeu ».
7. Exemple de profondeur attendue (à lire pour le ton et le niveau, **pas à recopier**) : clé `strategie` de `Cromba`
   dans `data/2026-27 L3 Aller/Données/combos/Limoges_Wargame.json`.

Ne pas lire l'entrée `combos` existante du joueur avant d'avoir écrit son analyse (analyse indépendante) ; la lire
ensuite seulement pour remplir `desaccords_combos`.

## Règles

- Données d'abord : vérifier que chaque unité de l'export est reconnue (renfort, « Scourge of Aqshy: » compris) et que
  les cartes de tactique sont celles de l'export. Tout écart va dans `controles`.
- Concept et règles constructrices d'abord, puis rôle de chaque unité (confirmer ou corriger les rôles suggérés),
  composantes (château lent + aile rapide…), plan round par round.
- **Points de commandement, obligatoire** : budget 4 PC/round (5 en outsider). Par round : ce que la liste veut payer
  (ordres génériques : Contre-charge, Relance de charge, All-out Attack/Defence, Ralliement… ; aptitudes propres à coût
  PC ; Intervention Magique), ce qui entre en concurrence, ce qui dépend de jouer en premier ou en second, et comment
  l'adversaire peut la forcer à dépenser ailleurs.
- Ressources de saison (MdG 26-27), manifestations (unités gratuites, lancées au tour adverse), sites, runes.
- Croiser les règles (chaque receveur avec tout ce qu'il reçoit déjà), timing des « une fois par bataille ».
- Une charge à 9" est un pari ; compter les tentatives et la redondance ; set-up au tour adverse = menace fiable.
- Comment la battre : allonge de menace, dégrader la charge, pression par set-up, encaisser et gagner le combat,
  supprimer la contre-charge en engageant ses chargeurs, cibles prioritaires (pièces centrales fragiles).
- Vérifier au lieu de laisser des questions ouvertes ; ne pas inventer de noms français de règles (nom anglais sinon).
- Chiffres en ordres de grandeur ; français ; le document est un tout (pas de « défauts du moteur » dedans : ils vont
  dans `moteur`).

## Sortie (JSON, UTF-8, indenté)

```json
{
  "equipe": "Limoges Wargame",
  "joueur": "Antoine",
  "faction": "…",
  "date": "AAAA-MM-JJ",
  "auteur": "claude (brouillon, à valider)",
  "confiance": "haute | moyenne | basse — et pourquoi en une ligne",
  "controles": ["unités non reconnues, cartes, écarts de sources Wahapedia / faction_rules_fr"],
  "strategie": {
    "analyse": "texte suivi, 300-700 mots, à la manière de l'exemple : concept, composantes, rôles, plan round par round, ressources",
    "pc": ["R1 : …", "R2 : …", "R3 : …", "R4-5 : …", "concurrence / premier ou second / outsider : …"],
    "contre_jeu": ["comment la battre, concrètement (unités à cibler, distances, timing)"],
    "challenge": ["points où le moteur et le texte divergent, hypothèses fragiles"],
    "questions": ["2-4 questions fermées (oui/non ou choix) pour l'utilisateur, qui tranchent les hypothèses clés"]
  },
  "tactiques": {"cartes": [], "faciles": [], "difficiles": [], "plan": "", "scenarios": [], "realistes": "x/4", "bilan": "",
                "niveaux": {"<nom FR exact de chaque sous-tactique des 2 cartes, Domination comprise>": "facile | moyen-facile | moyen | difficile | abandon"}},
  "note_plan_proposee": 2,
  "justification_note": "une ligne",
  "moteur": ["ce que la fiche couche 4 ne voit pas"],
  "desaccords_combos": ["où l'entrée combos existante te semble fausse ou incomplète, après ton analyse"]
}
```

Format de `tactiques` : celui de `plan_agent.md` / des entrées validées de Melusior (`faciles`/`difficiles` = une
ligne par tactique avec unités, règles et round ; `scenarios` = seulement les cartes où c'est notable).
`niveaux` (lu par le solveur d'appariement `l3/pairing_scores.py`) : un niveau **absolu** (indépendant de l'adversaire
et du scénario) par sous-tactique des 2 cartes, nom FR exact tel que dans `battle_tactic_cards.json`. Quand le niveau
dépend de l'ordre de jeu (premier/second au round 1), donner celui du **cas attendu** de la liste et le dire dans la
ligne de la tactique. `faciles` = facile et moyen-facile ; `difficiles` = moyen, difficile et abandon.

Règle des tactiques : la mémoire `aos-battle-tactics-rules` (une tentative **par famille** à chaque tour) prime sur
la clé `regles` de `tactiques.json`, plus ancienne.

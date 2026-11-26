# Consigne de l'agent « texte de plan » (archétype, plan, combos, limites)

Un agent par liste (Opus : lecture de règles), worktree isolé, sans réseau. Il rédige l'entrée `<joueur>` de
`data/2026-27 L3 Aller/Données/combos/<équipe>.json` ; l'intégration (fusion JSON, validation de la note) reste dans
la boucle principale.

## Entrées

1. `.venv/bin/python -m aospy roster dossier --list "<Listes texte/équipe/joueur.txt>" --out <dossier>` : fiche couche 4
   (rôles et composantes, empilement, sur qui poser les aptitudes à cible unique, assaut, montée en puissance,
   enchaînements, règles mortes) + textes et profils complets.
2. L'aide de jeu : `Aides de jeu/<équipe>/<joueur> (fr-split-simple).json` (sinon le PDF).
3. Cartes de tactique de l'export (ligne `Battle Tactic Cards:`), textes : `data/json/battle_tactic_cards.json`.
4. Consigne de méthode : les 13 leçons de la mémoire `list-building-concept` (à recopier telles quelles dans le
   prompt), plus `aos-set-up-rules`, `charge-9-is-a-gamble`, `aos-battle-tactics-rules`, `player-jargon`.

## Règles

- Analyse indépendante depuis les textes et les profils : ne pas lire l'entrée existante du joueur.
- Le moteur donne les chiffres, pas le plan : partir des règles constructrices, confirmer ou corriger chaque rôle
  suggéré, dérouler le plan round par round avec les ressources (PC, saison).
- Vérifier au lieu de laisser des questions ouvertes ; ne pas inventer de noms français de règles.
- `note_plan` : proposée avec une ligne de justification dans `moteur`, **à valider** par l'utilisateur
  (`aospy l3 plan-note` ne la prédit pas : voir plus bas).

## Sortie (JSON, mêmes clés que les entrées existantes)

```json
{
  "archetype": "une ligne",
  "choix": "formation, domaines, général, optimisations",
  "plan": "2-4 phrases : l'idée de la liste et comment la jouer",
  "combos": ["règle × règle : effet chiffré, conditions"],
  "interactions": ["règles mortes, doublons partiels, contraintes de placement"],
  "limites": ["ce qui punit la liste"],
  "moteur": ["ce que la fiche couche 4 ne voit pas ; justification de la note proposée"],
  "note_plan": 2,
  "tactiques": {"cartes": [], "faciles": [], "difficiles": [], "plan": "", "scenarios": [], "realistes": "x/4"}
}
```

## Pourquoi la note n'est pas calculée (2026-11-25)

`aospy l3 plan-note` (ridge sur 11 indices couche 4 + rôles, validation un contre tous) ne fait pas mieux que la note
constante 2 : 54-56 % d'accord exact dans les deux cas, Spearman +0,42. Les indices de puissance couche 4 sont même
**anti-corrélés** à la note (empilement −0,26, leviers −0,29) : la note corrige justement ce que le moteur ne voit pas
(magie, téléportation, plan). Seule la diversité des rôles porte un signal (+0,39). Le critère « ±1 cran » ne
discrimine rien sur une échelle utilisée de 1 à 3 (la constante 2 le passe à 100 %).

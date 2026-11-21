---
name: l3-matchups
description: Contexte et outils des grilles de matchups / analyse des listes de la L3 Centre AOSFF 2026-27 (aller) pour les équipes Melusior et Vae Victis Vernou — méthode de score, fichiers, leviers de correction, scripts de diagnostic et de comparatif. Utiliser dès qu'on parle de matchups, de grille d'estimés, d'appariement/pairing L3, de score ligue, d'une liste adverse de la L3, ou de revoir la méthode.
---

# L3 Centre 2026-27 (aller) — matchups

Lire ce fichier **avant** d'ouvrir les gros Markdown générés : la plupart des questions se
règlent avec `aospy l3 diag` (sorties de quelques lignes). Répondre en français.

## Fichiers (`data/2026-27 L3 Aller/`)

| Dossier | Contenu | Qui l'écrit |
|---|---|---|
| `Sources/` | PDF des listes de l'orga, règlement AOSFF, `Rondes.md` (appariements), images scénario | orga, ne pas modifier |
| `Données/combos/<équipe>.json` | par joueur : `archetype`, `choix`, `plan`, `combos`, `interactions`, `limites`, `moteur`, **`note_plan` (0-3)** ; `_équipe` | à la main (Claude), à valider par l'équipe |
| `Données/ajustements_matchups.json` | `listes` (vide depuis la méthode v2) et `matchups` (`"Nous\|Eux"` → `[{bonus, raison}]`, 56 entrées) | à la main |
| `Données/ajustements_listes_ancienne_methode.json` | sauvegarde des 50 corrections par liste d'avant la v2 | archive |
| `Listes/Listes <équipe>.md` | 9 fichiers : rang ligue /54, métriques, combos | `aospy l3 listes` |
| `Matchups/Matchups <équipe>.md` + `Matchups <équipe>/Ronde N — contre X/` | index (méthode + grilles) ; par ronde `00 Grille et profils.md` + un fichier par joueur | `aospy l3 matchups` |
| `Matchups/instantanés/*.json` | instantanés de grilles pour les comparatifs | `aospy l3 compare` |
| `Fiches/` | fiches d'équipe (pairing) | à la main |
| `Données/scenarios.json` | les 12 cartes MdG 2026-27 (`objectifs`, `score`, `aptitudes`, `gagne`), `rappels`, maps par ronde, calendrier de nos 2 équipes | à la main (cartes lues dans `MdG26-27 Scenarii.pdf`, extraire les scans avec pypdf `page.images`) |
| `Données/notes_scenarios.json` | `equipes.<équipe>.joueurs.<joueur>.notes.<clé scénario>` = `[note ++…−−, commentaire]` pour nos 12 listes (12 scénarios) et les 42 adverses (maps où elles nous affrontent) ; `profil`, `grille_montre`, `a_verifier` pour nos équipes | à la main, à valider par les joueurs |
| `Données/tactiques.json` | règles des tactiques (hypothèse à confirmer), lecture générale des 18 tactiques (facile/moyen/difficile), interactions notables par scénario ; par joueur, clé `tactiques` des combos (`cartes`, `bilan`, `faciles`, `difficiles`, `scenarios`, `plan`) | à la main (Claude), à valider |
| `Scénarios/Scénarios <équipe>.md` | par ronde : nos défenseurs conseillés, leurs défenseurs probables, chaque map (objectifs, score, aptitudes, ce qui gagne) avec nos notes et les leurs | `aospy l3 scenarios` (`tm-aospy-l3-scenarios`) |

Ne jamais éditer les `.md` générés : modifier les données ou le code, puis relancer.

### Scénarios : règles de lecture (corrections de l'utilisateur, 2026-11-18)

- Un objectif pris **reste acquis** tant que l'adversaire ne le reprend pas : la mobilité (voler, intercepter les voleurs) compte plus que le nombre d'unités pour « tenir ».
- Le contrôle se compte **après les combats** : une unité à faible contrôle reprend un objectif en tuant ce qui le conteste. Ne pas compter un faible contrôle comme un handicap pour une liste qui tue.
- Écrire « pts de victoire » et « points de vie », jamais « PV ».
- Défenseur conseillé = score contre le 2e meilleur contre adverse (grille `Matchups/`) + 2 pts de victoire par cran de note scénario.

## Scripts (tous via `.venv/bin/python`, alias entre parenthèses)

- `aospy l3 matchups` (`tm-aospy-l3-matchups`) : régénère `Matchups/`. `--check` = parsing des listes seulement.
- `aospy l3 listes` (`tm-aospy-l3-listes`) : régénère `Listes/`.
- `aospy l3 diag` (`tm-aospy-l3-diag`) : sans option = corrélations (contrôle des biais) ; `--rank [N]` ; `--player P…` (indices, familles d'aptitudes détectées et leur source) ; `--match A B` (décomposition d'un score) ; `--team Melusior|"Vae Victis Vernou"` (grilles compactes).
- `aospy l3 compare` (`tm-aospy-l3-compare`) : `snapshot <nom> --note "…"` **avant** toute modif de méthode/notes/ajustements, puis `diff <nom>` (vs état actuel) ; `--md` écrit le comparatif dans `Matchups/`. `list`.
- `src/aospy/l3/aptitudes.py` : module (pas de CLI), lecture des aptitudes par regex (anglais Wahapedia ; français pour les contenus de l'aide de jeu absents de Wahapedia, `RULES_FR`).
- `aospy l3 export-lists` : les 54 listes au format App (`Listes texte/<équipe>/<joueur>.txt` ; nos 12 = exports App de `Proposition de listes/`, les 42 adverses reconstruites depuis le PDF de l'orga) ; `--pdf` génère l'aide de jeu fr-split-simple (`Aides de jeu/<équipe>/<joueur> (fr-split-simple).pdf`) **et** son JSON d'aptitudes par carte (`deploy`/`any`/`mine`/`enemy`/`warscrolls`/`battle_traits`, via `RosterPdfResult.ability_cards`). **L'aide de jeu fait foi** : `l3/aptitudes.py::profile` ne garde que les aptitudes qui y figurent (formation, domaines, améliorations, armée de renom, versions récentes des warscrolls), ajoute celles qu'elle seule contient (règles d'armée de renom, manifestations), et ignore les règles génériques (≥ 75 % des aides + MdG + saison). À relancer si une liste ou `faction_rules_fr.json` change.
- `aospy l3 scenarios` (`tm-aospy-l3-scenarios`) : régénère `Scénarios/` depuis les deux JSON scénario + les grilles. `--team <équipe>`. À relancer après `aospy l3 matchups` (les défenseurs conseillés dépendent des grilles).

## Méthode v2 (depuis le 2026-11-18) — `evaluate()` dans l3/matchups.py

Score = écart de PV attendu pour la liste A, borné à ±20 (±3 équilibré, ±8 net).
- **Combat ±6** (`COMBAT_MAX`) : `6·tanh(ln(attrition A / attrition B))`. Attrition = moteur aospy (dégâts de chaque unité contre chaque unité adverse, pondérés par les points) + 1,5 attaque de Fureur + aptitudes à mortelles directes. **Fiabilité** (depuis le 2026-11-18, demande de l'utilisateur) : dégâts d'armes = 50 % moyenne + 50 % plancher « 2 fois sur 3 » de la distribution exacte (`RELIABILITY_WEIGHT`, `RELIABILITY_COVERAGE`). Effet faible : la variance pénalise souvent les deux camps, le rapport bouge peu.
- **Set-up** (frappe en profondeur, TP, arrivée par un bord) pèse 1 dans la mobilité (au lieu de 2) : voir « Principes stratégiques ».
- **Scénario ±7** : contrôle ±2, nombre d'unités ±1, **mobilité ±4** (`al.mob` = moyenne des z-scores de mouvement pondéré, part de VOL, √score des aptitudes « mobilité »).
- **Aptitudes et plan ±7,6** : `4·tanh(Δapt/1,5)` + `1,2·Δnote_plan`. `al.apt` = z-score de Σ√(famille) sur soins, protection, buff, débuff, objectifs + √(1,5·niv. sorcier + niv. prêtre + bonus de lancement). Aptitude d'unité pondérée par la part de l'armée (aura 0,6), trait de bataille ×2.
- **Ajustements** : seulement par matchup désormais (anti-monstre, anti-magie, anti-soin…). Les anti-magie/anti-soin ne sont **pas** automatisés exprès : ils sont déjà dans ces ajustements nommés (double comptage sinon).
- Les z-scores sont relatifs aux 54 listes : changer une liste fait bouger quelques cases d'autres joueurs de ±1.

Diagnostic de référence (v2) : corrélation score ligue ~ PV +0,40 (v1 : +0,71), ~ mouvement −0,10 (v1 : −0,37), ~ sorciers +0,33 (v1 : +0,06).

## Leviers, du plus au moins direct

1. `note_plan` dans `Données/combos/<équipe>.json` (toutes notées par Claude, **à valider** ; Shadow 1 et Totosai 3 sont les plus discutables).
2. `ajustements_matchups.json` → `matchups` : correction ciblée avec `raison` (suffixe « proposé par Claude … à valider » si c'est moi).
3. `BT_RULES` dans l3/matchups.py : règle lue dans le battletome quand Wahapedia est tronqué, avec le choix du joueur (`ward` par nom d'unité, `aptitudes` = (famille, poids, description)). Ex. Totosai : que des Alaithi (Rune de la Montagne) → Protection 5+ sur Avalenor + 3 Spirits. Totosai a aussi +4 A aux marteaux (Force of a Landslide, moyenne sur 5 rounds). `damage_cap` (libellé → Damage max des armes qui le ciblent, ex. Darkflame Pendant du Daemon Prince de Shadow, Ward 5+ par Pledged to Nurgle). Aussi `melee_attacks` (libellé d'entrée → +N Attaques en mêlée), ex. Shadow : Varanguard R marqués de Khorne au round 1, Chaos Knights par la Bannière de Rage. Limite : l'attrition plafonne les dégâts à la cible tuée (pas de report de surplus), donc un bonus offensif sur une unité qui tue déjà ses cibles bouge peu le score.
3b. Mortelles directes (`parse_direct_ability`) : `needs_charge` (« charged this turn/phase » → seulement dans le cas « a chargé », fréquence ≤ 1) ; `DIRECT_OVERRIDES` (lecture corrigée à la main, ex. Rampaging Destruction 10,7 vs MONSTRE) ; `army_direct_abilities` (traits de bataille portés par les entrées : Ogor Eat 'Em Alive, Bull Charge). `Entry.ignore_first` = « Ignore the first damage point … each phase » (Stone Skeleton), −1 par phase où l'attaquant blesse. Les soins ne sont **pas** dans l'attrition (seulement famille « soins » de l'indice d'aptitudes).
4. `RULES` dans l3/aptitudes.py (regex des familles) et poids dans `evaluate()` : changer la méthode → snapshot + diff + vérifier `aospy l3 diag` (corrélations).

Texte français des battletomes : `data/json/faction_rules_fr.json` (`factions.<faction>.rules.<catégorie>`, clé de jointure `wahapedia_name`).

## Tactiques de bataille (étape d'analyse, depuis le 2026-11-19)

Pour chaque liste : facilité à scorer ses 2 cartes de tactique, d'abord en général (quelles tactiques sont faciles, lesquelles abandonner, ordre conseillé), puis seulement les scénarios où c'est notable (Nuées bloque Siège de Cendres, Avalanche/Rogne punissent l'empilement, diagonales et Cernez l'Ennemi…). Rendu par `aospy l3 listes` (section joueur + « lecture générale » en fin de fichier). Bilan sur les **4 tactiques réalistes** (Échauffourées + Frappes) : selon l'utilisateur, la Domination est souvent irréalisable à notre niveau (ne la compter que si la liste a un moyen concret). Règlement AOSFF 3.1 : chaque carte prise 1 à 3 fois par équipe, donc Écran de Fumée obligatoire (Martoni, Cartoone). Qualitatif : rien n'entre dans les grilles tant que ce n'est pas validé. Fait pour nos 12 listes, adversaires à faire.

**Avant de juger une liste, lire ses règles d'armée, pas seulement ses chartes** (correction de l'utilisateur, 2026-11-19). Par exemple, le réseau de décors de l'invasion végétale Sylvaneth rend faciles les tactiques de placement de Pierrodactyl. Méthode : dans l'aide de jeu (`Aides de jeu/<équipe>/<joueur> (fr-split-simple).json`, cartes `deploy`/`any`/`mine`/`enemy`), relever toutes les aptitudes de placement, de replacement et de bonus de mouvement, en particulier celles d'armée (`unites` vide, hors `MdG`), puis les confronter à chaque tactique de placement. Nos 12 listes ont été refaites de cette façon le 2026-11-19 (passage de 2 à 3 tactiques réalistes pour Pierrodactyl, Martoni et Totosai ; de 3 à 4 pour SoDarkSnow, Laytorne et Razemme). Il reste des questions aux joueurs : marques de Tzeentch de Shadow ; Martoni : une unité replacée au tour adverse compte-t-elle comme « n'a pas bougé » ?

## Trois regards sur chaque liste

1. **Stats** (moteur : combat, scénario, indices) — `aospy l3 diag --player P`.
2. **Textes** (combos, aptitudes, plan, `note_plan`) — `Données/combos/<équipe>.json`, rédigés par Claude.
3. **Analyse stratégique de l'utilisateur** — clé `strategie` du joueur dans le même JSON, rendue
   en section « Analyse stratégique » des fichiers `Listes/` :
   `{"auteur", "date", "analyse": texte verbatim, "challenge": [...], "conclusions": [...], "en_suspens": [...], "impact": [...]}`.

Quand l'utilisateur donne son analyse d'une liste :
- l'enregistrer **verbatim** dans `analyse` (ne pas reformuler) ;
- la confronter point par point aux regards 1 et 2, chiffres à l'appui (`--player`, `--match` contre
  les adversaires concernés, textes Wahapedia / `faction_rules_fr.json`) ; dire franchement où les
  données la contredisent ou ne la couvrent pas, et où elle corrige mes notes ; proposer, pas imposer ;
- **toujours forcer la réflexion « points de commandement »** (demande de l'utilisateur, il ne la fait pas
  spontanément) : budget générique 4 PC/round (5 en outsider), ordres génériques communs à tous ;
  lister ce que la liste veut payer chaque round (ses aptitudes propres à coût PC, surtout des
  résurrections façon Slann, + Intervention Magique, relance de charge…), ce qui entre en concurrence,
  et comment l'adversaire peut la forcer à dépenser ailleurs ; poser la question explicitement ;
- après échange, consigner `challenge` / `conclusions` / `en_suspens` ; ne traduire en chiffres
  (`note_plan`, `ajustements_matchups.json`, `BT_RULES`) que ce qui est **validé** par l'utilisateur,
  en le listant dans `impact` ; snapshot avant, diff après, puis régénérer (`aospy l3 matchups`, `aospy l3 listes`).

## Principes stratégiques (de l'utilisateur, à appliquer dans toutes les analyses)

- **Set-up au tour adverse ≠ pari** : une unité placée pendant le tour adverse (ex. via Intervention Magique) n'est plus « set up » à son tour suivant : mouvement normal **puis** charge. C'est une menace fiable, à compter comme telle (contre-jeu : l'adversaire la voit venir et a le reste de son tour pour réagir).
- **Une charge à 9" est un pari, pas un plan.** Même avec la relance d'un ordre, ~50 % ; l'ordre ne sert qu'une fois par tour. Un set-up sans bonus de charge ni occurrences multiples est donc peu fiable comme arme d'assaut : il sert à prendre un objectif, sauver ou replacer une unité. Un pari peut sauver une partie mal engagée, pas la gagner.
- **La fiabilité des dégâts compte**, pas seulement leur moyenne (variance).
- **Lire une liste par composantes** (ex. château lent + aile rapide) : le moteur moyenne tout et ne voit pas le tempo (une aile seule devant = 1000 pts contre 2000). Les renforts arrivent aussi par « sédimentation » (résurrections et unités lentes qui se rejoignent), sans TP.
- **Le nombre de tentatives compense la fiabilité** : plusieurs chargeurs après set-up, avec bonus de charge et relance (ex. Hibou_2 : Skitterleap Illimité sur chaque sorcier, +1 Short-tempered, relance des Chronomantic Cogs → 4 Verminlords à 66 % chacun, ≥ 2 réussites à 88 %) font un plan, pas un pari.
- **Commencer par nos listes** (demande de l'utilisateur) : comprendre d'abord les plans de jeu de Melusior et de Vae Victis, puis analyser les adversaires en fonction d'eux.
- **Contre la contre-charge** : une unité en mêlée ne peut pas charger, donc engager (charger) toutes les unités adverses qui pourraient contre-charger la supprime. Demande assez d'unités pour couvrir tous ses chargeurs crédibles.
- Réponses génériques à une liste d'assaut : allonge de menace supérieure, dégrader la charge, pression par set-up, ou encaisser et gagner le combat (attention à l'Anti-X adverse avant de choisir d'encaisser).

## Règles de jeu : interprétations de l'utilisateur (2026-11-18)

- **Set-up (règle générale)** : on se place en général à plus de 9" des unités ennemies ; les **manifestations qui ont une caractéristique de Mouvement comptent comme des unités** pour cette distance. Une fois placée, l'unité ne peut plus utiliser d'aptitude **de base** de la phase de mouvement (ni mouvement normal, ni course, ni repli). La limitation vaut **après** le set-up : une unité peut courir **puis** être replacée (ex. Slaves to Darkness marqués de Tzeentch : course, puis aptitude de Tzeentch).
- **Séquencement d'une phase** (hors phase de mêlée, qui alterne les activations) : le joueur actif utilise toutes les aptitudes qu'il veut, puis l'adversaire utilise les siennes (souvent celles à coût en PC, avec beaucoup d'exceptions). Conséquence : une réaction adverse (contre-charge…) se décide **après** avoir vu tout ce que le joueur actif a fait ; un « appât » pour la déclencher ne marche pas.
- **Intervention Magique** (MdG 2026-27, phase des héros adverse) : un Sorcier/Prêtre ami utilise un Sort/une Prière/un Bannissement comme si c'était votre phase des héros, −1 au lancement. Selon l'utilisateur, la Translocation Céleste des Seraphon (Eternal Starhost) se lance en phase des héros et peut donc passer par là ; Wahapedia la donne en « Your Movement Phase », non-Sort : écart à trancher sur la carte du battletome avant de chiffrer.
- **Dé de charge supplémentaire** : sans mention de défausse, les 3 dés s'additionnent (+3,5" dans `charge_inches`) ; avec défausse du plus bas, +1,5". Bonus de charge d'**armée** plafonné à 3" dans la menace (`charge_prob`) — validé.
- **Double activation en mêlée** (`DOUBLE_FIGHT_SELF`/`DOUBLE_FIGHT_GRANT`, validée) : l'unité a chargé, son 2e combat vise une 2e cible à ~6" qui ne riposte pas → report de surplus, compté en dégâts « chargé » (les bonus de charge, ex. Charge (+1 Damage) des Varanguard, valent pour les 2 activations).
- Toujours vérifier le texte (Wahapedia **et** `faction_rules_fr.json`) et signaler un écart de sources plutôt que trancher seul.

## Pièges connus

- Wahapedia tronque certains textes : **Depict Rune** (runes Lumineth — Totosai traité via `BT_RULES`, TyraNounours et Darkane pas encore : demander leurs runes). Unités absentes de la base (Gotrek, Be'lakor, Belga, Frost Sabres) : comptées au prorata des points.
- Le cache de dégâts est indexé par `(attaquant, figurines, défenseur, ward du défenseur)` : toute modif de profil défensif doit passer dans la clé.
- Le scratchpad est vidé entre sessions : sauvegarder les états à comparer avec `aospy l3 compare snapshot`, pas dans `/tmp`.
- Le hook rtk réécrit les commandes Bash ; si le classifieur refuse, relancer exactement l'entrée réécrite.
- Appariement AOSFF : le défenseur choisit son adversaire (voir la mémoire `aosff-pairing-defender-chooses`).

## État (2026-11-18)

Méthode v2 + fiabilité + set-up = pari, dernier instantané `2026-11-18-setup-pari`. Analyses stratégiques faites : Cromba (Limoges), Hibou_2 (Melusior, en cours). En attente : validation des notes de plan et des 56 ajustements par les joueurs ; runes de TyraNounours/Darkane ; scénario de chaque ronde pas encore pris en compte.

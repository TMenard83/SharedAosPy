# L3 matchups — leviers de correction et pièges connus

Annexe du skill `l3-matchups` (déplacée de SKILL.md, contenu inchangé).

## Leviers, du plus au moins direct

1. `note_plan` dans `Données/combos/<équipe>.json` (toutes notées par Claude, **à valider** ; Shadow 1 et Totosai 3 sont les plus discutables).
2. `ajustements_matchups.json` → `matchups` : correction ciblée avec `raison` (suffixe « proposé par Claude … à valider » si c'est moi).
3. `BT_RULES` dans l3/matchups.py : règle lue dans le battletome quand Wahapedia est tronqué, avec le choix du joueur (`ward` par nom d'unité, `aptitudes` = (famille, poids, description)). Ex. Totosai : que des Alaithi (Rune de la Montagne) → Protection 5+ sur Avalenor + 3 Spirits. Totosai a aussi +4 A aux marteaux (Force of a Landslide, moyenne sur 5 rounds). `damage_cap` (libellé → Damage max des armes qui le ciblent, ex. Darkflame Pendant du Daemon Prince de Shadow, Ward 5+ par Pledged to Nurgle). Aussi `melee_attacks` (libellé d'entrée → +N Attaques en mêlée), ex. Shadow : Varanguard R marqués de Khorne au round 1, Chaos Knights par la Bannière de Rage. Limite : l'attrition plafonne les dégâts à la cible tuée (pas de report de surplus), donc un bonus offensif sur une unité qui tue déjà ses cibles bouge peu le score.
3b. Mortelles directes (`parse_direct_ability`) : `needs_charge` (« charged this turn/phase » → seulement dans le cas « a chargé », fréquence ≤ 1) ; `DIRECT_OVERRIDES` (lecture corrigée à la main, ex. Rampaging Destruction 10,7 vs MONSTRE) ; `army_direct_abilities` (traits de bataille portés par les entrées : Ogor Eat 'Em Alive, Bull Charge). `Entry.ignore_first` = « Ignore the first damage point … each phase » (Stone Skeleton), −1 par phase où l'attaquant blesse. Les soins ne sont **pas** dans l'attrition : ils passent par l'indice couche 4 (durabilité × (1 + soins), `l3/layer4.heal_and_control`).
4. `RULES` dans l3/aptitudes.py (regex des familles) et poids dans `evaluate()` : changer la méthode → snapshot + diff + vérifier `aospy l3 diag` (corrélations).

Texte français des battletomes : `data/json/faction_rules_fr.json` (`factions.<faction>.rules.<catégorie>`, clé de jointure `wahapedia_name`).

## Pièges connus

- Wahapedia tronque certains textes : **Depict Rune** (runes Lumineth — Totosai traité via `BT_RULES`, TyraNounours et Darkane pas encore : demander leurs runes). Unités absentes de la base (Gotrek, Be'lakor, Belga, Frost Sabres) : comptées au prorata des points.
- Le cache de dégâts est indexé par `(attaquant, figurines, défenseur, ward du défenseur)` : toute modif de profil défensif doit passer dans la clé.
- Le scratchpad est vidé entre sessions : sauvegarder les états à comparer avec `aospy l3 compare snapshot`, pas dans `/tmp`.
- Le hook rtk réécrit les commandes Bash ; si le classifieur refuse, relancer exactement l'entrée réécrite.
- Appariement AOSFF : le défenseur choisit son adversaire (voir la mémoire `aosff-pairing-defender-chooses`).

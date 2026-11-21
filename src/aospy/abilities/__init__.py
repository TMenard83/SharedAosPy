"""Analyse hors contexte de toutes les aptitudes du jeu (warscrolls + règles de faction).

Chaque aptitude Wahapedia est lue, nettoyée, dédoublonnée puis analysée
*individuellement*, sans tenir compte de l'unité qui la porte : une bonne aptitude
sur une mauvaise unité reste une bonne aptitude. L'analyse suit la grille
« charge » de l'utilisateur :

* **mise en place** (`ease`) — conditions, portée, coût, timing ;
* **puissance** (`power`) — poids de l'effet quand il marche ;
* **aléa** (`reliability`) — probabilité de déclenchement (2+, 3+, sort à 7…)
  combinée à la variance de l'effet ;

puis tranche un verdict **plan / pari / anecdotique**, et pose des tags
d'utilité (`degats`, `mobilite`, `blessures-mortelles`, `fiable`…) sur lesquels
les analyses de niveau supérieur (meilleures unités, combos de liste, scoring,
matchups) s'appuient via les tables DuckDB `ability*`.

Pipeline, du bas vers le haut (chaque module n'appelle que ceux du dessus) :

1. `models.py`    — dataclasses (aucune logique) ;
2. `text.py`      — HTML Wahapedia → texte brut, découpe Annonce/Effet ;
3. `source.py`    — lecture des CSV, filtrage Legends/périmé, dédoublonnage ;
4. `extract/`     — extraction par règles : déclenchement, coût, jet, portée,
   cible, effets chiffrés ;
5. `tags.py`      — tags d'utilité dérivés de l'extraction ;
6. `scoring.py`   — trois axes + verdict, avec justification lisible ;
7. `overrides.py` — corrections manuelles (`data/json/ability_overrides.json`) ;
8. `pipeline.py`  — orchestre 3→7, renvoie des `AbilityAnalysis` prêtes à
   persister (`persistence/repository.py::replace_ability_analyses`).
"""

"""Outils de la L3 Centre AOSFF 2026-27 (phase aller) : grilles de matchups, diagnostics, analyse
des listes, scénarios, export des listes adverses — lancés par `aospy l3 <commande>`.

`aptitudes.py` (lecture des textes Wahapedia d'une liste) → `matchups.py` (listes, score de chaque
paire, grilles Markdown) → `diag.py`/`compare.py`/`listes.py`/`export_lists.py` ; `scenarios.py` est
indépendant. Données et sorties sous `data/2026-27 L3 Aller/` ; base lue : `data/aospy.duckdb`
(lecture seule, l'option `--db` de la CLI ne s'applique pas ici). Contexte : skill `l3-matchups`.
"""

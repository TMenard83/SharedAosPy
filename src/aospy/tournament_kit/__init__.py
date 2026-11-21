"""Kit de tournoi — compile une liste d'armée (export brut de l'App) et les
profils d'unité correspondants (extraits des PDF de battletome) en un seul
PDF prêt à emporter en tournoi.

`list_parser.py` parse le texte brut, `warscroll_index.py` résout chaque
unité vers ses pages de battletome via `data/json/warscroll_index.json` (curation
manuelle, voir ce fichier), `pdf_builder.py` assemble le PDF final. Aucun
accès DB requis. Voir README.md (même dossier) pour le détail d'architecture.
"""

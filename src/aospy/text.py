"""Normalisation de texte partagée par plusieurs paquets.

N'y regrouper que des fonctions **strictement identiques** à l'usage. Les variantes voisines restent dans leur
module car elles ne normalisent pas la même chose : `engine.loadout._norm` (balises, apostrophes, espaces
réduits), `analysis.encounter._norm` (tout non-alphanumérique → espace), `importers.bsdata._normalize_name`
(apostrophes, sans réduire les espaces internes), `importers.verify._norm` (apostrophe ’ seule, espaces réduits),
`tournament_kit.sources.wahapedia_lookup.normalize_name` (apostrophes, « : », suffixe saisonnier, espaces
simples conservés).
"""

from __future__ import annotations

import unicodedata


def fold_name(name: str) -> str:
    """Clé de comparaison sans accents (NFKD → ASCII), sans casse et sans aucun espace."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return "".join(folded.lower().split())

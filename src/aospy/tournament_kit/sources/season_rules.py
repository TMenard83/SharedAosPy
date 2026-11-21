"""Chargement de `data/json/season_rules.json` — transcription manuelle, verbatim
en français, des « Règles de Saison 2026-27 » (`data/Manuel du général/
MdG26-27 Aptitudes.pdf`, page 5 : les 4 aptitudes que les deux joueurs
peuvent utiliser quel que soit leur faction, sans couche de texte comme tout
le reste de ce PDF — relevé à la main, même convention que
`tactic_cards.py`/`army_rules.json`). Chargeur pur, pas de DB, relu à froid à
chaque appel.

Contrairement aux profils d'unité/règles de faction (Wahapedia, anglais), ces
4 aptitudes n'existent nulle part ailleurs que dans ce PDF — le texte reste
en français, sans repli possible. `condition`/`ability_phase` restent
toutefois écrits dans le mini-vocabulaire anglais que `render/`
sait déjà classer par bandeau de phase (cf. son en-tête de module) — un
simple tag de classification interne, jamais affiché tel quel."""

from __future__ import annotations

import json
from pathlib import Path

from .generic_core_abilities import apply_english_layer
from .wahapedia_lookup import AbilityEntry

DEFAULT_SEASON_RULES_FILE = Path("data") / "json" / "season_rules.json"
#: verbatim anglais (mode `en-split-simple`), relevé dans l'app Warhammer Age
#: of Sigmar (General's Handbook 2026-27 › Season Rules 2026-27)
DEFAULT_SEASON_RULES_EN_FILE = Path("data") / "json" / "season_rules_en.json"


def load_season_rules(
    path: str | Path = DEFAULT_SEASON_RULES_FILE,
    en_path: str | Path | None = None,
) -> list[AbilityEntry]:
    """Fichier absent -> liste vide (pas de carte "Règles de Saison" plutôt
    qu'un plantage, même filet de sécurité que `tactic_cards.load_tactic_cards`).
    `en_path` : couche anglaise, cf. `generic_core_abilities.apply_english_layer`."""
    p = Path(path)
    if not p.exists():
        return []
    rows = apply_english_layer(json.loads(p.read_text(encoding="utf-8")), en_path)
    return [
        AbilityEntry(
            name=row["name"],
            description=row["description"],
            legend="",
            condition=row.get("condition", ""),
            keywords=row.get("keywords", ""),
            ability_phase=row.get("ability_phase", ""),
            resources=tuple(tuple(r) for r in row.get("resources", [])),
        )
        for row in rows
    ]

"""Chargement de `data/json/battle_tactic_cards.json` — transcription manuelle,
verbatim en français, des 6 cartes de tactique de bataille de la saison
2026-27 (`data/Manuel du général/MdG26-27 Tactiques.pdf`, sans couche de
texte comme tout le reste de ce PDF — relevé à la main page par page, même
convention que `warscroll_index.json`/`army_rules.json`). Chargeur pur, pas
de DB, relu à froid à chaque appel.

Ce texte reste en français (la carte source l'est) — contrairement aux
profils d'unité/règles de faction (Wahapedia, anglais), il n'y a pas de repli
possible : ces 6 cartes n'existent nulle part ailleurs que dans ce PDF.

`data/json/battle_tactic_cards_en.json` (mode `en-split-simple`, `en_path`)
est leur verbatim anglais, relevé dans l'app Warhammer Age of Sigmar
(General's Handbook 2026-27 › Battle Tactics 2026-27) : chaque carte (par
`number`) y remplace sa règle spéciale et le nom/la condition de chaque
sous-tactique (même ordre) ; type et points restent ceux du français, la
carte est marquée `english`."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_TACTIC_CARDS_FILE = Path("data") / "json" / "battle_tactic_cards.json"
DEFAULT_TACTIC_CARDS_EN_FILE = Path("data") / "json" / "battle_tactic_cards_en.json"


@dataclass(frozen=True)
class SubTactic:
    kind: str  # "Échauffourée" / "Frappe" / "Domination"
    name: str
    flavor: str
    condition: str
    points: int


@dataclass(frozen=True)
class TacticCard:
    number: int
    name_en: str
    title_fr: str
    flavor: str
    special_rule: str | None
    sub_tactics: tuple[SubTactic, ...]
    #: texte remplacé par la couche anglaise (`load_tactic_cards(en_path=...)`)
    english: bool = False


def _normalize(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return "".join(folded.lower().split())


def load_tactic_cards(
    path: str | Path = DEFAULT_TACTIC_CARDS_FILE, en_path: str | Path | None = None,
) -> dict[str, TacticCard]:
    """`{nom anglais (tel qu'utilisé dans un export de liste) -> TacticCard}`.
    Fichier absent -> dict vide (une liste citant une carte tombe alors en
    `rules_unmatched`, jamais un plantage). `en_path` : couche anglaise, cf.
    le docstring du module."""
    p = Path(path)
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8"))
    cards = {
        row["name_en"]: TacticCard(
            number=row["number"],
            name_en=row["name_en"],
            title_fr=row["title_fr"],
            flavor=row["flavor"],
            special_rule=row.get("special_rule"),
            sub_tactics=tuple(
                SubTactic(kind=s["kind"], name=s["name"], flavor=s["flavor"], condition=s["condition"], points=s["points"])
                for s in row["sub_tactics"]
            ),
        )
        for row in rows
    }
    if en_path is None or not Path(en_path).exists():
        return cards
    english = {row["number"]: row for row in json.loads(Path(en_path).read_text(encoding="utf-8"))}
    for key, card in cards.items():
        en = english.get(card.number)
        if en is None:
            continue
        cards[key] = replace(
            card, special_rule=en.get("special_rule"), flavor="", english=True,
            sub_tactics=tuple(
                replace(sub, name=e["name"], condition=e["condition"], flavor="")
                for sub, e in zip(card.sub_tactics, en["sub_tactics"])
            ),
        )
    return cards


def find_tactic_card(cards: dict[str, TacticCard], name: str) -> TacticCard | None:
    """Correspondance exacte puis normalisée (accents/casse) — même
    tolérance que `warscroll_index._lookup_normalized` pour le nom tel que
    cité dans l'export de liste."""
    if name in cards:
        return cards[name]
    target = _normalize(name)
    for key, card in cards.items():
        if _normalize(key) == target:
            return card
    return None


#: début de condition commun aux 18 sous-tactiques (`compress_tactic_conditions`)
_TACTIC_CONDITION_PREFIX = "Vous exécutez cette tactique de bataille à la fin de votre tour "


def compress_tactic_conditions(card: TacticCard) -> TacticCard:
    """`fr-split-simple` : « Vous exécutez cette tactique de bataille à la fin
    de votre tour si… » -> « Fin de votre tour, si… » (demande de
    l'utilisateur, toutes les listes)."""
    return replace(card, sub_tactics=tuple(
        replace(sub, condition=sub.condition.replace(_TACTIC_CONDITION_PREFIX, "Fin de votre tour, ", 1))
        for sub in card.sub_tactics
    ))

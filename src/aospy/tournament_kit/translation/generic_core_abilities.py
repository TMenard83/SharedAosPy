"""Chargement de `data/json/generic_core_abilities.json` — vérbatim français de
*toutes* les aptitudes génériques utilisables à chaque phase, transcrites
depuis `data/Manuel du général/MdG26-27 Aptitudes.pdf` (même PDF que
`season_rules.json`, qui n'en transcrit que la page 5 — les 4 règles de
saison, incluses dans tous les modes). Ce fichier-ci est le superset complet,
inclus uniquement en mode `fr-extended` (`pdf_builder.build_roster_pdf`).
Chargeur pur, pas de DB, relu à froid à chaque appel — même convention que
`season_rules.py`, à ceci près qu'il lit aussi `points_type`/`points` (les
"Ordres" du PDF coûtent des points de commandement, ce que les 4 règles de
saison ne font jamais) pour que le badge hexagonal "PC" de
`warscroll_card._cast_pill` s'affiche. Fichier absent ou `[]` -> liste vide,
jamais un plantage.

Une ligne peut porter `requires_unit_keyword` (ex. "MUSICIAN" pour
« Musicien », "STANDARD BEARER" pour « Porte-Étendard », "CHAMPION" pour
« Champion ») : elle n'est alors gardée que si une unité de la liste porte ce
mot-clé Wahapedia (`unit_keywords`, suffixe entre parenthèses ignoré — un
warscroll porte `CHAMPION (1/9)`) — une aptitude qu'aucune unité ne peut utiliser n'a rien à
faire sur la carte (demande explicite de l'utilisateur). Le champ accepte aussi
une liste, lue comme « l'un de ces mots-clés suffit » : « Rites Sacrés » exige
`PRIEST`, « Dissipation » `WIZARD`, « Intervention Magique »/« Bannir une
Manifestation » `["WIZARD", "PRIEST"]` (leur texte dit « un Sorcier ou un
Prêtre ami »).

`data/json/generic_core_abilities_en.json` (mode `en-split-simple`, `en_path`)
est une couche anglaise par-dessus : chaque ligne nomme l'entrée française
qu'elle remplace (`fr_name`) et porte son `name`/`description` en verbatim
des Core Rules GW (+ errata), plus `condition`/`keywords` quand ils diffèrent
(une réaction, des mots-clés anglais) ; le reste (`ability_phase`, coût,
`requires_unit_keyword`...) est repris de l'entrée française. Une entrée sans
ligne anglaise (texte modifié par le Manuel du général 2026-27, dont aucune
version anglaise n'est disponible) reste en français. Les entrées remplacées
portent le badge source « Core Rules », sauf celles qui viennent du Manuel du
général (`"source": ""`, badge « MdG » posé par l'appelant comme pour le
français)."""

from __future__ import annotations

import json
from pathlib import Path

from .wahapedia_lookup import AbilityEntry

DEFAULT_GENERIC_CORE_ABILITIES_FILE = Path("data") / "json" / "generic_core_abilities.json"
DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE = Path("data") / "json" / "generic_core_abilities_en.json"

#: badge source d'une entrée remplacée par la couche anglaise
CORE_RULES_SOURCE = "Core Rules"


def apply_english_layer(rows: list[dict], en_path: str | Path | None, default_source: str = "") -> list[dict]:
    """Remplace chaque ligne française nommée par une ligne anglaise de
    `en_path` (`fr_name`) : `name`/`description`, plus `condition`/`keywords`
    s'ils y figurent ; le reste vient de la ligne française. Le badge source
    de la ligne anglaise (`source`, sinon `default_source` ; vide = aucun, la
    source est alors posée par l'appelant) rejoint ses mots-clés. Partagé avec
    `season_rules.py`."""
    if en_path is None or not Path(en_path).exists():
        return rows
    english = {row["fr_name"]: row for row in json.loads(Path(en_path).read_text(encoding="utf-8"))}
    out = []
    for row in rows:
        en = english.get(row["name"])
        if en is None:
            out.append(row)
            continue
        source = en.get("source", default_source)
        keywords = en.get("keywords", row.get("keywords", ""))
        out.append({
            **row, "name": en["name"], "description": en["description"],
            "condition": en.get("condition", row.get("condition", "")),
            "keywords": ", ".join(k for k in (keywords, source) if k),
        })
    return out


def load_generic_core_abilities(
    path: str | Path = DEFAULT_GENERIC_CORE_ABILITIES_FILE, unit_keywords: frozenset[str] | None = None,
    en_path: str | Path | None = None,
) -> list[AbilityEntry]:
    """`unit_keywords` : mots-clés (majuscules) de toutes les unités de la
    liste ; `None` = aucun filtrage par `requires_unit_keyword`. `en_path` :
    couche anglaise (cf. le docstring du module)."""
    p = Path(path)
    if not p.exists():
        return []
    rows = json.loads(p.read_text(encoding="utf-8"))
    rows = apply_english_layer(rows, en_path, default_source=CORE_RULES_SOURCE)
    if unit_keywords is not None:
        unit_keywords = frozenset(kw.split("(", 1)[0].strip() for kw in unit_keywords)

    def _keep(row: dict) -> bool:
        required = row.get("requires_unit_keyword")
        if unit_keywords is None or not required:
            return True
        if isinstance(required, str):
            required = [required]
        return any(kw.strip().upper() in unit_keywords for kw in required)

    return [
        AbilityEntry(
            name=row["name"],
            description=row["description"],
            legend="",
            condition=row.get("condition", ""),
            keywords=row.get("keywords", ""),
            ability_phase=row.get("ability_phase", ""),
            resources=tuple(tuple(r) for r in row.get("resources", [])),
            points_type=row.get("points_type", ""),
            points=row.get("points", ""),
        )
        for row in rows
        if _keep(row)
    ]

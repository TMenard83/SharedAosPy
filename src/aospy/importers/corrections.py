"""Corrections d'erreurs de source — elles l'emportent sur tout (`data/json/source_corrections.json`).

Trois sources décrivent une même charte : Wahapedia (CSV), BattleScribe (BSData) et les scans des
battletomes/faction packs. Quand une donnée importée est fausse ou tronquée (mot-clé perdu, profil
erroné, texte d'aptitude coupé), la valeur vérifiée sur le scan — ou, à défaut, sur l'autre source —
est consignée ici avec sa provenance, comme les mises à jour de règles corrigent un battletome :

* **unités** : réappliquées après chaque import (`apply_unit_corrections`, appelé par
  `aospy import bsdata|wahapedia`) — mots-clés ajoutés/retirés, caractéristiques, profils d'arme ;
* **aptitudes** : appliquées à la lecture des CSV (`abilities.source.load_raw_abilities`), avant le
  calcul de l'uid — un texte corrigé change donc l'uid (un override existant devient orphelin et
  `ability analyze` le signale).

Format :

```json
{"units": [{"faction": "Skaven", "unit": "Thanquol on Boneripper",
            "keywords_add": ["WIZARD (2)"], "keywords_remove": [], "stats": {"save": 4},
            "weapons": {"Staff of the Horned Rat": {"damage": 2}},
            "source": "BT Skaven FR p.80", "note": "…"}],
 "abilities": [{"faction": "Lumineth Realm-lords", "name": "DEPICT RUNE",
                "condition": null, "declare": null, "effect": "…",
                "source": "BT LRL FR", "note": "texte tronqué dans Wahapedia"}]}
```

Les textes d'aptitude restent en anglais (l'extracteur lit l'anglais GW) ; une traduction depuis un
scan français le dit dans `source`.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional

DEFAULT_CORRECTIONS_PATH = Path("data") / "json" / "source_corrections.json"

_UNIT_STATS = {"move", "save", "health", "control", "models", "points", "ward"}
_WEAPON_STATS = {"range_in", "attacks", "hit", "wound", "rend", "damage", "abilities"}


def load_corrections(path: str | Path = DEFAULT_CORRECTIONS_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {"units": [], "abilities": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {"units": data.get("units", []), "abilities": data.get("abilities", [])}


def correct_unit(unit, entry: dict):
    """Copie corrigée d'une `Unit` (cœur pur)."""
    kws = (set(unit.keywords) | {k.upper() for k in entry.get("keywords_add", [])}) - {
        k.upper() for k in entry.get("keywords_remove", [])
    }
    stats = {k: v for k, v in entry.get("stats", {}).items() if k in _UNIT_STATS}
    wfix = entry.get("weapons", {})
    weapons = [
        dataclasses.replace(w, **{k: v for k, v in wfix[w.name].items() if k in _WEAPON_STATS}) if w.name in wfix else w
        for w in unit.weapons
    ]
    return dataclasses.replace(unit, keywords=frozenset(kws), is_hero="HERO" in kws, weapons=weapons, **stats)


def apply_unit_corrections(con, path: str | Path = DEFAULT_CORRECTIONS_PATH) -> list[str]:
    """Réapplique les corrections d'unités en base ; renvoie les entrées sans unité correspondante."""
    from ..persistence import repository

    missing = []
    for entry in load_corrections(path)["units"]:
        army = repository.get_army_by_name(con, entry["faction"])
        unit = repository.get_unit_by_name(con, army.id, entry["unit"]) if army else None
        if unit is None:
            missing.append(f"{entry['faction']} / {entry['unit']}")
            continue
        repository.replace_unit(con, correct_unit(unit, entry))
    return missing


def ability_correction(corrections: list[dict], faction_name: str, name: str) -> Optional[dict]:
    """Correction d'aptitude pour (faction, nom), insensible à la casse ; None sinon."""
    key = (faction_name.lower(), name.strip().lower())
    for c in corrections:
        if (c.get("faction", "").lower(), c.get("name", "").strip().lower()) == key:
            return c
    return None


def correct_ability_fields(fields: dict, correction: Optional[dict]) -> dict:
    """Champs `_base_fields` d'une aptitude avec les textes corrigés (condition/declare/effect)."""
    if not correction:
        return fields
    out = dict(fields)
    for key in ("condition", "declare", "effect"):
        if correction.get(key) is not None:
            out[key] = correction[key]
    return out

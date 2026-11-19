"""Lecture des aptitudes Wahapedia (warscrolls + règles de faction) en `RawAbility`.

Périmètre : toutes les warscrolls canoniques non-Legends (y compris
manifestations, terrains de faction, Régiments de Renom) et toutes les lignes de
`Faction_abilities.csv` (pseudo-faction `EnS` = domaines de manifestations
génériques). Les variantes « Scourge of Ghyran » sont écartées, comme dans les
importeurs.

Dédoublonnage : une même aptitude (même nom, même condition, même texte) imprimée
sur plusieurs warscrolls (doublons de Régiment de Renom, variantes ×5/×10…) ne
donne qu'une `RawAbility`, avec la liste de tous ses porteurs dans `owners`.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from ..importers.bsdata import _is_expired_variant
from ..importers.wahapedia import _canonical_ids, _legends_warscroll_ids
from .models import AbilityOwner, RawAbility, SourceKind
from .text import clean, split_declare_effect

DEFAULT_DATA_DIR = Path("data") / "wahapedia"

#: `type_name` (ou, pour une Armée de Renom, `subtype_name`) → origine.
_RULE_KINDS: dict[str, SourceKind] = {
    "Battle Traits": "battle_trait",
    "Battle Formations": "formation",
    "Regiment Abilities": "formation",
    "Heroic Traits": "heroic_trait",
    "Artefacts of Power": "artefact",
    "Spell Lore": "spell",
    "Prayer Lore": "prayer",
    "Manifestation Lore": "manifestation",
    "Monstrous Traits": "monstrous_trait",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="|"))


def _uid(name: str, condition: str, declare: str, effect: str) -> str:
    key = "\x1f".join((name.strip().lower(), condition, declare, effect))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _rule_kind(type_name: str, subtype_name: str) -> SourceKind:
    if type_name in _RULE_KINDS:
        return _RULE_KINDS[type_name]
    if subtype_name in _RULE_KINDS:          # Armée de Renom : catégorie en sous-type
        return _RULE_KINDS[subtype_name]
    return "enhancement" if subtype_name and subtype_name != "_1" else "other"


def _base_fields(row: dict[str, str]) -> dict:
    declare, effect = split_declare_effect(clean(row.get("description") or ""))
    condition = clean(row.get("condition") or "")
    return {
        "name": clean(row.get("name") or "").strip(),
        "condition": condition,
        "phase": (row.get("ability_phase") or "").strip(),
        "wahapedia_type": (row.get("ability_type") or "").strip(),
        "is_reaction": (row.get("is_reaction") or "") == "true",
        "keywords": clean(row.get("keywords") or ""),
        "cost_type": (row.get("points_type") or "").strip(),
        "cost_value": (row.get("points") or "").strip(),
        "declare": declare,
        "effect": effect,
    }


def load_raw_abilities(data_dir: str | Path = DEFAULT_DATA_DIR) -> list[RawAbility]:
    """Toutes les aptitudes du jeu, dédoublonnées, triées par (faction, nom)."""
    data_dir = Path(data_dir)
    factions = {f["id"]: f["name"] for f in _read_csv(data_dir / "Factions.csv")}
    warscrolls = _read_csv(data_dir / "Warscrolls.csv")
    legends = _legends_warscroll_ids(data_dir)
    canonical = _canonical_ids(warscrolls)
    kept = {
        w["id"]: w for w in warscrolls
        if w["id"] in canonical and w["id"] not in legends
        and not _is_expired_variant(w.get("name") or "")
    }

    merged: dict[str, dict] = {}

    def add(fields: dict, kind: SourceKind, group: str, owner: AbilityOwner) -> None:
        uid = _uid(fields["name"], fields["condition"], fields["declare"], fields["effect"])
        entry = merged.get(uid)
        if entry is None:
            entry = merged[uid] = {**fields, "uid": uid, "source_kind": kind,
                                   "group_name": group, "owners": []}
        if owner not in entry["owners"]:
            entry["owners"].append(owner)

    for row in _read_csv(data_dir / "Warscrolls_abilities.csv"):
        w = kept.get(row.get("warscroll_id") or "")
        if w is None:
            continue
        fid = w.get("faction_id") or ""
        owner = AbilityOwner(fid, factions.get(fid, fid), "warscroll", w["name"], w["id"],
                             (w.get("role") or "").strip())
        add(_base_fields(row), "warscroll", "", owner)

    for row in _read_csv(data_dir / "Faction_abilities.csv"):
        fid = row.get("faction_id") or ""
        type_name = (row.get("type_name") or "").strip()
        subtype = (row.get("subtype_name") or "").strip()
        if _is_expired_variant(type_name) or _is_expired_variant(subtype):
            continue
        group = f"{type_name} › {subtype}" if subtype and subtype != "_1" else type_name
        owner = AbilityOwner(fid, factions.get(fid, fid), "faction_rule", group)
        add(_base_fields(row), _rule_kind(type_name, subtype), subtype or type_name, owner)

    out = [
        RawAbility(**{k: v for k, v in e.items() if k != "owners"}, owners=tuple(e["owners"]))
        for e in merged.values()
        if e["name"]
    ]
    out.sort(key=lambda a: (a.owners[0].faction_name if a.owners else "", a.name))
    return out

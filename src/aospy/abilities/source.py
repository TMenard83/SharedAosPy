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

import hashlib
import re
from pathlib import Path

from ..importers.corrections import (
    DEFAULT_CORRECTIONS_PATH,
    ability_correction,
    correct_ability_fields,
    load_corrections,
)
from ..sources.wahapedia_csv import (
    DEFAULT_DATA_DIR,
    ROR_ROLE,
    canonical_ids,
    is_expired_variant,
    legends_warscroll_ids,
    read_csv,
)
from .models import AbilityOwner, RawAbility, SourceKind
from .text import clean, fix_typos, split_declare_effect

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


#: Catégories de règles de faction de base (`type_name` Wahapedia).
_CORE_TYPES = frozenset(t for t in _RULE_KINDS if t != "Regiment Abilities")

#: Origines hors jeu égal : armées Spearhead (format à part) et règles de campagne Path to Glory.
NON_MATCHED_ORIGINS = frozenset({"spearhead", "path_to_glory"})


def origin_of(type_name: str, subtypes: frozenset[str]) -> str:
    """Origine d'un `type_name` de `Faction_abilities.csv`, d'après les sous-types qu'il regroupe.

    Wahapedia range les règles de base sous leur catégorie (« Battle Traits », « Spell Lore »…), mais une
    Armée de Renom ou une armée Spearhead sous SON nom, la catégorie passant en sous-type :
    - « PATH TO GLORY » → `path_to_glory` ;
    - un type qui regroupe des « Regiment Abilities » → `spearhead` (constaté sur toutes les boîtes Spearhead :
      Battle Traits + Regiment Abilities + Enhancements — Vigilant Brotherhood, Fusil-Platoon…) ;
    - un type qui regroupe une catégorie de base (Battle Traits, Heroic Traits, Spell Lore…) → `army_of_renown`
      (y compris les AoR à catégories propres, « First Circle Titles », « Little Toes ») ;
    - sinon → `base` : catégorie de base, ou table d'optimisations propre à la faction dont le seul sous-type
      porte le nom du type (Scars of War, Brazen Mutations, Big Names…)."""
    if type_name in _CORE_TYPES:
        return "base"
    if type_name.strip().upper() == "PATH TO GLORY":
        return "path_to_glory"
    if "Regiment Abilities" in subtypes:
        return "spearhead"
    if subtypes & _CORE_TYPES:
        return "army_of_renown"
    return "base"


def _uid(name: str, condition: str, declare: str, effect: str) -> str:
    key = "\x1f".join((name.strip().lower(), condition, declare, effect))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _rule_kind(type_name: str, subtype_name: str) -> SourceKind:
    if type_name in _RULE_KINDS:
        return _RULE_KINDS[type_name]
    if subtype_name in _RULE_KINDS:  # Armée de Renom : catégorie en sous-type
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


def bearer_restriction_of(text: str) -> str:
    """Restriction de porteur lisible dans la description d'un groupe/type d'optimisations, '' sinon.

    « HERO only », « (HERO only excluding Cannonade Cogfort and Conqueror Cogfort) », « Brazen Mutations are
    unique enhancements that can be given to non-Hero Blades of Khorne Infantry or Cavalry units »,
    « Give your general 1 of the following enhancements »."""
    txt = re.sub(r"<[^>]+>", " ", text or "")
    txt = re.sub(r"\$\d+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return ""
    m = re.search(r"[^.]*?\bcan (?:only )?be given to [^.]+", txt, re.I)
    if m:
        return m.group(0).strip()
    m = re.search(r"\(?\s*(?:[Nn]on-)?\(?[A-Z][A-Z' -]*\)?\s+[Oo]n[l]?y\b[^.()]*\)?", txt)
    if m:
        return m.group(0).strip(" ()")
    m = re.search(r"Give your general [^.]+", txt)
    return m.group(0).strip() if m else ""


def load_raw_abilities(
    data_dir: str | Path = DEFAULT_DATA_DIR, corrections_path: str | Path = DEFAULT_CORRECTIONS_PATH
) -> list[RawAbility]:
    """Toutes les aptitudes du jeu, dédoublonnées, triées par (faction, nom).

    Les corrections d'erreurs de source (`importers.corrections`) remplacent les textes Wahapedia
    tronqués ou faux avant le calcul de l'uid."""
    data_dir = Path(data_dir)
    fixes = load_corrections(corrections_path)["abilities"]
    factions = {f["id"]: f["name"] for f in read_csv(data_dir / "Factions.csv")}
    warscrolls = read_csv(data_dir / "Warscrolls.csv")
    legends = legends_warscroll_ids(data_dir)
    canonical = canonical_ids(warscrolls)
    kept = {
        w["id"]: w
        for w in warscrolls
        if w["id"] in canonical and w["id"] not in legends and not is_expired_variant(w.get("name") or "")
    }

    merged: dict[str, dict] = {}
    restrictions: dict[tuple[str, str], str] = {}
    for f_name, key in (("Faction_ability_types.csv", "type"), ("Faction_ability_subtypes.csv", "subtype")):
        path = data_dir / f_name
        if path.exists():
            for row in read_csv(path):
                r = bearer_restriction_of(row.get("description") or "")
                if r:
                    restrictions[(key, row.get("id") or "")] = r

    def add(fields: dict, kind: SourceKind, group: str, owner: AbilityOwner) -> None:
        fields = correct_ability_fields(fields, ability_correction(fixes, owner.faction_name, fields["name"]))
        uid = _uid(fields["name"], fields["condition"], fields["declare"], fields["effect"])
        entry = merged.get(uid)
        if entry is None:
            entry = merged[uid] = {**fields, "uid": uid, "source_kind": kind, "group_name": group, "owners": []}
        if owner not in entry["owners"]:
            entry["owners"].append(owner)

    for row in read_csv(data_dir / "Warscrolls_abilities.csv"):
        w = kept.get(row.get("warscroll_id") or "")
        if w is None:
            continue
        fid = w.get("faction_id") or ""
        role = (w.get("role") or "").strip()
        owner = AbilityOwner(
            fid,
            factions.get(fid, fid),
            "warscroll",
            w["name"],
            w["id"],
            role,
            origin_kind="regiment_of_renown" if role == ROR_ROLE else "warscroll",
            origin_name=w["name"] if role == ROR_ROLE else "",
            category="warscroll",
        )
        add(_base_fields(row), "warscroll", "", owner)

    faction_rows = read_csv(data_dir / "Faction_abilities.csv")
    subtypes_of: dict[tuple[str, str], set[str]] = {}
    for row in faction_rows:
        key = (row.get("faction_id") or "", (row.get("type_name") or "").strip())
        subtypes_of.setdefault(key, set()).add((row.get("subtype_name") or "").strip())

    for row in faction_rows:
        fid = row.get("faction_id") or ""
        type_name = (row.get("type_name") or "").strip()
        subtype = (row.get("subtype_name") or "").strip()
        if is_expired_variant(type_name) or is_expired_variant(subtype):
            continue
        group = f"{type_name} › {subtype}" if subtype and subtype != "_1" else type_name
        origin = origin_of(type_name, frozenset(subtypes_of.get((fid, type_name), ())))
        kind = _rule_kind(type_name, subtype)
        owner = AbilityOwner(
            fid,
            factions.get(fid, fid),
            "faction_rule",
            group,
            origin_kind=origin,
            origin_name=type_name if origin in ("army_of_renown", "spearhead") else "",
            category=kind,
        )
        fields = _base_fields(row)
        # le groupe (sous-type) est plus précis que le type : « HERO only » vs « Brazen Mutations are … »
        fields["bearer_restriction"] = (
            restrictions.get(("subtype", row.get("subtype_id") or ""))
            or restrictions.get(("type", row.get("type_id") or ""))
            or ""
        )
        add(fields, kind, subtype or type_name, owner)

    # fautes de l'export corrigées après l'uid (v28) : l'uid, clé des overrides, ne bouge pas
    out = [
        RawAbility(
            **{k: (fix_typos(v) if k in ("declare", "effect") else v) for k, v in e.items() if k != "owners"},
            owners=tuple(e["owners"]),
        )
        for e in merged.values()
        if e["name"]
    ]
    out.sort(key=lambda a: (a.owners[0].faction_name if a.owners else "", a.name))
    return out

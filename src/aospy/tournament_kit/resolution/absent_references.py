"""Aptitudes d'une liste qui citent une unité absente de cette liste (demande
de l'utilisateur, principe 7 de `data/roster_simplifications.md` : « retirer
ce qui ne peut plus servir dans cette liste »).

Ex. « Le Très Redouté Treizième Sort » de Skreech ramène des figurines dans
une unité de *Clanrats*, « Assaut de Diversion » de Crixxit cible des *Gutter
Runners* : si la liste n'a ni l'une ni l'autre, cette partie de l'aptitude (ou
l'aptitude entière) ne sert à rien. Ce module ne fait que *signaler* — la
simplification elle-même reste dictée et validée par le joueur.

Lecture du texte anglais Wahapedia (`data/wahapedia/*.csv`), le seul où les
noms d'unité sont fiables (le texte français les traduit) : on y cherche le
nom de chaque warscroll de la faction qui n'est pas dans la liste. Lecture
seule, aucun accès DB."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ...sources.wahapedia_csv import read_csv
from ..sources.wahapedia_lookup import DEFAULT_WAHAPEDIA_DIR

_POINTS_SUFFIX_RE = re.compile(r"\s*-\s*\(\d+\)\s*Points\s*$|\s*\(\d+ Points\)\s*$")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class AbsentReference:
    ability: str  # nom Wahapedia (anglais) de l'aptitude
    owner: str  # unité qui la porte, ou catégorie de règle d'armée
    unit: str  # warscroll cité, absent de la liste


@lru_cache(maxsize=8)
def _read(base_dir: str, name: str) -> tuple[dict[str, str], ...]:
    return tuple(read_csv(Path(base_dir) / name))


def _plain(description: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", description or ""))
    return re.sub(r"\s+", " ", text.replace("’", "'"))


def _base(name: str) -> str:
    return _POINTS_SUFFIX_RE.sub("", name or "").split(" (", 1)[0].strip().lower()


def _list_context(parsed, base: str):
    """(ids de faction, warscrolls non virtuels, noms d'unités de la liste,
    aptitudes à examiner `(aptitude, porteur, texte)`)."""
    factions = {r["name"].strip().lower(): r["id"] for r in _read(base, "Factions.csv")}
    fids = {factions[p.strip().lower()] for p in parsed.faction.split("|") if p.strip().lower() in factions}
    warscrolls = [r for r in _read(base, "Warscrolls.csv") if r.get("virtual") != "true"]

    in_list = {u.name for reg in parsed.regiments for u in reg.units}
    for ror in parsed.regiments_of_renown:
        in_list.update(ror.units)

    sources: list[tuple[str, str, str]] = []
    ids = {r["id"]: r["name"] for r in warscrolls if r["name"] in in_list}
    for a in _read(base, "Warscrolls_abilities.csv"):
        if a["warscroll_id"] in ids:
            sources.append((a["name"], ids[a["warscroll_id"]], a["description"]))
    chosen_lores = {_base(x) for x in (parsed.spell_lore, parsed.prayer_lore, parsed.manifestation_lore) if x}
    formation = _base(parsed.allegiance or "")
    options = {_base(o) for reg in parsed.regiments for u in reg.units for o in u.options}
    for a in _read(base, "Faction_abilities.csv"):
        if a["faction_id"] not in fids | {"EnS"}:
            continue
        sub = _base(a["subtype_name"])
        keep = (
            (a["faction_id"] in fids and a["type_name"] == "Battle Traits")
            or (a["type_name"] == "Battle Formations" and sub == formation)
            or sub in chosen_lores
            or (a["faction_id"] in fids and a["name"].strip().lower() in options)
        )
        if keep:
            sources.append((a["name"], a["subtype_name"] or a["type_name"], a["description"]))
    return fids, warscrolls, in_list, set(ids), sources


def find_absent_references(parsed, base_dir: str | Path = DEFAULT_WAHAPEDIA_DIR) -> list[AbsentReference]:
    """Aptitudes des unités de `parsed` (`ParsedList`) et de ses règles d'armée
    choisies (traits de bataille, formation, domaines, optimisations prises)
    dont le texte anglais cite un warscroll de la faction absent de la liste."""
    base = str(base_dir)
    fids, warscrolls, in_list, _, sources = _list_context(parsed, base)
    terrain = parsed.faction_terrain if isinstance(parsed.faction_terrain, list) else (
        [parsed.faction_terrain] if parsed.faction_terrain else []
    )
    present = {_base(n) for n in in_list} | {_base(t) for t in terrain}

    # candidats : warscrolls de la faction, hors liste, hors manifestations
    # (citées par leur propre domaine) et hors décors de faction
    candidates = sorted({
        r["name"] for r in warscrolls
        if r["faction_id"] in fids and _base(r["name"]) not in present
        and r.get("role") not in ("Manifestation", "Endless Spell", "Faction Terrain")
    }, key=len, reverse=True)
    if not candidates:
        return []
    patterns = [(name, re.compile(rf"(?<![\w']){re.escape(name.replace('’', chr(39)))}(?![\w'])")) for name in candidates]

    found: dict[AbsentReference, None] = {}
    for ability, owner, text in sources:
        plain = _plain(text)
        for name, pattern in patterns:
            if pattern.search(plain):
                found[AbsentReference(ability, owner, name)] = None
                plain = pattern.sub(" ", plain)  # « Clanrats » ne refait pas surface sous un nom plus court
    return list(found)


#: mots-clés de type d'unité vérifiés par `find_absent_keywords`
UNIT_TYPE_KEYWORDS = ("INFANTRY", "CAVALRY", "MONSTER", "WAR MACHINE", "BEAST", "HERO", "WIZARD", "PRIEST")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.:;])\s+|<br\s*/?>|</?li>|</?p>", re.I)


def find_absent_keywords(parsed, base_dir: str | Path = DEFAULT_WAHAPEDIA_DIR) -> list[AbsentReference]:
    """Aptitudes (même périmètre que `find_absent_references`) dont une
    phrase visant des unités *amies* (« friendly », sans « enemy ») cite un
    mot-clé de type (`UNIT_TYPE_KEYWORDS`, en majuscules comme dans
    Wahapedia) qu'aucune unité de la liste ne porte — ex. « INFANTRY and
    CAVALRY » sans cavalerie dans l'armée. `AbsentReference.unit` porte alors
    le mot-clé. Signalement seulement : la réécriture reste validée par le
    joueur (une mention peut viser l'ennemi dans une tournure non détectée)."""
    base = str(base_dir)
    _, _, _, ids, sources = _list_context(parsed, base)
    present = {r["keyword"].strip().upper() for r in _read(base, "Warscrolls_keywords.csv") if r["warscroll_id"] in ids}
    absent = [k for k in UNIT_TYPE_KEYWORDS if k not in present]
    if not ids or not absent:
        return []
    patterns = [(k, re.compile(rf"(?<![A-Z]){k}(?![A-Z])")) for k in absent]

    found: dict[AbsentReference, None] = {}
    for ability, owner, text in sources:
        for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
            plain = _plain(sentence)
            low = plain.lower()
            if "friendly" not in low or "enem" in low:
                continue
            for keyword, pattern in patterns:
                if pattern.search(plain):
                    found[AbsentReference(ability, owner, keyword)] = None
    return list(found)

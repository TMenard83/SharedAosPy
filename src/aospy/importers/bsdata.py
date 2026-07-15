"""Importeur BSData : télécharge et parse les catalogues BattleScribe (AoS 4)."""

from __future__ import annotations

import csv
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb

from ..domain.models import Army, Unit, Weapon
from ..persistence import repository

NS = "http://www.battlescribe.net/schema/catalogueSchema"
BASE_URL = "https://raw.githubusercontent.com/BSData/age-of-sigmar-4th/main/"

#: Répertoire des CSV Wahapedia, utilisé uniquement pour recouper le statut
#: Legends (cf. `_wahapedia_legends_names`) — aucune dépendance vers `wahapedia.py`
#: pour ne pas inverser le sens de dépendance documenté dans CLAUDE.md.
WAHAPEDIA_DATA_DIR = Path("data") / "wahapedia"

# Arméees disponibles : nom -> (fichier_principal, fichier_library, grand_alliance)
KNOWN_ARMIES: dict[str, tuple[str, str, str]] = {
    # Order
    "Cities of Sigmar": ("Cities of Sigmar.cat", "Cities of Sigmar - Library.cat", "Order"),
    "Daughters of Khaine": ("Daughters of Khaine.cat", "Daughters of Khaine - Library.cat", "Order"),
    "Fyreslayers": ("Fyreslayers.cat", "Fyreslayers - Library.cat", "Order"),
    "Idoneth Deepkin": ("Idoneth Deepkin.cat", "Idoneth Deepkin - Library.cat", "Order"),
    "Kharadron Overlords": ("Kharadron Overlords.cat", "Kharadron Overlords - Library.cat", "Order"),
    "Lumineth Realm-lords": ("Lumineth Realm-lords.cat", "Lumineth Realm-lords - Library.cat", "Order"),
    "Seraphon": ("Seraphon.cat", "Seraphon - Library.cat", "Order"),
    "Stormcast Eternals": ("Stormcast Eternals.cat", "Stormcast Eternals - Library.cat", "Order"),
    "Sylvaneth": ("Sylvaneth.cat", "Sylvaneth - Library.cat", "Order"),
    # Chaos
    "Beasts of Chaos": ("Beasts of Chaos.cat", "Beasts of Chaos - Library.cat", "Chaos"),
    "Blades of Khorne": ("Blades of Khorne.cat", "Blades of Khorne - Library.cat", "Chaos"),
    "Disciples of Tzeentch": ("Disciples of Tzeentch.cat", "Disciples of Tzeentch - Library.cat", "Chaos"),
    "Hedonites of Slaanesh": ("Hedonites of Slaanesh.cat", "Hedonites of Slaanesh - Library.cat", "Chaos"),
    "Helsmiths of Hashut": ("Helsmiths of Hashut.cat", "Helsmiths of Hashut - Library.cat", "Chaos"),
    "Maggotkin of Nurgle": ("Maggotkin of Nurgle.cat", "Maggotkin of Nurgle - Library.cat", "Chaos"),
    "Skaven": ("Skaven.cat", "Skaven - Library.cat", "Chaos"),
    "Slaves to Darkness": ("Slaves to Darkness.cat", "Slaves to Darkness - Library.cat", "Chaos"),
    # Death
    "Flesh-eater Courts": ("Flesh-eater Courts.cat", "Flesh-eater Courts - Library.cat", "Death"),
    "Nighthaunt": ("Nighthaunt.cat", "Nighthaunt - Library.cat", "Death"),
    "Ossiarch Bonereapers": ("Ossiarch Bonereapers.cat", "Ossiarch Bonereapers - Library.cat", "Death"),
    "Soulblight Gravelords": ("Soulblight Gravelords.cat", "Soulblight Gravelords - Library.cat", "Death"),
    # Destruction
    "Bonesplitterz": ("Bonesplitterz.cat", "Bonesplitterz - Library.cat", "Destruction"),
    "Gloomspite Gitz": ("Gloomspite Gitz.cat", "Gloomspite Gitz - Library.cat", "Destruction"),
    "Ironjawz": ("Ironjawz.cat", "Ironjawz - Library.cat", "Destruction"),
    "Kruleboyz": ("Kruleboyz.cat", "Kruleboyz - Library.cat", "Destruction"),
    "Ogor Mawtribes": ("Ogor Mawtribes.cat", "Ogor Mawtribes - Library.cat", "Destruction"),
    "Sons of Behemat": ("Sons of Behemat.cat", "Sons of Behemat - Library.cat", "Destruction"),
}


@dataclass
class ParsedWeapon:
    name: str
    kind: str  # 'melee' | 'ranged'
    range_in: int
    attacks: int
    hit: int
    wound: int
    rend: int
    damage: int
    abilities: Optional[str] = None
    wielders: int = 0  # nb de modèles porteurs (0 = défaut, ne devrait pas survenir post-parse)


@dataclass
class ParsedUnit:
    target_id: str
    name: str
    move: int
    save: int
    health: int
    control: int
    models: int
    is_hero: bool
    ward: Optional[int]
    keywords: frozenset[str] = frozenset()
    weapons: list[ParsedWeapon] = field(default_factory=list)


# ----- Conversions BattleScribe -----------------------------------------------

_DICE_RE = re.compile(r"^(\d+)?D(\d+)([+-]\d+)?$", re.IGNORECASE)


def parse_dice(s: str) -> int:
    """Convertit '3'→3, 'D3'→2, 'D6'→4, '2D6'→7, 'D6+3'→7, '-'→0."""
    s = (s or "").strip().replace('"', "").replace("\u201d", "")
    s = s.replace("&quot;", "")
    if not s or s == "-":
        return 0
    m = _DICE_RE.match(s)
    if m:
        n = int(m.group(1) or 1)
        d = int(m.group(2))
        offset = int(m.group(3) or 0)
        return max(1, round(n * (d + 1) / 2) + offset)
    try:
        return int(s)
    except ValueError:
        return 0


def parse_target(s: str) -> int:
    """Convertit '4+'→4, '-'→7 (impossible)."""
    s = (s or "").strip()
    if not s or s == "-":
        return 7
    m = re.match(r"^(\d+)\+?$", s)
    return int(m.group(1)) if m else 7


def _ns(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _char(profile: ET.Element, name: str) -> str:
    for c in profile.findall(_ns("characteristics") + "/" + _ns("characteristic")):
        if c.get("name") == name:
            return (c.text or "").strip()
    return ""


# ----- Téléchargement ---------------------------------------------------------

def download(filename: str, *, timeout: float = 30.0) -> str:
    """Télécharge un fichier .cat depuis le dépôt BSData (raw)."""
    url = BASE_URL + urllib.parse.quote(filename)
    req = urllib.request.Request(url, headers={"User-Agent": "AoSPy/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ----- Parsing ----------------------------------------------------------------

def parse_main_costs(xml_text: str) -> dict[str, int]:
    """Extrait {targetId: points} des entryLinks racines avec un coût en pts.

    Quand plusieurs entryLinks pointent vers le même targetId (cas des unités
    proposées à la fois en version standalone et en "compagnon" d'un héros),
    on conserve la valeur maximale — la version standalone est toujours la
    plus chère et c'est elle qui correspond au profil de la library.
    """
    root = ET.fromstring(xml_text)
    costs: dict[str, int] = {}
    for link in root.findall(_ns("entryLinks") + "/" + _ns("entryLink")):
        target = link.get("targetId")
        if not target:
            continue
        for cost in link.findall(_ns("costs") + "/" + _ns("cost")):
            if cost.get("name") == "pts" and cost.get("typeId") == "points":
                try:
                    val = int(cost.get("value") or "0")
                except ValueError:
                    val = 0
                if val > 0 and val > costs.get(target, 0):
                    costs[target] = val
                break
    return costs


def _entry_minmax(entry: ET.Element, scope: str) -> tuple[Optional[int], Optional[int]]:
    """Retourne (min, max) des contraintes 'selections' sur un scope donné."""
    mn: Optional[int] = None
    mx: Optional[int] = None
    for c in entry.findall(_ns("constraints") + "/" + _ns("constraint")):
        if c.get("field") != "selections" or c.get("scope") != scope:
            continue
        try:
            val = int(c.get("value") or "0")
        except ValueError:
            continue
        if c.get("type") == "min":
            mn = val if mn is None else max(mn, val)
        elif c.get("type") == "max":
            mx = val if mx is None else min(mx, val)
    return mn, mx


def _weapon_wielders(weapon_entry: ET.Element, model_count: int, unit_id: str) -> int:
    """Calcule le nombre de modèles porteurs d'une arme à partir des contraintes BSData.

    - Arme requise (min ≥ 1 scope=parent) → portée par chaque modèle du groupe.
    - Arme optionnelle plafonnée scope=unit → limite globale du cap.
    - Arme optionnelle plafonnée scope=parent → cap × modèles du groupe.
    - Aucune contrainte → tous les modèles du groupe (comportement par défaut).
    """
    min_pp, max_pp = _entry_minmax(weapon_entry, "parent")
    _, max_iu = _entry_minmax(weapon_entry, unit_id)
    if min_pp is not None and min_pp >= 1:
        return max(1, model_count * min_pp)
    caps: list[int] = []
    if max_iu is not None:
        caps.append(max_iu)
    if max_pp is not None:
        caps.append(model_count * max_pp)
    if caps:
        return max(1, min(caps))
    return max(1, model_count)


def _extract_weapons(unit_entry: ET.Element) -> list[ParsedWeapon]:
    """Parcourt récursivement les profils Melee/Ranged Weapon et calcule les porteurs.

    Dédoublonnage par `id` d'entrée BattleScribe (pas par nom d'arme) : quand
    plusieurs modèles *distincts* du même sous-groupe portent chacun une arme au nom
    identique (ex. "Freeguild Command Corps Adjutants" : Great Herald, Arch-Knight et
    Mascot Gargoylian portent chacun leur propre "Adjutant Weapons", trois
    `selectionEntry` différentes), leurs `wielders` sont additionnés sous une seule
    entrée `ParsedWeapon` plutôt que de garder seulement la première rencontrée (le
    dédoublonnage par nom sous-comptait ces porteurs : 1 au lieu de 3).
    """
    weapons: list[ParsedWeapon] = []
    by_name: dict[str, ParsedWeapon] = {}
    seen_ids: set[str] = set()
    unit_id = unit_entry.get("id") or ""
    base_models = _base_models(unit_entry)

    def walk(entry: ET.Element, model_count: int) -> None:
        if entry.get("type") == "model":
            mn, _mx = _entry_minmax(entry, "parent")
            model_count = mn if mn and mn > 0 else 1
        for profile in entry.findall(_ns("profiles") + "/" + _ns("profile")):
            kind_xml = profile.get("typeName") or ""
            if kind_xml not in ("Melee Weapon", "Ranged Weapon"):
                continue
            entry_id = entry.get("id") or ""
            dedup_key = entry_id or f"{entry.get('name')}::{profile.get('name')}"
            if dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)
            name = profile.get("name") or "?"
            wielders = _weapon_wielders(entry, model_count, unit_id)
            if name in by_name:
                by_name[name].wielders += wielders
                continue
            kind = "ranged" if kind_xml == "Ranged Weapon" else "melee"
            rng = _char(profile, "Rng")
            range_in = parse_dice(rng) if kind == "ranged" else 1
            ability = _char(profile, "Ability")
            w = ParsedWeapon(
                name=name, kind=kind, range_in=max(1, range_in),
                attacks=parse_dice(_char(profile, "Atk")),
                hit=parse_target(_char(profile, "Hit")),
                wound=parse_target(_char(profile, "Wnd")),
                rend=parse_dice(_char(profile, "Rnd")),
                damage=parse_dice(_char(profile, "Dmg")),
                abilities=None if ability in ("", "-") else ability,
                wielders=wielders,
            )
            weapons.append(w)
            by_name[name] = w
        for child in entry.findall(_ns("selectionEntries") + "/" + _ns("selectionEntry")):
            walk(child, model_count)
        # Choix mutuellement exclusifs (Lance vs Warblade) : descendre dans les groupes.
        for group in entry.findall(_ns("selectionEntryGroups") + "/" + _ns("selectionEntryGroup")):
            for child in group.findall(_ns("selectionEntries") + "/" + _ns("selectionEntry")):
                walk(child, model_count)

    walk(unit_entry, base_models)
    return weapons


def _ward_from_categories(unit_entry: ET.Element) -> Optional[int]:
    for link in unit_entry.findall(_ns("categoryLinks") + "/" + _ns("categoryLink")):
        name = link.get("name") or ""
        m = re.match(r"^WARD \((\d+)\+\)$", name)
        if m:
            return int(m.group(1))
    return None


def _is_hero(unit_entry: ET.Element) -> bool:
    for link in unit_entry.findall(_ns("categoryLinks") + "/" + _ns("categoryLink")):
        if (link.get("name") or "").upper() == "HERO":
            return True
    return False


def _keywords(unit_entry: ET.Element) -> frozenset[str]:
    """Mots-clés de l'unité (mêmes noms que les catégories BattleScribe, en MAJUSCULES).

    Exclut la pseudo-catégorie ``WARD (N+)`` (une note de stat, gérée séparément par
    `_ward_from_categories`, pas un mot-clé de jeu comme HERO/MONSTER/INFANTRY…).
    """
    out: set[str] = set()
    for link in unit_entry.findall(_ns("categoryLinks") + "/" + _ns("categoryLink")):
        name = (link.get("name") or "").strip().upper()
        if name and not re.match(r"^WARD \(\d+\+\)$", name):
            out.add(name)
    return frozenset(out)


def _base_models(unit_entry: ET.Element) -> int:
    """Nombre de modèles de base : somme des min des selectionEntry type=model."""
    total = 0
    for model_entry in unit_entry.findall(_ns("selectionEntries") + "/" + _ns("selectionEntry")):
        if model_entry.get("type") != "model":
            continue
        min_val = 1
        for c in model_entry.findall(_ns("constraints") + "/" + _ns("constraint")):
            if c.get("type") == "min" and c.get("field") == "selections":
                try:
                    min_val = max(min_val, int(c.get("value") or "1"))
                except ValueError:
                    pass
                break
        total += min_val
    return max(1, total)


def parse_library_units(xml_text: str) -> dict[str, ParsedUnit]:
    """Extrait {unit_id: ParsedUnit} depuis un fichier Library.cat."""
    root = ET.fromstring(xml_text)
    units: dict[str, ParsedUnit] = {}
    selector = _ns("sharedSelectionEntries") + "/" + _ns("selectionEntry")
    for entry in root.findall(selector):
        if entry.get("type") != "unit":
            continue
        uid = entry.get("id") or ""
        name = entry.get("name") or "?"
        unit_profile = None
        for p in entry.findall(_ns("profiles") + "/" + _ns("profile")):
            if p.get("typeName") == "Unit":
                unit_profile = p
                break
        if unit_profile is None:
            continue
        units[uid] = ParsedUnit(
            target_id=uid, name=name,
            move=parse_dice(_char(unit_profile, "Move")),
            save=parse_target(_char(unit_profile, "Save")),
            health=parse_dice(_char(unit_profile, "Health")),
            control=parse_dice(_char(unit_profile, "Control")),
            models=_base_models(entry),
            is_hero=_is_hero(entry),
            ward=_ward_from_categories(entry),
            keywords=_keywords(entry),
            weapons=_extract_weapons(entry),
        )
    return units


# ----- Filtrage Legends / packs narratifs périmés ------------------------------

#: Fragments de nom (minuscules) signalant une variante de pack narratif expiré.
#: "Scourge of Aqshy" et "Scourge of Ghyran" sont des packs narratifs saisonniers
#: dépassés ; absents des CSV Wahapedia (Aqshy) ou explicitement écartés (Ghyran),
#: mais BSData continue de les exposer sous ces deux formes de nommage
#: (suffixe « (Scourge of Ghyran) » côté BSData, préfixe « Scourge of Ghyran »
#: côté Wahapedia — cf. `wahapedia.py::import_faction`).
_EXPIRED_VARIANT_MARKERS: frozenset[str] = frozenset({
    "scourge of aqshy", "scourge of ghyran",
})


def _is_expired_variant(name: str) -> bool:
    lname = name.strip().lower()
    return any(marker in lname for marker in _EXPIRED_VARIANT_MARKERS)


def _is_legends_catalogue(xml_text: str) -> bool:
    """Détecte un catalogue BSData entièrement retiré (nom suffixé « [LEGENDS] »).

    Pendant BSData du contrôle par `Source.csv`/notes côté Wahapedia — ici le
    signal porte sur le catalogue entier (ex. Beasts of Chaos, Bonesplitterz),
    pas sur des warscrolls individuels.
    """
    root = ET.fromstring(xml_text)
    return "[legends]" in (root.get("name") or "").lower()


def _wahapedia_legends_names(data_dir: Path = WAHAPEDIA_DATA_DIR) -> set[str]:
    """Noms (minuscules) des unités Legends selon les CSV Wahapedia.

    Recoupement par nom (les deux sources n'ont pas d'ID commun) pour appliquer
    à l'import BSData le même filtre Legends qu'à l'import Wahapedia
    (`wahapedia.py::_legends_warscroll_ids`, qui exclut par `Source.csv` de type
    Legends ou note de retrait annoncé) — cible les unités individuellement
    retirées d'une armée par ailleurs toujours jouable (ex. Terrorgheist côté
    Soulblight Gravelords), en plus du cas « catalogue entier » traité par
    `_is_legends_catalogue`.
    """
    if not data_dir.exists():
        return set()

    def _read(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh, delimiter="|"))

    sources = _read(data_dir / "Source.csv")
    legend_sources = {s["id"] for s in sources if "legends" in (s.get("name") or "").lower()}
    names: set[str] = set()
    for w in _read(data_dir / "Warscrolls.csv"):
        is_legend = (
            w.get("source_id") in legend_sources
            or "legend" in (w.get("notes") or "").lower()
        )
        if is_legend:
            names.add((w.get("name") or "").strip().lower())
    return names


# ----- Unités "agglomérat" (un warscroll payant + sous-entrées gratuites qui en dépendent) ---

def _entrylink_pts(link: ET.Element) -> float:
    for c in link.findall(_ns("costs") + "/" + _ns("cost")):
        if c.get("name") == "pts":
            try:
                return float(c.get("value") or "0")
            except ValueError:
                return 0.0
    return 0.0


def _detect_composite_units(main_xml: str) -> dict[str, tuple[str, Optional[str]]]:
    """Détecte les "agglomérats" directement dans le catalogue BSData, sans mapping en dur.

    BSData représente un warscroll composite — une entrée payante accompagnée d'un
    ou plusieurs éléments gratuits qui n'existent que parce qu'elle a été prise, que
    ce soit un unique datasheet scindé en plusieurs `selectionEntry` ("Freeguild
    Command Corps" = Adjutants payante + Auxiliaries/Whisperblade à 0 pt) ou un héros
    accompagné d'une unité/second héros gratuit ("Neave Blacktalon" + Neave's
    Companions/Lorai, "Morathi-Khaine" + The Shadow Queen, "Callis and Toll" +
    Toll's Companions, "Gunnar Brand" + Singri Brand/The Oathsworn Kin) — par une
    `entryLink` à 0 pt dont une condition, quelque part dans son arbre (`atLeast`
    top-level pour le premier cas, `localConditionGroup`/`instanceOf` imbriqué pour
    les autres), référence par `childId` une AUTRE `entryLink` du même catalogue qui,
    elle, est payante. Ce signal est repéré ici plutôt que hardcodé par nom : c'est
    la donnée BSData elle-même qui dit "ceci n'existe que grâce à cette autre
    entrée", donc c'est elle qui doit piloter la fusion (vérifié sur les 27
    catalogues connus : 7 sous-entrées trouvées dans 4 armées, toutes confirmées par
    recoupement avec un UnitSize/points Wahapedia cohérent).

    Retourne ``{targetId_sous-entrée_gratuite: (targetId_parent_payant, nom_optionnel)}``
    — ``nom_optionnel`` est le `childName` BattleScribe de la condition quand il est
    présent (cas Command Corps : renomme le parent fusionné en perdant le
    qualificatif du sous-groupe payant, "...Adjutants" → "Freeguild Command Corps"),
    sinon `None` (le nom du parent payant est alors conservé tel quel, ex. "Neave
    Blacktalon", "Morathi-Khaine").
    """
    root = ET.fromstring(main_xml)
    id_to_target: dict[str, str] = {}
    id_paid: dict[str, bool] = {}
    for link in root.findall(".//" + _ns("entryLink")):
        if link.get("type") == "selectionEntry" and link.get("id") and link.get("targetId"):
            lid = link.get("id") or ""
            id_to_target[lid] = link.get("targetId") or ""
            id_paid[lid] = _entrylink_pts(link) > 0

    out: dict[str, tuple[str, Optional[str]]] = {}
    for link in root.findall(".//" + _ns("entryLink")):
        if link.get("type") != "selectionEntry":
            continue
        lid = link.get("id") or ""
        if id_paid.get(lid, False):
            continue
        extra_target = link.get("targetId")
        if not extra_target:
            continue
        parent_ids: set[str] = set()
        merged_name: Optional[str] = None
        for cond in link.findall(".//" + _ns("condition")):
            cid = cond.get("childId")
            if cid and cid != lid and id_paid.get(cid):
                parent_ids.add(cid)
                if cond.get("childName"):
                    merged_name = cond.get("childName")
        if len(parent_ids) == 1:
            parent_target = id_to_target[next(iter(parent_ids))]
            if parent_target != extra_target:
                out[extra_target] = (parent_target, merged_name)
    return out


def _merge_composite_units(
    units: dict[str, ParsedUnit], composite: dict[str, tuple[str, Optional[str]]],
) -> None:
    """Fusionne in-place les sous-entrées gratuites dans leur parent payant.

    Simplification documentée : quand les sous-groupes ont des caractéristiques
    (Save notamment) différentes du parent, le schéma aospy n'ayant qu'une valeur
    par `Unit`, celles du parent payant sont conservées pour l'unité fusionnée.
    """
    for extra_id, (parent_id, merged_name) in composite.items():
        extra = units.pop(extra_id, None)
        parent = units.get(parent_id)
        if extra is None or parent is None:
            continue
        parent.models += extra.models
        parent.weapons += extra.weapons
        parent.keywords |= extra.keywords
        if merged_name:
            parent.name = merged_name


# ----- Import dans la base ----------------------------------------------------

@dataclass
class ImportSummary:
    army: str
    inserted: int = 0
    updated: int = 0
    skipped_no_points: int = 0
    skipped_no_profile: int = 0
    skipped_legends: int = 0
    skipped_terrain: int = 0


def import_army(
    con: duckdb.DuckDBPyConnection, army_name: str,
) -> ImportSummary:
    """Importe une armée depuis BSData. Remplace les unités existantes (par nom)."""
    if army_name not in KNOWN_ARMIES:
        raise ValueError(
            f"armée inconnue '{army_name}'. Connues : {', '.join(KNOWN_ARMIES)}"
        )
    main_file, lib_file, alliance = KNOWN_ARMIES[army_name]
    main_xml = download(main_file)
    summary = ImportSummary(army=army_name)
    if _is_legends_catalogue(main_xml):
        return summary

    costs = parse_main_costs(main_xml)
    units = parse_library_units(download(lib_file))
    _merge_composite_units(units, _detect_composite_units(main_xml))
    legends_names = _wahapedia_legends_names()

    existing = repository.get_army_by_name(con, army_name)
    if existing is None or existing.id is None:
        army_id = repository.add_army(con, Army(name=army_name, grand_alliance=alliance))  # type: ignore[arg-type]
    else:
        army_id = existing.id

    for target_id, points in costs.items():
        parsed = units.get(target_id)
        if parsed is None:
            summary.skipped_no_profile += 1
            continue
        if parsed.name.strip().lower() in legends_names or _is_expired_variant(parsed.name):
            summary.skipped_legends += 1
            continue
        if "FACTION TERRAIN" in parsed.keywords:
            # décors de table (Shrine of Dark Tribute, Stormreach Portal…) : pas une unité de
            # combat, aucun rapport entre points et profil (move=0, control=0, pas d'armes) —
            # même exclusion que `wahapedia.py::INGESTIBLE_ROLES`, appliquée ici via le mot-clé
            # faute d'un champ "role" côté BattleScribe.
            summary.skipped_terrain += 1
            continue
        unit = Unit(
            name=parsed.name, army_id=army_id,
            move=parsed.move, save=parsed.save, health=parsed.health,
            control=parsed.control, models=parsed.models, points=points,
            is_hero=parsed.is_hero, ward=parsed.ward, keywords=parsed.keywords,
            weapons=[Weapon(
                name=w.name, kind=w.kind, range_in=w.range_in,  # type: ignore[arg-type]
                attacks=w.attacks, hit=w.hit, wound=w.wound,
                rend=w.rend, damage=w.damage, abilities=w.abilities,
                wielders=w.wielders,
            ) for w in parsed.weapons],
        )
        was_update = repository.replace_unit(con, unit)
        if was_update:
            summary.updated += 1
        else:
            summary.inserted += 1
    # Comptabilise les coûts sans correspondance comme "no_profile" (déjà fait)
    return summary

"""Importeur BSData : télécharge et parse les catalogues BattleScribe (AoS 4)."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import duckdb

from . import repository
from .models import Army, Unit, Weapon

NS = "http://www.battlescribe.net/schema/catalogueSchema"
BASE_URL = "https://raw.githubusercontent.com/BSData/age-of-sigmar-4th/main/"

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
    """Parcourt récursivement les profils Melee/Ranged Weapon et calcule les porteurs."""
    weapons: list[ParsedWeapon] = []
    seen: set[str] = set()
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
            name = profile.get("name") or "?"
            if name in seen:
                continue
            seen.add(name)
            kind = "ranged" if kind_xml == "Ranged Weapon" else "melee"
            rng = _char(profile, "Rng")
            range_in = parse_dice(rng) if kind == "ranged" else 1
            ability = _char(profile, "Ability")
            weapons.append(ParsedWeapon(
                name=name, kind=kind, range_in=max(1, range_in),
                attacks=parse_dice(_char(profile, "Atk")),
                hit=parse_target(_char(profile, "Hit")),
                wound=parse_target(_char(profile, "Wnd")),
                rend=parse_dice(_char(profile, "Rnd")),
                damage=parse_dice(_char(profile, "Dmg")),
                abilities=None if ability in ("", "-") else ability,
                wielders=_weapon_wielders(entry, model_count, unit_id),
            ))
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
            weapons=_extract_weapons(entry),
        )
    return units


# ----- Import dans la base ----------------------------------------------------

@dataclass
class ImportSummary:
    army: str
    inserted: int = 0
    updated: int = 0
    skipped_no_points: int = 0
    skipped_no_profile: int = 0


def import_army(
    con: duckdb.DuckDBPyConnection, army_name: str,
) -> ImportSummary:
    """Importe une armée depuis BSData. Remplace les unités existantes (par nom)."""
    if army_name not in KNOWN_ARMIES:
        raise ValueError(
            f"armée inconnue '{army_name}'. Connues : {', '.join(KNOWN_ARMIES)}"
        )
    main_file, lib_file, alliance = KNOWN_ARMIES[army_name]
    costs = parse_main_costs(download(main_file))
    units = parse_library_units(download(lib_file))

    existing = repository.get_army_by_name(con, army_name)
    if existing is None or existing.id is None:
        army_id = repository.add_army(con, Army(name=army_name, grand_alliance=alliance))  # type: ignore[arg-type]
    else:
        army_id = existing.id

    summary = ImportSummary(army=army_name)
    for target_id, points in costs.items():
        parsed = units.get(target_id)
        if parsed is None:
            summary.skipped_no_profile += 1
            continue
        unit = Unit(
            name=parsed.name, army_id=army_id,
            move=parsed.move, save=parsed.save, health=parsed.health,
            control=parsed.control, models=parsed.models, points=points,
            is_hero=parsed.is_hero, ward=parsed.ward,
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

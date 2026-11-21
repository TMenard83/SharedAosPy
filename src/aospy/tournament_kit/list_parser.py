"""Parse une liste d'armée exportée en texte brut par Warhammer Age of
Sigmar: The App (voir `data/Proposition de listes/*.txt`) en dataclasses.

Format ligne-à-ligne stable observé sur tous les exports : titre, faction,
allégeance optionnelle, en-tête (« General's Handbook », « Drops: N », lores —
« Spell Lore »/« Prayer Lore » selon que la faction lance des sorts ou des
prières, parfois les deux, plus « Manifestation Lore »),
« Battle Tactic Cards: ... », puis des sections « General's Regiment » /
« Regiment N » listant des lignes `Nom (points)` avec des sous-lignes
d'option ` • Option` rattachées à l'unité précédente, des sections optionnelles
« Regiments of Renown » (une ligne `Nom (points totaux)` suivie de ses unités
membres, sans points propres puisqu'inclus dans le prix du régiment) et
« Faction Terrain », et un pied de page « Created with... »/« App: ... »
ignoré.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Battletomes couvrant plusieurs factions jouables à la fois (ex. « Orruk
#: Warclans » = Ironjawz + Kruleboyz). L'App exporte alors la ligne de
#: faction comme « <nom du tome> | <sous-faction> <id de liste numérique> »
#: (ex. « Orruk Warclans | Ironjawz 104433899 ») — à l'inverse du cas armée
#: de renom (« Slaves to Darkness | Legion of the First Prince ») où c'est le
#: segment *avant* le « | » qui est la vraie faction, ici c'est celui
#: *après*, sans l'id de liste, qui l'est. `base_faction` doit distinguer les
#: deux pour indexer correctement `warscroll_index.json`/Wahapedia.
_COMBINED_BOOK_NAMES = frozenset({"Orruk Warclans"})
_TRAILING_LIST_ID_RE = re.compile(r"\s+\d+$")

_UNIT_RE = re.compile(r"^(?P<name>.+?) \((?P<points>\d+)\)$")
#: Un Faction Terrain payant est exporté avec son coût inline (ex. « Shrine
#: of Dark Tribute (20 Points) »), contrairement à `_UNIT_RE` (juste des
#: chiffres, ex. « Morathi-Khaine (750) ») ou à un terrain gratuit (aucun
#: suffixe, ex. « Nexus Chaotica ») — nécessaire pour que le nom recherché
#: dans le battletome/Wahapedia corresponde au nom canonique de la charte.
_TERRAIN_POINTS_RE = re.compile(r"^(?P<name>.+?) \(\d+ Points\)$")
#: Puce d'option, cherchée après `strip()` : selon l'export, la ligne
#: commence par « • » avec ou sans espace devant.
_OPTION_PREFIX = "• "
_REGIMENT_HEADER_RE = re.compile(r"^(General's Regiment|Regiment \d+)$")

#: Variantes de l'export Sigdex (sigdex.io), sinon identique au format de
#: l'App : variante saisonnière en suffixe (« Namarti Reavers (Scourge of
#: Aqshy) », réécrit en « Scourge of Aqshy: Namarti Reavers » comme l'App),
#: coût d'option nu (« Aqshian Sea Nettles (10) », réécrit en
#: « ... - (10) Points ») et en-têtes numériques en plus (« Wounds: 117 »).
_VARIANT_SUFFIX_RE = re.compile(r"^(?P<name>.+?) \((?P<variant>Scourge of \w+)\)$")
_BARE_OPTION_COST_RE = re.compile(r"\s*\((?P<points>\d+)\)$")
_NUMERIC_HEADER_RE = re.compile(r"^[A-Za-z][\w ]*:\s*\d+$")

#: Second format d'export, « compact » (observé sur une liste partagée par un
#: joueur, ex. `Vae Victis Vernou/Sylv - Pierrodactyl - nom_de_liste.txt`) :
#: pas de titre, 1re ligne « <faction> | <formation> », 2e ligne
#: « 2000/2000 points - 4 drops », en-têtes « Clé: valeur » (au lieu de
#: « Clé - valeur »), cartes de tactique séparées par « / », Faction Terrain
#: en en-tête, apostrophe typographique dans « General’s Regiment », options
#: sur la même ligne que l'unité (« Nom (190)  • Opt  • Opt », parfois
#: « Nom (620) , • General »), effectif préfixé (« 6x ») et coût d'option en
#: « (10 pts) ». `_normalize_compact` le réécrit au format standard ci-dessus
#: plutôt que de dupliquer le parseur.
_COMPACT_POINTS_RE = re.compile(r"^\d+\s*/\s*\d+\s*points?(?:\s*-\s*(?P<drops>\d+)\s*drops?)?$", re.IGNORECASE)
_COMPACT_HEADERS = {
    "spell lore": "Spell Lore",
    "prayer lore": "Prayer Lore",
    "manifestation lore": "Manifestation Lore",
}
_COMPACT_UNIT_RE = re.compile(r"^(?:\d+x\s+)?(?P<name>.+?)\s*\((?P<points>\d+)\)\s*,?\s*(?P<rest>.*)$")
_COMPACT_PAID_OPTION_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<points>\d+)\s*pts?\)$", re.IGNORECASE)


def _compact_offset(lines: list[str]) -> int | None:
    """Nombre de lignes de titre (0 ou 1) avant la ligne « <faction> | ... »
    d'une liste au format compact, ou `None` si ce n'est pas ce format — un
    joueur peut ajouter son propre titre en 1re ligne avant de la partager."""
    nonblank = [line.strip() for line in lines if line.strip()]
    for offset in (0, 1):
        if len(nonblank) >= offset + 2 and _COMPACT_POINTS_RE.match(nonblank[offset + 1]):
            return offset
    return None


def _is_compact(lines: list[str]) -> bool:
    return _compact_offset(lines) is not None


def _normalize_compact(lines: list[str], title: str | None) -> list[str]:
    offset = _compact_offset(lines) or 0
    nonblank = [line.strip() for line in lines if line.strip()]
    if offset:
        title = title or nonblank[0]
        nonblank = nonblank[offset:]
    faction, _, formation = nonblank[0].partition("|")
    out = [title or nonblank[0], faction.strip()]
    if formation.strip():
        out.append(formation.strip())
    m = _COMPACT_POINTS_RE.match(nonblank[1])
    if m.group("drops"):
        out.append(f"Drops: {m.group('drops')}")
    terrain: list[str] = []
    body_start = len(lines)
    seen = 0
    for i, raw in enumerate(lines):
        stripped = raw.strip().replace("’", "'")
        if not stripped:
            continue
        seen += 1
        if seen <= 2 + offset:
            continue
        key, sep, value = stripped.partition(":")
        key_l = key.strip().lower()
        if sep and key_l in _COMPACT_HEADERS:
            out.append(f"{_COMPACT_HEADERS[key_l]} - {value.strip()}")
        elif sep and key_l == "battle tactic cards":
            out.append("Battle Tactic Cards: " + ", ".join(c.strip() for c in re.split(r"[/,]", value) if c.strip()))
        elif sep and key_l == "faction terrain":
            terrain.extend(t.strip() for t in value.split(",") if t.strip())
        else:
            body_start = i
            break
    out.append("")
    for raw in lines[body_start:]:
        stripped = raw.strip().replace("’", "'")
        unit = _COMPACT_UNIT_RE.match(stripped) if not _REGIMENT_HEADER_RE.match(stripped) else None
        if unit is None:
            out.append(stripped)
            continue
        out.append(f"{unit.group('name')} ({unit.group('points')})")
        for opt in (o.strip(" ,") for o in unit.group("rest").split("•")):
            if not opt:
                continue
            paid = _COMPACT_PAID_OPTION_RE.match(opt)
            out.append(
                f"{_OPTION_PREFIX}{paid.group('name')} - ({paid.group('points')}) Points"
                if paid
                else f"{_OPTION_PREFIX}{opt}"
            )
    if terrain:
        out += ["", "Faction Terrain", *terrain]
    return out


@dataclass(frozen=True)
class UnitEntry:
    name: str
    points: int
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Regiment:
    title: str
    units: list[UnitEntry]


@dataclass(frozen=True)
class RegimentOfRenown:
    name: str
    points: int
    units: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedList:
    title: str
    faction: str
    allegiance: str | None
    drops: int | None
    spell_lore: str | None
    prayer_lore: str | None
    manifestation_lore: str | None
    battle_tactic_cards: list[str]
    regiments: list[Regiment]
    regiments_of_renown: list[RegimentOfRenown]
    faction_terrain: list[str]

    @property
    def base_faction(self) -> str:
        """Faction sans le suffixe d'armée de renom (ex. « Slaves to Darkness »
        pour « Slaves to Darkness | Legion of the First Prince ») — c'est ce
        nom qui indexe `data/json/warscroll_index.json`, la battletome de base
        restant la même pour une armée de renom.

        Cas inverse pour un tome multi-factions (voir `_COMBINED_BOOK_NAMES`) :
        le segment avant le « | » est le nom du tome, pas une faction jouable
        — c'est celui après, une fois l'id de liste numérique retiré, qu'il
        faut utiliser."""
        left, sep, right = self.faction.partition("|")
        left = left.strip()
        if sep and left in _COMBINED_BOOK_NAMES:
            right = _TRAILING_LIST_ID_RE.sub("", right.strip()).strip()
            if right:
                return right
        return left

    @property
    def army_of_renown(self) -> str | None:
        """Armée de Renom de la liste (« Lords of the Clan » pour « Sylvaneth | Lords of the Clan »), None
        sinon — y compris pour un tome multi-factions, dont le segment après le « | » est la faction."""
        left, sep, right = self.faction.partition("|")
        if not sep or left.strip() in _COMBINED_BOOK_NAMES:
            return None
        return right.strip() or None

    def unique_unit_names(self) -> list[str]:
        """Noms d'unité uniques (dédoublonne p. ex. les entrées Reinforced
        répétées), dans l'ordre d'apparition. Inclut le Faction Terrain et les
        unités membres des Regiments of Renown (le régiment lui-même n'a pas
        de profil d'unité propre — voir `regiments_of_renown`)."""
        seen: dict[str, None] = {}
        for regiment in self.regiments:
            for unit in regiment.units:
                seen.setdefault(unit.name, None)
        for ror in self.regiments_of_renown:
            for name in ror.units:
                seen.setdefault(name, None)
        for name in self.faction_terrain:
            m = _TERRAIN_POINTS_RE.match(name)
            seen.setdefault(m.group("name") if m else name, None)
        return list(seen)


def _next_nonblank(lines: list[str], start: int) -> int:
    i = start
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i


def parse_list(text: str, *, title: str | None = None) -> ParsedList:
    """`title` ne sert qu'au format compact (sans ligne de titre, voir
    `_normalize_compact`) ; à défaut, sa ligne « faction | formation »."""
    lines = text.splitlines()
    if _is_compact(lines):
        lines = _normalize_compact(lines, title)

    idx = _next_nonblank(lines, 0)
    title = lines[idx].strip()
    idx = _next_nonblank(lines, idx + 1)
    faction = lines[idx].strip()
    idx = _next_nonblank(lines, idx + 1)

    header_keywords = (
        "General's Handbook",
        "Drops:",
        "Spell Lore -",
        "Prayer Lore -",
        "Manifestation Lore -",
        "Battle Tactic Cards:",
    )
    allegiance = None
    if idx < len(lines) and lines[idx].strip() and not lines[idx].strip().startswith(header_keywords):
        allegiance = lines[idx].strip()
        idx += 1

    drops = None
    spell_lore = None
    prayer_lore = None
    manifestation_lore = None
    battle_tactic_cards: list[str] = []

    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped == "":
            idx += 1
            continue
        if stripped.startswith("General's Handbook"):
            idx += 1
            continue
        if stripped.startswith("Drops:"):
            drops = int(stripped.split(":", 1)[1].strip())
            idx += 1
            continue
        if stripped.startswith("Spell Lore -"):
            spell_lore = stripped.split("-", 1)[1].strip()
            idx += 1
            continue
        if stripped.startswith("Prayer Lore -"):
            # domaine de prières — même mécanique que le domaine de sorts,
            # pour les factions à Prêtres (ex. Flesh-eater Courts) plutôt
            # qu'à Sorciers ; une liste peut porter l'un, l'autre, les deux
            # ou aucun.
            prayer_lore = stripped.split("-", 1)[1].strip()
            idx += 1
            continue
        if stripped.startswith("Manifestation Lore -"):
            manifestation_lore = stripped.split("-", 1)[1].strip()
            idx += 1
            continue
        if stripped.startswith("Battle Tactic Cards:"):
            cards_raw = stripped.split(":", 1)[1].strip()
            battle_tactic_cards = [c.strip() for c in cards_raw.split(",") if c.strip()]
            idx += 1
            continue
        if _NUMERIC_HEADER_RE.match(stripped):
            # en-tête informatif sans usage ici (ex. « Wounds: 117 », Sigdex)
            idx += 1
            continue
        break

    regiments: list[Regiment] = []
    regiments_of_renown: list[RegimentOfRenown] = []
    faction_terrain: list[str] = []

    while idx < len(lines):
        raw = lines[idx]
        stripped = raw.strip()
        if stripped == "":
            idx += 1
            continue
        if stripped.startswith("Created with") or stripped.startswith("App:"):
            idx += 1
            continue
        if _REGIMENT_HEADER_RE.match(stripped):
            regiment_title = stripped
            idx += 1
            units: list[UnitEntry] = []
            while idx < len(lines) and lines[idx].strip() != "":
                entry_raw = lines[idx]
                entry_stripped = entry_raw.strip()
                if entry_stripped.startswith(_OPTION_PREFIX):
                    if units:
                        units[-1].options.append(
                            _BARE_OPTION_COST_RE.sub(r" - (\g<points>) Points", entry_stripped[1:].strip())
                        )
                else:
                    m = _UNIT_RE.match(entry_stripped)
                    if m:
                        name = _VARIANT_SUFFIX_RE.sub(r"\g<variant>: \g<name>", m.group("name"))
                        units.append(UnitEntry(name=name, points=int(m.group("points"))))
                idx += 1
            regiments.append(Regiment(title=regiment_title, units=units))
            continue
        if stripped == "Regiments of Renown":
            idx += 1
            while idx < len(lines) and lines[idx].strip() != "":
                entry_stripped = lines[idx].strip()
                m = _UNIT_RE.match(entry_stripped)
                if m:
                    regiments_of_renown.append(RegimentOfRenown(name=m.group("name"), points=int(m.group("points"))))
                elif regiments_of_renown:
                    regiments_of_renown[-1].units.append(entry_stripped)
                idx += 1
            continue
        if stripped == "Faction Terrain":
            idx += 1
            while idx < len(lines) and lines[idx].strip() != "":
                faction_terrain.append(lines[idx].strip())
                idx += 1
            continue
        idx += 1

    return ParsedList(
        title=title,
        faction=faction,
        allegiance=allegiance,
        drops=drops,
        spell_lore=spell_lore,
        prayer_lore=prayer_lore,
        manifestation_lore=manifestation_lore,
        battle_tactic_cards=battle_tactic_cards,
        regiments=regiments,
        regiments_of_renown=regiments_of_renown,
        faction_terrain=faction_terrain,
    )


def parse_list_file(path: str | Path) -> ParsedList:
    path = Path(path)
    return parse_list(path.read_text(encoding="utf-8"), title=path.stem)

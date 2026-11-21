"""Grilles d'évaluation des matchups de la L3 Centre 2026-27 (match aller, rondes 1 à 5).

Lit les listes du PDF de l'orga, retrouve chaque unité dans la base aospy, puis estime pour
chaque paire (notre liste, liste adverse) un écart de points de victoire attendu, avec un
texte explicatif chiffré pour pouvoir le discuter.

Le score combine (détail dans `method_body`) :
  * le combat (±6) : indice d'attrition du moteur (dégâts attendus unité par unité, toutes
    cibles de l'armée adverse, pondérées par leur coût) ;
  * le jeu de scénario (±7) : contrôle, nombre d'unités et mobilité ;
  * les aptitudes et le plan de jeu (±7,6) : textes Wahapedia lus par `l3/aptitudes.py`, plus
    une note de plan par liste (`Données/combos/<équipe>.json`, clé `note_plan`) ;
  * des ajustements manuels justifiés par matchup (`Données/ajustements_matchups.json`).

Usage : aospy l3 matchups [--check]
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
from pypdf import PdfReader

from aospy.domain.models import Unit
from aospy.engine.combat import (
    CombatModifiers,
    convolve,
    distribution_floor,
    effective_counts,
    expected_weapon_damage,
    normalize_abilities,
    weapon_crit_type,
    weapon_damage_distribution,
)
from aospy.persistence.repository import load_all_units_with_weapons

from . import aptitudes as apt

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "data" / "2026-27 L3 Aller"
PDF = FOLDER / "Sources" / "2027 L3 Centre (aller) - listes.pdf"
ADJUSTMENTS = FOLDER / "Données" / "ajustements_matchups.json"
WAHAPEDIA = ROOT / "data" / "wahapedia"
# Fiabilité des dégâts : poids du plancher (dégâts atteints au moins 2 fois sur 3) face à la moyenne.
RELIABILITY_COVERAGE = 0.66
RELIABILITY_WEIGHT = 0.5
COMBAT_MAX = 6  # poids max du combat (était 10 : il écrasait mobilité et aptitudes)
FURY_ATTACKS = 1.5 # Explosion de Fureur (fin de tour) : ~3 attaques sur 2 tours, meilleur profil
DB = ROOT / "data" / "aospy.duckdb"

# Joueur -> (équipe, faction en base)
PLAYERS: dict[str, tuple[str, str]] = {}
_TEAMS = {
    "L'hydre de la petite Creuse": {
        "DamienW": "Skaven", "Dunkhan": "Ogor Mawtribes", "GabrielSab": "Slaves to Darkness",
        "Kazerole": "Sylvaneth", "Seraph": "Disciples of Tzeentch", "Zieg": "Stormcast Eternals"},
    "La Tour du Cygor": {
        "Fabien": "Stormcast Eternals", "Karrman": "Ossiarch Bonereapers", "Kross": "Seraphon",
        "SGO": "Soulblight Gravelords", "TyraNounours": "Lumineth Realm-lords", "Waarde": "Ogor Mawtribes"},
    "Le Bastion du Wargame": {
        "Von glutten": "Flesh-eater Courts", "microFlow": "Idoneth Deepkin", "cynwall": "Skaven",
        "Gex": "Slaves to Darkness", "Darkane": "Lumineth Realm-lords", "Gravity": "Ogor Mawtribes"},
    "Limoges Wargame": {
        "Cromba": "Seraphon", "WereMonkey": "Ogor Mawtribes", "Antoine": "Blades of Khorne",
        "Darkjawz": "Ironjawz", "Thiradil": "Stormcast Eternals", "Skarbrand": "Daughters of Khaine"},
    "Melusior": {
        "Hibou_2": "Skaven", "Martoni": "Kruleboyz", "Shadow": "Slaves to Darkness",
        "Sharowkyn": "Ogor Mawtribes", "SoDarkSnow": "Flesh-eater Courts", "Totosai": "Lumineth Realm-lords"},
    "Méta des Boiteux": {
        "Moctezuma": "Sons of Behemat", "Brunehildr": "Daughters of Khaine", "T-rence": "Cities of Sigmar",
        "Syffe": "Nighthaunt", "Aeorl": "Hedonites of Slaanesh", "Lautre": "Blades of Khorne"},
    "Team Maelstrom": {
        "Otter": "Kharadron Overlords", "Kalirath": "Cities of Sigmar", "Draz": "Skaven",
        "Yaratchiku": "Daughters of Khaine", "Juval": "Idoneth Deepkin", "Zoko": "Sylvaneth"},
    "Torgnoles et Traditions": {
        "Hyrielle": "Idoneth Deepkin", "Cheveux": "Nighthaunt", "Joe Rampage": "Stormcast Eternals",
        "POP": "Maggotkin of Nurgle", "Arakzadhum": "Ironjawz", "KnoKosS": "Ogor Mawtribes"},
    "Vae Victis Vernou": {
        "Cartoone": "Seraphon", "Haldahir": "Blades of Khorne", "Laytorne": "Stormcast Eternals",
        "MuaD_Dib": "Ossiarch Bonereapers", "Pierrodactyl": "Sylvaneth", "Razemme": "Daughters of Khaine"},
}
for _team, _players in _TEAMS.items():
    for _p, _f in _players.items():
        PLAYERS[_p] = (_team, _f)

SCHEDULE = {
    "Melusior": ["Limoges Wargame", None, "Méta des Boiteux", "L'hydre de la petite Creuse",
                 "Torgnoles et Traditions"],
    "Vae Victis Vernou": ["Le Bastion du Wargame", "Team Maelstrom", "Torgnoles et Traditions",
                          "La Tour du Cygor", "Limoges Wargame"],
}
OUTPUT = {"Melusior": "Matchups/Matchups Melusior.md", "Vae Victis Vernou": "Matchups/Matchups Vae Victis.md"}

# Nom dans l'export de liste -> nom en base, quand ils diffèrent.
ALIASES = {
    "Kruleboyz Monsta-killaz": "Monsta-killaz",
    "Kurnoth Hunters with Kurnoth Greatswords": "Kurnoth Hunters with Greatswords",
    "Gelgus Pust": "Gelgus Pust, the Prince of Sores",
    "Tzaangor Enlightened on Foot": "Tzaangor Enlightened",  # approximation : profil monté
}
# Compagnons gratuits pris avec une unité payante : unités séparées en base, à 0 pt. Le coût du
# parent est réparti sur le groupe au prorata des PV (sinon tout le prix pèse sur le seul parent).
COMPANIONS = {
    "Morathi-Khaine": ["The Shadow Queen"],
    "Neave Blacktalon": ["Lorai, Child of the Abyss", "Neave’s Companions"],
    "Gunnar Brand": ["Singri Brand", "The Oathsworn Kin"],
}
# Règles lues dans le battletome quand le texte Wahapedia est tronqué, avec le choix fait par
# le joueur. « ward » : unités qui reçoivent cette Protection (nom en base -> valeur) ;
# « aptitudes » : (famille, poids, description) ajoutées au profil d'aptitudes de la liste.
BT_RULES = {
    "Totosai": {
        # Inscription de Rune (BT Lumineth, faction_rules_fr.json) : Totosai n'inscrit que des
        # Alaithi, la Rune de la Montagne. Chaque exemplaire donne Protection (5+) à 2 unités et
        # les exemplaires s'additionnent : 2 cibles au round 1, ses 4 monstres de la montagne dès
        # le round 2. Aucune autre rune inscrite, donc aucun effet amélioré.
        "ward": {"Avalenor, The Stoneheart King": 5, "Alarith Spirit of the Mountain": 5},
        # With the Force of a Landslide (+1 Attaque aux marteaux par Alaithi inscrite) + Call of the
        # Mountains (Avalenor : +1 instance aux ALARITH entièrement à 12") : +2 au round 1 -> +6 au
        # round 5 avec une rune par round, +4 de moyenne retenue par l'utilisateur (2026-11-18).
        "melee_attacks": {"Avalenor, The Stoneheart King": 4, "Alarith Spirit of the Mountain": 4},
        "aptitudes": [("protection", 2.0, "Alaithi, la Rune de la Montagne (BT, Inscription de Rune) : "
                                         "Protection (5+) sur Avalenor et les 3 Spirits of the Mountain")],
    },
    "Shadow": {
        # Pledged to Khorne (+1 Attaque aux armes de mêlée, trait de bataille Slaves to Darkness) :
        # le gros pack de Varanguard prend la marque au round 1 (Pledge to Chaos, une marque par
        # round) et la garde toute la partie ; les Chaos Knights l'ont dès le début (Bannière de Rage).
        # Clé = libellé de l'entrée dans la liste (« R » = renforcée).
        "melee_attacks": {"Varanguard R": 1, "Chaos Knights": 1},
        # Pledged to Nurgle (trait de bataille) sur un Prince déjà Ward (6+) : Ward (5+).
        "ward": {"Daemon Prince": 5},
        # Darkflame Pendant (artefact) : les armes qui ciblent le Prince ont Damage 1 maximum
        # (Crit (Mortal) compris, il suit la caractéristique Damage ; pas les aptitudes directes).
        "damage_cap": {"Daemon Prince": 1},
    },
    "Haldahir": {
        # Trempés de Sang (trait de bataille Blades of Khorne) : à chaque déverrouillage d'une
        # aptitude de Dîme (une fois par tour), une unité garde pour la bataille, sur ses armes
        # Soif de Sang (Blood-hungry) : Crit (Mortel) si BLOODBOUND, +1 Perforation si DÉMON non
        # Monstre. Actif dès le round 2 (validé par l'utilisateur, 2026-11-19), compté plein comme
        # la marque de Shadow. Cibles prioritaires du joueur : Claws, puis un pack de Bloodletters.
        # Valeur = (effet, nombre d'entrées de ce libellé à modifier, dans l'ordre de la liste).
        "blood_drenched": {"Claws of Karanak R": ("crit_mortal", 1), "Bloodletters R": ("rend", 1)},
        # Commandant des Tyrans (Bloodthirster, une fois par tour, cible visible sans portée) : +1 A
        # en mêlée sur le même pack de Bloodletters, utilisé à chaque tour selon l'utilisateur
        # (au moins jusqu'au T3-T4) ; compté plein. (bonus, nombre d'entrées de ce libellé).
        "melee_attacks": {"Bloodletters R": (1, 1)},
    },
}

# Lignes qui ressemblent à une unité mais n'en sont pas (décor de faction, formation).
NOT_UNITS = {"Charnel Throne", "Akhelian Beastmasters", "Aspect of Heartwood"}

_UNIT_RE = re.compile(r"^(?:(?P<aqshy>Scourge of Aqshy:\s*|SoA\s+))?(?:\d+x\s+)?(?P<name>.+?)\s*\((?P<pts>\d+)(?:\s*pts)?\)")
_SKIP_PREFIXES = ("Manifestation Lore", "Spell Lore", "Prayer Lore", "Faction Terrain", "Battle Tactic",
                  "General", "Regiment", "Drops", "Points", "Grand Alliance", "Faction:", "Formation:",
                  "•", "~", "-", "===", "Wounds")


@dataclass
class Entry:
    unit: object
    models: int
    reinforced: bool
    points: int
    label: str
    damage_cap: int | None = None   # Damage max des armes qui ciblent cette unité (BT_RULES)
    extra_direct: list = field(default_factory=list)  # mortelles venant de règles d'armée (ex. Eat 'Em Alive)
    ignore_first: bool = False      # « ignore le 1er dégât alloué à chaque phase » (ex. Stone Skeleton)

    @property
    def hp(self) -> int:
        return self.unit.health * self.models


@dataclass
class ArmyList:
    player: str
    team: str
    faction: str
    entries: list[Entry] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)    # en-tête de la liste (formation, domaines)
    options: list[str] = field(default_factory=list)   # améliorations (« • Nom »)
    prof: object = None        # l3_aptitudes.Profile
    mob: float = 0.0           # indice de mobilité (z-score sur les 54 listes)
    apt: float = 0.0           # indice d'aptitudes (z-score sur les 54 listes)
    plan: int = 2              # note de plan de jeu (0-3), combos/<équipe>.json

    @property
    def points(self) -> int:
        return sum(e.points for e in self.entries)

    @property
    def missing_points(self) -> int:
        return sum(int(re.search(r"\((\d+)\)$", u)[1]) for u in self.unmatched)

    @property
    def control(self) -> int:
        return sum(e.unit.control * e.models for e in self.entries)

    @property
    def hp(self) -> int:
        return sum(e.hp for e in self.entries)

    @property
    def n_units(self) -> int:
        return len(self.entries)

    def casters(self, kind: str) -> int:
        return sum(1 for e in self.entries if any(k.startswith(kind) for k in e.unit.keywords))

    @property
    def monsters(self) -> int:
        return sum(1 for e in self.entries if "MONSTER" in e.unit.keywords)

    @property
    def avg_move(self) -> float:
        pts = self.points or 1
        return sum(e.unit.move * e.points for e in self.entries) / pts

    @property
    def avg_save(self) -> float:
        hp = self.hp or 1
        return sum(e.unit.save * e.hp for e in self.entries) / hp


def _apply_blood_drenched(al: "ArmyList") -> None:
    """Trempés de Sang (BT_RULES « blood_drenched ») sur les armes Soif de Sang des entrées choisies."""
    left = {label: n for label, (_, n) in BT_RULES.get(al.player, {}).get("blood_drenched", {}).items()}
    for e in al.entries:
        if not left.get(e.label):
            continue
        left[e.label] -= 1
        effect = BT_RULES[al.player]["blood_drenched"][e.label][0]

        def drench(w):
            if "Blood-hungry" not in (w.abilities or ""):
                return w
            if effect == "rend":
                return dataclasses.replace(w, rend=w.rend + 1)
            return dataclasses.replace(w, abilities=re.sub(r"Crit \([^)]*\)", "Crit (Mortal)", w.abilities))
        e.unit = dataclasses.replace(e.unit, weapons=[drench(w) for w in e.unit.weapons])


def _apply_pack_hunters(al: "ArmyList") -> None:
    """Chasseurs en Meute (Claws of Karanak) : critique sur 5+ en mêlée si la liste a Karanak ou des
    Flesh Hounds (supposés entièrement à 12", la liste est construite pour). Tag lu par combat.py."""
    names = {e.unit.name for e in al.entries}
    if not names & {"Karanak", "Flesh Hounds"}:
        return
    for e in al.entries:
        if e.unit.name == "Claws of Karanak":
            e.unit = dataclasses.replace(e.unit, weapons=[
                dataclasses.replace(w, abilities=f"{w.abilities}, Crits on 5+") if w.kind == "melee" else w
                for w in e.unit.weapons])


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_lists(pdf: Path) -> dict[str, list[str]]:
    """Joueur -> lignes de sa liste (à partir de la page 3 du PDF)."""
    reader = PdfReader(pdf)
    lines: list[str] = []
    for page in reader.pages[2:]:
        lines += [ln.strip() for ln in (page.extract_text() or "").splitlines()]
    blocks: dict[str, list[str]] = {}
    current = None
    for ln in lines:
        if ln in PLAYERS:
            current = ln
            blocks[current] = []
        elif current:
            blocks[current].append(ln)
    return blocks


def build_lists(con) -> dict[str, ArmyList]:
    armies = {name: aid for aid, name in con.execute("select id, name from army").fetchall()}
    by_army = load_all_units_with_weapons(con)
    all_units = [u for units in by_army.values() for u in units]
    lists: dict[str, ArmyList] = {}
    for player, lines in parse_lists(PDF).items():
        team, faction = PLAYERS[player]
        al = ArmyList(player, team, faction)
        cut = next((k for k, ln in enumerate(lines) if ln.startswith("General's Regiment")), len(lines))
        al.header = lines[:cut]
        al.options = [ln.lstrip("•~ ").strip() for ln in lines if ln.startswith("•")
                      and ln.lstrip("•~ ").strip() not in ("General", "Reinforced")]
        pool = by_army.get(armies[faction], [])
        index = {_norm(u.name): u for u in pool}
        last: Entry | None = None
        for ln in lines:
            if last and re.search(r"\bReinforced\b", ln) and not _UNIT_RE.match(ln.lstrip("•~ ")):
                last.reinforced, last.models = True, last.unit.models * 2
                last.label += " R"
                continue
            if ln.startswith(_SKIP_PREFIXES) and not ln.startswith("Scourge"):
                continue
            m = _UNIT_RE.match(ln)
            if not m:
                continue
            pts = int(m["pts"])
            raw = re.sub(r"\s*\((Scourge of (Aqshy|Ghyran))\)", "", m["name"]).strip()
            aqshy = bool(m["aqshy"]) or "(Scourge of Aqshy)" in m["name"]
            if pts == 0 or raw in NOT_UNITS:
                continue
            raw = ALIASES.get(raw, raw)
            unit = None
            if aqshy:
                unit = index.get(_norm("Scourge of Aqshy " + raw))
            unit = unit or index.get(_norm(raw))
            if unit is None:  # unité d'une autre faction (ex. Régiment de Renom)
                unit = next((u for u in all_units if _norm(u.name) == _norm(raw)), None)
            if unit is None:
                al.unmatched.append(f"{raw} ({pts})")
                last = None
                continue
            reinforced = bool(re.search(r"\bReinforced\b", ln))
            last = Entry(unit, unit.models * (2 if reinforced else 1), reinforced, pts,
                         raw + (" R" if reinforced else ""))
            al.entries.append(last)
        _add_companions(al, all_units)
        used: dict[str, int] = {}
        for e in al.entries:
            bonus = BT_RULES.get(player, {}).get("melee_attacks", {}).get(e.label)
            if isinstance(bonus, tuple):  # (bonus, nombre d'entrées de ce libellé, dans l'ordre)
                used[e.label] = used.get(e.label, 0) + 1
                bonus = bonus[0] if used[e.label] <= bonus[1] else None
            if bonus:
                e.unit = dataclasses.replace(e.unit, weapons=[
                    dataclasses.replace(w, attacks=w.attacks + bonus) if w.kind == "melee" else w
                    for w in e.unit.weapons])
            ward = BT_RULES.get(player, {}).get("ward", {}).get(e.unit.name)
            if ward and (not e.unit.ward or e.unit.ward > ward):
                e.unit = dataclasses.replace(e.unit, ward=ward)
            e.damage_cap = BT_RULES.get(player, {}).get("damage_cap", {}).get(e.label)
        _apply_blood_drenched(al)
        _apply_pack_hunters(al)
        army_direct_abilities(al)
        for e in al.entries:
            e.ignore_first = bool(unit_ability_names(e.unit) & ignore_first_names())
        lists[player] = al
    rate_lists(lists)
    return lists


# --- Mobilité et aptitudes (textes Wahapedia, voir l3/aptitudes.py) ------------------------

APT_FAMILIES = ("soins", "protection", "buff", "débuff", "objectifs")


def _z(values: dict[str, float]) -> dict[str, float]:
    vals = list(values.values())
    mu = sum(vals) / len(vals)
    sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
    return {k: (v - mu) / sd for k, v in values.items()}


def rate_lists(lists: dict[str, ArmyList]) -> None:
    """Calcule pour chaque liste ses indices de mobilité et d'aptitudes, relatifs aux 54 listes.

    Racine carrée par famille : la 5e aura de +1 pour toucher apporte moins que la 1re.
    """
    lib = apt.Library()
    plans = {}
    for path in (FOLDER / "Données" / "combos").glob("*.json"):
        for player, data in json.loads(path.read_text(encoding="utf-8")).items():
            if not player.startswith("_") and "note_plan" in data:
                plans[player] = data["note_plan"]
    for al in lists.values():
        al.prof = apt.profile(lib, al, al.header, al.options)
        for fam, weight, desc in BT_RULES.get(al.player, {}).get("aptitudes", []):
            al.prof.score[fam] += weight
            al.prof.detail[fam].append(desc)
        al.plan = plans.get(al.player, 2)
    move = _z({p: al.avg_move for p, al in lists.items()})
    fly = _z({p: al.prof.fly_share for p, al in lists.items()})
    mob = _z({p: al.prof.score["mobilité"] ** 0.5 for p, al in lists.items()})
    for p, al in lists.items():
        al.mob = (move[p] + fly[p] + mob[p]) / 3
    magic = {p: (1.5 * al.prof.wizard_levels + al.prof.priest_levels + al.prof.score["magie"]) ** 0.5
             for p, al in lists.items()}
    aptz = _z({p: sum(al.prof.score[f] ** 0.5 for f in APT_FAMILIES) + magic[p] for p, al in lists.items()})
    for p, al in lists.items():
        al.apt = aptz[p]


def _add_companions(al: ArmyList, all_units: list) -> None:
    for parent in list(al.entries):
        names = COMPANIONS.get(parent.unit.name)
        if not names:
            continue
        group = [parent]
        for name in names:
            unit = next((u for u in all_units if _norm(u.name) == _norm(name)), None)
            if unit is not None:
                entry = Entry(unit, unit.models, False, 0, f"{unit.name} (avec {parent.label})")
                al.entries.append(entry)
                group.append(entry)
        total_pts, total_hp = parent.points, sum(e.hp for e in group)
        for e in group:
            e.points = round(total_pts * e.hp / total_hp)


_MODS = CombatModifiers(attacker_charged=True)
_MODS_STILL = CombatModifiers(attacker_charged=False)

# Qui charge ? Un combat se fait avec ou sans bonus de charge selon l'écart de mobilité entre les
# deux unités : allonge = mouvement + 1" si elle VOLE + 1,5" par point d'indice de mobilité de
# sa liste + amélioration du jet de charge (l3_aptitudes.charge_inches : +N, 3 dés, relance ;
# bonus d'armée plafonné à 3"). Probabilité de charger bornée à [0,15 ; 0,85] :
# même la liste la plus lente finit par charger quelque chose, et la plus rapide se fait parfois
# prendre de vitesse.
CHARGE_SCALE = 4.0
CHARGE_BOUNDS = (0.15, 0.85)


def threat(e: "Entry", al: "ArmyList") -> float:
    """Allonge de charge : mouvement, vol, outils de la liste, et jet de charge amélioré (au-delà de 2D6)."""
    charge = al.prof.charge_unit.get(e.unit.name, 0.0) + min(al.prof.charge_army, 3.0)
    return e.unit.move + (1.0 if "FLY" in e.unit.keywords else 0.0) + 1.5 * al.mob + charge


def charge_prob(ea: "Entry", a: "ArmyList", eb: "Entry", b: "ArmyList") -> float:
    p = 0.5 + 0.5 * math.tanh((threat(ea, a) - threat(eb, b)) / CHARGE_SCALE)
    return min(CHARGE_BOUNDS[1], max(CHARGE_BOUNDS[0], p))


# --- Aptitudes à dégâts directs (texte Wahapedia) -----------------------------------------

@dataclass
class DirectAbility:
    name: str
    amount: float               # dégâts mortels attendus par utilisation, cible valide
    per_target_model: bool      # « roll a dice for each model in the target »
    per_own_model: bool         # « ... for each model in this unit »
    target_keyword: str | None  # « pick an enemy MONSTER ... » -> MONSTER
    frequency: float            # utilisations par round
    needs_charge: bool = False  # « if this unit charged this turn/phase » : nul quand l'unité n'a pas chargé
    vs_keyword: tuple[str, float] | None = None  # (mot-clé, montant) : option meilleure contre ce mot-clé


def _dice_mean(token: str) -> float:
    token = token.upper()
    return {"D3": 2.0, "D6": 3.5, "2D3": 4.0, "2D6": 7.0}.get(token, float(token) if token.isdigit() else 0.0)


def _p_plus(x: int) -> float:
    return max(0.0, min(1.0, (7 - x) / 6))


def _p_2d6(x: int) -> float:
    return sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= x) / 36


def parse_direct_ability(name: str, condition: str, html: str) -> DirectAbility | None:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).replace("’", "'")
    if "mortal damage" not in text:
        return None
    low = text.lower()
    # Déclencheurs défensifs / conditionnels rares : on ne les compte pas comme dégâts infligés.
    if any(k in low for k in ("is slain", "is destroyed", "targets this unit", "save roll of 6",
                              "uses a move ability", "on this unit", "friendly unit")):
        return None
    effect = text.split("Effect:", 1)[-1]
    per_target = per_own = False
    amount = 0.0
    m_each = re.search(r"For each (\d)(?:-(\d))?\+?, inflict (D3|D6|\d+) mortal damage", effect)
    m_roll = re.search(r"Roll a (D3|dice)\b.{0,90}?On a (\d)\+, inflict an amount of mortal damage .{0,40}?equal to the roll", effect)
    m_on = re.search(r"On a (\d)\+, inflict (D3|D6|\d+) mortal damage", effect)
    m_flat = re.search(r"[Ii]nflict (D3|D6|2D3|\d+) mortal damage", effect)
    if m_each:
        lo = int(m_each[1])
        p = (int(m_each[2]) - lo + 1) / 6 if m_each[2] else _p_plus(lo)
        amount = p * _dice_mean(m_each[3])
        # Tranche supérieure éventuelle (« For each 6+, inflict D3 »).
        m6 = re.search(r"For each 6\+?, inflict (D3|D6|\d+) mortal damage", effect)
        if m_each[2] and m6:
            amount += _dice_mean(m6[1]) / 6
        n = re.search(r"[Rr]oll (\d+) dice", text)
        if "each model in the target" in low or "number of models in the target" in low:
            per_target = True
        elif "each model in this unit" in low or "number of models in this unit" in low:
            per_own = True
        elif n:
            amount *= int(n[1])
        elif "number of damage points" in low:
            amount *= 5
    elif m_roll:
        lo = int(m_roll[2])
        faces = 3 if m_roll[1] == "D3" else 6
        amount = sum(k for k in range(lo, faces + 1)) / faces
    elif m_on:
        amount = _p_plus(int(m_on[1])) * _dice_mean(m_on[2])
    elif m_flat:
        amount = _dice_mean(m_flat[1])
    if amount <= 0:
        return None
    cast = re.search(r"casting roll of 2D6.*?On a (\d+)\+", text)
    if cast:
        amount *= _p_2d6(int(cast[1])) / max(_p_plus(int(m_on[1])) if m_on else 1.0, 1e-9) if m_on else _p_2d6(int(cast[1]))
    cond = condition.lower()
    freq = 1.0
    if "once per battle" in cond:
        freq = 0.25
    elif "reaction" in cond:
        freq = 0.5
    elif "any " in cond or "end of any turn" in cond:
        freq = 1.3
    if "pick 1 of the following" in low:
        freq *= 0.5
    # Mortelles d'impact (« if this unit charged this turn ») : comptées seulement dans le cas
    # « a chargé » d'`unit_damage` (pondéré par qui charge), une fois par round au plus.
    needs_charge = bool(re.search(r"charged this (?:turn|phase)", text))
    if needs_charge and "once per battle" not in cond:
        freq = min(freq, 1.0)
    # Restriction de cible : seulement si elle figure dans l'Annonce (sinon, c'est souvent une option parmi d'autres).
    kw = re.search(r"[Pp]ick an enemy ([A-Z][A-Z ]+?) (?:unit|in combat|within|that)", text.split("Effect:", 1)[0])
    keyword = kw[1].strip() if kw and kw[1].strip() not in ("UNIT",) else None
    return DirectAbility(name, min(amount, 8.0), per_target, per_own, keyword, freq, needs_charge)


def load_direct_abilities() -> dict[str, list[DirectAbility]]:
    """Nom de warscroll normalisé -> aptitudes à dégâts directs."""
    csv.field_size_limit(10**8)
    with open(WAHAPEDIA / "Warscrolls.csv", encoding="utf-8-sig") as fh:
        names = {r["id"]: r["name"] for r in csv.DictReader(fh, delimiter="|")}
    out: dict[str, dict[str, DirectAbility]] = {}
    with open(WAHAPEDIA / "Warscrolls_abilities.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            name = names.get(r["warscroll_id"])
            if not name:
                continue
            ab = parse_direct_ability(r["name"], r.get("condition") or "", r.get("description") or "")
            if ab:
                out.setdefault(_norm(name), {})[ab.name] = ab
    for abilities in out.values():
        for key, fix in DIRECT_OVERRIDES.items():
            if key in abilities:
                abilities[key] = dataclasses.replace(abilities[key], **fix)
    return {k: list(v.values()) for k, v in out.items()}


# Lectures corrigées à la main (texte vérifié) quand la regex générique se trompe.
DIRECT_OVERRIDES = {
    # Kragnos : le joueur choisit l'option (pas de moyenne des deux). D6 par ennemi à 1" (2+ ->
    # le jet) ou, contre un MONSTRE, produit des 2D6 sauf sur 7 : (441 − 56) / 36 = 10,7.
    "Rampaging Destruction": {"amount": 10 / 3, "frequency": 1.0, "vs_keyword": ("MONSTER", 385 / 36)},
    # Annihilators : seulement le tour où l'unité arrive par Scions of the Storm, donc une fois
    # par partie en pratique (validé par l'utilisateur, 2026-11-20) — pas à chaque round.
    "Blazing Impact": {"frequency": 0.25},
}


def army_direct_abilities(al: ArmyList) -> None:
    """Mortelles des traits de bataille, portées par les entrées concernées (`Entry.extra_direct`)."""
    if al.faction != "Ogor Mawtribes":
        return
    ogors = [e for e in al.entries if "OGOR" in e.unit.keywords]
    # Eat 'Em Alive (fin de n'importe quel tour) : D3 mortelles par unité d'Ogors qui a combattu.
    for e in ogors:
        e.extra_direct.append(DirectAbility("Eat ’Em Alive", 2.0, False, False, None, 1.3))
    # Bull Charge (une fois par tour, armée) : un dé par figurine à 3" de la cible, 1 mortelle sur
    # 3+ (+1 au jet pour les GUTBUSTERS). Interdit à l'unité qui a utilisé son propre Saccage : on
    # la donne à la meilleure unité qui n'a pas d'aptitude d'impact à elle.
    best, value = None, 0.0
    for e in ogors:
        if any(ab.needs_charge for ab in direct_abilities(e.unit)):
            continue
        v = min(e.models, 8) * (5 / 6 if "GUTBUSTERS" in e.unit.keywords else 4 / 6)
        if v > value:
            best, value = e, v
    if best:
        best.extra_direct.append(DirectAbility("Bull Charge", value, False, False, None, 1.0, True))


_DIRECT: dict[str, list[DirectAbility]] = {}


def direct_abilities(unit) -> list[DirectAbility]:
    key = _norm(unit.name)
    return _DIRECT.get(key) or _DIRECT.get(key.replace("scourge of aqshy ", "", 1)) or []


def _ward_fail(defender) -> float:
    return 1 - _p_plus(defender.ward) if defender.ward else 1.0


@dataclass
class Attrition:
    index: float                 # part (en points) de l'armée adverse retirée par round
    best: list[tuple[str, float]]  # meilleures unités : (nom, points retirés par round)
    ranged_share: float
    direct_share: float
    direct_names: list[str]
    charge_share: float = 0.5    # probabilité moyenne que nos unités aient chargé leurs combats


def unit_damage(attacker, models: int, defender, charged: bool = True, extra_direct=()) -> tuple[float, float, float]:
    """(dégâts totaux, dont tir, dont aptitudes directes) d'une unité en un round.

    Les modes d'une même arme (« Arme: Mode A » / « Arme: Mode B ») sont des alternatives :
    on garde le meilleur, au lieu de les additionner comme le fait `expected_unit_damage`.
    """
    mods = _MODS if charged else _MODS_STILL
    best: dict[tuple, tuple[float, str, object, int]] = {}
    for i, (w, c) in enumerate(zip(attacker.weapons, effective_counts(attacker, models), strict=True)):
        key = (w.kind, w.name.split(":")[0].strip()) if ":" in w.name else (w.kind, i)
        dmg = expected_weapon_damage(w, c, defender, mods)
        if dmg > best.get(key, (-1.0, "", None, 0))[0]:
            best[key] = (dmg, w.kind, w, c)
    mean_dmg = sum(b[0] for b in best.values())
    # Fiabilité : on mélange la moyenne et le plancher « 2 fois sur 3 » de la distribution exacte.
    # Un profil à peu d'attaques et gros dégâts (variance forte) vaut moins que sa moyenne.
    pmf = [1.0]
    for _, _, w, c in best.values():
        pmf = convolve(pmf, weapon_damage_distribution(w, c, defender, mods))
    floor = distribution_floor(pmf, RELIABILITY_COVERAGE)
    factor = (1 - RELIABILITY_WEIGHT) + RELIABILITY_WEIGHT * min(1.0, floor / mean_dmg) if mean_dmg else 1.0
    weapons_dmg = mean_dmg * factor
    ranged = sum(b[0] for b in best.values() if b[1] == "ranged") * factor
    # Explosion de Fureur : FURY_ATTACKS attaques en plus avec le meilleur profil, par round.
    per_attack = max((expected_weapon_damage(w, 1, defender, mods) / max(w.attacks, 1)
                      for w in attacker.weapons), default=0.0)
    fury = FURY_ATTACKS * per_attack
    # Aptitudes à dégâts directs (dégâts mortels : pas de sauvegarde, la ward s'applique).
    direct = 0.0
    for ab in [*direct_abilities(attacker), *extra_direct]:
        if ab.target_keyword and ab.target_keyword not in defender.keywords:
            continue
        if ab.needs_charge and not charged:
            continue
        amount = ab.amount
        if ab.vs_keyword and ab.vs_keyword[0] in defender.keywords:
            amount = max(amount, ab.vs_keyword[1])
        if ab.per_target_model:
            amount *= min(defender.models, 10)
        elif ab.per_own_model:
            amount *= min(models, 10)
        direct += amount * ab.frequency * _ward_fail(defender)
    return weapons_dmg + fury + direct, ranged, direct


def _profile_sig(unit) -> int:
    """Signature du profil offensif : distingue une unité modifiée par BT_RULES (même id en base)."""
    return hash(tuple((w.attacks, w.rend, w.abilities) for w in unit.weapons))


def _damage(ea: Entry, eb: Entry, charged: bool, cache: dict) -> tuple[float, float, float]:
    """`unit_damage` de ea sur eb, mis en cache (et plafonné par le Damage max de eb, s'il en a un)."""
    key = (ea.unit.id, ea.models, _profile_sig(ea.unit), tuple(ab.name for ab in ea.extra_direct),
           eb.unit.id, eb.unit.ward, eb.damage_cap, eb.ignore_first, charged)
    if key not in cache:
        attacker = ea.unit
        if eb.damage_cap:  # ex. Darkflame Pendant : Damage plafonné pour toutes les armes qui le ciblent
            attacker = dataclasses.replace(attacker, weapons=[
                dataclasses.replace(w, damage=min(w.damage, eb.damage_cap)) for w in attacker.weapons])
        dmg, ranged, direct = unit_damage(attacker, ea.models, eb.unit, charged, ea.extra_direct)
        if eb.ignore_first and dmg:
            # 1 dégât ignoré par phase où l'attaquant blesse : tir, mêlée, mortelles d'aptitude
            # (impact en phase de charge, fin de tour…), sans descendre sous 0 dans chaque phase.
            melee = dmg - ranged - direct
            ranged, direct, melee = (max(0.0, x - 1) if x > 0 else 0.0 for x in (ranged, direct, melee))
            dmg = ranged + direct + melee
        cache[key] = (dmg, ranged, direct)
    return cache[key]


def pair_damage(ea: Entry, a: ArmyList, eb: Entry, b: ArmyList, cache: dict) -> tuple[float, float, float, float]:
    """(dégâts, dont tir, dont aptitudes directes, probabilité que ea ait chargé) de ea sur eb,
    pondérés entre « a chargé » et « a été chargé » selon l'écart de mobilité."""
    out = [_damage(ea, eb, charged, cache) for charged in (True, False)]
    p = charge_prob(ea, a, eb, b)
    return tuple(p * x + (1 - p) * y for x, y in zip(*out)) + (p,)


# --- Double activation en mêlée (« can use 2 FIGHT abilities this phase ») -------------------
# Le 2e combat d'une unité qui a chargé vise une 2e cible (allonge ~6", 3" de rapprochement + 3"
# de portée), qui n'était pas en mêlée et ne riposte pas entre les deux : c'est un report de
# surplus sur une autre cible, que le plafond « dégâts ≤ cible tuée » d'`attrition` ne compte pas.
# Le round d'`attrition` est une moyenne sur une cible tirée au prorata des points : un 2e combat
# vaut donc la part mêlée de l'unité, multipliée par la fréquence d'usage par round (5 rounds).
# Le Frappe en dernier qui suit le 1er combat est ignoré (la 2e cible ne riposte pas).
# Validé par l'utilisateur le 2026-11-18 (instantanés avant-double-combat / double-combat).
DOUBLE_FIGHT = True
# Aptitude sur l'unité elle-même : nom -> (fréquence par round, 2e combat contre un HÉROS seulement).
DOUBLE_FIGHT_SELF = {
    "Relentless Killers": (0.2, False),      # Varanguard, une fois par bataille (par bloc)
    "Heralds of Ruination": (0.2, False),    # Chaos Chosen, une fois par bataille
    "Storm of Blades": (0.2, False),         # Ikon of the Storm, une fois par bataille
    "Excitable Followers": (0.7, False),     # Mancrusher, entièrement à 12" d'un HÉROS Sons of Behemat
    "Carve a Path To Glory": (0.5, True),    # Gunnar Brand, en combat avec un HÉROS ennemi
}
# Aptitude donnée à une autre unité amie : nom -> (fréquence par round, mots-clés exigés de la
# cible, au moins un des groupes complet). On donne le doublé à la meilleure unité éligible.
DOUBLE_FIGHT_GRANT = {
    "Vanhel’s Danse Macabre": (0.7, [{"DEATHRATTLE"}, {"DEADWALKERS"}]),           # Necromancer, à 12"
    "Supreme Lord of the Bonereaper Legions": (0.3, [{"OSSIARCH BONEREAPERS"}]),  # Katakros, coûte la Santé en points RD
    "The Death Frenzy": (0.6, [{"SKAVEN", "INFANTRY"}]),                           # Vizzik, jet de chant
    "Front-Line Commander": (0.14, [{"SIGMARITE", "INFANTRY"}, {"SIGMARITE", "MONSTER"}]),  # Marshal, 1/bataille, sous ordres
}
_UNIT_ABILITY_NAMES: dict[str, set[str]] | None = None


def unit_ability_names(unit) -> set[str]:
    """Noms des aptitudes de la charte Wahapedia de l'unité (toutes ses versions)."""
    global _UNIT_ABILITY_NAMES
    if _UNIT_ABILITY_NAMES is None:
        csv.field_size_limit(10**8)
        with open(WAHAPEDIA / "Warscrolls.csv", encoding="utf-8-sig") as fh:
            names = {r["id"]: _norm(r["name"]) for r in csv.DictReader(fh, delimiter="|")}
        _UNIT_ABILITY_NAMES = {}
        with open(WAHAPEDIA / "Warscrolls_abilities.csv", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh, delimiter="|"):
                if r["warscroll_id"] in names:
                    _UNIT_ABILITY_NAMES.setdefault(names[r["warscroll_id"]], set()).add(r["name"].strip())
    key = _norm(unit.name)
    return _UNIT_ABILITY_NAMES.get(key) or _UNIT_ABILITY_NAMES.get(key.replace("scourge of aqshy ", "", 1)) or set()


_IGNORE_FIRST: set[str] | None = None


def ignore_first_names() -> set[str]:
    """Aptitudes « Ignore the first damage point that would be allocated to this unit in each phase »."""
    global _IGNORE_FIRST
    if _IGNORE_FIRST is None:
        csv.field_size_limit(10**8)
        with open(WAHAPEDIA / "Warscrolls_abilities.csv", encoding="utf-8-sig") as fh:
            _IGNORE_FIRST = {r["name"].strip() for r in csv.DictReader(fh, delimiter="|")
                             if re.search(r"Ignore the first damage point that would be allocated to this unit in each phase",
                                          re.sub(r"<[^>]+>", "", r["description"]))}
    return _IGNORE_FIRST


def double_fights(a: ArmyList, b: ArmyList, melee: dict[str, float], melee_hero: dict[str, float]
                  ) -> list[tuple[str, float, str]]:
    """(libellé de l'unité, valeur ajoutée par round, aptitude) des 2es combats de la liste a."""
    out = []
    if not DOUBLE_FIGHT:
        return out
    has_sob_hero = any({"HERO", "SONS OF BEHEMAT"} <= e.unit.keywords for e in a.entries)
    for e in a.entries:
        for ab in unit_ability_names(e.unit):
            if ab in DOUBLE_FIGHT_SELF:
                freq, hero_only = DOUBLE_FIGHT_SELF[ab]
                if ab == "Excitable Followers" and not has_sob_hero:
                    continue
                value = melee_hero[e.label] if hero_only else melee[e.label]
                if value > 0:
                    out.append((e.label, freq * value, ab))
            elif ab in DOUBLE_FIGHT_GRANT:
                freq, groups = DOUBLE_FIGHT_GRANT[ab]
                ok = [t for t in a.entries if t is not e and any(g <= t.unit.keywords for g in groups)]
                if ok:
                    best = max(ok, key=lambda t: melee[t.label])
                    if melee[best.label] > 0:
                        out.append((best.label, freq * melee[best.label], f"{ab} ({e.label})"))
    return out


def attrition(a: ArmyList, b: ArmyList, cache: dict) -> Attrition:
    total_b = b.points or 1
    per_unit: list[tuple[str, float]] = []
    ranged_val = direct_val = 0.0
    p_sum = p_w = 0.0
    melee: dict[str, float] = {}
    melee_hero: dict[str, float] = {}
    hero_share = sum(eb.points for eb in b.entries if "HERO" in eb.unit.keywords) / total_b
    for ea in a.entries:
        val = m_val = m_hero = 0.0
        for eb in b.entries:
            dmg, ranged, direct, p = pair_damage(ea, a, eb, b, cache)
            p_sum += p * eb.points
            p_w += eb.points
            frac = min(dmg / max(eb.hp, 1), 1.0)
            contrib = frac * eb.points * (eb.points / total_b)
            val += contrib
            ranged_val += contrib * (ranged / dmg if dmg else 0.0)
            direct_val += contrib * (direct / dmg if dmg else 0.0)
            # 2e combat : l'unité a chargé, ses bonus de charge (ex. Charge (+1 Damage) des
            # Varanguard) valent pour les deux activations -> dégâts « chargé », pas le mélange.
            c_dmg, c_ranged, c_direct = _damage(ea, eb, True, cache)
            c_frac = min(c_dmg / max(eb.hp, 1), 1.0)
            m = c_frac * eb.points * (eb.points / total_b) * (1 - (c_ranged + c_direct) / c_dmg) if c_dmg else 0.0
            m_val += m
            if "HERO" in eb.unit.keywords:
                m_hero += m
        per_unit.append((ea.label, val))
        melee[ea.label] = max(melee.get(ea.label, 0.0), m_val)
        melee_hero[ea.label] = max(melee_hero.get(ea.label, 0.0), m_hero / hero_share if hero_share else 0.0)
    for label, extra, _ in double_fights(a, b, melee, melee_hero):
        per_unit.append((label + " (2e combat)", extra))
    total = sum(v for _, v in per_unit)
    per_unit.sort(key=lambda x: -x[1])
    return Attrition(total / total_b, per_unit[:2], ranged_val / total if total else 0.0,
                     direct_val / total if total else 0.0,
                     sorted({ab.name for e in a.entries for ab in [*direct_abilities(e.unit), *e.extra_direct]}),
                     p_sum / p_w if p_w else 0.5)


def load_adjustments() -> dict:
    if ADJUSTMENTS.exists():
        return json.loads(ADJUSTMENTS.read_text(encoding="utf-8"))
    return {"listes": {}, "matchups": {}}


@dataclass
class Matchup:
    score: int
    combat: float
    board: float       # jeu de scénario : contrôle, activations, mobilité
    apt: float         # aptitudes et plan de jeu
    adj: list[tuple[float, str]]
    att_a: Attrition
    att_b: Attrition


def evaluate(a: ArmyList, b: ArmyList, adjustments: dict, cache: dict) -> Matchup:
    att_a, att_b = attrition(a, b, cache), attrition(b, a, cache)
    ratio = (att_a.index + 1e-6) / (att_b.index + 1e-6)
    combat = COMBAT_MAX * math.tanh(math.log(ratio) / 1.0)
    ctrl_ratio = (a.control + 1) / (b.control + 1)
    board = (2 * math.tanh(math.log(ctrl_ratio) / 0.9) + 1 * math.tanh((a.n_units - b.n_units) / 4)
             + 4 * math.tanh((a.mob - b.mob) / 1.5))
    aptitudes = 4 * math.tanh((a.apt - b.apt) / 1.5) + 1.2 * (a.plan - b.plan)
    adj: list[tuple[float, str]] = []
    for al, sign in ((a, 1), (b, -1)):
        if al.missing_points:
            # L'unité absente manque à l'attaque de sa liste : ~14 pts d'écart pour une armée entière.
            bonus = round(14 * al.missing_points / 2000 * 2) / 2
            adj.append((sign * bonus, f"{al.player} : {', '.join(al.unmatched)} absent de la base, "
                                      "compté au prorata de ses points"))
    for player, sign in ((a.player, 1), (b.player, -1)):
        for item in adjustments.get("listes", {}).get(player, []):
            adj.append((sign * item["bonus"], f"{player} : {item['raison']}"))
    for key, sign in ((f"{a.player}|{b.player}", 1), (f"{b.player}|{a.player}", -1)):
        for item in adjustments.get("matchups", {}).get(key, []):
            adj.append((sign * item["bonus"], item["raison"]))
    total = combat + board + aptitudes + sum(v for v, _ in adj)
    return Matchup(max(-20, min(20, round(total))), combat, board, aptitudes, adj, att_a, att_b)

# --- Profil offensif / défensif d'une liste ---------------------------------------------------

# Cible de référence pour pondérer les profils d'arme (sauvegarde 4+, sans ward ni mot-clé).
_REF = Unit(name="référence", army_id=0, move=5, save=4, health=10, control=1, models=1, points=100)
_ANTI_RE = re.compile(r"Anti-([A-Za-z][A-Za-z \-]*?) \(\+(\d+) (\w+)\)")


@dataclass
class Offense:
    rend: float                 # perforation moyenne, pondérée par les dégâts
    rend2_share: float          # part des dégâts à perforation 2 ou plus
    mortal_share: float         # part qui ignore la sauvegarde (critiques mortels + aptitudes directes)
    anti: list[tuple[str, str, str]]   # (unité, MOT-CLÉ, bonus)
    anti_charge: list[str]      # unités avec Anti-charge (bonus contre qui les charge)
    max_range: int


@dataclass
class Defense:
    save: float                 # sauvegarde moyenne, pondérée par les points
    heavy_share: float          # part des points en sauvegarde 3+ ou mieux
    ward_share: float           # part des points avec une ward
    ward_avg: float             # ward moyenne de ces unités


def _best_weapons(unit, models: int):
    """Arme(s) retenue(s) par mode alternatif, avec leur nombre de porteurs."""
    best: dict[tuple, tuple[float, object, int]] = {}
    for i, (w, c) in enumerate(zip(unit.weapons, effective_counts(unit, models), strict=True)):
        key = (w.kind, w.name.split(":")[0].strip()) if ":" in w.name else (w.kind, i)
        d = expected_weapon_damage(w, c, _REF, _MODS)
        if d > best.get(key, (-1.0, None, 0))[0]:
            best[key] = (d, w, c)
    return list(best.values())


def offense(al: ArmyList) -> Offense:
    total = rend_sum = rend2 = mortal = 0.0
    anti: list[tuple[str, str, str]] = []
    anti_charge: list[str] = []
    max_range = 0
    for e in al.entries:
        for d, w, c in _best_weapons(e.unit, e.models):
            total += d
            rend_sum += w.rend * d
            if w.rend >= 2:
                rend2 += d
            if weapon_crit_type(w.abilities) == "mortal":
                mortal += c * w.attacks * w.damage / 6
            if w.kind == "ranged":
                max_range = max(max_range, w.range_in)
            for kw, n, stat in _ANTI_RE.findall(normalize_abilities(w.abilities or "")):
                if kw.lower() == "charge":
                    if e.label not in anti_charge:
                        anti_charge.append(e.label)
                elif (e.label, kw.upper(), f"+{n} {stat}") not in anti:
                    anti.append((e.label, kw.upper(), f"+{n} {stat}"))
        for ab in [*direct_abilities(e.unit), *e.extra_direct]:
            amount = ab.amount * (min(e.models, 10) if ab.per_own_model else 1)
            mortal += amount * ab.frequency
            total += amount * ab.frequency
    return Offense(rend_sum / total if total else 0.0, rend2 / total if total else 0.0,
                   min(mortal / total, 1.0) if total else 0.0, anti, anti_charge, max_range)


def defense(al: ArmyList) -> Defense:
    pts = al.points or 1
    warded = [e for e in al.entries if e.unit.ward]
    ward_pts = sum(e.points for e in warded)
    return Defense(
        sum(e.unit.save * e.points for e in al.entries) / pts,
        sum(e.points for e in al.entries if e.unit.save <= 3) / pts,
        ward_pts / pts,
        sum(e.unit.ward * e.points for e in warded) / ward_pts if ward_pts else 7.0,
    )


def anti_hits(off: Offense, target: ArmyList) -> list[tuple[str, str, list[str], int]]:
    """(MOT-CLÉ, bonus et unités qui le portent, unités adverses concernées, leurs points)."""
    by_kw: dict[str, tuple[set, set]] = {}
    for label, kw, bonus in off.anti:
        hit = [e for e in target.entries if kw in e.unit.keywords]
        if hit:
            carriers, _ = by_kw.setdefault(kw, (set(), set()))
            carriers.add(f"{label} {bonus}")
            by_kw[kw] = (carriers, {e.label for e in hit})
    out = []
    for kw, (carriers, hit) in by_kw.items():
        pts = sum(e.points for e in target.entries if e.label in hit)
        out.append((kw, ", ".join(sorted(carriers)), sorted(hit), pts))
    return sorted(out, key=lambda x: -x[3])


def targets(a: ArmyList, b: ArmyList, cache: dict) -> tuple[tuple[str, float, str], tuple[str, float, str]]:
    """Leur unité la plus dure / la plus facile à retirer : (unité, activations de notre meilleure unité, laquelle)."""
    rows = []
    for eb in b.entries:
        if eb.points < 60:
            continue
        best_dmg, best_a = 0.0, ""
        for ea in a.entries:
            dmg = pair_damage(ea, a, eb, b, cache)[0]
            if dmg > best_dmg:
                best_dmg, best_a = dmg, ea.label
        rows.append((eb.label, eb.hp / best_dmg if best_dmg else 99.0, best_a))
    rows.sort(key=lambda r: r[1])
    return rows[-1], rows[0]


def _save_txt(x: float) -> str:
    return "aucune" if x >= 6.95 else f"{x:.1f}+".replace(".", ",")


def _rend_txt(x: float) -> str:
    return f"−{x:.1f}".replace(".", ",")


def lecture(a: ArmyList, b: ArmyList, oa: Offense, ob: Offense, da: Defense, db: Defense,
            m, hits_a, hits_b) -> list[str]:
    out = []
    # Perforation contre armure, dans les deux sens.
    for us, off, dfn, who in ((True, oa, db, b.player), (False, ob, da, a.player)):
        subj, obj = ("Notre", "leur") if us else ("Leur", "notre")
        if dfn.save <= 3.5:
            if off.rend >= 1.3:
                out.append(f"{subj} perforation ({_rend_txt(off.rend)}) est adaptée à {obj} armure lourde.")
            elif off.mortal_share >= 0.15:
                out.append(f"{subj} perforation est faible ({_rend_txt(off.rend)}) contre {obj} armure lourde, "
                           f"mais les mortelles ({off.mortal_share:.0%} des dégâts) compensent.")
            else:
                out.append(f"{subj} perforation est faible ({_rend_txt(off.rend)}) contre {obj} armure lourde "
                           f"({_save_txt(dfn.save)}) : " + ("point noir du matchup pour nous." if us
                                                             else "ils auront du mal à nous entamer."))
        elif dfn.save >= 4.6 and off.rend < 1:
            out.append(f"{obj.capitalize()} armure est légère ({_save_txt(dfn.save)}) : même sans perforation, "
                       f"{'nos' if us else 'leurs'} profils passent.")
    if db.ward_share >= 0.3:
        out.append(f"Leur ward ({_save_txt(db.ward_avg)} sur {db.ward_share:.0%} des points) réduit aussi nos mortelles.")
    if da.ward_share >= 0.3:
        out.append(f"Notre ward ({_save_txt(da.ward_avg)} sur {da.ward_share:.0%} des points) amortit leurs mortelles.")
    for hits, al, us in ((hits_a, b, True), (hits_b, a, False)):
        pts = sum(h[3] for h in hits[:1])
        if hits and pts / (al.points or 1) >= 0.4:
            out.append((f"Nos Anti-{hits[0][0]} touchent {pts / al.points:.0%} de leur armée : vrai levier."
                        if us else f"Attention : leurs Anti-{hits[0][0]} touchent {pts / al.points:.0%} de notre armée."))
    if ob.anti_charge and m.att_a.ranged_share < 0.3:
        out.append(f"Leurs unités Anti-charge ({', '.join(ob.anti_charge[:3])}) punissent nos charges : "
                   "les engager en contre-charge ou les tirer d'abord.")
    if oa.anti_charge and m.att_b.ranged_share < 0.3:
        out.append(f"Nos unités Anti-charge ({', '.join(oa.anti_charge[:3])}) punissent leurs charges.")
    if m.att_a.ranged_share >= 0.4 and m.att_b.ranged_share <= 0.15:
        out.append("On a l'avantage du tir : ils doivent traverser la table sous le feu.")
    elif m.att_b.ranged_share >= 0.4 and m.att_a.ranged_share <= 0.15:
        out.append("Ils ont l'avantage du tir : il faut aller au contact vite ou se cacher.")
    ratio = (a.control + 1) / (b.control + 1)
    if ratio >= 1.5:
        out.append(f"On domine le contrôle ({a.control} contre {b.control}) : jouer le scénario plutôt que la tuerie.")
    elif ratio <= 0.67:
        out.append(f"Ils tiennent mieux les objectifs ({b.control} contre {a.control}) : il faut tuer pour scorer.")
    return out


def verdict(score: int) -> str:
    if score >= 8:
        return "net avantage"
    if score >= 3:
        return "avantage"
    if score > -3:
        return "équilibré"
    if score > -8:
        return "désavantage"
    return "net désavantage"


def fmt(score: int) -> str:
    return f"+{score}" if score > 0 else str(score)


def profile_row(al: ArmyList) -> str:
    o, d = offense(al), defense(al)
    return (f"| **{al.player}** | {al.faction} | {al.n_units} | {al.hp} | {_save_txt(d.save)} | "
            f"{d.ward_share:.0%} | {_rend_txt(o.rend)} | {o.mortal_share:.0%} | {al.control} | "
            f"{al.avg_move:.0f}\" | {al.monsters} |")


def match_text(a: ArmyList, b: ArmyList, m: Matchup, cache: dict) -> str:
    oa, ob, da, db = offense(a), offense(b), defense(a), defense(b)
    hits_a, hits_b = anti_hits(oa, b), anti_hits(ob, a)
    best_a = ", ".join(f"{n} ({v:.0f} pts/round)" for n, v in m.att_a.best)
    best_b = ", ".join(f"{n} ({v:.0f} pts/round)" for n, v in m.att_b.best)
    hard_b, easy_b = targets(a, b, cache)
    hard_a, easy_a = targets(b, a, cache)
    lines = [
        f"**{a.player} – {b.player} : {fmt(m.score)} ({verdict(m.score)})**",
        f"- *Combat ({m.combat:+.1f})* : indice d'attrition {m.att_a.index:.0%} contre {m.att_b.index:.0%} "
        f"(part de l'armée adverse, en points, retirée par round si toutes les unités frappent ; "
        f"nous chargeons dans ~{m.att_a.charge_share:.0%} des combats, eux dans ~{m.att_b.charge_share:.0%}). "
        f"Nos meilleures unités ici : {best_a}. Leurs menaces : {best_b}."
        + (f" Part de tir : {m.att_a.ranged_share:.0%} chez nous (portée max {oa.max_range}\"), "
           f"{m.att_b.ranged_share:.0%} chez eux (portée max {ob.max_range}\")."
           if max(m.att_a.ranged_share, m.att_b.ranged_share) >= 0.2 else ""),
        f"- *Perforation contre armure* : nos dégâts ont une perforation moyenne de {_rend_txt(oa.rend)} "
        f"({oa.rend2_share:.0%} à −2 ou mieux) face à une armure moyenne de {_save_txt(db.save)} "
        f"({db.heavy_share:.0%} de leurs points en 3+ ou mieux), soit une sauvegarde effective "
        f"d'environ {_save_txt(min(7, db.save + oa.rend))}. Dans l'autre sens : {_rend_txt(ob.rend)} "
        f"({ob.rend2_share:.0%} à −2 ou mieux) contre notre {_save_txt(da.save)} "
        f"({da.heavy_share:.0%} en 3+ ou mieux), effective {_save_txt(min(7, da.save + ob.rend))}.",
        f"- *Dégâts qui ignorent l'armure* (critiques mortels + aptitudes) : {oa.mortal_share:.0%} des nôtres, "
        f"{ob.mortal_share:.0%} des leurs. Wards : {db.ward_share:.0%} de leurs points"
        + (f" ({_save_txt(db.ward_avg)})" if db.ward_share else "")
        + f", {da.ward_share:.0%} des nôtres" + (f" ({_save_txt(da.ward_avg)})" if da.ward_share else "") + ".",
    ]
    anti_lines = []
    for kw, carriers, hit, pts in hits_a:
        anti_lines.append(f"nos Anti-{kw} ({carriers}) → {', '.join(hit)} ({pts} pts, {pts / (b.points or 1):.0%})")
    for kw, carriers, hit, pts in hits_b:
        anti_lines.append(f"leurs Anti-{kw} ({carriers}) → {', '.join(hit)} ({pts} pts, {pts / (a.points or 1):.0%})")
    if ob.anti_charge:
        anti_lines.append(f"Anti-charge chez eux : {', '.join(ob.anti_charge)}")
    if oa.anti_charge:
        anti_lines.append(f"Anti-charge chez nous : {', '.join(oa.anti_charge)}")
    lines.append("- *Anti-X* : " + ("; ".join(anti_lines) if anti_lines else "aucun bonus Anti-X ne s'active") + ".")
    lines.append(
        f"- *Cibles* : leur unité la plus dure à retirer est {hard_b[0]} (~{hard_b[1]:.1f} activation(s) de {hard_b[2]}), "
        f"la plus facile {easy_b[0]} (~{easy_b[1]:.1f} activation(s) de {easy_b[2]}). "
        f"Chez nous, ils peinent le plus sur {hard_a[0]} (~{hard_a[1]:.1f} activation(s) de {hard_a[2]}) "
        f"et retirent le plus vite {easy_a[0]} (~{easy_a[1]:.1f} activation(s) de {easy_a[2]}).")
    lines.append(
        f"- *Scénario ({m.board:+.1f})* : contrôle {a.control} contre {b.control}, "
        f"{a.n_units} unités contre {b.n_units}, mouvement moyen {a.avg_move:.0f}\" contre {b.avg_move:.0f}\", "
        f"vol {a.prof.fly_share:.0%} contre {b.prof.fly_share:.0%} ; indice de mobilité {a.mob:+.1f} contre {b.mob:+.1f}"
        + _mob_detail(a, b) + ".")
    lines.append(
        f"- *Aptitudes et plan ({m.apt:+.1f})* : indice d'aptitudes {a.apt:+.1f} contre {b.apt:+.1f} "
        f"({_apt_summary(a)} ; contre {_apt_summary(b)}), note de plan {a.plan} contre {b.plan}.")
    lec = lecture(a, b, oa, ob, da, db, m, hits_a, hits_b)
    if lec:
        lines.append("- *Lecture* : " + " ".join(lec))
    if m.adj:
        lines.append("- *Ajustements* : " + " ; ".join(f"{v:+g} — {r}" for v, r in m.adj) + ".")
    return "\n".join(lines)


def _apt_summary(al: ArmyList) -> str:
    pr = al.prof
    parts = [f"{f} {pr.score[f]:.1f}" for f in APT_FAMILIES if pr.score[f] >= 0.5]
    if pr.wizard_levels or pr.priest_levels:
        parts.append(f"sorciers {pr.wizard_levels}, prêtres {pr.priest_levels}")
    return ", ".join(parts) or "rien de détecté"


def _mob_detail(a: ArmyList, b: ArmyList) -> str:
    def names(al):
        return sorted({d.split(" (")[0] for d in al.prof.detail["mobilité"]})[:4]
    na, nb = names(a), names(b)
    if not na and not nb:
        return ""
    return f" (nous : {', '.join(na) or 'aucune aptitude de mouvement'} ; eux : {', '.join(nb) or 'aucune'})"


SUMMARY = "00 Grille et profils.md"


def _round_dir(i: int, opp_team: str) -> str:
    return f"Ronde {i} — contre {opp_team}"


def _md_link(path: str) -> str:
    return path.replace(" ", "%20")


def method_body() -> list[str]:
    """Description des composantes du score (partagée avec l3/listes.py)."""
    return [
        f"- **Combat** (jusqu'à ±{COMBAT_MAX}) : moteur aospy, dégâts attendus de chaque unité contre chaque unité "
        "adverse (touche, blessure, sauvegarde/perforation, ward, critiques, Anti-X, bonus de charge), "
        "ramenés en points d'armée retirés par round. On compare les deux camps. S'y ajoutent "
        f"**{FURY_ATTACKS:g} attaque(s) par round avec le meilleur profil d'arme** (Explosion de Fureur) et les "
        "**aptitudes à dégâts directs** lues dans les warscrolls Wahapedia (dégâts mortels ; la ward s'applique). "
        "Son poids a été réduit (il était de ±10) : il écrasait tout le reste.",
        "- **Jeu de scénario** (jusqu'à ±7) : contrôle total (±2), nombre d'unités (±1) et **mobilité** (±4). "
        "La mobilité combine le mouvement moyen (pondéré par les points), la part de l'armée qui VOLE et les "
        "aptitudes de mouvement lues dans les textes (frappe en profondeur, téléportation, redéploiement, "
        "mouvements gratuits, course et charge dans le même tour, bonus de course/charge).",
        "- **Aptitudes et plan de jeu** (jusqu'à ±7,6) : un indice d'aptitudes (±4) lu automatiquement dans les "
        "textes Wahapedia de la liste (warscrolls, traits de bataille, formation, domaines choisis, "
        "améliorations) : soins, protections (ward, −1 pour toucher/blesser, +1 sauvegarde), buffs (+1 "
        "pour toucher/blesser, perforation, attaques, Frappe en premier), débuffs, objectifs, et magie "
        "(niveaux de sorcier et de prêtre). Une aptitude d'unité pèse selon la part de l'armée qu'elle "
        "touche (aura : 0,6 ; sinon le poids de l'unité), un trait de bataille double. Plus une **note de "
        "plan de jeu** de 0 à 3 par liste (±1,2 par point d'écart), dans `Données/combos/<équipe>.json` "
        "(`note_plan`, à valider par l'équipe) : cohérence et solidité du plan, nombre de leviers.",
        "- **Ajustements** : ce que le reste ne voit pas, matchup par matchup (anti-monstre, anti-magie, "
        "anti-soin...), avec leur justification, dans `Données/ajustements_matchups.json` (à corriger par "
        "l'équipe, puis relancer `tm-aospy-l3-matchups`). Les anciennes corrections par liste ont été remises "
        "à zéro : l'axe aptitudes les remplace.",
        "- **Limites** : la lecture des textes est un compteur d'expressions, pas une lecture des règles. "
        "Certains textes Wahapedia sont tronqués (Depict Rune des Lumineth : la note de plan compense). "
        "Le scénario de chaque ronde n'est pas pris en compte.", ""]


def _method() -> list[str]:
    return [
           "## Méthode", "",
           "- **Score** = écart de points de victoire attendu pour **notre** liste sur une partie "
           "(+ = on gagne de tant). Échelle de −20 à +20 : ±3 équilibré, ±8 net.",
           *method_body()]


def _grid_lines(ours, theirs, grid) -> list[str]:
    out = ["| Nous \\ Eux | " + " | ".join(b.player for b in theirs) + " | Moy. |",
           "|---|" + "---|" * (len(theirs) + 1)]
    for a in ours:
        scores = [grid[(a.player, b.player)].score for b in theirs]
        out.append(f"| **{a.player}** | " + " | ".join(fmt(s) for s in scores)
                   + f" | {fmt(round(sum(scores) / len(scores)))} |")
    return out


def build_reports(team: str, lists: dict[str, ArmyList], adjustments: dict, cache: dict) -> dict[str, str]:
    """Un index (méthode + grilles résumées), puis un dossier par ronde : profils et grille, et un
    fichier de détail par joueur de notre équipe."""
    ours = [lists[p] for p in _TEAMS[team]]
    folder = OUTPUT[team].removesuffix(".md")
    local = folder.rsplit("/", 1)[-1]  # chemins relatifs à l'index, rangé dans le même dossier
    index = [f"# Matchups {team} — L3 Centre 2026-27, rondes 1 à 5", "",
             "*Grille de travail : chaque score est une estimation à discuter et corriger. "
             "La stratégie de pairing se construira sur la version validée.*", "",
             f"Le détail est rangé sous `{local}/` : un dossier par ronde, avec la grille et les profils, "
             "puis un fichier par joueur (ses 6 matchups).", ""] + _method()
    files: dict[str, str] = {}
    for i, opp_team in enumerate(SCHEDULE[team], 1):
        if opp_team is None:
            index += [f"## Ronde {i} — BYE", ""]
            continue
        theirs = [lists[p] for p in _TEAMS[opp_team]]
        name = _round_dir(i, opp_team)
        grid = {(a.player, b.player): evaluate(a, b, adjustments, cache) for a in ours for b in theirs}
        link = f"{local}/{name}/{SUMMARY}".replace(" ", "%20")
        index += [f"## Ronde {i} — contre {opp_team}", "", f"Détail : [{name}]({link})", ""]
        index += _grid_lines(ours, theirs, grid) + [""]
        back = f"[Matchups {team}](../../{local.replace(' ', '%20')}.md)"
        out = [f"# Matchups {team} — Ronde {i}, contre {opp_team}", "",
               f"*Méthode, échelle et biais connus : voir {back}.*", "",
               "Détail des matchups, un fichier par joueur : "
               + " · ".join(f"[{a.player}]({_md_link(a.player + '.md')})" for a in ours), "",
               "## Profils", "",
               "| Joueur | Faction | Unités | PV | Svg moy. | Ward (pts) | Perf. moy. | Mortelles | Contrôle | Mvt | Monstres |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        out += [profile_row(al) for al in ours] + ["|  |  |  |  |  |  |  |  |  |  |  |"]
        out += [profile_row(al) for al in theirs] + [""]
        missing = [f"{al.player} : {', '.join(al.unmatched)}" for al in theirs if al.unmatched]
        if missing:
            out += ["*Non trouvé dans la base (non compté, voir ajustements)* : " + " · ".join(missing), ""]
        out += ["## Grille", ""] + _grid_lines(ours, theirs, grid) + [""]
        files[f"{folder}/{name}/{SUMMARY}"] = "\n".join(out)
        for a in ours:
            scores = " · ".join(f"{b.player} {fmt(grid[(a.player, b.player)].score)}" for b in theirs)
            det = [f"# {a.player} — Ronde {i}, contre {opp_team}", "",
                   f"*Grille et profils de la ronde : [{SUMMARY.removesuffix('.md')}]({_md_link(SUMMARY)}). "
                   f"Méthode : {back}.*", "", f"Scores : {scores}.", ""]
            for b in theirs:
                det += [match_text(a, b, grid[(a.player, b.player)], cache), ""]
            files[f"{folder}/{name}/{a.player}.md"] = "\n".join(det)
    files[OUTPUT[team]] = "\n".join(index)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aospy l3 matchups", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="affiche seulement le parsing des listes")
    args = parser.parse_args(argv)
    con = duckdb.connect(str(DB), read_only=True)
    _DIRECT.update(load_direct_abilities())
    lists = build_lists(con)
    if args.check:
        for al in lists.values():
            print(f"{al.team} / {al.player} ({al.faction}) : {al.points} pts, {al.n_units} unités")
            print("   ", ", ".join(e.label for e in al.entries))
            if al.unmatched:
                print("    NON TROUVÉ :", ", ".join(al.unmatched))
        missing = set(PLAYERS) - set(lists)
        if missing:
            print("Listes absentes :", missing)
        return 0
    adjustments = load_adjustments()
    cache: dict = {}
    for team in OUTPUT:
        for rel, text in build_reports(team, lists, adjustments, cache).items():
            path = FOLDER / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print("écrit :", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

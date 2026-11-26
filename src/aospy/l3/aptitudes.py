"""Lecture des aptitudes d'une liste dans les textes Wahapedia (L3 Centre 2026-27).

Pour chaque liste, rassemble les textes qui la concernent :
  * les aptitudes de warscroll de chaque unité ;
  * les traits de bataille de la faction, la formation choisie, les domaines de sorts,
    de prières et de manifestations choisis, les améliorations (traits héroïques, artefacts...).

Chaque texte est classé par des expressions régulières en familles d'effets (mobilité, soins,
protection, buff, débuff, objectifs, anti-magie, anti-soin), avec un poids et une fréquence
d'usage. Ce n'est pas une lecture fine des règles : c'est un compteur, assez stable pour
comparer les listes entre elles, pas pour chiffrer une aptitude précise.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WAHAPEDIA = ROOT / "data" / "wahapedia"
AIDS = ROOT / "data" / "2026-27 L3 Aller" / "Aides de jeu"
FR_RULES = ROOT / "data" / "json" / "faction_rules_fr.json"

# (famille, poids, motif) ; un texte compte au plus une fois par famille.
RULES: list[tuple[str, float, re.Pattern]] = [
    (f, w, re.compile(p))
    for f, w, p in [
        # Mobilité
        # Set-up (frappe en profondeur, téléportation, arrivée par un bord) : utile pour prendre un
        # objectif ou sauver une unité, mais la charge à 9" qui suit est un pari (~50 % avec la
        # relance, une seule relance par tour), pas un plan : poids réduit de 2 à 1.
        ("mobilité", 1.0, r"set (?:it|this unit|them|that unit|the unit) up (?:again )?anywhere on the battlefield"),
        (
            "mobilité",
            1.0,
            r"remove (?:(?:this|that|the|those) units?|the targets?|it|them) from the battlefield and set (?:it|them) up again",
        ),
        ("mobilité", 1.0, r"wholly within \d+\" of (?:a|any) battlefield edge"),
        ("mobilité", 1.5, r"can (?:immediately )?(?:make a normal move|move up to|move a distance)"),
        (
            "mobilité",
            1.0,
            r"can (?:still )?(?:charge|shoot and/or charge|use charge abilities) (?:later )?in the same turn|run and still charge",
        ),
        ("mobilité", 1.0, r"retreat and still (?:charge|shoot)"),
        ("mobilité", 0.75, r"add \d+ to (?:run|charge) rolls|add \d+\" to (?:its|their|the) move"),
        # Soins
        ("soins", 1.5, r"\bheal \(|return (?:\d+|d3|d6|a number of) slain models|return slain models"),
        # Protection
        ("protection", 1.5, r"(?:has|have) ward \( ?\d\+ ?\)|ward \( ?\d\+ ?\) (?:for|while)"),
        ("protection", 1.5, r"subtract 1 from (?:hit|wound) rolls for (?:combat |shooting )?attacks that target"),
        ("protection", 1.5, r"add 1 to save rolls"),
        ("protection", 1.0, r"cannot be (?:picked as the target|targeted)|not visible"),
        # Buffs
        (
            "buff",
            1.5,
            r"add 1 to (?:hit|wound) rolls for (?:(?:this|that|the target's|each) unit's )?(?:combat |shooting )?attacks",
        ),
        ("buff", 1.5, r"add 1 to the rend|add \d+ to the attacks characteristic|add 1 to the damage"),
        ("buff", 1.0, r"\bstrike-first\b"),
        ("buff", 1.0, r"has crit \(|have crit \("),
        # Débuffs
        ("débuff", 1.5, r"subtract 1 from (?:hit|wound) rolls for (?:combat |shooting )?attacks made by"),
        ("débuff", 1.0, r"\bstrike-last\b"),
        ("débuff", 1.0, r"subtract \d+ from (?:charge|run) rolls|subtract 1 from save rolls|subtract 1 from the rend"),
        ("débuff", 1.0, r"cannot use commands|cannot be picked to use|cannot use (?:fight|shoot|move) abilities"),
        # Objectifs
        ("objectifs", 1.5, r"add \d+ to (?:the|its|their) control characteristic|control score"),
        ("objectifs", 1.0, r"contest(?:ing|s)? objectives|objective you control|counts? as (?:contesting|controlling)"),
        # Anti-magie / anti-soin (servent aux interactions de matchup)
        (
            "anti-magie",
            1.0,
            r"unbinding roll|\bunbind\b|cannot cast|casting rolls for enemy|has no effect.{0,20}spell|banish",
        ),
        ("anti-soin", 1.0, r"cannot be healed|cannot (?:heal|return slain models)|subtract .{0,20}heal"),
        # Bonus de lancement / de prière
        ("magie", 1.0, r"add 1 to casting rolls|add 1 to chanting rolls|cast (?:1|one|an) additional spell"),
    ]
]

# Effets qui peuvent viser les deux camps : on exige que le texte vise un ami (buff) ou un ennemi (débuff).
FRIENDLY = re.compile(r"\b(?:friendly|this unit|that unit|each unit in this|this hero|units? in your army)\b")
ENEMY = re.compile(r"\benemy\b")

# Mêmes familles et mêmes poids, pour le texte français des battletomes (aide de jeu).
RULES_FR: list[tuple[str, float, re.Pattern]] = [
    (f, w, re.compile(p))
    for f, w, p in [
        (
            "mobilité",
            1.0,
            r"placez-(?:la|le|les) (?:à nouveau|de nouveau)|retirez (?:cette unité|la cible|l'unité|les cibles?).{0,30}du champ de bataille",
        ),
        ("mobilité", 1.0, r"entièrement à \d+\" d'un bord du champ de bataille"),
        ("mobilité", 1.5, r"peut (?:immédiatement )?(?:se déplacer|parcourir) (?:de |jusqu'à )?(?:\d|d3|d6)"),
        ("mobilité", 1.0, r"même si elle a utilisé une aptitude de (?:course|repli)|peut (?:quand même )?charger"),
        ("mobilité", 0.75, r"ajoutez \d aux jets de (?:course|charge)|ajoutez \d\" à la caractéristique de mouvement"),
        ("soins", 1.5, r"\bsoignez|soins? \(\s?(?:\d|d3|d6)|ramenez .{0,30}figurines? tuées?"),
        ("protection", 1.5, r"protection \( ?\d\+ ?\)"),
        (
            "protection",
            1.5,
            r"soustrayez 1 aux jets de (?:touche|blessure) pour les attaques (?:de [a-z ]+ )?qui ciblent",
        ),
        ("protection", 1.5, r"ajoutez 1 aux jets de sauvegarde"),
        ("protection", 1.0, r"ne peut pas être (?:choisie|ciblée)|n'est pas visible"),
        ("buff", 1.5, r"ajoutez 1 aux jets de (?:touche|blessure) pour les attaques"),
        (
            "buff",
            1.5,
            r"ajoutez 1 à la (?:caractéristique de )?perf|ajoutez \d à la caractéristique d'attaques|ajoutez 1 à la caractéristique de dégâts",
        ),
        ("buff", 1.0, r"frappe en premier"),
        ("buff", 1.0, r"ont critique \(|a critique \("),
        (
            "débuff",
            1.5,
            r"soustrayez 1 aux jets de (?:touche|blessure) pour les attaques (?:faites par|des unités ennemies|de la cible|de cette unité ennemie)",
        ),
        ("débuff", 1.0, r"frappe en dernier"),
        (
            "débuff",
            1.0,
            r"soustrayez \d aux jets de (?:charge|course)|soustrayez 1 aux jets de sauvegarde|soustrayez 1 à la (?:caractéristique de )?perf",
        ),
        ("débuff", 1.0, r"ne peut pas utiliser d'ordres|ne peut pas être choisie pour utiliser"),
        ("objectifs", 1.5, r"ajoutez \d à (?:la|sa|leur) caractéristique de contrôle|score de contrôle"),
        ("objectifs", 1.0, r"contest(?:e|ent|er) (?:un |des |l')?objectif|objectif que vous contrôlez"),
        ("anti-magie", 1.0, r"dissip|jets de lancement (?:pour|des) (?:les )?(?:unités )?ennemi|bannir"),
        ("anti-soin", 1.0, r"ne (?:peut|peuvent) pas être soignée?s?|ne (?:peut|peuvent) pas ramener"),
        ("magie", 1.0, r"ajoutez 1 aux jets de (?:lancement|récitation)|lancer un sort supplémentaire"),
    ]
]
FRIENDLY_FR = re.compile(r"\bamie?s?\b|cette unité|cette cible")
ENEMY_FR = re.compile(r"\bennemie?s?\b")
TELEPORT_FR = re.compile(r"retirez (?:la cible|cette unité|l'unité|les cibles?).{0,40}du champ de bataille et placez")
CHARGE_ADD_FR = re.compile(r"ajoutez (\d) aux jets de (?:course et de )?charge")
CHARGE_DICE_FR = re.compile(r"ajoutez 1 au nombre de dés|1 dé supplémentaire")
CHARGE_REROLL_FR = re.compile(r"relance[rz]? (?:les )?jets de (?:course et de )?charge")
AURA_EN = re.compile(r"friendly (?:[a-z\- ]+ )?units? (?:while they are )?(?:wholly )?within")
AURA_FR = re.compile(r"unités? (?:[a-zéèê\- ]+ )?amies? (?:tant qu'elles sont )?entièrement à \d+")

#: aptitudes de score de contrôle (anglais et français), chiffrées par la couche 4
CONTROL_SCORE = re.compile(r"control (?:characteristic|score)|(?:caractéristique|score) de contrôle")

FAMILIES = ["mobilité", "soins", "protection", "buff", "débuff", "objectifs", "magie", "anti-magie", "anti-soin"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("’", "'")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _text(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", t).replace("’", "'").replace("“", '"').replace("”", '"').lower()


@dataclass
class Ability:
    source: str  # « unité Foo », « trait de bataille », « domaine Bar »...
    name: str
    condition: str
    text: str
    cost: str = ""  # « Command:1 », « Spell:7 »... (colonnes points_type/points de Wahapedia)
    keywords: str = ""  # mots-clés de l'aptitude (« Spell, Unlimited »...)
    lang: str = "en"  # « fr » : texte de l'aide de jeu (battletome) sans équivalent Wahapedia


@dataclass
class Profile:
    """Familles d'effets d'une liste : total pondéré et détail (source, aptitude)."""

    score: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    detail: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    charge_army: float = 0.0  # pouces de charge en plus pour toute la liste
    charge_unit: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # par unité (nom)
    charge_detail: list[str] = field(default_factory=list)
    from_aid: bool = False  # aptitudes filtrées par l'aide de jeu de la liste
    cp_costs: list[str] = field(default_factory=list)  # aptitudes qui coûtent des points de commandement
    cp_gains: list[str] = field(default_factory=list)  # ordres rendus gratuits (économie de PC)
    cp_deny: list[str] = field(default_factory=list)  # déni ou taxe sur les ordres adverses
    wizard_levels: int = 0
    priest_levels: int = 0
    fly_share: float = 0.0
    #: part de `score["objectifs"]` due aux aptitudes de score de contrôle : la couche 4 les chiffre
    #: (`l3.layer4.L4Indices.control`), le reste du compteur « objectifs » les retire alors (double compte)
    objectifs_controle: float = 0.0


def _frequency(cond: str) -> float:
    c = cond.lower()
    if "once per battle" in c or "une fois par bataille" in c:
        return 0.4
    if "reaction" in c or "réaction" in c:
        return 0.8
    return 1.0


def classify(ab: Ability) -> list[tuple[str, float]]:
    out: dict[str, float] = {}
    fr = ab.lang == "fr"
    rules, friendly, enemy = (RULES_FR, FRIENDLY_FR, ENEMY_FR) if fr else (RULES, FRIENDLY, ENEMY)
    eff = ab.text.split("effet :" if fr else "effect:", 1)[-1]
    for fam, weight, pat in rules:
        if fam in out or not pat.search(ab.text):
            continue
        if fam == "buff" and not friendly.search(ab.text):
            continue
        if fam == "débuff" and not enemy.search(ab.text):
            continue
        # Une pénalité que l'unité s'inflige elle-même n'est pas un débuff adverse.
        if fam == "débuff" and not enemy.search(eff):
            continue
        out[fam] = weight * _frequency(ab.condition)
    return list(out.items())


class Library:
    """Index des textes Wahapedia (chargé une fois)."""

    def __init__(self) -> None:
        csv.field_size_limit(10**8)
        with open(WAHAPEDIA / "Factions.csv", encoding="utf-8-sig") as fh:
            self.faction_id = {r["name"]: r["id"] for r in csv.DictReader(fh, delimiter="|")}
        with open(WAHAPEDIA / "Warscrolls.csv", encoding="utf-8-sig") as fh:
            names = {r["id"]: r["name"] for r in csv.DictReader(fh, delimiter="|")}
        self.unit: dict[str, list[Ability]] = defaultdict(list)
        with open(WAHAPEDIA / "Warscrolls_abilities.csv", encoding="utf-8-sig") as fh:
            seen = set()
            for r in csv.DictReader(fh, delimiter="|"):
                name = names.get(r["warscroll_id"])
                if not name:
                    continue
                key = (_norm(name), _norm(r["name"]))
                if key in seen:  # doublons de warscroll (versions RoR, etc.)
                    continue
                seen.add(key)
                self.unit[_norm(name)].append(
                    Ability(f"unité {name}", r["name"], r.get("condition") or "", _text(r.get("description")), _cost(r))
                )
        self.all_names = {_norm(ab.name) for abs_ in self.unit.values() for ab in abs_}
        self.faction: list[dict] = []
        with open(WAHAPEDIA / "Faction_abilities.csv", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh, delimiter="|"):
                r["_text"] = _text(r.get("description"))
                self.faction.append(r)
                self.all_names.add(_norm(r["name"]))

    def extra_from_aid(self, faction: str, names: set[str], already: set[str]) -> list[Ability]:
        """Aptitudes de l'aide de jeu que la collecte par catégorie rate : règles d'armée de renom,
        aptitudes des manifestations convoquées... (faction de la liste, Endless Spells, ou
        n'importe quel warscroll pour une manifestation)."""
        fid = self.faction_id.get(faction)
        out, seen = [], set(already)
        for r in self.faction:
            n = _norm(r["name"])
            if n in names and n not in seen and r["faction_id"] in (fid, "EnS"):
                seen.add(n)
                out.append(
                    Ability(
                        f"aide de jeu ({r.get('type_name')})",
                        r["name"],
                        r.get("condition") or "",
                        r["_text"],
                        _cost(r),
                        r.get("keywords") or "",
                    )
                )
        for abilities in self.unit.values():
            for ab in abilities:
                n = _norm(ab.name)
                if n in names and n not in seen:
                    seen.add(n)
                    out.append(
                        Ability(f"aide de jeu ({ab.source})", ab.name, ab.condition, ab.text, ab.cost, ab.keywords)
                    )
        return out

    def unit_abilities(self, unit_name: str) -> list[Ability]:
        key = _norm(unit_name)
        return self.unit.get(key) or self.unit.get(key.replace("scourge of aqshy ", "", 1)) or []

    def list_abilities(self, faction: str, header: list[str], options: list[str]) -> list[Ability]:
        """Aptitudes de faction choisies par la liste : traits, formation, domaines, améliorations."""
        fid = self.faction_id.get(faction)
        heads = {_norm(h) for h in header}
        head_blob = " | ".join(heads)
        lores = {
            _norm(h.split(" - ", 1)[1].split("(")[0])
            for h in header
            if h.startswith(("Spell Lore", "Prayer Lore", "Manifestation Lore")) and " - " in h
        }
        opts = {_norm(re.sub(r"^\d+x\s+", "", o)) for o in options}
        out: list[Ability] = []
        for r in self.faction:
            sub = _norm((r.get("subtype_name") or "").split("(")[0])
            typ = r.get("type_name") or ""
            ab = Ability("", r["name"], r.get("condition") or "", r["_text"], _cost(r), r.get("keywords") or "")
            if r["faction_id"] == fid and typ == "Battle Traits":
                # Marques du Chaos (Slaves to Darkness) : Pledge to Chaos marque une unité de plus à
                # chaque tour (plus les marques de départ, ex. Bannière de Rage = Khorne) ; les marques
                # s'accumulent sans couvrir toute l'armée : poids simple au lieu du double d'un trait.
                ab.source = "marque du Chaos" if r["name"].lower().startswith("pledged to") else "trait de bataille"
            elif r["faction_id"] == fid and typ == "Battle Formations" and sub and sub in head_blob:
                ab.source = f"formation {r['subtype_name']}"
            elif (
                typ in ("Spell Lore", "Prayer Lore", "Manifestation Lore")
                and sub in lores
                and r["faction_id"] in (fid, "EnS")
            ):
                ab.source = f"domaine {r['subtype_name']}"
            elif r["faction_id"] == fid and _norm(r["name"]) in opts:
                ab.source = f"amélioration ({typ})"
                # homonyme d'une armée Spearhead (type = nom de l'armée, sous-type « Enhancements ») : la Graine de
                # Renaissance de Bitterbark Copse comptait en plus de l'artefact de base (Zoko, 2026-11-25)
                if sub == "enhancements" and any(
                    _norm(r2["name"]) == _norm(r["name"]) and r2["faction_id"] == fid
                    and _norm(r2.get("subtype_name") or "") != "enhancements"
                    for r2 in self.faction
                ):
                    continue
            else:
                continue
            out.append(ab)
        return out


def _cost(row: dict) -> str:
    kind, pts = (row.get("points_type") or "").strip(), (row.get("points") or "").strip()
    return f"{kind}:{pts}" if kind and pts else ""


# Améliorations du jet de charge (2D6 de base), converties en pouces d'allonge moyenne.
CHARGE_ADD = re.compile(r"add (\d) to (?:run rolls and )?charge rolls|add (\d) to charge rolls and run rolls")
CHARGE_DICE = re.compile(r"add 1 to the number of dice rolled when making charge rolls|roll 1 additional dice")
CHARGE_DISCARD = re.compile(r"discard 1 dice")
CHARGE_REROLL = re.compile(r"re-?roll (?:run rolls and )?charge rolls")


_GENERIC_TARGET = {"", "visible", "other"}


def _target_exists(text: str, al) -> bool:
    """Faux si l'aptitude ne vise qu'un type d'unité amie absent de la liste (ex. « Gutter Runners »)."""
    m = re.search(r"pick (?:a|an|up to \d+|1) (?:visible )?(?:other )?friendly ([a-z\-' ]+?) units?\b", text)
    if not m or m[1].strip() in _GENERIC_TARGET:
        return True
    want = m[1].strip()
    for e in al.entries:
        blob = " ".join(k.lower() for k in e.unit.keywords) + " " + e.unit.name.lower()
        if all(w in blob for w in want.split()):
            return True
    return False


def charge_inches(ab: Ability) -> float:
    """Allonge moyenne ajoutée par une aptitude (0 si elle ne touche pas au jet de charge)."""
    txt = ab.text
    fr = ab.lang == "fr"
    if ("jet de charge" not in txt and "jets de charge" not in txt) if fr else "charge roll" not in txt:
        return 0.0
    inches = 0.0
    m = (CHARGE_ADD_FR if fr else CHARGE_ADD).search(txt)
    if m:
        inches = max(inches, float(m[1] if fr else (m[1] or m[2])))
    if (CHARGE_DICE_FR if fr else CHARGE_DICE).search(txt) and "charge" in txt:
        # 3 dés additionnés (+3,5") ; si l'on doit en défausser un, meilleurs 2 sur 3 (+1,5").
        inches = max(inches, 1.5 if re.search(r"discard 1 dice|défaussez", txt) else 3.5)
    if (CHARGE_REROLL_FR if fr else CHARGE_REROLL).search(txt):
        inches = max(inches, 1.5)
    return inches * _frequency(ab.condition)


TELEPORT = re.compile(r"remove (?:the target|this unit|that unit|it) from the battlefield and set (?:it|them) up again")

# Économie de PC en AoS4 : peu de « gains », surtout des ordres gratuits et du déni d'ordres adverses.
CP_FREE = re.compile(
    r"no command points? (?:are|is) spent|without any command points being spent"
    r"|do not spend any command points|command points spent to use it are regained(?! by your opponent)"
)
CP_DENY = re.compile(
    r"(?:command|it) (?:has|have) no effect|unless (?:your opponent|they) spends? \d+ "
    r"(?:additional )?command point"
)


def _fr_to_en() -> dict[str, str]:
    """Nom français (faction_rules_fr.json) -> nom Wahapedia anglais, normalisés."""
    out: dict[str, str] = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("wahapedia_name") and o.get("name"):
                out[_norm(o["name"])] = _norm(o["wahapedia_name"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(json.loads(FR_RULES.read_text(encoding="utf-8")))
    return out


_FR_EN: dict[str, str] | None = None


_GENERIC: set[str] | None = None


def _generic_names() -> set[str]:
    """Noms présents dans au moins 3/4 des aides de jeu : règles de base, communes à toutes les
    listes (elles s'annulent dans les comparaisons, inutile de les compter)."""
    global _GENERIC
    if _GENERIC is None:
        from collections import Counter

        files = list(AIDS.glob("*/*.json"))
        c = Counter()
        for f in files:
            cards = json.loads(f.read_text(encoding="utf-8"))
            c.update({_norm(re.sub(r"<[^>]+>", "", ab["name"])) for v in cards.values() for ab in v})
        _GENERIC = {n for n, k in c.items() if k >= 0.75 * max(1, len(files))}
        # Règles du Manuel du général et de la saison (même conditionnées, ex. « Porte-Étendard »).
        for name in ("generic_core_abilities.json", "season_rules.json"):
            path = ROOT / "data" / "json" / name
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
                _GENERIC |= {_norm(r.get("name", "")) for r in rows if isinstance(r, dict)}
    return _GENERIC


def aid_names(player: str, team: str) -> tuple[set[str], list[dict]] | None:
    """Aptitudes de l'aide de jeu split-simple de la liste : (noms anglais normalisés, entrées
    françaises sans équivalent Wahapedia connu, hors règles génériques). None si pas d'aide."""
    global _FR_EN
    hits = list((AIDS / team).glob(f"{player} (*).json"))
    if not hits:
        return None
    if _FR_EN is None:
        _FR_EN = _fr_to_en()
    cards = json.loads(hits[0].read_text(encoding="utf-8"))
    names: set[str] = set()
    fr_only: dict[str, dict] = {}
    generic = _generic_names()
    for entries in cards.values():
        for ab in entries:
            n = _norm(re.sub(r"<[^>]+>", "", ab["name"]))
            names.add(_FR_EN.get(n, n))
            if n not in generic and not n.endswith("regle speciale"):  # règles des cartes de tactique
                fr_only.setdefault(n, dict(ab, en=_FR_EN.get(n, n)))
    return names, list(fr_only.values())


def _level(keywords, kind: str) -> int:
    lv = 0
    for k in keywords:
        m = re.match(rf"{kind}\s*\((\d+)\)", k)
        if m:
            lv = max(lv, int(m[1]))
        elif k == kind:
            lv = max(lv, 1)
    return lv


def profile(lib: Library, al, header: list[str], options: list[str]) -> Profile:
    """Profil d'aptitudes d'une `ArmyList` (voir l3_matchups).

    Si l'aide de jeu split-simple de la liste existe (`aospy l3 export-lists --pdf`), elle fait foi :
    les aptitudes Wahapedia ne sont gardées que si elles y figurent, et ses aptitudes sans
    équivalent Wahapedia (battletome récent, contenus Aqshy...) sont lues en français.
    """
    pr = Profile()
    aid = aid_names(al.player, al.team)
    pr.from_aid = aid is not None
    english = set(lib.all_names) if aid else set()
    # Lue en français : aptitude de l'aide dont le nom anglais (traduit ou non) est absent de
    # Wahapedia — battletome plus récent que l'export Wahapedia, contenu Aqshy...
    fr_entries = [a for a in aid[1] if a["en"] not in english] if aid else []
    keep = (lambda ab: ab.lang == "fr" or _norm(ab.name) in aid[0]) if aid else (lambda ab: True)
    pts = al.points or 1
    by_unit: dict[str, list[Ability]] = defaultdict(list)
    loose_fr: list[Ability] = []
    for a in fr_entries:
        ab = Ability(
            "aide de jeu (battletome)",
            re.sub(r"<[^>]+>", "", a["name"]),
            a.get("condition") or "",
            _text(a.get("description")),
            a.get("cost", "").strip(":"),
            a.get("keywords") or "",
            "fr",
        )
        units = [u for u in a.get("unites", []) if any(e.unit.name == u for e in al.entries)]
        if units:
            for u in units:
                ab_u = Ability(f"unité {u} (battletome)", ab.name, ab.condition, ab.text, ab.cost, ab.keywords, "fr")
                by_unit[u].append(ab_u)
        else:
            loose_fr.append(ab)
    # Aptitudes d'unité : poids selon la part de l'armée, aura 0,6 ; une unité prise deux fois compte deux fois.
    unit_abs: list[tuple["object", Ability]] = []
    for e in al.entries:
        pr.wizard_levels += _level(e.unit.keywords, "WIZARD")
        pr.priest_levels += _level(e.unit.keywords, "PRIEST")
        seen = set()
        for ab in list(filter(keep, lib.unit_abilities(e.unit.name))) + by_unit.get(e.unit.name, []):
            if (ab.name, ab.lang) not in seen:
                seen.add((ab.name, ab.lang))
                unit_abs.append((e, ab))
    weighted: list[tuple[Ability, float]] = []
    for e, ab in unit_abs:
        aura = bool((AURA_FR if ab.lang == "fr" else AURA_EN).search(ab.text))
        weighted.append((ab, 0.6 if aura else min(1.0, 4 * e.points / pts)))
    n_wizards = sum(1 for e in al.entries if _level(e.unit.keywords, "WIZARD"))
    n_heroes = sum(1 for e in al.entries if "HERO" in e.unit.keywords)
    list_abs = list(filter(keep, lib.list_abilities(al.faction, header, options)))
    if aid:
        have = {_norm(a.name) for a in list_abs} | {_norm(ab.name) for _, ab in unit_abs}
        list_abs += lib.extra_from_aid(al.faction, aid[0], have)
    list_abs += loose_fr
    for ab in list_abs:
        # Trait de bataille : toute l'armée, il pèse double. Formation, domaine, amélioration : 1.
        mult = 2.0 if ab.source == "trait de bataille" or "traits de bataille" in ab.keywords.lower() else 1.0
        if ab.source == "marque du Chaos":
            # Tzeentch : peu jouée, tour situationnel (avis de l'utilisateur).
            mult = 0.5 if "tzeentch" in ab.name.lower() else 1.0
        # Sort Illimité de téléportation (ex. Skitterleap) : chaque sorcier le lance une fois par tour
        # sur un héros (lui-même ou un autre) : autant de téléportations que de sorciers, dans la
        # limite des héros à déplacer.
        unlimited = "unlimited" in ab.keywords.lower() or "illimité" in ab.keywords.lower()
        if unlimited and (TELEPORT_FR if ab.lang == "fr" else TELEPORT).search(ab.text):
            mult = max(1, min(n_wizards, n_heroes))
        weighted.append((ab, mult))
    pr.fly_share = sum(e.points for e in al.entries if "FLY" in e.unit.keywords) / pts
    # Allonge de charge : sur l'unité elle-même, en aura (toute la liste, ×0,6) ou sur une cible (×0,5).
    for e, ab in unit_abs:
        inch = charge_inches(ab)
        if not inch or (ab.lang == "en" and not _target_exists(ab.text, al)):
            continue
        target = "la cible" in ab.text if ab.lang == "fr" else "the target" in ab.text
        if (AURA_FR if ab.lang == "fr" else AURA_EN).search(ab.text):
            pr.charge_army += 0.6 * inch
            pr.charge_detail.append(f'{ab.name.title()} ({e.unit.name}, aura) +{0.6 * inch:.1f}"')
        elif target:
            pr.charge_army += 0.5 * inch
            pr.charge_detail.append(f'{ab.name.title()} ({e.unit.name}, cible) +{0.5 * inch:.1f}"')
        else:
            pr.charge_unit[e.unit.name] = max(pr.charge_unit[e.unit.name], inch)
            pr.charge_detail.append(f'{ab.name.title()} ({e.unit.name}) +{inch:.1f}"')
    for ab in list_abs:
        inch = charge_inches(ab)
        if inch and (ab.lang == "fr" or _target_exists(ab.text, al)):
            friendly = (
                ("amie" in ab.text and "la cible" not in ab.text)
                if ab.lang == "fr"
                else ("friendly" in ab.text and "the target" not in ab.text)
            )
            k = 1.0 if friendly else 0.5
            pr.charge_army += k * inch
            pr.charge_detail.append(f'{ab.name.title()} ({ab.source}) +{k * inch:.1f}"')
    seen_cp = set()
    for ab, _ in weighted:
        label = f"{ab.name.title()} ({ab.source}, {ab.condition or 'sans condition'})"
        if label in seen_cp:
            continue
        seen_cp.add(label)
        if ab.cost.startswith("Command:"):
            pr.cp_costs.append(f"{ab.cost.split(':')[1]} PC — {label}")
        if ab.lang == "en" and CP_FREE.search(ab.text):
            pr.cp_gains.append(label)
        if ab.lang == "en" and CP_DENY.search(ab.text) and "command" in ab.text:
            pr.cp_deny.append(label)
    for ab, mult in weighted:
        for fam, w in classify(ab):
            pr.score[fam] += w * mult
            pr.detail[fam].append(f"{ab.name.title()} ({ab.source})")
            if fam == "objectifs" and CONTROL_SCORE.search(ab.text):
                pr.objectifs_controle += w * mult
    return pr

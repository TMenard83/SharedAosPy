"""Repli en anglais sur `data/wahapedia/*.csv` pour tout ce qui n'existe dans
*aucun* des PDF fournis (battletomes, Manuel du général) : domaines de sorts/
manifestations génériques (partagés entre factions, stockés sous
`faction_id == "EnS"` — Endless Spells), règles d'armée de renom (« Legion of
the First Prince »...), Régiments de Renom (leur propre légende/composition/
aptitude, `Warscrolls.csv` avec `role == "Regiment of Renown"`), et le profil
complet d'une unité absente du battletome local (ex. un membre de Régiment de
Renown venu d'une autre faction).

Lecture seule, aucun accès DB — même esprit que `warscroll_index.py`, mais la
source ici est déjà en anglais (confirmé en parcourant l'intégralité de
`data/Battle tome/` et `data/Manuel du général/` : ce contenu n'y existe tout
simplement pas). `pdf_builder.py` rend ce qui est trouvé ici sur des pages
étiquetées « Source : Wahapedia (EN) », clairement séparées du reste (en
français, copié depuis les PDF)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from ...sources.wahapedia_csv import read_csv

DEFAULT_WAHAPEDIA_DIR = Path(__file__).resolve().parents[4] / "data" / "wahapedia"

_GENERIC_FACTION_ID = "EnS"

#: Catégories de `Faction_abilities.csv` qui s'appliquent à toute la liste
#: (jamais choisies puis rattachées à une seule unité) — exclues de
#: `WahapediaLookup.find_unit_enhancement`. `type_name` couvre les catégories
#: de premier niveau ; `subtype_name` couvre le même sens pour une catégorie
#: imbriquée sous un nom de formation/armée de renom (ex. "Bloodwind Legion"
#: -> "Battle Traits"/"Regiment Abilities", "Legion of the First Prince" ->
#: "Spell Lore") puisque `type_name` y porte alors ce nom-là, pas la
#: catégorie elle-même.
_ENHANCEMENT_EXCLUDED_TYPES = frozenset({"Battle Formations", "Spell Lore", "Manifestation Lore", "PATH TO GLORY"})
_ENHANCEMENT_EXCLUDED_SUBTYPES = frozenset({"Battle Traits", "Spell Lore", "Manifestation Lore", "Regiment Abilities"})

#: Libellé français d'une catégorie d'optimisation rattachable à une unité —
#: résolu depuis `subtype_name` d'abord (le nom réel de la catégorie pour une
#: ligne imbriquée sous une formation/armée de renom), sinon `type_name` (cas
#: direct). GW donne à chaque faction son propre nom pour cette « case de
#: Traits Héroïques/Artefacts, mais pour troupes » plutôt qu'un terme
#: générique commun -- chaque entrée ci-dessous n'est ajoutée que lorsque son
#: nom français officiel a été confirmé par une page « Fléau d'Aqshy »/
#: battletome fournie (jamais une traduction déduite du nom anglais) ; tant
#: qu'aucune page ne le confirme, la catégorie garde son nom Wahapedia tel
#: quel.
#:
#: `kind` distingue les deux façons dont GW nomme ces catégories :
#: - "named" : un nom de catégorie propre à la faction, unique en lui-même
#:   (ex. "Mutation d'Airain") -- le libellé suffit tel quel.
#: - "generic" : le mot-clé anglais générique "Enhancements", réutilisé tel
#:   quel pour plusieurs sous-warhosts/formations d'une même faction --
#:   `_enhancement_label` suffixe alors le `type_name` (le nom du sous-warhost)
#:   entre parenthèses pour distinguer, ex. "Optimisation (Fluxblade Coven)".
_ENHANCEMENT_CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "Heroic Traits": {"label": "Trait Héroïque", "kind": "named"},
    "Artefacts of Power": {"label": "Artefact de Pouvoir", "kind": "named"},
    "Monstrous Traits": {"label": "Trait Monstrueux", "kind": "named"},
    "Enhancements": {"label": "Optimisation", "kind": "generic"},
    "Brazen Mutations": {"label": "Mutation d'Airain", "kind": "named"},  # Blades of Khorne (Scourge of Aqshy)
    "Brands of the Dark Gods": {
        "label": "Marque des Dieux Sombres",
        "kind": "named",
    },  # Slaves to Darkness (Scourge of Aqshy)
    "Ensorcelled Banners": {"label": "Bannière Ensorcelée", "kind": "named"},  # Slaves to Darkness (Scourge of Aqshy)
    "Decorations for Valour": {"label": "Médaille de Bravoure", "kind": "named"},  # Cities of Sigmar (Scourge of Aqshy)
    "Origins of terrifying Folk Tales": {
        "label": "Fable Terrifiante",
        "kind": "named",
    },  # Soulblight Gravelords (Scourge of Aqshy)
}

_POINTS_SUFFIX_RE = re.compile(r"\s*-?\s*\(\d+\)\s*points?\s*$", re.IGNORECASE)
_QUANTITY_PREFIX_RE = re.compile(r"^\d+\s*x\s+", re.IGNORECASE)


def _enhancement_option_key(option_text: str) -> str:
    """Normalise une sous-ligne ` • ... ` de l'export de liste avant
    comparaison par nom : retire un coût entre parenthèses ajouté par l'App
    pour une optimisation payante (ex. "Radiance of Dark Glory - (20)
    Points" -> "Radiance of Dark Glory") et un préfixe de quantité (ex. "1x
    Pledged to Nurgle" -> "Pledged to Nurgle"). Un marqueur de rôle simple
    ("General", "Reinforced") ressort inchangé — il ne matchera simplement
    aucune aptitude."""
    text = _POINTS_SUFFIX_RE.sub("", option_text)
    text = _QUANTITY_PREFIX_RE.sub("", text)
    return text.strip()


def _enhancement_label(row: dict[str, str]) -> str:
    type_name = row.get("type_name", "")
    entry = _ENHANCEMENT_CATEGORY_LABELS.get(row.get("subtype_name", "")) or _ENHANCEMENT_CATEGORY_LABELS.get(type_name)
    if entry is None:
        return type_name
    return f"{entry['label']} ({type_name})" if entry["kind"] == "generic" else entry["label"]


#: Noms `Warscrolls.csv` où le scrape Wahapedia diverge du nom officiel
#: (BSData/l'App) sur un simple singulier/pluriel — jamais corrigé depuis
#: côté Wahapedia (re-téléchargé tel quel), donc traité ici plutôt que par
#: un patch du CSV qu'un futur re-téléchargement effacerait. Clé = nom normalisé
#: (via `normalize_name`) tel qu'exporté par l'App/dans `data/aospy.duckdb` (BSData),
#: valeur = nom normalisé tel qu'il apparaît réellement dans `Warscrolls.csv`.
#: Repéré sur la faction Fyreslayers (curation `faction_rules_fr` des aptitudes
#: d'unité, signalé par l'utilisateur) : "Hearthguard Berzerkers with Berzerker
#: Broadaxes" (BSData/App, pluriel) vs "Hearthguard Berzerker with Berzerker
#: Broadaxes" (Wahapedia, singulier) — sa variante "... with Flamestrike
#: Poleaxes" est au pluriel des deux côtés, ce n'est donc pas une convention
#: Wahapedia mais bien une coquille isolée sur cette seule ligne.
_WARSCROLL_NAME_ALIASES = {
    "hearthguard berzerkers with berzerker broadaxes": "hearthguard berzerker with berzerker broadaxes",
    # export de liste « with Kurnoth Greatswords » vs Wahapedia « with Greatswords »
    "kurnoth hunters with kurnoth greatswords": "kurnoth hunters with greatswords",
    "kurnoth hunters with kurnoth greatbows": "kurnoth hunters with greatbows",
    "kurnoth hunters with kurnoth greatscythes": "kurnoth hunters with greatscythes",
}


_SEASONAL_SUFFIX_RE = re.compile(r"^(.*?)\s*\((Scourge of \w+)\)\s*$", re.IGNORECASE)


def normalize_name(name: str) -> str:
    # apostrophes typographiques (ex. "Be’lakor" chez Wahapedia vs "Be'lakor"
    # dans l'export de liste) : à uniformiser *avant* le passage NFKD+ASCII,
    # sans quoi le caractère U+2019 (sans décomposition ASCII) disparaît
    # purement et simplement au lieu de matcher l'apostrophe droite.
    name = name.replace("’", "'").replace("‘", "'")
    # l'App insère parfois un ":" entre un préfixe de variante saisonnière et
    # le nom de base (ex. "Scourge of Aqshy: Black Coach"), absent du nom
    # Wahapedia correspondant ("Scourge of Aqshy Black Coach") — aucun nom
    # Wahapedia ne contient de ":", ce n'est donc jamais ambigu de le retirer.
    name = name.replace(":", "")
    # Sigdex exporte la même variante en suffixe ("Namarti Reavers (Scourge
    # of Aqshy)") plutôt qu'en préfixe : on la remet devant, à la Wahapedia.
    name = _SEASONAL_SUFFIX_RE.sub(r"\2 \1", name)
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.strip().lower().split())


#: quelques caractères Unicode présents dans le scrape (tiret insécable,
#: barre de fraction, flèche...) n'existent pas dans WinAnsiEncoding, le seul
#: jeu de caractères que les polices de base de reportlab (Helvetica...)
#: savent dessiner — sans ce remplacement ils s'affichent en carré noir
#: (glyphe manquant), ex. "LUMINETH REALM‑LORDS" (U+2011) dans les mots-clés.
#: Fait une fois ici, au chargement, plutôt qu'à chaque site de rendu.
_UNSUPPORTED_GLYPHS = {
    "‐": "-",
    "‑": "-",  # tiret / tiret insécable
    "⁄": "/",  # barre de fraction
    "→": "->",  # flèche
}


def sanitize_glyphs(text: str) -> str:
    for bad, good in _UNSUPPORTED_GLYPHS.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


def _read_csv(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path)
    for row in rows:
        for key, value in row.items():
            if value and any(ch in value for ch in _UNSUPPORTED_GLYPHS):
                row[key] = sanitize_glyphs(value)
    return rows


def _wound_rend_damage(row: dict[str, str]) -> dict[str, str]:
    """Blessure/Perforation/Dégâts d'une ligne `Warscrolls_weapons.csv`. Un
    `Wnd` « #N » est un `colspan` Wahapedia : l'arme n'a pas de valeur pour
    ses N colonnes (ex. Warp Lightning Blast, résolue par son aptitude) —
    affichées « - » au lieu du marqueur brut."""
    wnd = row.get("Wnd", "")
    if re.fullmatch(r"#\d+", wnd):
        return {"wound": "-", "rend": "-", "damage": "-"}
    return {"wound": wnd, "rend": row.get("Rnd", ""), "damage": row.get("Dmg", "")}


def _ability_entry(row: dict[str, str]) -> "AbilityEntry":
    """Construit une `AbilityEntry` à partir d'une ligne `Warscrolls_abilities.csv`
    ou `Faction_abilities.csv` — les deux partagent le même schéma d'aptitude
    (cf. `Export Data Specs.xlsx`)."""
    return AbilityEntry(
        name=row["name"],
        description=row["description"],
        legend=row["legend"],
        ability_type=row.get("ability_type", ""),
        is_reaction=row.get("is_reaction", "") == "true",
        condition=row.get("condition", ""),
        keywords=row.get("keywords", ""),
        ability_phase=row.get("ability_phase", ""),
        points_type=row.get("points_type", ""),
        points=row.get("points", ""),
        wahapedia_type=row.get("type_name", ""),
    )


@dataclass(frozen=True)
class AbilityEntry:
    name: str
    description: str
    legend: str
    ability_type: str = ""
    is_reaction: bool = False
    condition: str = ""
    keywords: str = ""
    ability_phase: str = ""
    points_type: str = ""
    points: str = ""
    # `type_name` de la ligne `Faction_abilities.csv` (ex. "Heroic Traits",
    # "Brazen Mutations"), vide pour une aptitude de warscroll — sert à
    # départager deux homonymes de catégories différentes dans
    # `faction_rules_fr.apply_fr_overrides` (clé `wahapedia_type` du JSON).
    wahapedia_type: str = ""
    # étiquette explicite de regroupement (cf. render/phases._ability_category) —
    # seule valeur posée aujourd'hui : "manifestation", par `set_ability_category`
    # dans pdf_builder.py pour une aptitude de convocation d'un domaine de
    # manifestations (son `points_type` seul ne suffit pas à la distinguer d'un
    # sort/d'une prière ordinaire, cf. le commentaire de `_ability_category`).
    ability_category: str = ""
    # warscroll(s) d'où vient l'aptitude, une fois sortie de sa carte d'unité
    # pour rejoindre une carte de règles par tour (mode `fr-split`, cf.
    # `pdf_builder.build_roster_pdf`) — rendu en badge dédié par
    # `render/pills._warscroll_pills`. Plusieurs noms quand la même
    # aptitude (texte identique) est portée par plusieurs unités de la liste.
    warscrolls: tuple[str, ...] = ()
    # sous-section d'affichage d'un bandeau de phase en mode `fr-split`
    # (« Règles de base », « Règles d'armée »), posée par `pdf_builder` qui
    # sait d'où vient l'aptitude — vide pour une aptitude de warscroll, rangée
    # sous le nom de son/ses warscroll(s) (cf. `render/phases.ability_section`).
    section: str = ""
    # aptitude qui ne modifie que le profil de sa propre unité, décidé sur le
    # texte Wahapedia d'origine avant tout correctif français (cf.
    # `split_pool._mark_self_profile`/`render/phases.is_self_profile_modifier`).
    self_profile: bool = False
    # rang explicite de la sous-section de l'aptitude dans son bandeau de
    # phase (mode sectionné, cf. `render/phases._section_rank`) — posé
    # uniquement par `roster_simplifications.py` (`before_spells`).
    section_rank: int | None = None
    # case pleine largeur dans la grille d'une sous-section (mode sectionné,
    # cf. `render/phases._ability_span`) — posé uniquement par
    # `split_pool._order_deploy`.
    full_width: bool = False
    # ressources de saison gagnées/dépensées, en icônes à côté des badges
    # (dé de rage, point de fureur — cf. `render/pills._resource_badges`) :
    # paires (type, valeur), ex. (("Rage", "+2"), ("Fury", "+2")). Posé par
    # le JSON (`season_rules.json`/`generic_core_abilities.json`, clé
    # `resources`).
    resources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class WeaponEntry:
    name: str
    range: str
    attacks: str
    hit: str
    wound: str
    rend: str
    damage: str
    kind: str
    abilities: str


@dataclass(frozen=True)
class WarscrollData:
    name: str
    faction_id: str
    legend: str
    role: str
    move: str
    save: str
    control: str
    health: str
    ward: str
    unit_size: str
    points: str
    keywords: list[str]
    weapons: list[WeaponEntry]
    abilities: list[AbilityEntry]
    description: str = ""  # texte libre de restriction d'arme (ex. "1/5 models
    # can replace their Warhammer with a Grandhammer") — sert à afficher un
    # ratio de porteurs discret sur l'arme concernée (cf. render/)
    # aptitude de convocation d'une manifestation (sort persistant), posée par
    # `rules_resolution.resolve_rules` — badge de lancement et note de pose
    # résumée sur la carte (cf. `render/cards.summon_placement_note`).
    summon: AbilityEntry | None = None
    # nom français affiché en petit sous le nom anglais de la carte (celui de
    # l'export de liste de l'App) — `subtitle_fr` de `faction_rules_fr.json`.
    subtitle: str = ""


@dataclass(frozen=True)
class RegimentOfRenownData:
    name: str
    legend: str
    points: str
    composition: list[str]
    abilities: list[AbilityEntry]
    faction_id: str = ""


class WahapediaLookup:
    """Charge les CSV Wahapedia utiles une fois, puis répond aux recherches
    par nom (normalisé accents/casse). Instancier une fois par appel à
    `build_roster_pdf` (`load_wahapedia`), pas par recherche."""

    def __init__(self, base_dir: str | Path = DEFAULT_WAHAPEDIA_DIR):
        self._dir = Path(base_dir)
        self._faction_abilities: list[dict[str, str]] | None = None
        self._warscrolls: list[dict[str, str]] | None = None
        self._weapons: list[dict[str, str]] | None = None
        self._abilities: list[dict[str, str]] | None = None
        self._keywords: list[dict[str, str]] | None = None
        self._organisation: list[dict[str, str]] | None = None
        self._factions: list[dict[str, str]] | None = None
        self._faction_specific_keywords: frozenset[str] | None = None

    @property
    def available(self) -> bool:
        return self._dir.exists()

    def _load(self, attr: str, filename: str) -> list[dict[str, str]]:
        cached = getattr(self, attr)
        if cached is None:
            path = self._dir / filename
            cached = _read_csv(path) if path.exists() else []
            setattr(self, attr, cached)
        return cached

    @property
    def faction_abilities(self) -> list[dict[str, str]]:
        return self._load("_faction_abilities", "Faction_abilities.csv")

    @property
    def factions(self) -> list[dict[str, str]]:
        return self._load("_factions", "Factions.csv")

    def _faction_id(self, faction_name: str) -> str | None:
        target = normalize_name(faction_name)
        for r in self.factions:
            if normalize_name(r["name"]) == target:
                return r["id"]
        return None

    def faction_name(self, faction_id: str) -> str | None:
        """Sens inverse de `_faction_id` — utilisé pour retrouver le nom de
        faction (comme `bsdata.KNOWN_ARMIES`) d'un `faction_id` brut lu dans
        un CSV (ex. `RegimentOfRenownData.faction_id`)."""
        for r in self.factions:
            if r["id"] == faction_id:
                return r["name"]
        return None

    @property
    def warscrolls(self) -> list[dict[str, str]]:
        return self._load("_warscrolls", "Warscrolls.csv")

    @property
    def weapons(self) -> list[dict[str, str]]:
        return self._load("_weapons", "Warscrolls_weapons.csv")

    @property
    def abilities(self) -> list[dict[str, str]]:
        return self._load("_abilities", "Warscrolls_abilities.csv")

    def faction_specific_keywords(self) -> frozenset[str]:
        """Valeurs d'`AbilityEntry.keywords` (ex. `Delusion`, propre aux Flesh-
        eater Courts) qui n'apparaissent que pour une seule faction dans tout
        le jeu de données — par opposition aux mots-clés génériques du cœur de
        règles (`Rampage`, `Spell`, `Deploy`...) partagés par plusieurs
        factions. Dérivé des CSV plutôt que d'une liste écrite à la main : un
        mot-clé propre à une armée le reste tant que sa faction ne le partage
        avec aucune autre dans `Warscrolls_abilities.csv` (jointe à
        `Warscrolls.csv` via `warscroll_id` pour connaître sa faction) et
        `Faction_abilities.csv` (`faction_id` déjà en colonne). Sert
        uniquement à teinter différemment le badge de ce mot-clé sur une
        carte (cf. `render/pills._keyword_pills`), jamais à filtrer quoi que
        ce soit. Normalisé en minuscules pour une comparaison insensible à la
        casse (les badges eux-mêmes affichent la valeur brute en majuscules)."""
        if self._faction_specific_keywords is None:
            faction_by_warscroll = {row["id"]: row.get("faction_id", "") for row in self.warscrolls}
            keyword_factions: dict[str, set[str]] = {}
            for row in self.abilities:
                faction_id = faction_by_warscroll.get(row.get("warscroll_id", ""), "")
                if not faction_id:
                    continue
                for kw in (row.get("keywords") or "").split(","):
                    kw = kw.strip().lower()
                    if kw:
                        keyword_factions.setdefault(kw, set()).add(faction_id)
            for row in self.faction_abilities:
                faction_id = row.get("faction_id", "")
                if not faction_id:
                    continue
                for kw in (row.get("keywords") or "").split(","):
                    kw = kw.strip().lower()
                    if kw:
                        keyword_factions.setdefault(kw, set()).add(faction_id)
            self._faction_specific_keywords = frozenset(
                kw for kw, factions in keyword_factions.items() if len(factions) == 1
            )
        return self._faction_specific_keywords

    @property
    def keywords(self) -> list[dict[str, str]]:
        return self._load("_keywords", "Warscrolls_keywords.csv")

    @property
    def organisation(self) -> list[dict[str, str]]:
        return self._load("_organisation", "Warscrolls_organisation.csv")

    # -- Domaines de sorts/manifestations génériques (faction_id == "EnS") --

    def find_generic_lore(self, lore_name: str) -> list[AbilityEntry] | None:
        target = normalize_name(lore_name.split("(", 1)[0].strip())
        rows = [
            r
            for r in self.faction_abilities
            if r["faction_id"] == _GENERIC_FACTION_ID and normalize_name(r["subtype_name"]) == target
        ]
        if not rows:
            return None
        rows.sort(key=lambda r: int(r["line"] or 0))
        return [_ability_entry(r) for r in rows]

    # -- Règles propres d'une faction normale (pas une armée de renom) --

    def find_faction_category(
        self,
        faction_name: str,
        type_name: str,
        subtype_name: str | None = None,
    ) -> list[AbilityEntry] | None:
        """Aptitudes d'une faction pour une catégorie donnée (`"Battle
        Traits"`, `"Battle Formations"`, `"Heroic Traits"`, `"Artefacts of
        Power"`...). `subtype_name` filtre en plus sur le nom précis (utile
        pour `"Battle Formations"` : chaque formation a son propre
        `subtype_name`, seule celle citée par la liste doit être incluse —
        `ParsedList.allegiance` porte ce nom, cf. `pdf_builder.py`). Sans
        `subtype_name`, renvoie toutes les lignes de la catégorie (ex. les 4
        traits de bataille d'une faction, ou la totalité de ses traits
        héroïques/artefacts disponibles — la liste ne "choisit" qu'un par
        héros, mais rien dans l'export de liste ne dit lequel va où sans
        analyse plus poussée, donc toutes les options sont incluses, comme le
        fait déjà la page de battletome copiée qu'elles remplacent)."""
        fid = self._faction_id(faction_name)
        if fid is None:
            return None
        rows = [r for r in self.faction_abilities if r["faction_id"] == fid and r["type_name"] == type_name]
        if subtype_name is not None:
            target = normalize_name(subtype_name.split("(", 1)[0].strip())
            rows = [r for r in rows if normalize_name(r["subtype_name"]) == target]
        if not rows:
            return None
        rows.sort(key=lambda r: (r["subtype_name"], int(r["line"] or 0)))
        return [_ability_entry(r) for r in rows]

    def find_unit_enhancement(self, faction_name: str, option_text: str) -> tuple[str, AbilityEntry] | None:
        """Cherche une sous-ligne ` • ... ` de l'export de liste (ex.
        "Darkflame Pendant", "Radiance of Dark Glory - (20) Points", "1x
        Pledged to Nurgle") parmi les aptitudes que la liste ne choisit
        qu'une fois puis rattache à une seule unité — Traits Héroïques,
        Artefacts de Pouvoir, Traits Monstrueux, et toute catégorie
        saisonnière propre à la faction (ex. StD "Brands of the Dark
        Gods"/"Ensorcelled Banners") — par opposition aux règles automatiques
        de toute la liste (Traits de Bataille, Formation, domaines de sorts/
        manifestations), exclues via `_ENHANCEMENT_EXCLUDED_TYPES`/
        `_ENHANCEMENT_EXCLUDED_SUBTYPES`. Les règles propres d'une armée de
        renom (ex. "Legion of the First Prince") partagent le `faction_id` de
        la faction de base dans `Faction_abilities.csv` et sont donc déjà
        couvertes sans traitement à part. Un marqueur de rôle ("General",
        "Reinforced") ou une option sans entrée Wahapedia (ex. "1x Wings",
        une option de monture) ne matche simplement rien : `None`,
        silencieusement — ce n'est pas une erreur, juste pas une optimisation.

        **Collision de nom connue (Blades of Khorne)** : Wahapedia stocke la
        Mutation d'Airain « Membres Tranchants » sous le nom anglais
        `FRENZIED TASKMASTER` -- une erreur de leur part, le vrai nom
        (visible sur la carte anglaise officielle) est `BLADE-LIMBS` ;
        confirmé par l'utilisateur via les cartes FR/EN de la faction
        (2026-09). Ce nom entre donc en collision avec le Trait Héroïque
        `Slaughterers of Thousands -> FRENZIED TASKMASTER` (un genuine
        homonyme différent), et cette fonction ne fait de correspondance que
        sur le nom -- elle ne sait pas distinguer les deux si l'un et l'autre
        apparaissent dans la même liste. `data/json/faction_rules_fr.json` garde
        `wahapedia_name: "FRENZIED TASKMASTER"` pour les deux entrées
        (c'est la seule clé qui matche réellement les données Wahapedia
        telles quelles) ; corriger `BLADE-LIMBS` dans le CSV lui-même casserait
        au prochain réimport (`aospy import wahapedia`)."""
        fid = self._faction_id(faction_name)
        if fid is None:
            return None
        key = _enhancement_option_key(option_text)
        if not key:
            return None
        target = normalize_name(key)
        matches = [
            r
            for r in self.faction_abilities
            if r["faction_id"] == fid
            and r["type_name"] not in _ENHANCEMENT_EXCLUDED_TYPES
            and r["subtype_name"] not in _ENHANCEMENT_EXCLUDED_SUBTYPES
            and normalize_name(r["name"]) == target
        ]
        if not matches:
            return None
        # Homonymes (cf. collision BoK ci-dessus) : l'App affiche « - (N)
        # Points » pour une option payante (Mutation d'Airain, Trait
        # Monstrueux...), jamais pour un Trait Héroïque/Artefact de Pouvoir.
        paid = bool(_POINTS_SUFFIX_RE.search(option_text))
        free_types = {"Heroic Traits", "Artefacts of Power"}
        r = next((m for m in matches if (m["type_name"] in free_types) != paid), matches[0])
        return _enhancement_label(r), _ability_entry(r)

    # -- Règles d'une armée de renom (ex. "Legion of the First Prince") --

    def find_renown_army_rules(self, renown_name: str) -> dict[str, list[AbilityEntry]] | None:
        """Renvoie les aptitudes d'une armée de renom, groupées par catégorie
        (« Battle Traits », « Heroic Traits », « Artefacts of Power »,
        « Spell Lore », « Manifestation Lore »...). `None` si le nom n'est
        associé à aucune ligne."""
        target = normalize_name(renown_name)
        rows = [r for r in self.faction_abilities if normalize_name(r["type_name"]) == target]
        if not rows:
            return None
        rows.sort(key=lambda r: (r["subtype_name"], int(r["line"] or 0)))
        grouped: dict[str, list[AbilityEntry]] = {}
        for r in rows:
            grouped.setdefault(r["subtype_name"], []).append(_ability_entry(r))
        return grouped

    # -- Régiments de Renom --

    def find_regiment_of_renown(self, name: str) -> RegimentOfRenownData | None:
        target = normalize_name(name)
        candidates = [
            r for r in self.warscrolls if r.get("role") == "Regiment of Renown" and normalize_name(r["name"]) == target
        ]
        if not candidates:
            return None
        # plusieurs lignes existent (une par faction pouvant inclure ce régiment) ;
        # celle de la faction d'origine porte le texte complet (legend non vide).
        row = next((r for r in candidates if r.get("legend")), candidates[0])
        composition = [org["unit"] for org in self.organisation if org["warscroll_id"] == row["id"]]
        own_abilities = [_ability_entry(a) for a in self.abilities if a["warscroll_id"] == row["id"]]
        return RegimentOfRenownData(
            name=row["name"],
            legend=row.get("legend", ""),
            points=row.get("Cost", ""),
            composition=composition,
            abilities=own_abilities,
            faction_id=row.get("faction_id", ""),
        )

    # -- Profil complet d'une unité (repli quand absente du battletome local) --

    def find_warscroll(self, name: str, *, prefer_faction: str | None = None) -> WarscrollData | None:
        """`prefer_faction` (nom de faction comme `bsdata.KNOWN_ARMIES`, pas un
        id) départage un nom ambigu entre plusieurs factions — cas réel :
        "Bloodletters" existe à la fois sous Blades of Khorne (150 pts, la
        version de base) et sous Slaves to Darkness (170 pts, `description`
        "This unit can only be taken in a Legion of the First Prince Army of
        Renown") ; sans ce paramètre, la liste "STD L3 First Prince 1980"
        affichait la charte générique Blades of Khorne au lieu de la variante
        propre à cette Armée de Renom (signalé par l'utilisateur). Ignoré si
        `None`/faction inconnue/aucun candidat de cette faction — retombe
        alors sur l'ancien comportement (premier candidat avec un `Move`
        renseigné, ordre `Warscrolls.csv`)."""
        target = normalize_name(name)
        candidates = [
            r for r in self.warscrolls if normalize_name(r["name"]) == target and r.get("role") != "Regiment of Renown"
        ]
        if not candidates:
            alias = _WARSCROLL_NAME_ALIASES.get(target)
            if alias is None:
                return None
            candidates = [
                r
                for r in self.warscrolls
                if normalize_name(r["name"]) == alias and r.get("role") != "Regiment of Renown"
            ]
            if not candidates:
                return None
        row = None
        if prefer_faction is not None:
            fid = self._faction_id(prefer_faction)
            if fid is not None:
                row = next((r for r in candidates if r["faction_id"] == fid and r.get("Move")), None)
        if row is None:
            row = next((r for r in candidates if r.get("Move")), candidates[0])
        wid = row["id"]
        weapons = [
            WeaponEntry(
                name=w["name"],
                range=w.get("Rng", ""),
                attacks=w.get("Atk", ""),
                hit=w.get("Hit", ""),
                kind=w.get("type", ""),
                abilities=w.get("abilities", ""),
                **_wound_rend_damage(w),
            )
            for w in self.weapons
            if w["warscroll_id"] == wid
        ]
        abilities = [_ability_entry(a) for a in self.abilities if a["warscroll_id"] == wid]
        # `WIZARD`/`PRIEST` portent leur niveau de magie/de prière dans la
        # colonne `parameter` (Warscrolls_keywords.csv), séparée du nom du
        # mot-clé lui-même — reconstitue le format "WIZARD (N)" que
        # `render/pills._caster_badges` reconnaît pour le badge d'en-tête,
        # plutôt que de laisser le mot-clé nu sans son niveau.
        keywords = []
        for k in self.keywords:
            if k["warscroll_id"] != wid:
                continue
            kw = k["keyword"]
            param = (k.get("parameter") or "").strip()
            if param and kw.upper() in ("WIZARD", "PRIEST"):
                kw = f"{kw} ({param})"
            keywords.append(kw)
        return WarscrollData(
            name=row["name"],
            faction_id=row["faction_id"],
            legend=row.get("legend", ""),
            role=row.get("role", ""),
            move=row.get("Move", ""),
            save=row.get("Save", ""),
            control=row.get("Control", ""),
            health=row.get("Health", ""),
            ward=row.get("Ward", ""),
            unit_size=row.get("UnitSize", ""),
            points=row.get("Cost", ""),
            keywords=keywords,
            weapons=weapons,
            abilities=abilities,
            description=row.get("description", ""),
        )


def load_wahapedia(base_dir: str | Path = DEFAULT_WAHAPEDIA_DIR) -> WahapediaLookup:
    return WahapediaLookup(base_dir)


def keyword_key(kw: str) -> str:
    # ignore la casse et un simple "s" de pluriel — une aptitude "Ensorcelled
    # Banners" (StD) porte déjà "Ensorcelled Banner" (singulier) dans son
    # propre `keywords` Wahapedia ; sans ce rapprochement, l'étiquetage
    # d'origine ajoutait un second badge quasi identique à côté du premier.
    return kw.strip().lower().rstrip("s")


def tag_ability_origin(abilities: list[AbilityEntry], origin_label: str) -> list[AbilityEntry]:
    """Ajoute `origin_label` (« Traits de Bataille », « Formation »...) au
    champ `keywords` de chaque aptitude — il en ressort comme un badge doré
    de plus à côté des mots-clés d'aptitude déjà présents, cf. `_name_line`/
    `_ability_row_flowables`. Un badge de carte aurait disparu si les
    aptitudes de plusieurs catégories se retrouvent réunies sur une seule
    carte (cf. `render_rule_card`) ou rejoignent la carte d'un héros ; un
    badge d'aptitude, lui, survit au déplacement. N'ajoute rien si un
    mot-clé quasi identique (cf. `keyword_key`) figure déjà — une aptitude
    dont Wahapedia porte déjà le nom de catégorie en mot-clé ne doit pas
    aussi le recevoir en badge d'origine, sous peine de deux badges
    redondants côte à côte."""
    target = keyword_key(origin_label)
    # mot-clé anglais Wahapedia dont `origin_label` est la traduction (ex.
    # « Ensorcelled Banner » pour « Bannière Ensorcelée ») : remplacé par le
    # badge d'origine plutôt que gardé à côté (même redondance, en 2 langues).
    translated = {
        keyword_key(en) for en, spec in _ENHANCEMENT_CATEGORY_LABELS.items() if keyword_key(spec["label"]) == target
    }
    result = []
    for ab in abilities:
        existing = [kw.strip() for kw in ab.keywords.split(",") if kw.strip()] if ab.keywords else []
        if any(keyword_key(kw) == target for kw in existing):
            result.append(ab)
            continue
        kept = [kw for kw in existing if keyword_key(kw) not in translated]
        result.append(replace(ab, keywords=",".join(kept + [origin_label])))
    return result

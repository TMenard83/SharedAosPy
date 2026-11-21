"""Chargement de `data/json/roster_simplifications.json` — simplifications propres
à *une* liste (mode `fr-split-simple`), dictées puis validées une à une par
l'utilisateur : aptitudes de synthèse ajoutées à une unité (ex. « Jet de
Lancement » de l'Illumineur, qui résume Baguette d'Argent + Érudit des
Sceaux + Shrine Luminor + Rune d'Enthlaï) et aptitudes qu'elles remplacent,
retirées du document. Clé = nom du fichier de liste sans suffixe. Chargeur
pur, pas de DB, relu à froid à chaque appel (même convention que
`season_rules.py`)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from .faction_rules_fr import ability_join_key
from .wahapedia_lookup import AbilityEntry

DEFAULT_ROSTER_SIMPLIFICATIONS_FILE = Path("data") / "json" / "roster_simplifications.json"

#: sous-texte d'une aptitude de synthèse (provenance), petit et gris pour ne
#: pas être mis en valeur.
_NOTE_MARKUP = '<br/><font size="6" color="#8a8a8a">{}</font>'


#: rang de sous-section entre les règles de base/d'armée/de choix (0-2) et
#: les Sorts (3), cf. `render/phases._SECTION_RANK`.
_BEFORE_SPELLS_RANK = 2


#: caractéristiques d'arme qu'une liste peut surcharger (`units.<unité>.weapons`).
_WEAPON_FIELDS = frozenset({"range", "attacks", "hit", "wound", "rend", "damage"})

#: caractéristiques d'un warscroll qu'une liste peut surcharger (`units.<unité>.stats`).
_STAT_FIELDS = frozenset({"move", "save", "control", "health", "ward", "points"})


#: « Annonce » d'un sort/d'une convocation (`_compress_spell_declare`).
_DECLARE_RE = re.compile(r"(<b>Annonce :</b>\s*)((?:(?!<br/>).)*)((?:<br/>)*)", re.S)
_ONE_PER_TYPE_RE = re.compile(r"S[’']il n[’']y a pas d.*? sur le champ de bataille,\s*", re.S)
_PICK_CASTER_RE = re.compile(
    r"[Cc]hoisissez un (?:<b>)?Sorcier[^,]*? ami pour (?:lancer|qu[’']il lance) ce sort,?\s*(?:puis\s+)?"
)
#: « …la cible. Puis faites un jet de lancement de 2D6. » : la phrase entière part.
_CASTING_ROLL_SENTENCE_RE = re.compile(r"(?<=\.)\s*Puis faites un jet de lancement de 2D6\.")
_CASTING_ROLL_RE = re.compile(r",?\s*(?:puis |et )?[Ff]aites un jet de lancement de 2D6")
#: ponctuation laissée en tête d'Annonce après retrait du lanceur et du jet.
_LEADING_PUNCT_RE = re.compile(r"^[\s.,;]+")
_PICK_TARGET_RE = re.compile(r"^[Cc]hoisissez comme cible\s+")


def _compress_spell_declare(description: str) -> str:
    """« Annonce » d'un sort réduite à sa cible (demande de l'utilisateur) :
    on sait que c'est un Sorcier qui lance, à 2D6, et qu'il n'y a qu'un sort
    persistant de chaque type — seuls la cible et ce qui s'y ajoute (malus au
    jet...) restent ; l'Effet (règles de placement comprises) est intact. Un
    jet de lancement autre que 2D6 laisse l'Annonce telle quelle."""

    def compress(m: re.Match) -> str:
        seg = m.group(2)
        if "jet de lancement de 2D6" not in seg:
            return m.group(0)
        seg = _ONE_PER_TYPE_RE.sub("", seg)
        seg = _PICK_CASTER_RE.sub("", seg)
        seg = _CASTING_ROLL_SENTENCE_RE.sub("", seg)
        seg = _LEADING_PUNCT_RE.sub("", _CASTING_ROLL_RE.sub("", seg).strip())
        seg = seg.replace(" de lui", " du lanceur")
        if seg in ("", "."):
            return ""  # plus rien à annoncer : l'Annonce disparaît
        if _PICK_TARGET_RE.match(seg):
            return "<b>Cible :</b> " + _PICK_TARGET_RE.sub("", seg) + m.group(3)
        return m.group(1) + seg[0].upper() + seg[1:] + m.group(3)

    return _DECLARE_RE.sub(compress, description, count=1)


_PICK_PRIEST_RE = re.compile(
    r"[Cc]hoisissez un (?:<b>)?Prêtre[^,]*? (?:ami )?pour (?:réciter|qu[’']il récite) cette prière,?\s*"
)
_CHANTING_ROLL_RE = re.compile(r",?\s*(?:puis |et )?[Ff]aites un jet de récitation (?:d[’']un|de) D6")
#: « S'il n'y a pas de / aucune / pas un X ami sur le champ de bataille »
#: d'une convocation par prière (formulations plus variées que les sorts).
_ONE_PER_TYPE_PRAYER_RE = re.compile(r"S[’']il n[’']y a (?:pas|aucune?)\b.*? sur le champ de bataille,\s*", re.S)


def _compress_prayer_declare(description: str) -> str:
    """Pendant de `_compress_spell_declare` pour une prière : « un Prêtre
    récite, à 1D6 » est sous-entendu, seule la cible reste. Un Prêtre précis
    (« Choisissez le Prêtre du Carnage de ce Régiment de Renom ») n'est pas
    un Prêtre quelconque : l'Annonce est alors laissée telle quelle."""

    def compress(m: re.Match) -> str:
        seg = m.group(2)
        if not (_PICK_PRIEST_RE.search(seg) and _CHANTING_ROLL_RE.search(seg)):
            return m.group(0)
        seg = _ONE_PER_TYPE_PRAYER_RE.sub("", seg)
        seg = _PICK_PRIEST_RE.sub("", seg)
        seg = _LEADING_PUNCT_RE.sub("", _CHANTING_ROLL_RE.sub("", seg).strip())
        seg = seg.replace(" de lui", " du Prêtre")
        if seg in ("", "."):
            return ""
        if _PICK_TARGET_RE.match(seg):
            return "<b>Cible :</b> " + _PICK_TARGET_RE.sub("", seg) + m.group(3)
        return m.group(1) + seg[0].upper() + seg[1:] + m.group(3)

    return _DECLARE_RE.sub(compress, description, count=1)


_PICK_TARGETS_RE = re.compile(r"^[Cc]hoisissez comme (cibles?(?:\s+(?:ennemie|amie)s?)?)\s+")


def _compress_declare(description: str) -> str:
    """« Annonce : Choisissez comme cible(s) X » de n'importe quelle aptitude
    -> « Cible(s) : X » (demande de l'utilisateur, principe 17 de
    `data/roster_simplifications.md`). Une Annonce qui commence autrement
    (« Choisissez un Prince Démon ami pour… », « Si… ») reste telle quelle."""

    def compress(m: re.Match) -> str:
        seg = m.group(2).strip()
        t = _PICK_TARGETS_RE.match(seg)
        if t is None:
            return m.group(0)
        label = t.group(1)[0].upper() + t.group(1)[1:]  # « Cible ennemie »
        return f"<b>{label} :</b> " + seg[t.end() :] + m.group(3)

    return _DECLARE_RE.sub(compress, description, count=1)


_TARGET_LABEL_RE = re.compile(r"<b>(?:Cibles?|Targets?)\s?:</b>", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"\.[ \t]+(?=(?:<[bi]>)?[A-ZÀ-ÖØ-Þ0-9+−-])")
_BREAK_RE = re.compile(r"<br\s*/?>|<ul>|<li>", re.IGNORECASE)


def _break_after_target(description: str) -> str:
    """Retour à la ligne après la phrase « Cible(s) : … » / « Target(s): … »
    quand le texte suivant continue sur la même ligne (règle générale des
    modes `*-split-simple`, demande de l'utilisateur : la cible se lit d'un
    coup d'œil, l'effet commence sur sa propre ligne)."""
    out, pos = [], 0
    for m in _TARGET_LABEL_RE.finditer(description):
        if m.start() < pos:
            continue
        end = _SENTENCE_END_RE.search(description, m.end())
        stop = _BREAK_RE.search(description, m.end())
        if end is None or (stop is not None and stop.start() <= end.start()):
            continue
        out.append(description[pos : end.start() + 1] + "<br/>")
        pos = end.end()
    return "".join(out) + description[pos:]


def _with_keyword(keywords: str, extra: str) -> str:
    if extra.lower() in {k.strip().lower() for k in (keywords or "").split(",")}:
        return keywords
    return f"{keywords}, {extra}" if keywords else extra


@dataclass(frozen=True)
class RosterSimplifications:
    #: nom d'unité (tel qu'écrit dans la liste) -> aptitudes ajoutées
    unit_abilities: dict[str, list[AbilityEntry]] = field(default_factory=dict)
    #: clés `ability_join_key` (nom anglais Wahapedia ou nom français) des
    #: aptitudes retirées du document
    removed: frozenset[str] = frozenset()
    #: option ` • ...` de la liste -> libellé affiché sur la page de garde
    #: (ex. préciser la rune choisie d'Érudit des Sceaux) ; la résolution des
    #: optimisations continue de lire l'option d'origine.
    option_labels: dict[str, str] = field(default_factory=dict)
    #: aptitudes (nom EN ou FR) qui restent sur leur carte de warscroll plutôt
    #: que de rejoindre les cartes de tour (ex. « Plusieurs Parties » d'une
    #: manifestation : on s'y intéresse en regardant son châssis).
    keep_on_warscroll: frozenset[str] = frozenset()
    #: warscrolls (nom de carte) placés en tête des cartes, dans cet ordre —
    #: les cartes allant 2 par ligne, sert à apparier 2 cartes de hauteurs
    #: proches (ex. Avalenor + Alarith Spirit of the Mountain) ; les autres
    #: suivent dans leur ordre habituel.
    warscroll_order: tuple[str, ...] = ()
    #: clé de bandeau de phase (`render/phases._PHASE_ORDER`, ex. "hero") ->
    #: titres de sous-section (nom d'unité) placés en tête de ce bandeau, dans
    #: cet ordre (ex. Skreech, dont « Le Rat aux Treize Têtes » se choisit
    #: avant les sorts de Thanquol).
    section_order: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: clé `ability_join_key` du nom -> texte de remplacement (ex. runes
    #: réordonnées/retirées d'« Inscription de Rune ») ; la section
    #: `all_lists` en porte aussi (règle générale compressée, ex. « Éruption
    #: de Fureur »), qu'une liste peut surcharger.
    description_overrides: dict[str, str] = field(default_factory=dict)
    #: clé `ability_join_key` du nom -> mots-clés ajoutés (ex. badge
    #: « Simple » d'une règle de base déjà compressée) ; vient surtout de la
    #: section `all_lists`, commune à toutes les listes.
    add_keywords: dict[str, str] = field(default_factory=dict)
    #: clé `ability_join_key` du nom -> `ability_phase`(s) remplaçant(s)
    #: (vocabulaire Wahapedia, ex. "Movement Phase", ou une liste : une copie
    #: par phase) : une aptitude dont la version simplifiée ne garde que des
    #: effets de phases précises (FEC « A Splendid Pageant » -> Mouvement,
    #: « The One True King » -> Mouvement + Charge) quitte le bandeau
    #: « N'importe quelle phase ». Appliqué après les sous-sections de choix
    #: (`expand_phases`) : la copie de sous-section (Délires) reste unique.
    phase_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: clé `ability_join_key` du nom -> `condition` remplaçante (timing
    #: Wahapedia, ex. « Faim Dévorante » des Mâchoires de Ravenak : « Any
    #: Charge Phase » -> « Your Charge Phase », une manifestation ne chargeant
    #: qu'à votre phase de charge) : retire l'aptitude de la carte de tour où
    #: elle ne peut pas servir.
    condition_overrides: dict[str, str] = field(default_factory=dict)
    #: « Annonce » des sorts/convocations réduite à la cible
    #: (`_compress_spell_declare`).
    compress_spell_declare: bool = False
    #: idem pour les prières (`_compress_prayer_declare`).
    compress_prayer_declare: bool = False
    #: « Annonce : Choisissez comme cible X » de toute autre aptitude ->
    #: « Cible : X » (`_compress_declare`).
    compress_declare: bool = False
    #: clé `ability_join_key` de l'aptitude fusionnée -> (clé de l'aptitude
    #: qui l'absorbe, texte fusionné) ; section `all_lists` (ex. « Musicien »
    #: dans « Ralliement »). Ne joue que si l'aptitude fusionnée est présente
    #: (liste sans musicien -> « Ralliement » inchangé).
    merge_into: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: section `all_lists` : « Règles de base » en dernière sous-section de
    #: chaque bandeau de phase des cartes de tour (hors Déploiement/Début de
    #: Round, qui suivent le déroulé), cf. `render_rule_card(base_last=...)`.
    base_rules_last: bool = False
    #: nom d'unité -> {clé `ability_join_key` -> texte} : comme
    #: `description_overrides`, mais limité aux aptitudes de cette unité (ex.
    #: copie de « Voué à Nurgle » sur le Prince Démon réduite à « Appliqué »,
    #: la règle d'armée du même nom restant intacte).
    unit_description_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    #: nom d'unité -> caractéristiques affichées remplacées (`move`/`save`/
    #: `control`/`health`/`ward`/`points`), ex. Protection déjà améliorée par un
    #: vœu, points d'une unité avec son optimisation payante.
    unit_stats: dict[str, dict[str, str]] = field(default_factory=dict)
    #: nom d'unité -> mots-clés d'unité ajoutés à sa carte (ex. « WIZARD (1) »
    #: sur The Oathsworn Kin, sorcier par Nadja l'Éraillée — inexact au sens
    #: strict, le texte de l'aptitude le précise ; donne le badge Sorcier).
    unit_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: nom d'unité -> {nom d'arme tel qu'affiché sur la carte -> caractéristiques
    #: remplacées (`attacks`/`hit`/`wound`/`rend`/`damage`/`range`)} : un
    #: bonus permanent déjà compté sur le profil (« Voué à Khorne » *Appliqué*
    #: : +1 A à la Cursed Lance). Jamais sur une arme `Companion`, qui ne
    #: profite d'aucun bonus sauf mention explicite.
    unit_weapons: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    #: nom affiché -> (unité de la liste, options ` • ...` qui la désignent) :
    #: une entrée de la liste traitée comme un Héros à part, sous ce nom (ex.
    #: le Verminlord Warbringer qui porte Foulhide + Short-tempered, distinct
    #: des 2 autres Warbringers sans optimisation) — sa propre carte, ses
    #: propres pastilles d'unité.
    unit_aliases: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)

    def merge(self, pool: list[AbilityEntry]) -> list[AbilityEntry]:
        """Applique `merge_into` : l'aptitude fusionnée sort du bassin, celle
        qui l'absorbe prend le texte fusionné."""
        present = {ability_join_key(ab.name) for ab in pool}
        targets = {into: text for src, (into, text) in self.merge_into.items() if src in present and into in present}
        if not targets:
            return pool
        merged_sources = {src for src, (into, _) in self.merge_into.items() if into in targets}
        out = []
        for ab in pool:
            key = ability_join_key(ab.name)
            if key in merged_sources:
                continue
            out.append(replace(ab, description=targets[key]) if key in targets else ab)
        return out

    def expand_phases(self, pool: list[AbilityEntry], is_choice_copy) -> list[AbilityEntry]:
        """Applique `phase_overrides` (une copie par phase) aux aptitudes du
        bassin, sauf aux copies de sous-section de choix (`is_choice_copy`)."""
        out = []
        for ab in pool:
            phases = None if is_choice_copy(ab) else self.phase_overrides.get(ability_join_key(ab.name))
            out.extend([ab] if phases is None else [replace(ab, ability_phase=ph) for ph in phases])
        return out

    def is_removed(self, ab: AbilityEntry) -> bool:
        """Une aptitude de synthèse ajoutée n'est jamais retirée, même si elle
        reprend le nom d'une aptitude qu'elle remplace (« Gardien du Temple »)."""
        if any(ab == added for added_list in self.unit_abilities.values() for added in added_list):
            return False
        return ability_join_key(ab.name) in self.removed

    def rewrite(self, ab: AbilityEntry) -> AbilityEntry:
        key = ability_join_key(ab.name)
        new = self.description_overrides.get(key)
        if new is not None:
            ab = replace(ab, description=new)
        condition = self.condition_overrides.get(key)
        if condition is not None:
            ab = replace(ab, condition=condition)
        if self.compress_spell_declare and (ab.points_type or "").strip() == "Spell":
            compressed = _compress_spell_declare(ab.description)
            if compressed != ab.description:
                # texte compressé : plus le verbatim de sa source (badge SIMPLE)
                ab = replace(ab, description=compressed, keywords=_with_keyword(ab.keywords, "Simple"))
        if self.compress_prayer_declare and (ab.points_type or "").strip() == "Prayer":
            compressed = _compress_prayer_declare(ab.description)
            if compressed != ab.description:
                ab = replace(ab, description=compressed, keywords=_with_keyword(ab.keywords, "Simple"))
        if self.compress_declare:
            compressed = _compress_declare(ab.description)
            if compressed != ab.description:
                ab = replace(ab, description=compressed, keywords=_with_keyword(ab.keywords, "Simple"))
        extra = self.add_keywords.get(key)
        if extra:
            ab = replace(ab, keywords=_with_keyword(ab.keywords, extra))
        return replace(ab, description=_break_after_target(ab.description))

    def rewrite_unit(self, unit: str, ab: AbilityEntry) -> AbilityEntry:
        new = self.unit_description_overrides.get(unit, {}).get(ability_join_key(ab.name))
        return ab if new is None else replace(ab, description=_break_after_target(new))

    def keeps_on_warscroll(self, ab: AbilityEntry) -> bool:
        return ability_join_key(ab.name) in self.keep_on_warscroll


def load_roster_simplifications(
    list_name: str,
    path: str | Path = DEFAULT_ROSTER_SIMPLIFICATIONS_FILE,
    lang: str = "fr",
) -> RosterSimplifications:
    """Fichier absent -> aucune simplification. La section `all_lists`
    s'applique à toute liste en `fr-split-simple`, `lists.<nom>` en plus à
    celle-ci seulement. `lang="en"` (`en-split-simple`) lit la section `en`
    du fichier, de même forme (`en.all_lists`, `en.lists`) : les mêmes
    simplifications que le français, réécrites en anglais."""
    p = Path(path)
    if not p.exists():
        return RosterSimplifications()
    data = json.loads(p.read_text(encoding="utf-8"))
    if lang == "en":
        data = data.get("en", {})
    common = data.get("all_lists", {})
    entry = data.get("lists", {}).get(list_name) or {}
    unit_abilities = {
        unit: [
            AbilityEntry(
                name=row["name"],
                description=row["description"] + (_NOTE_MARKUP.format(row["note"]) if row.get("note") else ""),
                legend="",
                condition=row.get("condition", ""),
                keywords=row.get("keywords", ""),
                ability_phase=row.get("ability_phase", ""),
                section_rank=_BEFORE_SPELLS_RANK if row.get("before_spells") else None,
            )
            for row in spec.get("add_abilities", [])
        ]
        for unit, spec in entry.get("units", {}).items()
    }
    removed = frozenset(ability_join_key(n) for n in entry.get("remove_abilities", []))
    add_keywords = {**common.get("add_keywords", {}), **entry.get("add_keywords", {})}
    return RosterSimplifications(
        unit_abilities=unit_abilities,
        removed=removed,
        option_labels=dict(entry.get("option_labels", {})),
        description_overrides={
            ability_join_key(k): v
            for k, v in {**common.get("description_overrides", {}), **entry.get("description_overrides", {})}.items()
        },
        add_keywords={ability_join_key(k): v for k, v in add_keywords.items()},
        condition_overrides={ability_join_key(k): v for k, v in entry.get("condition_overrides", {}).items()},
        phase_overrides={
            ability_join_key(k): (v,) if isinstance(v, str) else tuple(v)
            for k, v in entry.get("phase_overrides", {}).items()
        },
        compress_spell_declare=bool(common.get("compress_spell_declare") or entry.get("compress_spell_declare")),
        compress_prayer_declare=bool(common.get("compress_prayer_declare") or entry.get("compress_prayer_declare")),
        compress_declare=bool(common.get("compress_declare") or entry.get("compress_declare")),
        warscroll_order=tuple(entry.get("warscroll_order", [])),
        section_order={k: tuple(v) for k, v in entry.get("section_order", {}).items()},
        keep_on_warscroll=frozenset(ability_join_key(n) for n in entry.get("keep_on_warscroll", [])),
        merge_into={
            ability_join_key(src): (ability_join_key(spec["into"]), spec["description"])
            for src, spec in common.get("merge_into", {}).items()
        },
        unit_description_overrides={
            unit: {ability_join_key(k): v for k, v in spec.get("description_overrides", {}).items()}
            for unit, spec in entry.get("units", {}).items()
            if spec.get("description_overrides")
        },
        unit_stats={
            unit: {k: v for k, v in spec["stats"].items() if k in _STAT_FIELDS}
            for unit, spec in entry.get("units", {}).items()
            if spec.get("stats")
        },
        unit_keywords={
            unit: tuple(spec["add_unit_keywords"])
            for unit, spec in entry.get("units", {}).items()
            if spec.get("add_unit_keywords")
        },
        unit_weapons={
            unit: {
                name: {k: str(v) for k, v in stats.items() if k in _WEAPON_FIELDS}
                for name, stats in spec["weapons"].items()
            }
            for unit, spec in entry.get("units", {}).items()
            if spec.get("weapons")
        },
        unit_aliases={
            alias: (spec["unit"], tuple(spec.get("options", [])))
            for alias, spec in entry.get("unit_aliases", {}).items()
        },
        base_rules_last=bool(common.get("base_rules_last")),
    )


def compress_tactic_conditions_enabled(path: str | Path = DEFAULT_ROSTER_SIMPLIFICATIONS_FILE) -> bool:
    """`all_lists.compress_tactic_conditions` : condition des sous-tactiques
    des cartes de tactique raccourcie (`tactic_cards.compress_tactic_conditions`)
    — les cartes sont résolues avant de connaître la liste, d'où une lecture
    de la seule section commune."""
    p = Path(path)
    if not p.exists():
        return False
    return bool(json.loads(p.read_text(encoding="utf-8")).get("all_lists", {}).get("compress_tactic_conditions"))

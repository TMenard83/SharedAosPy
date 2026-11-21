"""Pastilles et badges : `_pill`, conditions/fréquences/réactions, coûts (`_CastBadge`), mots-clés, warscrolls, légendes."""

from __future__ import annotations

import math
import re
from dataclasses import replace as _dc_replace

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, Spacer, Table, TableStyle

from ..sources.wahapedia_lookup import AbilityEntry
from .options import render_options, render_tracker
from .phases import (
    _BAND_ONLY_CONDITIONS,
    _CAST_SECTIONS,
    _CASTER_KW_RE,
    _CHOICE_CATEGORY_KEYWORDS,
    _FREQ_RE,
    _WIELDER_RATIO_RE,
    CHOICE_CATEGORIES,
    _ability_category,
    _frequency_label,
    _normalize_condition,
    _plain_condition,
    _qualifier_label,
)
from .text import (
    _KEYWORD_LABELS_FR,
    _clean_text,
    _safe_paragraph,
    tr,
)
from .theme import (
    _BADGE_BLOOD,
    _BADGE_COMMAND,
    _BADGE_FACTION,
    _BADGE_FURY,
    _BADGE_KEYWORD,
    _BADGE_MULTI_PHASE,
    _BADGE_NEUTRAL,
    _BADGE_PRAYER,
    _BADGE_RAGE,
    _BADGE_REACT,
    _BADGE_SEASON,
    _BADGE_SOURCE,
    _BADGE_SPELL,
    _BADGE_WARSCROLL,
    _PHASE_COLORS,
    _STEEL_LINE,
)

#: Police/taille des badges pleins (fréquence, condition, mot-clé...),
#: partagée par `_pill_natural_width` pour mesurer un texte *avant* de
#: construire la pastille — `Table.wrap(0, 0)` avait été essayé pour ça, mais
#: `wrap` avec une largeur disponible nulle force un `Paragraph` à se
#: réenligner sur son mot le plus long (le seul moyen pour lui de tenir dans
#: 0pt de large), ce qui renvoyait une largeur "naturelle" bien plus petite
#: que la vraie largeur sur une ligne — le badge gardait alors `width=None`
#: (jugé à tort assez court pour `max_width`) mais se faisait quand même
#: réenligner au rendu final, cette fois contraint par la vraie largeur de
#: colonne disponible (ex. "MA PHASE" coupé en "MA PH"/"ASE"). Mesurer la
#: largeur d'une ligne non enroulée avec `stringWidth` directement (comme
#: `_min_rail_height` le fait déjà pour le bandeau de phase) évite le
#: problème : jamais de `wrap()` avant que la largeur réelle ne soit connue.
_PILL_FONT = "Helvetica"
_PILL_FONT_SIZE = 6.6
_PILL_H_PADDING = 10  # LEFTPADDING + RIGHTPADDING de `_pill` (5 + 5)
_PILL_RADIUS = 4  # rayon des coins arrondis d'une pastille (`ROUNDEDCORNERS`)
#: marge de sécurité ajoutée à `_pill_natural_width` : sans elle, la largeur
#: passée en `colWidths` au `Paragraph` interne (largeur - `_PILL_H_PADDING`)
#: retombe exactement sur `stringWidth`, et une simple erreur d'arrondi flottant
#: (`36.4066 - 10 == 26.406599999999997 < 26.4066`) suffit alors à faire
#: réenligner le texte sur 2 lignes ("FRAPPE" -> "FRAPP"/"E") alors qu'il tient
#: très exactement sur une — vu en le comparant à un rendu sans cette marge.
_PILL_WIDTH_SLACK = 0.75


def _pill_natural_width(text: str) -> float:
    return stringWidth(text, _PILL_FONT, _PILL_FONT_SIZE) + _PILL_H_PADDING + _PILL_WIDTH_SLACK


def _reaction_trigger(ability: AbilityEntry) -> str | None:
    """Déclencheur d'une réaction (texte après « Reaction: »), `None` si
    l'aptitude n'en est pas une. Le préfixe de fréquence précède parfois
    "Reaction:" dans le même champ (ex. "Once Per Turn (Army), Reaction:
    ...") — la fréquence est déjà extraite à part par `_freq_pill`, tout ce
    qui précède "Reaction:" est jeté plutôt que de le montrer en double."""
    condition = (ability.condition or "").strip()
    if not condition or not (ability.is_reaction or "reaction:" in condition.lower()):
        return None
    return _translate_trigger(_clean_text(re.sub(r"^.*?reaction:\s*", "", condition, flags=re.IGNORECASE)).strip())


#: types d'aptitude cités par un déclencheur de réaction Wahapedia
_TRIGGER_ABILITY_FR = {
    "fight": "Corps à Corps",
    "shoot": "Tir",
    "charge": "Charge",
    "move": "Mouvement",
    "run": "Course",
    "retreat": "Repli",
    "spell": "Sort",
    "unlimited spell": "Sort Illimité",
    "prayer": "Prière",
    "attack": "Attaque",
    "rampage": "Rampage",
}
_TRIGGER_HEADS = [
    (re.compile(r"^You declared an? (?P<kw>[\w ]+?) ability", re.IGNORECASE), "Vous avez annoncé une aptitude"),
    (
        re.compile(r"^Opponent declared an? (?P<kw>[\w ]+?) ability", re.IGNORECASE),
        "L’adversaire a annoncé une aptitude",
    ),
]
_TRIGGER_TAILS = [
    (re.compile(r"^ for this unit\.?$"), " pour cette unité"),
    (re.compile(r"^ for your general\.?$"), " pour votre général"),
    (re.compile(r'^ for a unit within (\d+)" of this unit\.?$'), r' pour une unité à \1" de cette unité'),
    (
        re.compile(r'^ for a friendly unit wholly within (\d+)" of this unit\.?$'),
        r' pour une unité amie entièrement à \1" de cette unité',
    ),
    (re.compile(r"^\.?$"), ""),
]


def _translate_trigger(text: str) -> str:
    """Déclencheur anglais de Wahapedia (« You declared a FIGHT ability for
    this unit ») traduit quand il suit entièrement un schéma connu (début +
    type d'aptitude + fin) ; sinon laissé tel quel — jamais de
    demi-traduction."""
    if render_options().english_labels:
        return text
    plain = re.sub(r"<[^>]+>", "", text).strip()
    for head_re, head_fr in _TRIGGER_HEADS:
        m = head_re.match(plain)
        if not m:
            continue
        kw = _TRIGGER_ABILITY_FR.get(m.group("kw").strip().lower())
        rest = plain[m.end() :]
        for tail_re, tail_fr in _TRIGGER_TAILS:
            if kw is not None and tail_re.match(rest):
                of = "d’" if kw[0] in "AEIOUÉ" else "de "
                return f"{head_fr} {of}{kw}{tail_re.sub(tail_fr, rest)}"
        return text
    m = _NAMED_TRIGGER_RE.match(plain)
    if m:
        name = _TRIGGER_NAMED_FR.get(m.group("name").strip().lower())
        rest = plain[m.end() :]
        for tail_re, tail_fr in _TRIGGER_TAILS:
            if name is not None and tail_re.match(rest):
                return f"{_TRIGGER_WHO_FR[m.group('who').lower()]} « {name} »{tail_re.sub(tail_fr, rest)}"
    return text


#: réaction à une aptitude *nommée* (« You or your opponent declared the
#: ‘Eruption of Fury’ ability… ») : traduite seulement si le nom est connu
_NAMED_TRIGGER_RE = re.compile(
    r"^(?P<who>You or your opponent|You|Your opponent|Opponent) declared the [‘'’\"](?P<name>[^‘'’\"]+)[‘'’\"] ability",
    re.IGNORECASE,
)
_TRIGGER_WHO_FR = {
    "you or your opponent": "Vous ou l’adversaire avez annoncé",
    "you": "Vous avez annoncé",
    "your opponent": "L’adversaire a annoncé",
    "opponent": "L’adversaire a annoncé",
}
_TRIGGER_NAMED_FR = {"eruption of fury": "Éruption de Fureur"}


def _condition_pill(ability: AbilityEntry, max_width: float) -> tuple[Table, float] | None:
    """Le pendant `condition` (passif / réaction / qualificatif / brut) de
    `_freq_pill` — une seule pastille pleine, en pastille à liseré pour la
    réaction (elle reste la seule à porter *toujours* du texte de règle
    verbatim, donc potentiellement long — forcée à `max_width` pour se
    réenligner au lieu de déborder). Les autres badges (PASSIF, qualificatif,
    brut) se taillent d'abord sur leur propre contenu, comme les pastilles de
    mot-clé (`_keyword_pills`) — sans quoi le fond peint de la pastille
    s'étirait sur toute `max_width` même pour un texte court ("PASSIF").
    `max_width` ne sert de garde-fou (repli sur la même largeur forcée que la
    réaction) que si ce contenu se révèle malgré tout trop large une fois
    mesuré — un `condition` brut hors du vocabulaire couvert par
    `_PLAIN_CONDITION_FR` peut en théorie être long. La largeur renvoyée à
    côté de la pastille est celle réellement occupée (`max_width` si forcée,
    sinon la largeur naturelle) — c'est ce que `_pack_badges` utilise pour
    décider si la pastille suivante tient sur la même ligne."""
    condition = (ability.condition or "").strip()
    if not condition:
        return None
    trigger = _reaction_trigger(ability)
    if trigger is not None:
        if render_options().sectioned:
            return None  # ligne en tête du texte, cf. `_ability_row_flowables`
        pill = _pill(f"<b>{tr('Réaction :')}</b> {trigger}", _BADGE_REACT, "#fbeaec", width=max_width, outline=True)
        return pill, max_width
    if condition.lower() == "passive" or condition.lower().startswith("passive ("):
        text = "PASSIF"
    elif _FREQ_RE.fullmatch(_normalize_condition(condition)):
        return None  # fréquence seule, déjà portée par `_freq_pill` (ex. « Light A Pyre »)
    else:
        qual = _qualifier_label(condition)
        if qual and render_options().hide_turn_qualifier:
            return None
        text = qual.upper() if qual else (_plain_condition(_normalize_condition(condition)) or condition.upper())
    if text in _BAND_ONLY_CONDITIONS:
        return None
    text = tr(text)
    natural = _pill_natural_width(text)
    if natural > max_width:
        return _pill(text, _BADGE_NEUTRAL, "#eaf1f8", width=max_width, outline=True), max_width
    return _pill(text, _BADGE_NEUTRAL, "#eaf1f8", width=None, outline=True), natural


def _freq_pill(ability: AbilityEntry, max_width: float) -> tuple[Table, float] | None:
    freq = _frequency_label(ability.condition or "")
    if not freq:
        return None
    natural = _pill_natural_width(freq)
    if natural > max_width:
        return _pill(freq, _BADGE_NEUTRAL, "#eaf1f8", width=max_width, outline=True), max_width
    return _pill(freq, _BADGE_NEUTRAL, "#eaf1f8", width=None, outline=True), natural


#: Traduction du `points_type` d'une aptitude (Warscrolls_abilities.csv /
#: Faction_abilities.csv) vers le libellé de repli de sa pastille (utilisé
#: seulement quand l'aptitude ne porte aucune valeur numérique, cf.
#: `_cast_pill`) et vers la forme/couleur de son badge sinon — le
#: cercle/losange/hexagone de l'éditeur BattleScribe/Warhammer Age of
#: Sigmar: The App (cf. `_CastBadge`), qu'aucun badge ne portait encore ici
#: (perdu en repartant du prototype HTML, qui n'avait qu'une pastille
#: rectangulaire générique). `points` est la valeur d'incantation/de prière
#: ("7" -> "7+" à lancer) pour les deux premiers, un coût brut (en PC ou en
#: points de sang) pour "Command"/"Blood tithe" — jamais un seuil "+".
#: RÈGLE : chaque `points_type` a sa propre silhouette — deux types ne
#: partagent jamais une forme (vérifié par
#: `test_cast_badge_shapes_are_unique`), sinon un joueur les confond d'un
#: coup d'oeil. La couleur seule ne suffit pas (impression N&B, daltonisme).
#: "Blood tithe" (points_type de Faction_abilities.csv, propre aux Blades of
#: Khorne) n'a pas encore de faction important son armée depuis Wahapedia,
#: mais la donnée existe déjà dans le CSV — le badge est câblé par
#: anticipation plutôt que laissé en `_BADGE_KEYWORD` générique.
#: "Rage"/"Fury" (dés de rage/points de fureur des Règles de Saison 2026-27)
#: ne sont pas des `points_type` mais des ressources gagnées ou dépensées
#: (`AbilityEntry.resources`, cf. `_resource_badges`) — même règle de
#: silhouette unique : dé (carré arrondi) et flamme.
_CAST_BADGE_LABELS = {"Spell": "SORT", "Prayer": "PRIÈRE", "Command": "ORDRE", "Blood tithe": "DIME DE SANG"}
_CAST_BADGE_COLORS = {
    "Spell": _BADGE_SPELL,
    "Prayer": _BADGE_PRAYER,
    "Command": _BADGE_COMMAND,
    "Blood tithe": _BADGE_BLOOD,
    "Rage": _BADGE_RAGE,
    "Fury": _BADGE_FURY,
}
_CAST_BADGE_SHAPES = {
    "Spell": "circle",
    "Prayer": "diamond",
    "Command": "hexagon",
    "Blood tithe": "drop",
    "Rage": "die",
    "Fury": "flame",
}
_CAST_BADGE_FG = {
    "Spell": "#f3eefa",
    "Prayer": "#e6f3ec",
    "Command": "#f7ecd6",
    "Blood tithe": "#f9e3e3",
    "Rage": "#fff1ea",
    "Fury": "#fff6e5",
}


def _resource_badges(ability: AbilityEntry) -> list[tuple[Flowable, float]]:
    """Icônes dé de rage / point de fureur (`AbilityEntry.resources`), valeur
    inscrite au centre (« +2 » gagné, « 1-3 »/« X » dépensé)."""
    out = []
    for kind, value in ability.resources:
        badge = _CastBadge(_CAST_BADGE_SHAPES[kind], value, _CAST_BADGE_COLORS[kind], _CAST_BADGE_FG[kind])
        out.append((badge, badge.size))
    return out


def _cast_pill(ability: AbilityEntry, max_width: float) -> tuple[Flowable, float] | None:
    pts_type = (ability.points_type or "").strip()
    if not pts_type:
        return None
    value = (ability.points or "").strip()
    bg = _CAST_BADGE_COLORS.get(pts_type, _BADGE_KEYWORD)
    fg = _CAST_BADGE_FG.get(pts_type, "#f7ecd6")
    if value:
        text = f"{value}+" if pts_type in ("Spell", "Prayer") else value
        shape = _CAST_BADGE_SHAPES.get(pts_type, "circle")
        badge = _CastBadge(shape, text, bg, fg)
        return badge, badge.size
    # aucune valeur à inscrire au centre d'un badge : un sigle ("PC") n'a pas
    # sa place dans une forme aussi petite, on retombe sur la pastille
    # rectangulaire générique avec le libellé complet.
    label = tr(_CAST_BADGE_LABELS.get(pts_type, pts_type.upper()))
    natural = _pill_natural_width(label)
    if natural > max_width:
        return _pill(label, bg, fg, width=max_width), max_width
    return _pill(label, bg, fg, width=None), natural


#: mots-clés d'aptitude à couleur propre (demande de l'utilisateur) : SPELL
#: du même violet que le cercle de valeur de lancement d'un sort. Les badges
#: source (`_TEXT_SOURCE_KEYWORDS`, SIMPLE compris) ont tous `_BADGE_SOURCE`.
_KEYWORD_PILL_COLORS: dict[str, tuple[str, str]] = {
    # un sort, une manifestation ou une convocation (qui se lance comme un
    # sort) : même violet (demande de l'utilisateur) — EN et FR curé
    **{
        kw: (_BADGE_SPELL, _CAST_BADGE_FG["Spell"])
        for kw in ("spell", "sort", "manifestation", "summon", "convocation")
    },
    # prière sans valeur (avec valeur, le losange vert la masque) : vert prière
    **{kw: (_BADGE_PRAYER, _CAST_BADGE_FG["Prayer"]) for kw in ("prayer", "prière")},
    "saison": (_BADGE_SEASON, "#fff1ea"),
    # mot-clé d'aptitude liée à une phase : couleur du bandeau de cette phase
    # (demande de l'utilisateur) — EN Wahapedia et FR curé. ATTACK/RAMPAGE
    # servent dans plusieurs phases : pas de couleur de phase, cf.
    # `_MULTI_PHASE_KEYWORDS`.
    **{
        kw: _PHASE_COLORS[phase]
        for phase, kws in {
            "move": ("move", "mouvement", "run", "course", "retreat", "repli"),
            "shoot": ("shoot", "tir"),
            "charge": ("charge",),
            "melee": ("fight", "corps à corps"),
            "deploy": ("deploy", "déploiement", "deploy terrain", "déploiement de terrain"),
        }.items()
        for kw in kws
    },
    # bannissement/dissipation relèvent de la magie : violet des sorts
    # (demande de l'utilisateur)
    **{kw: (_BADGE_SPELL, _CAST_BADGE_FG["Spell"]) for kw in ("banish", "bannissement", "unbind", "dissipation")},
    # aptitude de base (CORE) : noir (demande de l'utilisateur)
    "core": ("#141414", "#f2ecdb"),
    "base": ("#141414", "#f2ecdb"),
}


#: badge « source » du texte d'une aptitude (`origin` de
#: `faction_rules_fr.json`, « MdG » des règles génériques/de saison/de
#: tactique, « Simple » d'une compression, « Wahapedia » par défaut) — un
#: par aptitude, cf. `_keyword_pills`.
#: mots-clés servant dans plusieurs phases : ardoise en contour, sans lien
#: avec aucune phase (demande de l'utilisateur).
_MULTI_PHASE_KEYWORDS = frozenset({"attack", "attaque", "rampage", "saccage"})
_TEXT_SOURCE_KEYWORDS = frozenset(
    {"bt", "bt (trad.)", "fp", "aqshy", "mdg", "core rules", "gw app", "simple", "wahapedia"}
)
_DEFAULT_TEXT_SOURCE = "Wahapedia"
#: badges d'origine « sous-source » (catégorie de règles d'armée dont vient
#: l'aptitude, cf. `tag_ability_origin`) : même couleur que les badges source
#: (demande de l'utilisateur), sans compter comme source exclusive.
_SUB_SOURCE_PREFIXES = ("trait de bataille", "traits de bataille", "formation")
#: mot-clé redit par le badge de valeur d'un sort/d'une prière (`_cast_pill`)
_CAST_TYPE_KEYWORDS = {"Spell": frozenset({"spell", "sort"}), "Prayer": frozenset({"prayer", "prière"})}


def _keyword_pills(ability: AbilityEntry) -> list[tuple[Table, float]]:
    # toute aptitude porte un badge source ; sans source curée, son texte
    # vient tel quel de Wahapedia (anglais)
    keywords = [kw.strip() for kw in (ability.keywords or "").split(",") if kw.strip()]
    if not any(kw.lower() in _TEXT_SOURCE_KEYWORDS for kw in keywords):
        ability = _dc_replace(ability, keywords=", ".join(keywords + [_DEFAULT_TEXT_SOURCE]))
    # "Deploy"/"Deployment" fait doublon avec la pastille de condition quand
    # celle-ci vaut déjà "Deployment Phase" (`_PLAIN_CONDITION_FR`) — ex.
    # Skaven « THE LURKING VERMINTIDE » affichait à la fois « DEPLOY » (brut,
    # non traduit, cf. absence d'équivalent à `_PLAIN_CONDITION_FR` ici) et
    # « PHASE DE DÉPLOIEMENT » côte à côte pour le même concept.
    is_deployment_condition = "deployment phase" in (ability.condition or "").lower()
    # dans sa sous-section de choix, le mot-clé qui la définit (« DELUSION »,
    # « BLOOD TITHE ») redit le titre de la sous-section : une ligne de
    # pastilles en moins par aptitude, pour qu'elle tienne sur une page.
    # La copie restée dans sa phase d'usage garde la pastille.
    section_keyword = _CHOICE_CATEGORY_KEYWORDS.get(ability.ability_category)
    # badge « source » du texte, un par aptitude et exclusif : vérbatim d'une
    # source (BT, FP, Aqshy, MdG...) ou compressé par nous (SIMPLE) — un texte
    # compressé n'est plus le vérbatim de sa source, SIMPLE la remplace
    # (demande de l'utilisateur). SAISON/BASE ne sont pas des sources.
    is_simple = any(kw.strip().lower() == "simple" for kw in ability.keywords.split(","))
    # le badge de valeur (cercle violet « 7+ », losange vert) dit déjà sort/
    # prière : la pastille SPELL/PRAYER ferait doublon (demande de l'utilisateur)
    pts_type = (ability.points_type or "").strip()
    cast_keywords = _CAST_TYPE_KEYWORDS.get(pts_type, frozenset()) if (ability.points or "").strip() else frozenset()
    out = []
    for kw in ability.keywords.split(","):
        kw = kw.strip().upper()
        if not kw:
            continue
        if is_simple and kw.lower() in _TEXT_SOURCE_KEYWORDS and kw.lower() != "simple":
            continue
        # « DÉPLOIEMENT »/« DÉPLOIEMENT DE TERRAIN » redisent le bandeau
        # « Déploiement » ; une aptitude jouée une fois par partie se lit en
        # entier (demande de l'utilisateur)
        if is_deployment_condition and kw.lower() in (
            "deploy",
            "deployment",
            "déploiement",
            "déploiement de terrain",
            "deploy terrain",
        ):
            continue
        if kw.lower() == section_keyword:
            continue
        if kw.lower() in cast_keywords:
            continue
        if kw.lower() in ("unlimited", "illimité"):
            # « Illimité » en français, couleur de son type de lancement (violet
            # pour un sort, vert pour une prière) — demande de l'utilisateur
            kw = tr("ILLIMITÉ")
            pts = (ability.points_type or "").strip()
            kinds = {k.strip().lower() for k in ability.keywords.split(",")}
            if pts == "Prayer" or kinds & {"prayer", "prière"}:
                bg, fg = _BADGE_PRAYER, _CAST_BADGE_FG["Prayer"]
            else:
                bg, fg = _BADGE_SPELL, _CAST_BADGE_FG["Spell"]
        elif kw.lower() in _TEXT_SOURCE_KEYWORDS or kw.lower().startswith(_SUB_SOURCE_PREFIXES):
            bg, fg = _BADGE_SOURCE, "#eef0f3"
        elif kw.lower() in _KEYWORD_PILL_COLORS:
            bg, fg = _KEYWORD_PILL_COLORS[kw.lower()]
        elif kw.lower() in render_options().faction_keywords:
            bg, fg = _BADGE_FACTION, "#f7e6ee"
        elif kw.lower() in _MULTI_PHASE_KEYWORDS:
            bg, fg = _BADGE_MULTI_PHASE, "#eef0f3"
        else:
            bg, fg = _BADGE_KEYWORD, "#f2eeea"
        outline = kw.lower() in _MULTI_PHASE_KEYWORDS
        if render_options().french_keywords:
            kw = _KEYWORD_LABELS_FR.get(kw.lower(), kw)
        kw = tr(kw)
        out.append((_pill(kw, bg, fg, outline=outline) if outline else _pill(kw, bg, fg), _pill_natural_width(kw)))
    return out


def _warscroll_pills(ability: AbilityEntry, max_width: float) -> list[tuple[Table, float]]:
    """Un badge par warscroll porteur (`AbilityEntry.warscrolls`, posé
    uniquement en mode `fr-split`) — même bleu nuit que l'en-tête des cartes
    d'unité, pour se lire comme « renvoi vers la carte X » et se distinguer
    d'un coup d'œil des mots-clés. Un nom d'unité peut être long
    ("Lord-Celestant on Gryph-Charger") : borné à `max_width` comme les
    autres pastilles plutôt que de déborder de la colonne de badges."""
    # en mode sectionné, le titre de sous-section dit déjà l'unité — sauf
    # dans « Sorts »/« Manifestations »/« Prières », qui mélangent domaine
    # d'armée et sorts/prières signature (propres à un warscroll) : la
    # pastille y désigne le lanceur — ni dans une sous-section de choix
    # (« Délires »...), dont le titre ne nomme pas l'unité : la pastille dit
    # que l'option dépend d'elle (ex. « Épicentre de l'Illusion », Ushoran).
    category = _ability_category(ability)
    if render_options().sectioned and category not in _CAST_SECTIONS and category not in CHOICE_CATEGORIES:
        return []
    out = []
    for name in ability.warscrolls:
        text = name.upper()
        natural = _pill_natural_width(text)
        if natural > max_width:
            out.append((_pill(text, _BADGE_WARSCROLL, "#f2ecdb", width=max_width), max_width))
        else:
            out.append((_pill(text, _BADGE_WARSCROLL, "#f2ecdb", width=None), natural))
    return out


def _wielder_ratios(description: str) -> dict[str, str]:
    """`{nom d'arme (normalisé, minuscules) -> "N/M"}` à partir du texte
    libre de restriction du warscroll (ex. « 1/5 models can replace their
    Warhammer with a Grandhammer » -> {"grandhammer": "1/5"}). Même source
    que `engine/loadout.py` lit déjà côté moteur de combat."""
    text = re.sub(r"<[^>]+>", " ", description or "")
    out: dict[str, str] = {}
    for ratio, weapon in _WIELDER_RATIO_RE.findall(text):
        out[weapon.strip().lower()] = ratio
    return out


def _pill(text: str, bg_hex: str, fg_hex: str, width: float | None = None, outline: bool = False) -> Table:
    """Une vraie pastille pleine — une mini-`Table` à une cellule avec un
    fond peint (`Paragraph` seul ne peint jamais de fond derrière son texte,
    même en HTML-ish reportlab) : c'est le même principe que `_phase_band`
    utilisait déjà pour son bandeau, appliqué à chaque badge individuel
    plutôt qu'à un texte coloré entre crochets. `width=None` laisse la
    pastille se tailler sur son contenu (badges courts : fréquence,
    qualificatif, mot-clé) ; un `width` fixe force le retour à la ligne
    (la réaction, seule à porter une phrase complète et potentiellement
    longue). `outline=True` — la réaction seule — garde un fond transparent
    et un liseré coloré plutôt qu'un aplat, pour rester l'exception qui
    attire l'œil comme une alerte plutôt qu'une classification de plus.

    `width` est toujours résolu à une valeur explicite avant de bâtir la
    `Table` (jamais `colWidths=[None]`) : un `Paragraph` compte comme un
    contenu "à largeur variable" pour reportlab, donc une colonne laissée
    `None` ne se taille pas sur son texte mais s'étire pour occuper toute la
    largeur disponible dans la cellule englobante (`_ability_row_flowables`
    empile plusieurs pastilles dans une même cellule alignée à droite) — la
    pastille perdait alors sa largeur naturelle et s'étalait sur toute la
    colonne, ce qui rendait l'alignement à droite invisible (toutes bord à
    bord) plutôt que de faire ressortir chaque pastille par sa propre
    largeur."""
    render_tracker().pill_colors.add(bg_hex.lower())
    if width is None:
        width = _pill_natural_width(text)
    style = ParagraphStyle(
        f"wc_pill_{bg_hex}_{outline}",
        fontName="Helvetica",
        fontSize=6.6,
        leading=8.4,
        textColor=colors.HexColor(bg_hex if outline else fg_hex),
    )
    inner = _safe_paragraph(text, style)
    t = Table([[inner]], colWidths=[width])
    cell_style = [
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROUNDEDCORNERS", [_PILL_RADIUS] * 4),
    ]
    if outline:
        cell_style.append(("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(bg_hex)))
    else:
        cell_style.append(("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_hex)))
    t.setStyle(TableStyle(cell_style))
    return t


#: espace laissé entre deux pastilles d'une même ligne par `_pill_row`
#: (`RIGHTPADDING` ci-dessous) — repris tel quel par `_pack_badges` pour que
#: son budget de largeur par ligne corresponde exactement à ce que la ligne
#: assemblée occupera réellement.
_PILL_GAP = 4

#: espace vertical ajouté entre deux lignes de badges empilées par
#: `_pack_badges` (via `spaceBefore`, respecté par Platypus même quand le
#: contenu d'une cellule est une simple liste de Flowables plutôt qu'un
#: Frame — cf. le commentaire sur `_CastBadge.spaceBefore`) — un peu d'air
#: pour que les pastilles ne se touchent pas verticalement.
_BADGE_ROW_GAP = 2


def _pack_badges(items: list[tuple[Flowable, float]], max_width: float) -> list[Table]:
    """Empile des pastilles de badge de toute nature (sort/fréquence/
    condition/mot-clé) sur autant de lignes que nécessaire, plusieurs
    pastilles par ligne quand leur largeur cumulée tient dans `max_width` —
    remplace l'ancien traitement à deux vitesses (fréquence/condition
    empilées une par ligne dans la colonne de droite, mots-clés sur une
    ligne séparée pleine largeur en dessous) par une seule grille commune,
    pour que par ex. « MA PHASE » (condition) et « TRAITS DE BATAILLE »
    (mot-clé/origine) puissent partager la même ligne au lieu de toujours
    s'empiler chacune sur la sienne. Chaque pastille va dans la première
    ligne où elle tient encore (et non seulement la dernière) : une pastille
    courte comme SIMPLE remonte dans un trou plutôt que d'ouvrir une ligne de
    plus (demande de l'utilisateur)."""
    rows: list[list[tuple[Flowable, float]]] = []
    row_widths: list[float] = []
    for fl, w in items:
        for i, used in enumerate(row_widths):
            if used + _PILL_GAP + w <= max_width:
                rows[i].append((fl, w))
                row_widths[i] += _PILL_GAP + w
                break
        else:
            rows.append([(fl, w)])
            row_widths.append(w)
    packed = [row for row in (_pill_row(r) for r in rows) if row is not None]
    for row in packed[1:]:
        row.spaceBefore = _BADGE_ROW_GAP
    return packed


def _pill_row(pills: list[tuple[Flowable, float]]) -> Table | None:
    """Plusieurs pastilles côte à côte (mots-clés d'aptitude, fréquence...) —
    une ligne à N colonnes, chacune taillée sur son contenu."""
    if not pills:
        return None
    # `colWidths` doit être donné explicitement (largeur déjà connue de
    # chaque pastille, cf. `_pill_natural_width`/`_CastBadge.size`) plutôt que
    # laissé à `None` ("auto") : reportlab ne sait calculer une largeur de
    # colonne "auto" qu'en interrogeant `Flowable._fixedWidth` de son contenu,
    # qui vaut 0 par défaut pour *toute* pastille (ce sont elles-mêmes des
    # `Table`/`Flowable` imbriquées) — jugée "non calculable rapidement",
    # reportlab bascule alors sur `_calcPreliminaryWidths`, qui étire la
    # colonne pour occuper toute la largeur disponible au lieu de la tailler
    # sur son contenu. Conséquence concrète : une fois cette ligne replacée
    # dans la cellule `cond_col` de `_ability_row_flowables`, sa largeur
    # mesurée valait `cond_col` pour *toutes* les lignes quel que soit leur
    # contenu réel, rendant l'alignement à droite (`ALIGN "RIGHT"` sur cette
    # cellule) indiscernable d'un alignement à gauche — repéré en comparant
    # les rects mesurés de plusieurs pastilles empilées (bords gauches
    # identiques, jamais les bords droits). Des `colWidths` explicites
    # évitent ce chemin de code entièrement.
    widths = [w + (_PILL_GAP if i < len(pills) - 1 else 0) for i, (_, w) in enumerate(pills)]
    t = Table([[fl for fl, _ in pills]], colWidths=widths)
    t.setStyle(
        TableStyle(
            [
                # le petit espace entre 2 pastilles voisines est réservé dans `widths`
                # ci-dessus (colonnes 0..avant-dernière) puis rendu visible ici via
                # RIGHTPADDING sur ces mêmes colonnes — jamais sur la dernière, dont
                # le bord droit doit rester exactement au bord de la ligne (repère de
                # l'alignement à droite de `_ability_row_flowables`).
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-2, -1), _PILL_GAP),
                ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ]
        )
    )
    return t


#: silhouettes de `_CastBadge` / couleurs de pastilles réellement dessinées
#: depuis la dernière remise à zéro : la légende de la couverture
#: (`cover._build_cover_pdf`, `pill_legend`) n'explique que celles-là.
#: Relevées dans le `RenderTracker` de la `render_session` en cours
#: (`render/options.py`) — les silhouettes au dessin (`draw`, les cartes de
#: warscroll/l'annexe sont construites tard, au moment de leur propre rendu
#: PDF), les pastilles à la construction (des `Table`, sans `draw` propre).


def reset_drawn_badge_shapes() -> None:
    render_tracker().badge_shapes.clear()


def drawn_badge_shapes() -> frozenset[str]:
    return frozenset(render_tracker().badge_shapes)


def reset_drawn_pills() -> None:
    render_tracker().pill_colors.clear()


#: une ligne de légende par famille de pastilles : (couleurs qui la
#: déclenchent, pastilles d'exemple (texte, fond, texte, contour),
#: explication). Ordre : source, propriétés, timing, mots-clés.
_PILL_LEGEND: list[tuple[frozenset[str], list[tuple[str, str, str, bool]], str]] = [
    (
        frozenset({_BADGE_SOURCE}),
        [("MDG", _BADGE_SOURCE, "#eef0f3", False)],
        "Source du texte : MDG (Manuel du Général), BT (battletome), FP (faction pack), AQSHY, WAHAPEDIA "
        "(anglais). Traits de Bataille, Formation : catégorie de règles d'armée.",
    ),
    (
        frozenset({_BADGE_SOURCE}),
        [("SIMPLE", _BADGE_SOURCE, "#eef0f3", False)],
        "Texte adapté, pas le verbatim : en cas de litige, revenir à la règle d'origine.",
    ),
    (
        frozenset({"#141414", _BADGE_SEASON}),
        [("BASE", "#141414", "#f2ecdb", False), ("SAISON", _BADGE_SEASON, "#fff1ea", False)],
        "Aptitude de base du jeu (Core) ; règle de la saison en cours (MdG 2026-27).",
    ),
    (
        frozenset({_BADGE_NEUTRAL}),
        [("×1 / TOUR (ARMÉE)", _BADGE_NEUTRAL, "#eaf1f8", True), ("PASSIF", _BADGE_NEUTRAL, "#eaf1f8", True)],
        "Fréquence — (ARMÉE) : une seule fois pour toute l'armée ; passif : toujours actif, rien à déclarer.",
    ),
    (
        frozenset({_BADGE_REACT}),
        [("RÉACTION", _BADGE_REACT, "#fbeaec", False)],
        "Réaction : utilisée en réponse à l'aptitude indiquée.",
    ),
    (
        frozenset(_PHASE_COLORS[k][0] for k in ("move", "shoot", "charge", "melee")),
        [("TIR", *_PHASE_COLORS["shoot"], False), ("CHARGE", *_PHASE_COLORS["charge"], False)],
        "Mot-clé d'aptitude, à la couleur de sa phase (Mouvement, Tir, Charge, Corps à Corps).",
    ),
    (
        frozenset({_BADGE_MULTI_PHASE}),
        [("ATTAQUE", _BADGE_MULTI_PHASE, "#eef0f3", True), ("SACCAGE", _BADGE_MULTI_PHASE, "#eef0f3", True)],
        "Mot-clé d'aptitude valable dans plusieurs phases.",
    ),
    (
        frozenset({_BADGE_SPELL, _BADGE_PRAYER}),
        [("SORT", _BADGE_SPELL, "#f3eefb", False), ("PRIÈRE", _BADGE_PRAYER, "#eaf5ef", False)],
        "Magie (sort, manifestation, bannissement…) ; prière. Illimité : utilisable plusieurs fois par tour.",
    ),
    (
        frozenset({_BADGE_WARSCROLL}),
        [("NOM D'UNITÉ", _BADGE_WARSCROLL, "#f2ecdb", False)],
        "Unité qui porte l'aptitude (pour un sort signature : son lanceur).",
    ),
    (
        frozenset({_BADGE_KEYWORD, _BADGE_FACTION}),
        [("TACTIQUE", _BADGE_KEYWORD, "#f2eeea", False), ("MOT-CLÉ", _BADGE_FACTION, "#f7e6ee", False)],
        "Autre mot-clé d'aptitude (Tactique : règle spéciale d'une carte de tactique) ; bordeaux : propre à la faction.",
    ),
]


def pill_legend() -> list[tuple[Flowable, float, str]]:
    """(rangée de pastilles d'exemple, sa largeur, explication) pour chaque
    famille de `_PILL_LEGEND` dont une pastille a été construite depuis
    `reset_drawn_pills`."""
    drawn = set(render_tracker().pill_colors)
    out = []
    for colors_, samples, text in _PILL_LEGEND:
        if not drawn & {c.lower() for c in colors_}:
            continue
        pills = [
            (_pill(tr(t), bg, fg, outline=outline) if outline else _pill(tr(t), bg, fg), _pill_natural_width(tr(t)))
            for t, bg, fg, outline in samples
        ]
        width = sum(w for _p, w in pills) + _PILL_GAP * len(pills)
        out.append((_pill_row(pills), width, tr(text)))
    return out


class _CastBadge(Flowable):
    """Badge géométrique (cercle/losange/hexagone/goutte), valeur inscrite au
    centre — reprend le code visuel de l'éditeur BattleScribe/Warhammer Age
    of Sigmar: The App pour un coût de Sort/Prière/Point de Commandement/
    Dime de Sang (une forme par type, cf. `_CAST_BADGE_SHAPES`), plutôt que
    la pastille rectangulaire générique de `_pill` utilisée ici avant —
    celle-ci ne distinguait ces types que par leur couleur et un préfixe
    textuel ("SORT 5+"), quand l'original les distingue d'abord par leur
    silhouette. `_cast_pill` retombe sur `_pill` (silhouette rectangulaire)
    quand l'aptitude ne porte aucune valeur numérique à inscrire au centre —
    un simple sigle ("PC") n'a pas sa place dans une forme aussi petite."""

    def __init__(self, shape: str, text: str, bg_hex: str, fg_hex: str, size: float = 14):
        super().__init__()
        self.shape = shape
        self.text = text
        self.bg = colors.HexColor(bg_hex)
        self.fg = colors.HexColor(fg_hex)
        self.size = size
        self.spaceBefore = 2  # même respiration que le `TOPPADDING` des pastilles voisines dans la pile

    def wrap(self, availWidth, availHeight):
        return (self.size, self.size)

    def _path(self, cx: float, cy: float, r: float):
        p = self.canv.beginPath()
        if self.shape == "circle":
            p.circle(cx, cy, r)
        elif self.shape == "diamond":
            p.moveTo(cx, cy + r)
            p.lineTo(cx + r, cy)
            p.lineTo(cx, cy - r)
            p.lineTo(cx - r, cy)
            p.close()
        elif self.shape == "die":  # dé de rage : carré aux coins arrondis
            side = r * 1.7
            p.roundRect(cx - side / 2, cy - side / 2, side, side, side * 0.22)
        elif self.shape == "flame":  # point de fureur : flamme, pointe en haut
            body_r = r * 0.72
            body_cy = cy - r + body_r
            k = 0.5523 * body_r
            p.moveTo(cx + r * 0.1, cy + r)
            p.curveTo(cx + body_r * 0.2, cy + r * 0.55, cx + body_r * 1.05, cy + r * 0.25, cx + body_r, body_cy)
            p.curveTo(cx + body_r, body_cy - k, cx + k, body_cy - body_r, cx, body_cy - body_r)
            p.curveTo(cx - k, body_cy - body_r, cx - body_r, body_cy - k, cx - body_r, body_cy)
            p.curveTo(cx - body_r, cy + r * 0.2, cx - body_r * 0.55, cy + r * 0.45, cx - body_r * 0.35, cy + r * 0.7)
            p.curveTo(cx - body_r * 0.2, cy + r * 0.35, cx + r * 0.05, cy + r * 0.6, cx + r * 0.1, cy + r)
            p.close()
        elif self.shape == "drop":  # goutte de sang, pointe en haut : la Dime de Sang
            body_r = r * 0.68
            body_cy = cy - r + body_r
            k = 0.5523 * body_r  # approximation de Bézier d'un quart de cercle
            p.moveTo(cx, cy + r)
            p.curveTo(cx + body_r * 0.35, cy + r * 0.45, cx + body_r, body_cy + k, cx + body_r, body_cy)
            p.curveTo(cx + body_r, body_cy - k, cx + k, body_cy - body_r, cx, body_cy - body_r)
            p.curveTo(cx - k, body_cy - body_r, cx - body_r, body_cy - k, cx - body_r, body_cy)
            p.curveTo(cx - body_r, body_cy + k, cx - body_r * 0.35, cy + r * 0.45, cx, cy + r)
            p.close()
        else:  # hexagone à sommet plat (2 côtés horizontaux) — le jeton PC de l'éditeur
            for i in range(6):
                angle = math.radians(60 * i)
                x, y = cx + r * math.cos(angle), cy + r * math.sin(angle)
                (p.moveTo if i == 0 else p.lineTo)(x, y)
            p.close()
        return p

    def draw(self):
        render_tracker().badge_shapes.add(self.shape)
        c = self.canv
        cx = cy = self.size / 2.0
        r = self.size / 2.0 - 0.4  # laisse la place au liseré sans le faire déborder du cadre alloué
        c.setFillColor(self.bg)
        c.setStrokeColor(_STEEL_LINE)
        c.setLineWidth(0.6)
        c.drawPath(self._path(cx, cy, r), fill=1, stroke=1)
        c.setFillColor(self.fg)
        if self.shape == "die":  # 2 points en coins opposés : se lit comme un dé
            off = r * 0.66
            for dx, dy in ((-off, off), (off, -off)):
                c.circle(cx + dx, cy + dy, 0.75, stroke=0, fill=1)
        # « 1-3 » dans un dé : police réduite, pour ne pas toucher ses points
        c.setFont("Helvetica-Bold", 6 if len(self.text) >= 3 else 7.2)
        # dans la goutte, la valeur se centre sur son corps rond, plus bas que
        # le centre du cadre
        text_y = cy - 2.6 - (r * 0.32 if self.shape in ("drop", "flame") else 0)
        c.drawCentredString(cx, text_y, self.text)


#: légende de chaque silhouette de `_CastBadge` (couverture du roster, cf.
#: `cast_badge_legend`), dans l'ordre de `_CAST_BADGE_SHAPES`, avec la
#: valeur d'exemple inscrite dans le picto.
_CAST_BADGE_LEGEND = {
    "Spell": (
        "7+",
        "Aptitude : valeur de lancement. Warscroll : niveau de Sorcier ; manifestation : valeur de lancement de sa convocation.",
    ),
    "Prayer": ("4+", "Aptitude : valeur de récitation. Warscroll : niveau de Prêtre."),
    "Command": ("1", "Ordre : coût en points d’ordre"),
    "Blood tithe": ("2", "Dîme de sang : coût en points de dîme de sang"),
    "Rage": ("+2", "Dés de rage : « +N » gagnés, sinon nombre dépensé"),
    "Fury": ("+2", "Niveau de fureur : « +N » augmenté, sinon diminué"),
}


def cast_badge_legend(shapes: frozenset[str]) -> list[tuple[Flowable, str]]:
    """(picto d'exemple, explication) pour chaque silhouette de `shapes`."""
    return [
        (
            _CastBadge(shape, _CAST_BADGE_LEGEND[kind][0], _CAST_BADGE_COLORS[kind], _CAST_BADGE_FG[kind]),
            tr(_CAST_BADGE_LEGEND[kind][1]),
        )
        for kind, shape in _CAST_BADGE_SHAPES.items()
        if shape in shapes
    ]


#: taille du badge Sorcier/Prêtre en en-tête — plus grand que le badge de
#: coût d'une aptitude (`_CastBadge` par défaut, 14pt) : il n'est plus
#: accolé à un texte de règle qui porte lui-même l'info, il doit se
#: distinguer tout seul près du nom de l'unité, comme sur l'éditeur
#: BattleScribe/l'App.
_CASTER_BADGE_SIZE = 16


def _caster_badges(keywords: list[str]) -> list[_CastBadge]:
    """Badges géométriques Sorcier/Prêtre (même silhouette que `_CastBadge`,
    cercle violet pour un sort/un sorcier, losange vert pour une prière/un
    prêtre) construits à partir des mots-clés `WIZARD (N)`/`PRIEST (N)` du
    warscroll — le niveau de magie/de prière de l'unité, reconstitué par
    `WahapediaLookup.find_warscroll` à partir de la colonne `parameter` de
    Warscrolls_keywords.csv. Affichés dans l'en-tête de carte plutôt que dans
    la liste de mots-clés en bas (cf. `_visible_keywords`) : un joueur
    cherche ce niveau au même endroit que sur l'éditeur BattleScribe/l'App,
    près du nom de l'unité, pas noyé dans une liste de mots-clés."""
    badges = []
    for kw in keywords:
        m = _CASTER_KW_RE.match(kw.strip())
        if not m:
            continue
        kind, level = m.group(1).upper(), m.group(2)
        if kind == "WIZARD":
            badges.append(_CastBadge("circle", level, _BADGE_SPELL, _CAST_BADGE_FG["Spell"], size=_CASTER_BADGE_SIZE))
        else:
            badges.append(
                _CastBadge("diamond", level, _BADGE_PRAYER, _CAST_BADGE_FG["Prayer"], size=_CASTER_BADGE_SIZE)
            )
    return badges


def _visible_keywords(keywords: list[str]) -> list[str]:
    """`keywords` moins `WIZARD (N)`/`PRIEST (N)` — ceux-ci rejoignent le
    badge d'en-tête (`_caster_badges`) plutôt que la liste de mots-clés en
    bas de carte, pour ne pas doublonner l'information."""
    return [kw for kw in keywords if not _CASTER_KW_RE.match(kw.strip())]


def _caster_badge_row(badges: list[_CastBadge]) -> tuple[Table, float]:
    """Aligne 1+ badges Sorcier/Prêtre côte à côte (une unité peut, en
    théorie, être à la fois Sorcier et Prêtre) avec un petit espace entre eux
    — même schéma `(flowable, largeur occupée)` que le reste du fichier
    utilise pour composer des lignes de badges (cf. `_pack_badges`)."""
    gap = 3
    cells: list = []
    col_widths: list[float] = []
    for i, b in enumerate(badges):
        if i:
            cells.append(Spacer(gap, 0))
            col_widths.append(gap)
        cells.append(b)
        col_widths.append(b.size)
    t = Table([cells], colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t, sum(col_widths)

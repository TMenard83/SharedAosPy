"""Mise en page des aptitudes : rail de phase, lignes et bandeaux, découpage (`_chunk_group`), colonnes, bandeaux sectionnés (shrink-to-fit), deux colonnes de cartes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, PageBreak, Paragraph, Spacer, Table, TableStyle

from ..sources.wahapedia_lookup import AbilityEntry
from .options import render_options, use_render_options
from .phases import (
    _CAST_SECTIONS,
    _CATEGORY_LABELS_FR,
    _CATEGORY_ORDER,
    _PHASE_ORDER,
    _SECTION_COLUMNS,
    _SECTION_HEADER_BG,
    _SECTION_HEADER_STYLE,
    _SECTION_RANK,
    CHOICE_CATEGORIES,
    SECTION_BASE,
    _ability_category,
    _ability_span,
    _section_rank,
    ability_section,
    classify_phase,
)
from .pills import (
    _CAST_BADGE_FG,
    _cast_pill,
    _condition_pill,
    _freq_pill,
    _keyword_pills,
    _pack_badges,
    _reaction_trigger,
    _resource_badges,
    _warscroll_pills,
)
from .text import (
    _bold_set_up,
    _break_long_name,
    _clean_text,
    _safe_paragraph,
    strip_flavor,
    tr,
)
from .theme import (
    _BADGE_BLOOD,
    _BADGE_FACTION,
    _BADGE_PRAYER,
    _BADGE_REACT,
    _BADGE_SPELL,
    _BADGE_STAT,
    _CARD_BG,
    _NAME_STYLE,
    _PHASE_COLORS,
    _PHASE_LABELS,
    _STEEL,
    _STEEL_LINE,
    _TEXT_STYLE,
)


class _PhaseRail(Flowable):
    """Bandeau de phase vertical, texte pivoté — le rendu que la maquette
    HTML utilisait et que la première passe avait abandonné (bandeau
    horizontal) faute d'un moyen simple de connaître, par avance, la
    hauteur qu'un `Flowable` occupera une fois posé. En réalité rien
    n'empêche de la calculer nous-même : le corps du groupe (les lignes
    d'aptitude) est construit et mesuré via son propre `.wrap()` *avant*
    d'instancier ce bandeau (cf. `_append_ability_groups`), avec cette
    hauteur déjà connue passée ici en dur plutôt que redemandée à
    `wrap()` — ce `Flowable` n'a donc plus qu'à dessiner un rectangle
    plein et un texte pivoté à 90° dans un espace dont la taille est fixée
    d'avance, ce que `canvas.rotate()` fait très bien."""

    def __init__(self, label: str, bg_hex: str, fg_hex: str, height: float, width: float = 5.2 * mm):
        super().__init__()
        self.label = label
        self.bg = colors.HexColor(bg_hex)
        self.fg = colors.HexColor(fg_hex)
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.saveState()
        c.setFillColor(self.fg)
        c.translate(self.width / 2.0, self.height / 2.0)
        c.rotate(90)
        c.setFont("Helvetica-Bold", 6.6)
        c.drawCentredString(0, -2.3, self.label)
        c.restoreState()


def _rail_label_min_height(label: str) -> float:
    """Largeur réelle (mesurée, pas devinée) de `label` à la police/taille du
    bandeau, plus une marge — un bandeau pivoté à 90° (`_PhaseRail`, gros
    bandeau de phase comme sous-bandeau de catégorie) a besoin d'au moins
    cette hauteur pour ne pas se faire couper."""
    return stringWidth(label, "Helvetica-Bold", 6.6) + 8


def _min_rail_height(phase_key: str) -> float:
    return _rail_label_min_height(tr(_PHASE_LABELS[phase_key]).upper())


_PLACEMENT_STYLE = ParagraphStyle("wc_placement", fontName="Helvetica", fontSize=7.5, leading=9.5)
_NOTE_STYLE = ParagraphStyle("wc_note", fontName="Helvetica-Oblique", fontSize=6.5, leading=8.5, textColor=_STEEL)


_RAIL_WIDTH = 5.2 * mm

#: sous-bandeau de catégorie (Aptitudes/Sorts/Prières/Manifestations, cf.
#: `_ability_group_body`) — même principe que `_PhaseRail`/`_RAIL_WIDTH` mais
#: plus étroit, pour se lire comme une subdivision du grand bandeau de phase
#: plutôt qu'un bandeau de même rang.
_CATEGORY_RAIL_WIDTH = 4.2 * mm

#: (fond, texte) de chaque sous-bandeau de catégorie — mêmes couleurs que
#: leurs pastilles (`_CATEGORY_COLORS`/`_CAST_BADGE_FG`) pour rester
#: reconnaissable d'un coup d'œil (le violet d'un sort, le vert d'une
#: prière...), avec un texte clair choisi pour le contraste plutôt que
#: réutilisé tel quel.
_CATEGORY_RAIL_COLORS: dict[str, tuple[str, str]] = {
    "normal": ("#6b6555", "#f5f2ea"),
    "spell": (_BADGE_SPELL, _CAST_BADGE_FG["Spell"]),
    "prayer": (_BADGE_PRAYER, _CAST_BADGE_FG["Prayer"]),
    "manifestation": (_BADGE_STAT, "#e8f5f7"),
    "delusion": (_BADGE_FACTION, "#f7e6ee"),
    "blood_tithe": (_BADGE_BLOOD, _CAST_BADGE_FG["Blood tithe"]),
    "khaine_blessing": (_BADGE_FACTION, "#f7e6ee"),
    "chaos_pledge": (_BADGE_FACTION, "#f7e6ee"),
}


def _ability_row_flowables(ab: AbilityEntry, name_col: float, cond_col: float, first: bool) -> list[tuple[list, tuple]]:
    """Les 2 lignes d'une aptitude (nom+badges, texte), chacune comme
    `(cellules_de_ligne, style_supplémentaire_ou_None)` — `_ability_group_body`
    les assemble en lignes de la sous-table du groupe, en gardant le
    numérotage d'index à sa charge."""
    entries: list[tuple[list, tuple | None]] = []

    name_cell: list = [_safe_paragraph(f"<b>{_break_long_name(ab.name, name_col)}</b>", _NAME_STYLE)]

    # logo sort/prière/point de commandement, fréquence ("×1 / TOUR"),
    # condition (passif/qualificatif/réaction) et mots-clés (dont le badge
    # d'origine, cf. `tag_ability_origin`) rejoignent tous la même grille de
    # droite — une seule pastille par nature de badge n'existe pas : elles
    # sont toutes packées ensemble par `_pack_badges`, plusieurs par ligne
    # quand leur largeur le permet, plutôt que les badges "condition"
    # empilés un par ligne dans la colonne de droite et les mots-clés sur
    # une ligne séparée pleine largeur en dessous (deux traitements
    # différents qui ne s'alignaient jamais entre eux). Le logo avait
    # d'abord été mis à côté du nom (même traitement que la portée d'une
    # arme) mais, contrairement à un nom d'arme (toujours court), un nom
    # d'aptitude peut être long ("EXCOMMUNICATION!", "DERANGED
    # TRANSFORMATION") — sur une carte de règles à 2 colonnes
    # (`render_rule_card`), la colonne de nom rétrécie ne laissait alors
    # plus assez de place aux deux sur une ligne, et reportlab réenlignait
    # le badge en 2-3 lignes ("PRIÈRE 4+" -> "PRI"/"ÈRE"/"4+"). La colonne
    # de droite a une largeur fixe indépendante du nom, jamais ce conflit.
    badge_items: list[tuple[Flowable, float]] = _warscroll_pills(ab, cond_col)
    cast_pill = _cast_pill(ab, cond_col)
    if cast_pill is not None:
        badge_items.append(cast_pill)
    badge_items.extend(_resource_badges(ab))
    freq = _freq_pill(ab, cond_col)
    if freq is not None:
        badge_items.append(freq)
    cond_pill = _condition_pill(ab, cond_col)
    if cond_pill is not None:
        badge_items.append(cond_pill)
    badge_items.extend(_keyword_pills(ab))
    badge_cell: list = _pack_badges(badge_items, cond_col)
    # une seule colonne pour la table extérieure (cf. `_ability_group_body`)
    # : nom et badges de droite restent 2 colonnes côte à côte, mais
    # imbriqués dans une mini-table qui, elle, tient toute seule dans cette
    # cellule.
    name_cond = Table([[name_cell, badge_cell if badge_cell else ""]], colWidths=[name_col, cond_col])
    name_cond.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    entries.append(([name_cond], "top" if first else "top-rule"))

    text = _clean_text(strip_flavor(_bold_set_up(ab.description) if render_options().bold_set_up else ab.description))
    if render_options().sectioned:
        # pas de ligne vide avant « Effet : »/« Utilisée par : » : le
        # libellé en gras sépare déjà les parties (cartes plus compactes)
        text = _BLANK_BEFORE_LABEL_RE.sub("<br/>", text)
    trigger = _reaction_trigger(ab) if render_options().sectioned else None
    if trigger:
        # mode sectionné : le déclencheur de réaction en 1re ligne du texte,
        # pleine largeur, plutôt qu'une pastille haute et étroite à droite
        # (demande de l'utilisateur, cartes plus compactes).
        text = f'<font color="{_BADGE_REACT}"><b>{tr("Réaction :")}</b> {trigger}</font><br/>{text}'
    entries.append(([_ability_text_flowable(text, name_col + cond_col)], "text"))
    return entries


_BLANK_BEFORE_LABEL_RE = re.compile(r"<br/>\s*<br/>\s*(?=<b>[^<]{1,80}?\s*:\s*</b>)")

#: début d'une section titrée dans un texte d'aptitude (« <b>Effet :</b> »,
#: « <b>Varinor, la Rune de Force :</b> »), en début de ligne.
_TEXT_SECTION_SPLIT_RE = re.compile(r"(?:<br/>\s*)+(?=<b>[^<]{1,80}?\s*:\s*</b>)")
#: à partir de combien de sections titrées un texte est découpé (cf.
#: `_ability_text_flowable`) — une aptitude ordinaire n'en a que 2
#: (Annonce/Effet), qui restent un seul paragraphe.
_MIN_TEXT_SECTIONS = 3
#: section d'étape numérotée (« <b>1 :</b> ») : dès 2 étapes, le texte est
#: découpé lui aussi (ex. « Début de Round de Bataille »).
_STEP_SECTION_RE = re.compile(r"^\s*<b>\d+\s*:\s*</b>")
_SECTION_RULE = colors.HexColor("#e2d9bf")


def _ability_text_flowable(text: str, width: float, min_sections: int = _MIN_TEXT_SECTIONS) -> Flowable:
    """Texte d'une aptitude (déjà passé par `_clean_text`). Un gros texte à
    plusieurs sections titrées (`_MIN_TEXT_SECTIONS`+, ex. « Inscription de
    Rune » : l'effet puis une section par rune) est rendu section par section,
    séparées par un filet fin, pour la lisibilité (demande de l'utilisateur,
    tous modes) ; de même pour 2+ étapes numérotées (`_STEP_SECTION_RE`) ;
    sinon un seul paragraphe."""
    sections = [sec for sec in _TEXT_SECTION_SPLIT_RE.split(text) if sec.strip()]
    steps = len(sections) >= 2 and all(_STEP_SECTION_RE.match(sec) for sec in sections)
    if len(sections) < min_sections and not steps:
        return _safe_paragraph(text, _TEXT_STYLE)
    t = Table([[_safe_paragraph(sec, _TEXT_STYLE)] for sec in sections], colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, _SECTION_RULE),
            ]
        )
    )
    return t


def _ability_rows_body(abilities: list[AbilityEntry], width: float) -> Table:
    """Empile les lignes (nom+badges, texte) de chaque aptitude de
    `abilities`, sans aucun repère de catégorie — le corps brut qu'utilise
    directement `_ability_group_body` pour un groupe à une seule catégorie
    (l'écrasante majorité des cartes), et que cette même fonction réutilise
    une fois par grappe de catégorie pour un groupe qui en mélange plusieurs
    (cf. `_ability_group_body`)."""
    # les cellules de cette table portent 8pt de marge de chaque côté (style
    # ci-dessous) : le contenu de chaque ligne — notamment la mini-table
    # nom+condition, dont la largeur est fixée d'avance — doit se caler sur
    # `width` *moins* cette marge, sans quoi elle déborde du cadre de la
    # carte (elle-même dimensionnée exactement à `width`).
    content_width = width - 16
    name_col = content_width * 0.56
    cond_col = content_width - name_col
    rows: list[list] = []
    styles: list[tuple] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, ab in enumerate(abilities):
        for cells, kind in _ability_row_flowables(ab, name_col, cond_col, first=(i == 0)):
            rows.append(cells)
            r = len(rows) - 1
            # mode sectionné : marges resserrées, pour qu'un bandeau de phase
            # tienne plus souvent sur une page (demande de l'utilisateur)
            top_pad, text_bottom_pad = (3, 3) if render_options().sectioned else (5, 6)
            if kind == "top" or kind == "top-rule":
                styles += [("TOPPADDING", (0, r), (-1, r), top_pad), ("BOTTOMPADDING", (0, r), (-1, r), 1)]
                if kind == "top-rule":
                    styles.append(("LINEABOVE", (0, r), (-1, r), 0.4, _STEEL_LINE))
            else:  # text
                styles += [("TOPPADDING", (0, r), (-1, r), 2), ("BOTTOMPADDING", (0, r), (-1, r), text_bottom_pad)]
    body = Table(rows, colWidths=[width])
    # une seule colonne pour la table extérieure : la 1re ligne (nom+condition)
    # a en réalité 2 "colonnes" logiques (nom, condition) mais elles sont déjà
    # fusionnées dans une cellule de liste + un flowable pilule, donc `rows`
    # reste à 1 colonne partout — SPAN inutile.
    body.setStyle(TableStyle(styles))
    return body


def _category_cluster_row(category: str, abilities: list[AbilityEntry], width: float) -> Table:
    """Une grappe d'aptitudes de même catégorie, accolée à son propre
    sous-bandeau vertical (même principe que `_PhaseRail`, mais plus étroit
    et coloré par catégorie plutôt que par phase) — remplace l'ancien
    intitulé de catégorie posé en ligne au-dessus de la grappe (« APTITUDES »/
    « SORTS »/« PRIÈRES » en petit texte), qui ne se lisait pas comme
    appartenant au même bloc que le nom+les badges de la 1re aptitude."""
    body_width = width - _CATEGORY_RAIL_WIDTH
    body = _ability_rows_body(abilities, body_width)
    _, body_height = body.wrap(body_width, 0xFFFF)
    rail_height = max(body_height, _rail_label_min_height(tr(_CATEGORY_LABELS_FR.get(category, category)).upper()))
    bg, fg = _CATEGORY_RAIL_COLORS.get(category, _CATEGORY_RAIL_COLORS["normal"])
    rail = _PhaseRail(
        tr(_CATEGORY_LABELS_FR.get(category, category)).upper(), bg, fg, rail_height, width=_CATEGORY_RAIL_WIDTH
    )
    row = Table([[rail, body]], colWidths=[_CATEGORY_RAIL_WIDTH, body_width])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return row


def _category_clusters(group: list[AbilityEntry]) -> list[tuple[str, list[AbilityEntry]]]:
    """Découpe `group` en grappes consécutives de même catégorie (`(catégorie,
    aptitudes)`) — partagé par `_ability_group_body` (pour poser un
    sous-bandeau par grappe) et `_chunk_group` (pour ne jamais couper une
    grappe entre deux pages/tronçons, cf. `_chunk_group`). `group` est supposé
    déjà trié par catégorie (cf. `_append_ability_groups`), jamais réordonné
    ici."""
    clusters: list[tuple[str, list[AbilityEntry]]] = []
    for ab in group:
        category = _ability_category(ab)
        if clusters and clusters[-1][0] == category:
            clusters[-1][1].append(ab)
        else:
            clusters.append((category, [ab]))
    return clusters


def _ability_group_body(group: list[AbilityEntry], width: float, show_category_headers: bool = False) -> Table:
    """La sous-table d'un groupe de phase (tout sauf le bandeau de phase
    lui-même) — isolée dans sa propre `Table` pour pouvoir mesurer sa hauteur
    réelle avant de construire le bandeau vertical à sa gauche, cf.
    `_append_ability_groups`. `show_category_headers` (calculé une fois pour
    tout le groupe de phase, avant tronçonnage/mise en colonnes, cf.
    `_append_ability_groups`) découpe le groupe en grappes consécutives de
    même catégorie (`_category_clusters`), chacune accolée à son propre
    sous-bandeau (cf. `_category_cluster_row`) — seulement utile quand le
    groupe mélange effectivement plusieurs catégories (ex. un sort et un
    trait de bataille tous deux en phase des héros)."""
    if not show_category_headers:
        return _ability_rows_body(group, width)
    clusters = _category_clusters(group)
    rows: list[list] = []
    styles: list[tuple] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, (category, abilities) in enumerate(clusters):
        rows.append([_category_cluster_row(category, abilities, width)])
        # pas de TOPPADDING ici : ce padding pousserait vers le bas la ligne
        # entière (sous-bandeau de catégorie inclus, pas seulement le texte),
        # ouvrant un blanc visible entre deux sous-bandeaux de couleurs
        # différentes (ex. le gris "APTITUDES" et le violet "SORTS") — ils
        # doivent au contraire se toucher, seul le `LINEABOVE` marque la
        # frontière entre grappes.
        if i > 0:
            styles.append(("LINEABOVE", (0, i), (-1, i), 0.4, _STEEL_LINE))
    body = Table(rows, colWidths=[width])
    body.setStyle(TableStyle(styles))
    return body


#: hauteur maximale d'un seul groupe de phase (bandeau + corps) — une seule
#: ligne de la table extérieure de la carte, donc une seule ligne du PDF
#: final : reportlab ne sait pas la couper à un saut de page. Un groupe
#: normal (une carte d'unité, une seule catégorie de règle) ne l'atteint
#: jamais ; seule une carte de règles *fusionnées* (plusieurs catégories
#: réunies dans la même phase, cf. `pdf_builder.resolve_rules`) le peut —
#: `_chunk_group` le fractionne alors en plusieurs segments qui reprennent
#: chacun le même bandeau (couleur + nom de phase), l'un sous l'autre,
#: plutôt que de tenter une seule ligne trop grande pour tenir sur une page.
#: Marge sous la hauteur utile d'une page A4 portrait avec les marges de
#: `assembly._build_rule_cards_pdf`/`_build_warscroll_cards_pdf` (~11mm).
_MAX_GROUP_HEIGHT = 240 * mm

#: hauteur utile d'une page A4 portrait avec les marges de
#: `assembly._build_warscroll_cards_pdf` (~5.5mm de chaque côté), moins la
#: marge de sécurité empirique entre `A4[1] - 2*marge` et la hauteur de cadre
#: réellement disponible que reportlab rapporte dans une `LayoutError` (le
#: padding interne par défaut d'un `Frame`, ~6pt de chaque côté). Sert de
#: seuil pour `build_warscroll_cards_flow` : une carte pairée à demi-largeur
#: (`_UNIT_CARD_WIDTH`) dont une aptitude est exceptionnellement longue (ex.
#: Skaven's Lord Skreech Verminking, "Le Rat aux Treize Têtes") peut dépasser
#: une page entière et faire échouer tout le PDF avec un
#: `reportlab.platypus.doctemplate.LayoutError` — jamais le cas en dessous de
#: ce seuil.
_MAX_CARD_HEIGHT = A4[1] - 2 * (5.5 * mm) - 20


def _chunk_group(
    group: list[AbilityEntry],
    body_width: float,
    show_category_headers: bool = False,
    n_cols: int = 1,
    max_height: float = _MAX_GROUP_HEIGHT,
) -> list[list[AbilityEntry]]:
    """Découpe `group` en tronçons dont le corps assemblé (cf.
    `_ability_group_body`) tient sous `max_height` (`_MAX_GROUP_HEIGHT` par
    défaut, cf. `_choice_segments` pour l'exception) — jamais une
    aptitude coupée en deux, seulement la frontière entre deux aptitudes
    consécutives. Une aptitude seule plus haute que la limite (texte de
    règle exceptionnellement long) reste seule dans son propre tronçon,
    trop grande malgré tout plutôt que tronquée. `show_category_headers` doit
    être le même que celui passé au rendu final (cf. `_append_ability_groups`)
    pour que la hauteur mesurée ici — qui doit rester un majorant sûr sous
    `_MAX_GROUP_HEIGHT` — ne sous-estime pas les intitulés de catégorie
    effectivement rendus.

    Quand `show_category_headers` est vrai, la coupe se fait au niveau de la
    grappe de catégorie (`_category_clusters`), pas de l'aptitude individuelle
    — une grappe (ex. les 3 aptitudes "Sorts" d'un même bandeau de phase) ne
    peut donc jamais se retrouver scindée en deux tronçons. Sans cette
    contrainte, une coupe pouvait tomber entre deux aptitudes de la *même*
    catégorie : chaque tronçon obtenait alors son propre sous-bandeau
    (`_category_cluster_row`), correctement dimensionné sur sa portion
    tronquée mais donc plus court que la grappe complète visible une fois les
    deux tronçons empilés sans saut de page entre eux (symptôme : le
    sous-bandeau "Sorts" ne couvrant pas toute la hauteur de ses 3 aptitudes)
    — et, si les deux tronçons tombaient de part et d'autre d'un saut de page,
    la grappe se retrouvait visuellement coupée en plein milieu. Une grappe
    entière plus haute que la limite (cas extrême, jamais vu en pratique tant
    les grappes restent petites) reste malgré tout seule dans son propre
    tronçon, comme une aptitude isolée trop longue — pas de repli plus fin sur
    un découpage par aptitude à l'intérieur de la grappe.

    La hauteur est mesurée sur le rendu réel à `n_cols` colonnes
    (`_ability_group_body_columns`), pas sur 1 colonne : une colonne plus
    étroite allonge chaque aptitude, et le partage par aptitude entière entre
    colonnes n'est jamais parfaitement équilibré — mesurer à 1 colonne n'est
    donc *pas* un majorant sûr. Les grosses phases du mode `fr-split` (règles
    + aptitudes de tous les warscrolls réunies) dépassaient ainsi une page
    (`LayoutError`)."""

    def height(abilities: list[AbilityEntry]) -> float:
        return _ability_group_body_columns(abilities, body_width, n_cols, show_category_headers).wrap(
            body_width, 0xFFFF
        )[1]

    if show_category_headers:
        # une grappe plus haute qu'une page à elle seule (jamais vu avant le
        # mode `fr-split`, où la grappe « Aptitudes » de la phase des héros
        # réunit celles de tous les warscrolls) est découpée par aptitude
        # malgré tout : un sous-bandeau scindé vaut mieux qu'une `LayoutError`.
        units = []
        for _category, abilities in _category_clusters(group):
            units.extend([[ab] for ab in abilities] if height(abilities) > max_height else [abilities])
    else:
        units = [[ab] for ab in group]
    chunks: list[list[AbilityEntry]] = []
    current: list[AbilityEntry] = []
    for unit in units:
        candidate = current + unit
        if height(candidate) > max_height and current:
            chunks.append(current)
            current = list(unit)
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


#: Espace entre les deux colonnes d'un groupe de phase sur la carte de règles
#: combinée (cf. `_ability_group_body_columns`) — assez pour rester lisible
#: comme un vrai intervalle plutôt qu'un simple accolement des cadres.
_COLUMN_GAP = 4 * mm


def _split_group_columns(group: list[AbilityEntry], col_width: float, n_cols: int) -> list[list[AbilityEntry]]:
    """Répartit `group` (dans l'ordre, jamais réordonné) en `n_cols` colonnes
    équilibrées par hauteur rendue à `col_width` — pas par nombre
    d'aptitudes, une aptitude au texte long ne doit pas peser autant qu'une
    courte. Choisit, pour chaque frontière entre 2 colonnes, l'index qui
    rapproche le plus la hauteur cumulée de sa part du total (`i/n_cols`) —
    pas un seuil glouton "colonne courante pleine, passe à la suivante" :
    celui-ci pouvait faire déborder toutes les aptitudes dans la première
    colonne dès que la dernière pesait à elle seule plus que la moitié du
    total (ex. 2 aptitudes, la 2e nettement plus longue que la 1re : la
    hauteur cumulée après la 1re restait sous la cible, donc la 2e
    rejoignait quand même la colonne 1 au lieu de basculer en colonne 2).
    Jamais plus de colonnes que d'aptitudes ; un groupe à une seule aptitude
    reste seul en colonne 1, les suivantes vides."""
    columns: list[list[AbilityEntry]] = [[] for _ in range(n_cols)]
    if not group:
        return columns
    # jamais plus de colonnes "actives" que d'aptitudes — les colonnes en
    # trop restent vides (`columns` garde `n_cols` éléments, la forme que
    # `_ability_group_body_columns` attend pour zipper avec `col_widths`).
    active_cols = max(1, min(n_cols, len(group)))
    if active_cols <= 1:
        columns[0] = list(group)
        return columns
    # mesurée sans intitulé de catégorie (même si le groupe en affichera) :
    # cette hauteur ne sert qu'à équilibrer les colonnes par proportion, pas
    # de garde-fou à respecter au pt près comme `_chunk_group` — l'écart
    # (quelques pt par frontière de catégorie, répartis sur tout le groupe)
    # est négligeable pour cet usage.
    heights = [_ability_group_body([ab], col_width).wrap(col_width, 0xFFFF)[1] for ab in group]
    cumulative = [0.0]
    for h in heights:
        cumulative.append(cumulative[-1] + h)
    total = cumulative[-1]
    n = len(group)
    boundaries = [0]
    for i in range(1, active_cols):
        target = total * i / active_cols
        lo = boundaries[-1] + 1  # au moins 1 aptitude dans la colonne précédente
        hi = n - (active_cols - i)  # au moins 1 aptitude par colonne restante
        best_idx = min(range(lo, hi + 1), key=lambda idx: abs(cumulative[idx] - target))
        boundaries.append(best_idx)
    boundaries.append(n)
    for i in range(active_cols):
        columns[i] = group[boundaries[i] : boundaries[i + 1]]
    return columns


def _ability_text_chunks(text: str) -> list[str]:
    """Découpe `text` (déjà passé par `_clean_text`) en blocs au niveau de ses
    `<br/>` de premier niveau — jamais à l'intérieur d'une liste `<ul>...
    </ul>` (profondeur suivie), pour ne jamais couper une balise en 2. Sert
    de points de coupe sûrs à `_split_long_ability_columns` pour répartir une
    aptitude trop longue sur plusieurs colonnes."""
    depth = 0
    chunks: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("<ul>", i):
            depth += 1
            buf.append("<ul>")
            i += 4
        elif text.startswith("</ul>", i):
            depth -= 1
            buf.append("</ul>")
            i += 5
        elif depth == 0 and text.startswith("<br/>", i):
            piece = "".join(buf).strip()
            if piece:
                chunks.append(piece)
            buf = []
            i += 5
        else:
            buf.append(text[i])
            i += 1
    tail = "".join(buf).strip()
    if tail:
        chunks.append(tail)
    return chunks


#: Au-delà de ce volume de texte (caractères de la description, une seule
#: aptitude), une aptitude seule dans son bandeau de phase bénéficie d'une
#: mise en page à colonnes dédiée (`_split_long_ability_columns`) plutôt que
#: de tomber en repli pleine-largeur (`_ability_group_body_columns`) —
#: demande explicite de l'utilisateur : une aptitude au texte long doit
#: rester à sa place chronologique normale (pas de section/page dédiée) mais
#: profiter des mêmes colonnes que le reste de la carte. Calibré sur
#: `data/json/faction_rules_fr.json` : l'aptitude la plus longue observée
#: (« Inscription de Rune », Lumineth Realm-lords, ~3470 caractères) le
#: dépasse largement, la suivante (« Éruption de Fureur », règle de saison
#: partagée par plusieurs factions, ~1281 caractères) reste confortablement
#: en-dessous.
_LONG_ABILITY_THRESHOLD = 2000


def _split_long_ability_columns(ab: AbilityEntry, body_width: float, n_cols: int) -> Table | None:
    """Répartit le corps d'une seule aptitude longue sur `n_cols` colonnes
    côte à côte — nom+badges en tête de la 1re colonne seulement, texte
    scindé au niveau de ses coupures `<br/>` de premier niveau
    (`_ability_text_chunks`), équilibré par hauteur rendue comme
    `_split_group_columns` mais entre morceaux d'une même aptitude plutôt
    qu'entre aptitudes voisines. `None` si le texte n'a pas assez de
    coupures de premier niveau pour remplir `n_cols` colonnes — l'appelant
    retombe alors sur le rendu pleine-largeur habituel plutôt que de risquer
    une colonne vide ou coupée au mauvais endroit."""
    text = _clean_text(strip_flavor(_bold_set_up(ab.description) if render_options().bold_set_up else ab.description))
    sectioned = len([sec for sec in _TEXT_SECTION_SPLIT_RE.split(text) if sec.strip()]) >= _MIN_TEXT_SECTIONS
    chunks = _ability_text_chunks(text)
    if len(chunks) < n_cols:
        return None
    col_width = (body_width - _COLUMN_GAP * (n_cols - 1)) / n_cols
    content_width = col_width - 16
    heights = [_safe_paragraph(c, _TEXT_STYLE).wrap(content_width, 0xFFFF)[1] for c in chunks]
    cumulative = [0.0]
    for h in heights:
        cumulative.append(cumulative[-1] + h)
    total = cumulative[-1]
    n = len(chunks)
    boundaries = [0]
    for i in range(1, n_cols):
        target = total * i / n_cols
        lo = boundaries[-1] + 1
        hi = n - (n_cols - i)
        best_idx = min(range(lo, hi + 1), key=lambda idx: abs(cumulative[idx] - target))
        boundaries.append(best_idx)
    boundaries.append(n)

    name_col = content_width * 0.56
    cond_col = content_width - name_col
    header_cells, _kind = _ability_row_flowables(ab, name_col, cond_col, first=True)[0]

    cells: list = []
    col_widths: list[float] = []
    for i in range(n_cols):
        seg_text = "<br/><br/>".join(chunks[boundaries[i] : boundaries[i + 1]])
        seg_rows: list[list] = []
        seg_styles: list[tuple] = [
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if i == 0:
            seg_rows.append(header_cells)
            seg_styles += [("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 1)]
            text_row = 1
        else:
            text_row = 0
        # une colonne n'est qu'un morceau du texte : filets dès 2 sections
        # quand le texte entier est sectionné, pour rester homogène
        seg_rows.append(
            [_ability_text_flowable(seg_text, col_width - 16, min_sections=2 if sectioned else _MIN_TEXT_SECTIONS)]
        )
        seg_styles += [
            ("TOPPADDING", (0, text_row), (-1, text_row), 2 if i == 0 else 5),
            ("BOTTOMPADDING", (0, text_row), (-1, text_row), 6),
        ]
        seg_table = Table(seg_rows, colWidths=[col_width])
        seg_table.setStyle(TableStyle(seg_styles))
        cells.append(seg_table)
        col_widths.append(col_width)
        if i < n_cols - 1:
            cells.append(Spacer(_COLUMN_GAP, 0))
            col_widths.append(_COLUMN_GAP)
    t = Table([cells], colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t


def _ability_group_body_columns(
    chunk: list[AbilityEntry],
    body_width: float,
    n_cols: int,
    show_category_headers: bool = False,
) -> Table:
    """Comme `_ability_group_body`, mais réparti sur `n_cols` colonnes côte à
    côte plutôt qu'empilé dans une seule — la carte de règles fusionnée
    (`render_rule_card`) peut réunir jusqu'à une dizaine d'aptitudes dans le
    même bandeau de phase (ex. tous les Traits Héroïques d'une faction) ;
    les étaler sur 2 colonnes exploite la largeur, plus généreuse que celle
    d'une carte d'unité, au lieu d'une longue colonne unique. `n_cols=1`
    retombe exactement sur `_ability_group_body`. `show_category_headers` est
    propagé tel quel à chaque colonne plutôt que recalculé par colonne : une
    catégorie qui déborde d'une colonne à l'autre doit répéter son intitulé
    en haut de la colonne suivante, comme un en-tête de tableau qui se répète
    à chaque page/colonne, pour rester lisible sans remonter à la colonne
    précédente. Réduit d'abord `n_cols` au nombre d'aptitudes du tronçon
    (`_split_group_columns` ne remplit de toute façon jamais plus de colonnes
    « actives » que ça) : sans ça, un tronçon plus court que `n_cols` (ex. un
    unique trait de bataille, particulièrement long) restait confiné dans une
    seule colonne à *moitié* de `body_width`, la ou les colonnes voisines
    restant vides — un gâchis de largeur qui aggrave le texte long au lieu de
    l'aider. Une exception : une aptitude dont le texte dépasse
    `_LONG_ABILITY_THRESHOLD` n'entre jamais dans ce partage par aptitude
    entière (que ce tronçon en compte une seule ou plusieurs) — déléguée à
    `_ability_group_body_columns_mixed`, elle obtient sa propre bande pleine
    largeur répartie sur ses colonnes (`_split_long_ability_columns`,
    nom+badges dans la 1re colonne, texte réparti sur les suivantes) plutôt
    que de monopoliser toute une colonne face à une aptitude courte voisine
    qui, elle, n'a rien à gagner à être étalée."""
    if n_cols > 1 and any(_is_long_ability(ab) for ab in chunk):
        return _ability_group_body_columns_mixed(chunk, body_width, n_cols, show_category_headers)
    n_cols = max(1, min(n_cols, len(chunk))) if chunk else n_cols
    if n_cols <= 1:
        return _ability_group_body(chunk, body_width, show_category_headers)
    col_width = (body_width - _COLUMN_GAP * (n_cols - 1)) / n_cols
    columns = _split_group_columns(chunk, col_width, n_cols)
    cells: list = []
    col_widths: list[float] = []
    for i, col in enumerate(columns):
        cells.append(_ability_group_body(col, col_width, show_category_headers) if col else Spacer(col_width, 0))
        col_widths.append(col_width)
        if i < n_cols - 1:
            cells.append(Spacer(_COLUMN_GAP, 0))
            col_widths.append(_COLUMN_GAP)
    t = Table([cells], colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t


def _is_long_ability(ab: AbilityEntry) -> bool:
    return len(_clean_text(ab.description)) > _LONG_ABILITY_THRESHOLD


def _ability_group_body_columns_mixed(
    chunk: list[AbilityEntry],
    body_width: float,
    n_cols: int,
    show_category_headers: bool,
) -> Table:
    """Repli de `_ability_group_body_columns` pour un tronçon qui mélange au
    moins une aptitude longue (cf. `_LONG_ABILITY_THRESHOLD`) avec d'autres
    aptitudes — découpe `chunk` en tronçons consécutifs (une aptitude longue
    toujours seule dans le sien, plusieurs aptitudes courtes regroupées dans
    le leur), empilés dans l'ordre d'origine plutôt que réordonnés. Un
    tronçon "longue" est rendu par `_split_long_ability_columns` (ses
    propres colonnes) ; un tronçon "courtes" repasse par
    `_ability_group_body_columns` (jamais d'aptitude longue dedans, donc
    jamais de récursion vers cette fonction) pour garder le même partage par
    hauteur qu'un bandeau sans aptitude longue. Sans ce découpage,
    `_split_group_columns` traiterait la longue comme une aptitude entière
    parmi d'autres et lui donnerait une colonne entière pour elle seule, face
    à une aptitude courte livrée à elle-même dans l'autre — la longue reste
    cramponnée à la largeur d'une seule colonne au lieu de profiter des deux
    (demande explicite de l'utilisateur)."""
    runs: list[list[AbilityEntry]] = []
    for ab in chunk:
        if _is_long_ability(ab) or not runs or _is_long_ability(runs[-1][0]):
            runs.append([ab])
        else:
            runs[-1].append(ab)

    rows: list[list] = []
    styles: list[tuple] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for i, run in enumerate(runs):
        if len(run) == 1 and _is_long_ability(run[0]):
            body = _split_long_ability_columns(run[0], body_width, n_cols)
            if body is None:
                body = _ability_group_body(run, body_width, show_category_headers)
        else:
            body = _ability_group_body_columns(run, body_width, n_cols, show_category_headers)
        rows.append([body])
        if i > 0:
            styles.append(("LINEABOVE", (0, i), (-1, i), 0.4, _STEEL_LINE))
    t = Table(rows, colWidths=[body_width])
    t.setStyle(TableStyle(styles))
    return t


#: hauteur maximale d'une sous-section de choix, plus généreuse que
#: `_MAX_GROUP_HEIGHT` (marge de sécurité commune à tous les bandeaux) : le
#: cadre réel d'une page de cartes fait ~273mm (A4 moins la marge haute de
#: `assembly._PAGE_LABEL_MARGIN`, la marge basse et le padding du
#: `Frame`). Garder ~8mm de marge sous ce cadre évite la `LayoutError`.
#: Mesuré : la Dîme de Sang des Blades of Khorne fait ~246mm en
#: `fr-extended`, au-dessus des 240mm communs.
_MAX_CHOICE_HEIGHT = 265 * mm


def _choice_segments(group: list[AbilityEntry]) -> list[tuple[list[AbilityEntry], float]]:
    """Sépare une sous-section de choix (`CHOICE_CATEGORIES`, toujours en
    tête de son bandeau, cf. `_CATEGORY_ORDER`) du reste du bandeau, avec sa
    propre hauteur maximale (`_MAX_CHOICE_HEIGHT`) : demande de
    l'utilisateur, elle doit tenir sur une seule page. Seule dans son
    tronçon, elle part entière sur la page suivante plutôt que d'être
    coupée (cf. `_chunk_group`). Plus haute que ça malgré tout,
    `_chunk_group` la découpe, plutôt qu'une `LayoutError`. (3 colonnes au
    lieu de 2 a été essayé : plus haut, les pastilles s'empilent dans des
    colonnes trop étroites.)"""
    choice = [ab for ab in group if _ability_category(ab) in CHOICE_CATEGORIES]
    if not choice:
        return [(group, _MAX_GROUP_HEIGHT)]
    rest = [ab for ab in group if _ability_category(ab) not in CHOICE_CATEGORIES]
    return [(choice, _MAX_CHOICE_HEIGHT)] + ([(rest, _MAX_GROUP_HEIGHT)] if rest else [])


def _append_ability_groups(
    rows: list[list],
    styles: list[tuple],
    abilities: list[AbilityEntry],
    width: float,
    columns: int = 1,
    phase_order: list[str] | None = None,
) -> None:
    """Ajoute au corps de carte (unité ou règle) un groupe par bandeau de
    phase, dans l'ordre canonique du tour — partagé par `render_warscroll_card`
    et `render_rule_card` pour ne garder qu'une seule implémentation du
    tableau d'aptitudes. Bandeau vertical (`_PhaseRail`) à gauche du groupe,
    sa hauteur mesurée sur le corps du groupe avant de le construire.
    `columns` (>1 seulement pour `render_rule_card`, cf.
    `_ability_group_body_columns`) répartit chaque groupe de phase sur
    plusieurs colonnes côte à côte plutôt qu'une seule colonne empilée.

    Au sein d'un même bandeau de phase, les aptitudes sont triées par
    catégorie (`_CATEGORY_ORDER` : normales, sorts, prières, manifestations —
    tri stable, jamais réordonnées à l'intérieur d'une même catégorie) plutôt
    que laissées dans l'ordre de `abilities` — sans quoi, ex., un sort et un
    trait de bataille qui se déclenchent tous deux en phase des héros
    resteraient entremêlés dans cette phase plutôt que regroupés par type. Un
    intitulé de catégorie (cf. `_category_header`) n'est affiché que si la
    phase mélange effectivement plusieurs catégories — une carte d'unité sans
    sort/prière, l'écrasante majorité des cas, ne montre donc jamais
    "Aptitudes" en tête de sa phase des héros."""
    grouped: dict[str, list[AbilityEntry]] = {}
    for ab in abilities:
        grouped.setdefault(classify_phase(ab), []).append(ab)

    body_width = width - _RAIL_WIDTH
    first_phase_row: int | None = None
    for key in phase_order or _PHASE_ORDER:
        group = grouped.get(key)
        if not group:
            continue
        group = sorted(group, key=lambda ab: _CATEGORY_ORDER.index(_ability_category(ab)))
        categories = {_ability_category(ab) for ab in group}
        # une sous-section de choix (« Délires », « Dîme de Sang ») est
        # toujours titrée, même seule dans sa phase : c'est un regroupement
        # demandé en tant que tel.
        show_headers = len(categories) > 1 or bool(categories & CHOICE_CATEGORIES)
        bg, fg = _PHASE_COLORS[key]
        # le découpage page-safe (`_chunk_group`) est mesuré sur le même
        # nombre de colonnes que le rendu (cf. sa docstring).
        # une aptitude pleine largeur (`AbilityEntry.full_width`, ordre de
        # déroulé du Déploiement) : toute sa phase sur une seule colonne.
        n_cols = 1 if any(ab.full_width for ab in group) else columns
        chunks = [
            chunk
            for segment, max_height in _choice_segments(group)
            for chunk in _chunk_group(segment, body_width, show_headers, n_cols=n_cols, max_height=max_height)
        ]
        for chunk_i, chunk in enumerate(chunks):
            body = _ability_group_body_columns(chunk, body_width, n_cols, show_headers)
            _, body_height = body.wrap(body_width, 0xFFFF)
            # un groupe très court (une seule aptitude sans texte long) peut
            # être plus bas que ce qu'il faut pour loger le nom de la phase
            # pivoté à 90° — sans plancher, le texte déborde du bandeau et se
            # fait recouvrir par la ligne suivante. `_min_rail_height` mesure
            # la largeur réelle du libellé le plus long à cette police/taille
            # plutôt que de deviner une marge.
            rail_height = max(body_height, _min_rail_height(key))
            rail = _PhaseRail(tr(_PHASE_LABELS[key]).upper(), bg, fg, height=rail_height, width=_RAIL_WIDTH)

            group_row = Table([[rail, body]], colWidths=[_RAIL_WIDTH, body_width])
            group_row.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            # Un tronçon de phase (déjà garanti tenir sous `_MAX_GROUP_HEIGHT`,
            # donc sous une page pleine, cf. `_chunk_group`) est une ligne à
            # part entière de la table extérieure (`rows`) : `Table.split()`
            # ne coupe jamais une ligne en deux, seulement entre deux lignes —
            # ce tronçon ne peut donc déjà pas se retrouver coupé au milieu de
            # ses aptitudes à un saut de page, il part entier sur la page
            # suivante s'il ne rentre pas dans l'espace restant (`KeepTogether`
            # a été essayé ici pour le rendre plus explicite, mais échoue :
            # imbriqué dans une cellule de `Table`, `KeepTogether.wrap()`
            # renvoie une hauteur sentinelle énorme que la table extérieure
            # interprète comme une ligne à dimensionner en conséquence —
            # `reportlab.platypus.doctemplate.LayoutError` dès qu'un tronçon
            # atterrit en page 2+. `KeepTogether` ne fonctionne qu'au niveau
            # du flux de document (`story`), jamais imbriqué dans une cellule).
            rows.append([group_row])
            r = len(rows) - 1
            styles += [
                ("LEFTPADDING", (0, r), (-1, r), 0),
                ("RIGHTPADDING", (0, r), (-1, r), 0),
                ("TOPPADDING", (0, r), (-1, r), 0),
                ("BOTTOMPADDING", (0, r), (-1, r), 0),
            ]
            if chunk_i == 0 and first_phase_row is not None:
                # filet épais à la couleur de la phase qui commence : le
                # changement de phase se lit sur toute la largeur, pas
                # seulement sur le bandeau vertical (cf. `_PHASE_HEADER_HEIGHT`,
                # même problème en mode sectionné).
                styles.append(("LINEABOVE", (0, r), (-1, r), 2.2, colors.HexColor(bg)))
            if first_phase_row is None:
                first_phase_row = r
            if chunk_i == len(chunks) - 1:
                styles.append(("LINEBELOW", (0, r), (-1, r), 0.6, _STEEL_LINE))


def _pack_section_rows(abilities: list[AbilityEntry]) -> list[list[tuple[AbilityEntry, int]]]:
    """Range les aptitudes d'une sous-section en lignes de `_SECTION_COLUMNS`
    colonnes, chacune occupant 1 à 3 colonnes (`_ability_span`). Remplissage
    « première ligne où ça rentre » dans l'ordre, puis la place restante d'une
    ligne incomplète est redonnée à ses aptitudes les plus longues — jamais de
    case vide."""
    rows: list[list[tuple[AbilityEntry, int]]] = []
    for ab in abilities:
        span = _ability_span(ab)
        for row in rows:
            if sum(sp for _a, sp in row) + span <= _SECTION_COLUMNS:
                row.append((ab, span))
                break
        else:
            rows.append([(ab, span)])
    for row in rows:
        spare = _SECTION_COLUMNS - sum(sp for _a, sp in row)
        while spare > 0:
            i = max(range(len(row)), key=lambda k: len(_clean_text(row[k][0].description)) / row[k][1])
            row[i] = (row[i][0], row[i][1] + 1)
            spare -= 1
    return rows


def _section_header(title: str, width: float) -> Table:
    t = Table([[Paragraph(tr(title).upper(), _SECTION_HEADER_STYLE)]], colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _SECTION_HEADER_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    t._aospy_section_header = True
    return t


def _is_section_header(flow: Flowable) -> bool:
    return getattr(flow, "_aospy_section_header", False)


#: largeur minimale d'une case de grille, en fraction de la ligne — sous ce
#: seuil, nom + pastilles ne tiennent plus.
_MIN_CELL_FRACTION = 0.24


def _balanced_widths(row: list[tuple[AbilityEntry, int]], width: float) -> list[float]:
    """Largeurs des cases d'une ligne de grille : d'abord proportionnelles à
    leur nombre de colonnes, puis rééquilibrées selon la surface de texte de
    chaque case (hauteur × largeur mesurées) pour que les cases d'une même
    ligne aient des hauteurs proches — la ligne prend la hauteur de sa case la
    plus haute, tout écart est de la place perdue."""
    base = [width * span / _SECTION_COLUMNS for _ab, span in row]
    if len(row) < 2:
        return base
    areas = [_ability_rows_body([ab], w).wrap(w, 0xFFFF)[1] * w for (ab, _span), w in zip(row, base)]
    total = sum(areas)
    widths = [width * a / total for a in areas]
    floor = width * _MIN_CELL_FRACTION
    short = [i for i, w in enumerate(widths) if w < floor]
    if short:
        rest = width - floor * len(short)
        others = sum(areas[i] for i in range(len(row)) if i not in short)
        widths = [floor if i in short else rest * areas[i] / others for i in range(len(row))]
    return widths


def _section_row(row: list[tuple[AbilityEntry, int]], width: float) -> Table:
    """Une ligne de la grille : chaque aptitude dans sa case, de largeur
    proportionnelle à son nombre de colonnes, séparée de la voisine par un
    filet vertical."""
    widths = _balanced_widths(row, width)
    cells = [_ability_rows_body([ab], w) for (ab, _span), w in zip(row, widths)]
    t = Table([cells], colWidths=widths)
    styles = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if len(row) > 1:
        styles.append(("LINEBEFORE", (1, 0), (-1, -1), 0.4, _STEEL_LINE))
    t.setStyle(TableStyle(styles))
    return t


@dataclass
class _SectionItem:
    """Un élément du corps d'un bandeau de phase sectionné : titre de
    sous-section ou ligne de grille, avec le titre de sa sous-section (pour
    reprendre « (suite) » après une coupe de page)."""

    flow: Flowable
    title: str
    is_header: bool
    is_choice: bool


#: bandeaux qui suivent le déroulé de la partie étape par étape (« Placez le
#: Champ de Bataille », jet de priorité...) : jamais réordonnés par `RenderOptions.base_last`.
_SEQUENCE_PHASES = frozenset({"deploy", "round_start"})


def _sectioned_phase_items(
    group: list[AbilityEntry],
    body_width: float,
    phase_key: str = "",
) -> list[_SectionItem]:
    """Corps d'un bandeau de phase en sous-sections (titre noir + grille), à
    plat : `_SectionedPhaseGroup` se charge des coupes de page."""
    sections: dict[str, list[AbilityEntry]] = {}
    for ab in group:
        sections.setdefault(ability_section(ab), []).append(ab)
    base_last = render_options().base_last and phase_key not in _SEQUENCE_PHASES

    # `AbilityEntry.section_rank` (aptitude de synthèse `fr-split-simple`,
    # ex. « Jet de Lancement » juste avant les Sorts) prime sur le rang du titre.
    # `base_last` (`fr-split-simple`) : les règles de base, que le joueur
    # connaît, passent après celles de son armée (demande de l'utilisateur).
    def rank(kv: tuple[str, list[AbilityEntry]]) -> int:
        if base_last and kv[0] == SECTION_BASE:
            return max(_SECTION_RANK.values()) + 2
        return min(
            (ab.section_rank for ab in kv[1] if ab.section_rank is not None),
            default=_section_rank(kv[0]),
        )

    ordered = sorted(sections.items(), key=rank)  # tri stable
    items: list[_SectionItem] = []
    for title, abilities in ordered:
        abilities = sorted(abilities, key=lambda ab: _CATEGORY_ORDER.index(_ability_category(ab)))
        is_choice = title in _CATEGORY_LABELS_FR.values() and title not in _CAST_SECTIONS.values()
        items.append(_SectionItem(_section_header(title, body_width), title, True, is_choice))
        for row in _pack_section_rows(abilities):
            items.append(_SectionItem(_section_row(row, body_width), title, False, is_choice))
    return items


#: hauteur utile d'une page de cartes de règles (cadre de
#: `assembly._build_rule_cards_pdf` avec la marge haute du libellé de page,
#: ~273mm) moins une marge de sécurité — cf. `_MAX_CHOICE_HEIGHT`.
_FULL_PAGE_HEIGHT = 265 * mm


#: sous-sections gardées sur une même page (cf. `_SectionedPhaseGroup.split`).
_CONTIGUOUS_CAST_SECTIONS = ("Sorts", "Manifestations")

#: en-tête horizontal d'un bandeau de phase (cf. `_SectionedPhaseGroup`) et
#: espace entre deux bandeaux : sans eux, deux phases consécutives n'étaient
#: séparées que par le changement de couleur du bandeau vertical, la nouvelle
#: phase s'ouvrant sur un titre de sous-section noir identique aux autres —
#: changement de phase peu visible (signalé par l'utilisateur).
_PHASE_HEADER_HEIGHT = 3.4 * mm
_PHASE_HEADER_FONT_SIZE = 7.2
_PHASE_GAP = 2.2 * mm


#: un bandeau de phase sectionné qui manque la place restante de peu (au
#: moins ce ratio de sa hauteur tient) est réduit uniformément pour y tenir
#: au lieu de partir à la page suivante (demande de l'utilisateur).
_SHRINK_TO_FIT = 0.95


class _ShrunkFlowable(Flowable):
    """`flowable` réduit uniformément d'un facteur `scale` (< 1), centré
    horizontalement sur `width` (par défaut sa largeur réduite)."""

    def __init__(self, flowable: Flowable, scale: float, width: float | None = None):
        super().__init__()
        self._flowable = flowable
        self._scale = scale
        self.spaceBefore = getattr(flowable, "spaceBefore", 0)
        self.hAlign = getattr(flowable, "hAlign", "CENTER")
        self.width = flowable.width * scale if width is None else width
        self.height = flowable.height * scale

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate((self.width - self._flowable.width * self._scale) / 2, 0)
        c.scale(self._scale, self._scale)
        self._flowable.drawOn(c, 0, 0)
        c.restoreState()


class _SectionedPhaseGroup(Flowable):
    """Un bandeau de phase sectionné, posé directement dans le flux du
    document (pas dans une cellule de `Table`, que reportlab ne sait pas
    couper) : s'il ne rentre pas dans la place restante, part à la page
    suivante ; plus haut qu'une page, il se coupe alors entre deux lignes de
    grille (`split`) à partir de ce haut de page. Chaque
    morceau redessine le bandeau de phase à gauche ; une sous-section coupée
    reprend son titre « (suite) ». Une sous-section de choix (« Délires »...)
    n'est jamais coupée si elle tient sur une page (demande de
    l'utilisateur, cf. `_choice_segments`). Dessine aussi les bords gauche/
    droit/bas de la carte, que porte ailleurs la `Table` de `render_rule_card`."""

    def __init__(
        self,
        phase_key: str,
        items: list[_SectionItem],
        width: float,
        space_before: float = 0.0,
        continued: bool = False,
    ):
        super().__init__()
        self.phase_key = phase_key
        self.items = items
        self.width = width
        # ignoré par le `Frame` en haut de page : ne sépare que deux bandeaux
        # posés l'un sous l'autre.
        self.spaceBefore = space_before
        self.continued = continued
        #: recompose ce bandeau à une autre largeur (`_sectioned_phase_groups`,
        #: bandeau entier seulement — jamais un morceau déjà coupé)
        self.rebuild = None
        # centré comme la `Table` d'en-tête de carte (hAlign par défaut de
        # reportlab) : la carte est plus large que la zone utile du `Frame`
        # (padding de 6pt de chaque côté), un flowable aligné à gauche serait
        # décalé de 12pt vers la droite par rapport à son en-tête.
        self.hAlign = "CENTER"
        self.body_width = width - _RAIL_WIDTH
        self._heights = [it.flow.wrap(self.body_width, 0xFFFF)[1] for it in items]
        self.height = max(sum(self._heights), _min_rail_height(phase_key)) + _PHASE_HEADER_HEIGHT

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def split(self, availWidth, availHeight):
        # un bandeau qui ne rentre pas dans la place restante part sur la page
        # suivante, même s'il est plus haut qu'une page : il n'est alors coupé
        # qu'à partir d'un haut de page, jamais en laissant un petit morceau en
        # bas de la page précédente (demande de l'utilisateur). Sauf s'il est
        # déjà en haut de page (`availHeight` ≈ une page pleine), sans quoi
        # reportlab bouclerait.
        if self.rebuild is not None and _SHRINK_TO_FIT * self.height <= availHeight < self.height:
            # il ne manque presque rien : plutôt que de partir à la page
            # suivante en laissant un grand blanc, le bandeau est recomposé
            # plus large puis réduit à la largeur de la carte (texte un peu
            # plus petit, même largeur que les autres bandeaux).
            scale = availHeight / self.height
            for _ in range(6):
                wide = self.rebuild(self.width / scale)
                if wide.height * scale <= availHeight + 0.01:
                    return [_ShrunkFlowable(wide, scale, self.width)]
                scale *= availHeight / (wide.height * scale)
                if scale < _SHRINK_TO_FIT:
                    break
        if availHeight < _FULL_PAGE_HEIGHT:
            return []
        cumulative = _PHASE_HEADER_HEIGHT
        k = 0
        for h in self._heights:
            if cumulative + h > availHeight:
                break
            cumulative += h
            k += 1
        # jamais finir sur un titre de sous-section orphelin
        while k > 0 and self.items[k - 1].is_header:
            k -= 1
        if 0 < k < len(self.items) and self.items[k].is_choice and not self.items[k].is_header:
            # coupe au milieu d'une sous-section de choix : elle part entière
            start = k
            while start > 0 and not self.items[start].is_header:
                start -= 1
            k = start
        # plus haut qu'une page : coupé de préférence entre deux
        # sous-sections plutôt qu'au milieu de l'une d'elles.
        section_cut = max((i for i in range(1, k + 1) if i < len(self.items) and self.items[i].is_header), default=0)
        if section_cut > 0:
            k = section_cut
        # Sorts et Manifestations restent sur la même page quand ils y
        # tiennent ensemble (demande de l'utilisateur) : une coupe entre/dans
        # eux recule au titre « Sorts ».
        cast = [i for i, it in enumerate(self.items) if it.title in _CONTIGUOUS_CAST_SECTIONS]
        if cast and 0 < cast[0] < k <= cast[-1] and sum(self._heights[cast[0] : cast[-1] + 1]) <= _FULL_PAGE_HEIGHT:
            k = cast[0]
        if (
            k <= 0
            or sum(self._heights[:k]) < _min_rail_height(self.phase_key)
            and _min_rail_height(self.phase_key) > availHeight
        ):
            return []
        head, rest = self.items[:k], self.items[k:]
        if not rest:
            return [self]
        if not rest[0].is_header:
            title = rest[0].title
            rest = [
                _SectionItem(_section_header(f"{title} (suite)", self.body_width), title, True, rest[0].is_choice)
            ] + rest
        return [
            _SectionedPhaseGroup(self.phase_key, head, self.width, self.spaceBefore, self.continued),
            _SectionedPhaseGroup(self.phase_key, rest, self.width, continued=True),
        ]

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(_CARD_BG)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        bg, fg = _PHASE_COLORS[self.phase_key]
        label = tr(_PHASE_LABELS[self.phase_key]).upper()
        # bandeau vertical + en-tête horizontal de même couleur, en « L » : le
        # libellé se lit sans tourner la tête et le début de phase se repère
        # d'un coup d'œil sur toute la largeur de la carte.
        rail = _PhaseRail(label, bg, fg, height=self.height, width=_RAIL_WIDTH)
        rail.wrap(_RAIL_WIDTH, self.height)
        rail.drawOn(c, 0, 0)
        c.setFillColor(colors.HexColor(bg))
        c.rect(0, self.height - _PHASE_HEADER_HEIGHT, self.width, _PHASE_HEADER_HEIGHT, fill=1, stroke=0)
        c.setFillColor(colors.HexColor(fg))
        c.setFont("Helvetica-Bold", _PHASE_HEADER_FONT_SIZE)
        c.drawString(
            _RAIL_WIDTH + 2,
            self.height - _PHASE_HEADER_HEIGHT / 2 - _PHASE_HEADER_FONT_SIZE * 0.35,
            f"{label} (SUITE)" if self.continued else label,
        )
        y = self.height - _PHASE_HEADER_HEIGHT
        prev_header = True
        for it, h in zip(self.items, self._heights):
            y -= h
            it.flow.drawOn(c, _RAIL_WIDTH, y)
            if not it.is_header and not prev_header:
                # filet entre deux lignes de grille d'une même sous-section
                c.setStrokeColor(_STEEL_LINE)
                c.setLineWidth(0.4)
                c.line(_RAIL_WIDTH, y + h, self.width, y + h)
            prev_header = it.is_header
        c.setStrokeColor(_STEEL_LINE)
        c.setLineWidth(0.8)
        c.line(0, 0, 0, self.height)
        c.line(self.width, 0, self.width, self.height)
        c.setLineWidth(0.6)
        c.line(0, 0, self.width, 0)
        c.restoreState()


def _sectioned_phase_groups(
    abilities: list[AbilityEntry],
    width: float,
    phase_order: list[str] | None = None,
) -> list[Flowable]:
    """Variante de `_append_ability_groups` (mode `fr-split`) : même bandeau
    de phase vertical à gauche, mais le corps est découpé en sous-sections
    horizontales — règles de base (génériques), règles d'armée, puis une par
    unité — chacune titrée dans un bandeau noir (plutôt qu'une pastille par
    aptitude) au-dessus d'une grille de 1 à 3 colonnes (`_pack_section_rows`).
    Un `_SectionedPhaseGroup` par phase, à poser dans le flux du document."""
    grouped: dict[str, list[AbilityEntry]] = {}
    for ab in abilities:
        grouped.setdefault(classify_phase(ab), []).append(ab)
    keys = [key for key in phase_order or _PHASE_ORDER if grouped.get(key)]

    def build(key: str, w: float, space_before: float, with_rebuild: bool) -> _SectionedPhaseGroup:
        group = _SectionedPhaseGroup(
            key,
            _sectioned_phase_items(grouped[key], w - _RAIL_WIDTH, phase_key=key),
            w,
            space_before=space_before,
        )
        if with_rebuild:
            # une recomposition (`rebuild`) a lieu à la mise en page, une fois
            # sorti de `render_rule_card` : options rétablies telles qu'à la
            # composition
            options = render_options()

            def rebuild(new_w: float) -> _SectionedPhaseGroup:
                with use_render_options(options):
                    return build(key, new_w, space_before, False)

            group.rebuild = rebuild
        return group

    return [build(key, width, _PHASE_GAP if i else 0.0, True) for i, key in enumerate(keys)]


def _two_columns_block(columns: list[list[Flowable]], width: float, gap: float) -> Table:
    """Une table d'une ligne, une colonne d'écart dédiée entre les 2 colonnes
    de cartes empilées (une cellule reportlab accepte une liste de
    `Flowable`) : un padding sur la cellule forcerait seulement la table à
    s'élargir, chaque carte ayant sa largeur interne fixe."""
    return Table(
        [[columns[0], "", columns[1]]],
        colWidths=[width, gap, width],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )


def pack_cards_two_columns(
    cards: list[Flowable],
    heights: list[float],
    width: float = 88 * mm,
    gap: float = 5 * mm,
    solo: list[bool] | None = None,
    page_height: float = _MAX_CARD_HEIGHT,
    groups: list[str | None] | None = None,
) -> list:
    """Empile des cartes en 2 colonnes indépendantes, page par page (demande
    de l'utilisateur : une carte courte ne laisse plus un grand vide à côté
    d'une carte haute, comme avec des lignes de 2). Dans l'ordre d'entrée,
    chaque carte va dans la colonne la moins haute de la page en cours où
    elle tient (sinon l'autre) ; sinon elle passe à la page suivante, et les
    cartes suivantes qui tiennent encore comblent la page en cours. `solo[i]` marque
    une carte redessinée en pleine largeur (`width * 2 + gap`, cf.
    `build_warscroll_cards_flow`) : elle clôt les colonnes en cours et prend
    toute la largeur. `heights[i]` = hauteur de `cards[i]` à sa largeur ;
    `page_height` = hauteur utile d'une page (cadre `_CARD_PAGE_MARGIN`).
    `groups[i]` : les cartes d'un même groupe (non `None`, ex. toutes les
    chartes de manifestation) sont posées ensemble sur une même page, à la
    place de la première d'entre elles — sinon le groupe entier passe à la
    page suivante."""
    solo = solo or [False] * len(cards)
    groups = groups or [None] * len(cards)
    story: list = []
    used = 0.0  # hauteur déjà occupée sur la page en cours (blocs clos)
    columns: list[list[Flowable]] = [[], []]
    col_h = [0.0, 0.0]

    def block_height() -> float:
        return max(col_h)

    def close_block() -> None:
        nonlocal used, columns, col_h
        if not any(columns):
            return
        if story and used > 0:
            story.append(Spacer(1, gap))
            used += gap
        story.append(_two_columns_block(columns, width, gap))
        used += block_height()
        columns, col_h = [[], []], [0.0, 0.0]

    def new_page() -> None:
        nonlocal used
        story.append(PageBreak())
        used = 0.0

    def try_place(item: list[tuple[Flowable, float]]) -> bool:
        # toutes les cartes de `item` ou aucune (groupe d'une même page)
        room = page_height - used - (gap if used > 0 else 0)
        sim_h = list(col_h)
        plan = []
        for _card, h in item:
            for c in sorted((0, 1), key=lambda c: sim_h[c]):
                add = h + (gap if (columns[c] or any(p == c for p in plan)) else 0)
                if sim_h[c] + add <= room:
                    sim_h[c] += add
                    plan.append(c)
                    break
            else:
                return False
        for (card, h), c in zip(item, plan):
            if columns[c]:
                columns[c].append(Spacer(1, gap))
            columns[c].append(card)
        col_h[:] = sim_h
        return True

    def place_run(run: list[list[tuple[Flowable, float]]]) -> None:
        # premier emplacement libre : une carte (ou un groupe) qui ne tient
        # plus passe à la page suivante, mais les suivantes qui tiennent
        # encore comblent la page en cours (l'ordre ne bouge que d'une page
        # au plus).
        while run:
            deferred = [item for item in run if not try_place(item)]
            if len(deferred) == len(run) and used == 0 and not any(columns):
                if len(deferred[0]) > 1:
                    # groupe trop haut même pour une page vide : ses cartes
                    # reprennent le placement normal, une à une
                    run = [[pair] for pair in deferred[0]] + deferred[1:]
                    continue
                # page vide et une carte plus haute qu'une page : posée
                # quand même, reportlab la coupera
                columns[0].append(deferred[0][0][0])
                col_h[0] = deferred[0][0][1]
                deferred = deferred[1:]
            if deferred:
                close_block()
                new_page()
            run = deferred

    run: list[list[tuple[Flowable, float]]] = []
    group_items: dict[str, list[tuple[Flowable, float]]] = {}
    for card, h, is_solo, group in zip(cards, heights, solo, groups):
        if not is_solo:
            if group is None:
                run.append([(card, h)])
            elif group in group_items:
                group_items[group].append((card, h))
            else:
                group_items[group] = [(card, h)]
                run.append(group_items[group])
            continue
        place_run(run)
        run = []
        close_block()
        if used > 0 and used + gap + h > page_height:
            new_page()
        elif used > 0:
            story.append(Spacer(1, gap))
            used += gap
        story.append(card)
        used += h
    place_run(run)
    close_block()
    return story

"""Cartes maison : warscroll (`render_warscroll_card`), règles (`render_rule_card`), tactique (`render_tactic_card`)."""

from __future__ import annotations

import re

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

from ..sources.tactic_cards import SubTactic, TacticCard
from ..sources.wahapedia_lookup import AbilityEntry, WarscrollData
from .layout import (
    _MAX_CARD_HEIGHT,
    _NOTE_STYLE,
    _PLACEMENT_STYLE,
    _append_ability_groups,
    _sectioned_phase_groups,
    pack_cards_two_columns,
)
from .options import render_options, render_options_override
from .pills import (
    _CAST_BADGE_COLORS,
    _CAST_BADGE_FG,
    _CAST_BADGE_SHAPES,
    _CASTER_BADGE_SIZE,
    _CastBadge,
    _caster_badge_row,
    _caster_badges,
    _pill,
    _visible_keywords,
    _wielder_ratios,
)
from .text import (
    _clean_text,
    _safe_paragraph,
    tr,
    weapon_abilities_fr,
)
from .theme import (
    _BADGE_NEUTRAL,
    _BADGE_REACT,
    _BADGE_STAT,
    _CARD_BG,
    _HEAD_STYLE,
    _INK,
    _KW_STYLE,
    _META_STYLE,
    _PHASE_COLORS,
    _PROV_STYLE,
    _ROLE_STYLE,
    _STAT_STYLE,
    _STEEL,
    _STEEL_LINE,
    _SUBTITLE_STYLE,
    _WHD_STYLE,
    _WNAME_STYLE,
    _WTAG_STYLE,
    _WVAL_STYLE,
    CARD_TITLE_FONT,
)

#: en-deçà de ce volume de texte cumulé (caractères des descriptions, tous
#: bandeaux de phase confondus), une carte de règles fusionnée tient
#: confortablement sur une seule colonne — l'étaler sur 2 colonnes n'aidait
#: alors qu'à rétrécir chaque bandeau sans rien gagner en compacité (ex. une
#: Armée de Renom sans Formation propre, ou une faction dont seuls 2-3
#: Traits de Bataille courts sont couverts). Au-delà, la carte réunit assez
#: de contenu (Traits de Bataille + Formation + Traits Héroïques/Artefacts +
#: domaines...) pour qu'un bandeau de phase chargé (ex. tous les Traits
#: Héroïques) bénéficie vraiment des 2 colonnes — cas de figure le plus
#: courant en pratique, une faction pleinement curée dépassant largement ce
#: seuil (généralement >15000 caractères).
_RULE_CARD_TWO_COLUMN_THRESHOLD = 2000


def _rule_card_columns(abilities: list[AbilityEntry]) -> int:
    total_chars = sum(len(_clean_text(ab.description)) for ab in abilities)
    return 2 if total_chars > _RULE_CARD_TWO_COLUMN_THRESHOLD else 1


def render_rule_card(
    title: str, abilities: list[AbilityEntry], width: float = 88 * mm, subtitle: str | None = None,
    phase_order: list[str] | None = None, hide_turn_qualifier: bool = False, sectioned: bool = False,
    base_last: bool = False,
) -> Flowable | list[Flowable] | None:
    """Carte de règle — même grammaire visuelle que `render_warscroll_card`
    mais sans bandeau de stats ni armes, ces cartes ne sont pas des unités.
    `abilities` est déjà étiqueté par catégorie (`tag_ability_origin`) côté
    appelant, avant d'être éventuellement fusionné avec d'autres catégories
    sur une seule carte triée par phase (cf. `pdf_builder.resolve_rules`) —
    ce n'est plus la responsabilité de cette fonction de le faire.  `None`
    si `abilities` est vide (rien à afficher)."""
    if not abilities:
        return None
    rows: list[list] = []
    styles: list[tuple] = []

    header_cell = [Paragraph(title, _HEAD_STYLE)]
    if subtitle:
        header_cell.append(Paragraph(subtitle, _ROLE_STYLE))
    rows.append([header_cell])
    styles.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161a2b")))
    styles.append(("TOPPADDING", (0, 0), (-1, 0), 5))
    styles.append(("BOTTOMPADDING", (0, 0), (-1, 0), 5))
    styles.append(("LEFTPADDING", (0, 0), (-1, 0), 8))

    # jusqu'à 2 colonnes par bandeau de phase (cf. `_rule_card_columns`) :
    # cette carte réunit plusieurs catégories (Traits de Bataille,
    # Formation, Traits Héroïques...) triées ensemble par phase, donc un
    # bandeau peut compter beaucoup d'aptitudes — sa largeur (130mm, contre
    # 88mm pour une carte d'unité) s'y prête mieux qu'une longue colonne
    # unique, mais seulement si le contenu total le justifie.
    # `sectioned` (mode `fr-split`) : sous-sections titrées par origine puis
    # par unité, grille de 1 à 3 colonnes (`_append_sectioned_ability_groups`).
    # Rendu sectionné : une liste de flowables (en-tête de carte puis un
    # `_SectionedPhaseGroup` par phase) plutôt qu'une seule `Table`, pour que
    # chaque bandeau de phase puisse se couper entre deux pages.
    with render_options_override(hide_turn_qualifier=hide_turn_qualifier, sectioned=sectioned, base_last=base_last):
        if sectioned:
            header = Table(rows, colWidths=[width])
            header.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                *styles,
            ]))
            # l'en-tête de carte ne reste jamais seul en bas de page
            header.keepWithNext = True
            return [header] + _sectioned_phase_groups(abilities, width, phase_order=phase_order)
        _append_ability_groups(rows, styles, abilities, width, columns=_rule_card_columns(abilities), phase_order=phase_order)

    card = Table(rows, colWidths=[width])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *styles,
    ]))
    return card


#: Marge de la cellule qui contient le tableau d'armes — utilisée à la fois
#: pour dimensionner `col_widths` (cf. `content_width` ci-dessous) et pour
#: poser le style de padding de cette cellule, afin que les deux ne puissent
#: pas diverger de nouveau.
_WEAPON_ROW_LEFT_PAD = 8
_WEAPON_ROW_RIGHT_PAD = 6


_PLACE_WHOLLY_RE = re.compile(r"entièrement à (\d+)\"|wholly within (\d+)\"", re.I)
_PLACE_WITHIN_RE = re.compile(r"\bà (\d+)\"|\bwithin (\d+)\"", re.I)
_PLACE_EDGE_RE = re.compile(r"d['’]un bord|battlefield edge", re.I)
_PLACE_ENEMY_RE = re.compile(r"à plus de (\d+)\" (?:de toutes les |des )unités ennemies|more than (\d+)\" from all enemy units", re.I)
_PLACE_PARTS_RE = re.compile(
    r"(?:a|se compose de) (\d+) parties qui doivent être placées à (\d+)\" l['’]une de l['’]autre"
    r"|has (\d+) parts that must be set up within (\d+)\" of each other", re.I,
)
_PLACE_EACH_PART_RE = re.compile(
    r"(?:a|se compose de) (\d+) parties chacune devant être placée à (\d+)\" d['’]au moins 1 autre partie"
    r"|has (\d+) parts that must each be set up within (\d+)\" of at least 1 other part", re.I,
)
_PLACE_CIRCLE_RE = re.compile(r"(\d+) parties qui doivent être placées en contact|(\d+) parts that must be set up touching", re.I)
_PLACE_TRIANGLE_RE = re.compile(r"exactement (\d+)\" de la première|exactly (\d+)\" from the first part", re.I)


def _first(m: re.Match | None) -> list[str]:
    return [g for g in m.groups() if g is not None] if m else []


def summon_placement_note(summon: AbilityEntry) -> list[str]:
    """Règle de pose d'une convocation de manifestation en puces courtes
    (« Entièrement à 12" et visible du lanceur », « À plus de 9" de
    l'ennemi », « 2 parties à 9" l'une de l'autre »), lue sur l'effet du sort
    de convocation lui-même (pas sur l'encadré « Référence de convocation »
    des chartes GW, qui en oublie parfois, ex. les 2 parties des Géminides
    d'Uhl-Gysh). Français (`faction_rules_fr.json`, formulations variables :
    « visible et entièrement à 18" du Prêtre », « entièrement à 12" du
    lanceur et visible de lui »...) ou anglais (Wahapedia). Rien si aucune
    distance n'est reconnue (mieux vaut pas de note qu'une note fausse). La
    valeur de lancement n'y figure pas : badge dédié."""
    text = re.sub(r"<[^>]+>", " ", summon.description or "").replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    effect = re.split(r"Effet ?:|Effect:", text, maxsplit=1)[-1].strip()
    first_sentence = effect.split(". ", 1)[0]
    lines: list[str] = []

    en = render_options().english_labels
    is_priest = re.search(r"prêtre|chanter|priest", first_sentence, re.I)
    if en:
        who = "of the priest" if is_priest else "of the caster"
        visible = " and visible to" if re.search(r"visible", first_sentence, re.I) else ""
        who = ("the priest" if is_priest else "the caster") if visible else who
    else:
        who = "du prêtre" if is_priest else "du lanceur"
        visible = " et visible" if re.search(r"visible", first_sentence, re.I) else ""
    if _PLACE_EDGE_RE.search(first_sentence) and (n := _first(_PLACE_WHOLLY_RE.search(first_sentence))):
        lines.append(f'Wholly within {n[0]}" of a battlefield edge' if en else f'Entièrement à {n[0]}" d\'un bord de table')
    elif n := _first(_PLACE_WHOLLY_RE.search(first_sentence)):
        lines.append(f'Wholly within {n[0]}"{visible} {who}' if en else f'Entièrement à {n[0]}"{visible} {who}')
    elif n := _first(_PLACE_WITHIN_RE.search(first_sentence)):
        lines.append(f'Within {n[0]}"{visible} {who}' if en else f'À {n[0]}"{visible} {who}')
    if not lines:
        return []
    if n := _first(_PLACE_ENEMY_RE.search(effect)):
        lines.append(f'More than {n[0]}" from the enemy' if en else f'À plus de {n[0]}" de l\'ennemi')
    if n := _first(_PLACE_PARTS_RE.search(effect)):
        lines.append(f'{n[0]} parts within {n[1]}" of each other' if en else f'{n[0]} parties à {n[1]}" l\'une de l\'autre')
    elif n := _first(_PLACE_EACH_PART_RE.search(effect)):
        lines.append(f'{n[0]} parts, each within {n[1]}" of another' if en else f'{n[0]} parties, chacune à {n[1]}" d\'une autre')
    elif n := _first(_PLACE_CIRCLE_RE.search(effect)):
        lines.append(f"{n[0]} parts touching, in a circle" if en else f"{n[0]} parties en contact, en cercle")
    elif n := _first(_PLACE_TRIANGLE_RE.search(effect)):
        lines.append(f'3 parts exactly {n[0]}" from each other, in a triangle' if en else f'3 parties à exactement {n[0]}" l\'une de l\'autre, en triangle')
    return lines


def _summon_badge(summon: AbilityEntry) -> _CastBadge | None:
    pts_type = (summon.points_type or "").strip()
    value = (summon.points or "").strip()
    if pts_type not in ("Spell", "Prayer") or not value:
        return None
    return _CastBadge(
        _CAST_BADGE_SHAPES[pts_type], f"{value}+", _CAST_BADGE_COLORS[pts_type], _CAST_BADGE_FG[pts_type],
        size=_CASTER_BADGE_SIZE,
    )


def render_warscroll_card(ws: WarscrollData, width: float = 88 * mm, regiment_note: str | None = None) -> Flowable:
    """Construit la carte d'une unité en un seul `Flowable` composite (table
    imbriquée) : bandeau nom/rôle, stats, armes, aptitudes groupées par
    bandeau de phase (ordre canonique du tour), mots-clés. Verbatim anglais,
    aucune page de battletome copiée."""
    rows: list[list] = []
    styles: list[tuple] = []

    # Pas de sous-titre de rôle ("INFANTRY", "INFANTRY HERO"...) sous le nom :
    # `ws.role` ne fait que redire un mot-clé déjà affiché dans la liste de
    # mots-clés en pied de carte (`ws.keywords` porte toujours "Infantry"/
    # "Hero" séparément, cf. Wahapedia) — un vrai nom français y prendrait sa
    # place plus tard (cf. la maquette HTML), mais aucune source de données
    # fiable n'existe encore pour ça.
    name_role_cell: list = [Paragraph(ws.name, _HEAD_STYLE)]
    if ws.subtitle:
        name_role_cell.append(Paragraph(ws.subtitle, _SUBTITLE_STYLE))

    # badge Sorcier/Prêtre en haut à droite de l'en-tête (cf.
    # `_caster_badges`) : seulement construit un en-tête à 2 colonnes quand
    # l'unité en porte un, pour ne rien changer à la mise en page de
    # l'écrasante majorité des unités (aucun niveau de magie/de prière).
    caster_badges = _caster_badges(ws.keywords)
    # manifestation : valeur de lancement de sa convocation, même place
    summon_badge = _summon_badge(ws.summon) if ws.summon is not None else None
    if summon_badge is not None:
        caster_badges.append(summon_badge)
    if caster_badges:
        badge_flow, badge_w = _caster_badge_row(caster_badges)
        name_col_w = width - 8 - 8 - badge_w - 6  # 8+8 = LEFTPADDING/RIGHTPADDING posés plus bas sur cette ligne
        header_inner = Table([[name_role_cell, badge_flow]], colWidths=[name_col_w, badge_w + 6])
        header_inner.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        header_cell = [header_inner]
    else:
        header_cell = name_role_cell
    rows.append([header_cell])
    styles.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor("#161a2b")))
    styles.append(("TOPPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 5))
    styles.append(("BOTTOMPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 5))
    styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))
    styles.append(("RIGHTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))

    stat_labels = ["MV", "CT", "SV", "WD", "HP"]
    stat_values = [ws.move or "—", ws.control or "—", ws.save or "—", ws.ward or "—", ws.health or "—"]
    stat_cells = [
        Paragraph(f'{k}<br/><font size=12 color="#14172a"><b>{v}</b></font>', _STAT_STYLE)
        for k, v in zip(stat_labels, stat_values)
    ]
    stat_table = Table([stat_cells], colWidths=[width / 5] * 5)
    stat_table.setStyle(TableStyle([
        ("LINEAFTER", (0, 0), (-2, 0), 0.4, _STEEL_LINE),
        ("LINEBEFORE", (2, 0), (2, 0), 1, _STEEL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    rows.append([stat_table])
    styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    meta_left = f"{ws.unit_size} model" + ("s" if ws.unit_size not in ("1", "") else "") if ws.unit_size else ""
    # une manifestation/un sort vivant n'a pas de coût en points (invoqué en
    # jeu, jamais acheté dans la liste) — `ws.points` y est vide.
    meta_right = f"{ws.points} pts" if ws.points else tr("Invoquée")
    meta_table = Table([[Paragraph(meta_left, _META_STYLE), Paragraph(meta_right, ParagraphStyle("wc_metar", parent=_META_STYLE, alignment=2))]], colWidths=[width / 2] * 2)
    meta_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    rows.append([meta_table])
    styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    placement = summon_placement_note(ws.summon) if ws.summon is not None else []
    if placement:
        rows.append([Paragraph("<br/>".join(f"• {line}" for line in placement), _PLACEMENT_STYLE)])
        styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))
        styles.append(("TOPPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 3))
        styles.append(("BOTTOMPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 4))
        styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    if regiment_note:
        rows.append([Paragraph(regiment_note, _NOTE_STYLE)])
        styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))
        styles.append(("TOPPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 2))
        styles.append(("BOTTOMPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 2))
        styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    if ws.weapons:
        ratios = _wielder_ratios(ws.description)
        # une colonne Portée dédiée seulement si l'unité porte au moins une
        # arme de tir — sinon elle serait vide sur toute la carte (toutes
        # armes de mêlée) et ne ferait que grignoter la colonne Nom pour
        # rien. Une arme de mêlée sur une carte qui en a une la laisse vide
        # plutôt que d'y répéter un tiret.
        has_ranged = any(w.range for w in ws.weapons)
        whd = ["", tr("Portée"), "Atk", "Hit", "Wnd", "Rnd", "Dmg"] if has_ranged else ["", "Atk", "Hit", "Wnd", "Rnd", "Dmg"]
        wrows = [[Paragraph(h, _WHD_STYLE) for h in whd]]
        stat_col_w = 9 * mm
        n_stat_cols = 6 if has_ranged else 5
        # `width` est la largeur pleine de la carte, mais cette table est
        # posée dans une cellule qui porte elle-même `_WEAPON_ROW_LEFT_PAD` +
        # `_WEAPON_ROW_RIGHT_PAD` de marge (cf. plus bas) — sans en tenir
        # compte ici, `colWidths` sommait à `width` plein alors que l'espace
        # réellement disponible dans la cellule est plus étroit, et une
        # valeur de dégât large ("D3+3") débordait du cadre de la carte
        # (repéré sur Terrorgheist's Fanged Maw, FEC). Même correction que
        # `_ability_group_body.content_width` applique déjà pour son propre
        # padding.
        content_width = width - _WEAPON_ROW_LEFT_PAD - _WEAPON_ROW_RIGHT_PAD
        col_widths = [content_width - n_stat_cols * stat_col_w] + [stat_col_w] * n_stat_cols
        # souligne chaque ligne d'arme dans la couleur de sa phase (même
        # palette que les bandeaux d'aptitude, `_PHASE_COLORS`) — mêlée en
        # rouge, tir en bleu — pour la distinguer au premier coup d'œil sans
        # avoir à lire la colonne Portée, et sépare visuellement les entrées
        # quand l'unité porte plusieurs profils d'arme.
        row_underlines: list[tuple[int, str]] = []
        for w in ws.weapons:
            name_para = _safe_paragraph(f"<b>{w.name}</b>", _WNAME_STYLE)
            ratio = ratios.get(w.name.strip().lower())
            ratio_pill = _pill(ratio, _BADGE_NEUTRAL, "#eaf1f8") if ratio else None
            if ratio_pill is not None:
                # ratio de porteurs à côté du nom, sur la même ligne
                # (colonnes auto-taillées, pas de `colWidths` fixe) — pas en
                # dessous, pour ne pas désaligner le nom par rapport aux
                # colonnes Atk/Hit/Wnd/Rnd/Dmg de la même ligne.
                name_line = Table([[name_para, ratio_pill]])
                name_line.setStyle(TableStyle([
                    ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 5),
                    ("RIGHTPADDING", (1, 0), (1, 0), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]))
                name_cell: list = [name_line]
            else:
                name_cell = [name_para]
            if w.abilities:
                tags = _clean_text(w.abilities)
                if render_options().french_weapon_tags:
                    tags = weapon_abilities_fr(tags)
                name_cell.append(_safe_paragraph(tags, _WTAG_STYLE))
            row = [name_cell]
            if has_ranged:
                row.append(Paragraph(w.range, _WVAL_STYLE) if w.range else Paragraph("", _WVAL_STYLE))
            row += [
                Paragraph(w.attacks, _WVAL_STYLE), Paragraph(w.hit, _WVAL_STYLE), Paragraph(w.wound, _WVAL_STYLE),
                Paragraph(w.rend, _WVAL_STYLE), Paragraph(w.damage, _WVAL_STYLE),
            ]
            wrows.append(row)
            underline_color = _PHASE_COLORS["shoot"][0] if w.range else _PHASE_COLORS["melee"][0]
            row_underlines.append((len(wrows) - 1, underline_color))
        weapons_table = Table(wrows, colWidths=col_widths)
        weapon_styles: list[tuple] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (1, 0), (-1, -1), 1), ("RIGHTPADDING", (1, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 3),
        ]
        for row_i, color in row_underlines:
            weapon_styles.append(("LINEBELOW", (0, row_i), (-1, row_i), 1, colors.HexColor(color)))
        weapons_table.setStyle(TableStyle(weapon_styles))
        rows.append([weapons_table])
        styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), _WEAPON_ROW_LEFT_PAD))
        styles.append(("RIGHTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), _WEAPON_ROW_RIGHT_PAD))
        styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    _append_ability_groups(rows, styles, ws.abilities, width)

    visible_keywords = _visible_keywords(ws.keywords)
    if visible_keywords:
        kw_text = " · ".join(k.upper() for k in visible_keywords)
        kw_table = Table([[Paragraph(kw_text, _KW_STYLE), Paragraph("Wahapedia (EN)", _PROV_STYLE)]], colWidths=[width * 0.75, width * 0.25])
        kw_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        rows.append([kw_table])

    card = Table(rows, colWidths=[width])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *styles,
    ]))
    return card


def build_warscroll_cards_flow(
    warscrolls: list[WarscrollData], width: float = 88 * mm, gap: float = 5 * mm,
    regiment_notes: dict[str, str] | None = None,
) -> list:
    """`regiment_notes` (clé = `WarscrollData.name`) ajoute la petite note de
    provenance d'un Regiment of Renown à une seule unité membre — cf.
    `pdf_builder.py`."""
    regiment_notes = regiment_notes or {}
    full_width = width * 2 + gap
    cards: list[Flowable] = []
    heights: list[float] = []
    solo: list[bool] = []
    # chartes de manifestation : toutes sur une même page (demande de
    # l'utilisateur), cf. `pack_cards_two_columns(groups=...)`
    groups: list[str | None] = [
        "manifestation" if any(kw.strip().upper() == "MANIFESTATION" for kw in ws.keywords) else None
        for ws in warscrolls
    ]
    for ws in warscrolls:
        note = regiment_notes.get(ws.name)
        card = render_warscroll_card(ws, width=width, regiment_note=note)
        _, height = card.wrap(width, 0xFFFF)
        oversized = height > _MAX_CARD_HEIGHT
        if oversized:
            # à demi-largeur, cette carte ne tiendrait sur aucune page (cf.
            # `_MAX_CARD_HEIGHT`) ; redessinée en pleine largeur, le même
            # texte s'enroule sur bien moins de lignes et repasse sous la
            # hauteur d'une page — posée seule sur toute la largeur, cf.
            # `pack_cards_two_columns`.
            card = render_warscroll_card(ws, width=full_width, regiment_note=note)
            _, height = card.wrap(full_width, 0xFFFF)
        cards.append(card)
        heights.append(height)
        solo.append(oversized)
    return pack_cards_two_columns(cards, heights, width=width, gap=gap, solo=solo, groups=groups)


# -- Cartes de tactique de bataille --------------------------------------
# Transcription manuelle, verbatim en français (`tactic_cards.py`) — même
# grammaire visuelle (pastilles pleines, pas de texte coloré entre crochets)
# que les cartes d'unité/de règle, adaptée : pas de bandeau de phase ici (une
# tactique se déclenche « à la fin de votre tour », pas liée à une phase
# précise du Manuel du général), 3 sous-tactiques (Échauffourée / Frappe /
# Domination) à la place, chacune avec sa propre pastille de type et sa
# pastille de points de victoire.

#: une couleur de pastille par type de sous-tactique — l'échelle de gravité
#: de la carte source (échauffourée -> frappe -> domination, en principe de
#: plus en plus difficile à déclencher) mappée sur l'échelle de sévérité déjà
#: en place pour les badges d'aptitude (neutre -> stat mise en avant ->
#: alerte), pas une nouvelle palette inventée pour l'occasion.
_TACTIC_KIND_COLORS: dict[str, tuple[str, str]] = {
    "Échauffourée": (_BADGE_NEUTRAL, "#eaf1f8"),
    "Frappe": (_BADGE_STAT, "#eaf4f6"),
    "Domination": (_BADGE_REACT, "#fbeaec"),
}
#: pastille de points de victoire — un aplat doré plus riche que
#: `_BADGE_KEYWORD` (réservé aux mots-clés) : ce badge doit se repérer d'un
#: coup d'œil même sans lire le texte, comme la médaille dorée de la carte
#: source, pas se confondre avec une classification de plus.
_POINTS_GOLD = "#c9a227"
_POINTS_INK = "#2a2005"

_TACTIC_HEAD_STYLE = ParagraphStyle("tc_head", fontName=CARD_TITLE_FONT, fontSize=13, leading=15, textColor=colors.white)
_TACTIC_SPECIAL_STYLE = ParagraphStyle("tc_special", fontName="Helvetica", fontSize=7.8, leading=10, textColor=_STEEL)
_TACTIC_NAME_STYLE = ParagraphStyle("tc_name", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=_INK)
_TACTIC_COND_STYLE = ParagraphStyle("tc_cond", fontName="Helvetica", fontSize=7.8, leading=10, textColor=_STEEL)
_TACTIC_POINTS_STYLE = ParagraphStyle("tc_points", fontName="Helvetica-Bold", fontSize=13, leading=15, textColor=colors.HexColor(_POINTS_INK), alignment=1)
_TACTIC_POINTS_LABEL_STYLE = ParagraphStyle("tc_points_lbl", fontName="Helvetica-Bold", fontSize=5.4, leading=6.4, textColor=colors.HexColor(_POINTS_INK), alignment=1)


def _points_badge(points: int, width: float) -> Table:
    """Pastille « points de victoire » dédiée, plus grande que `_pill` — la
    valeur numérique doit rester lisible même isolée dans sa propre colonne,
    c'est le seul badge de la carte que le lecteur doit pouvoir repérer sans
    lire le texte qui l'entoure."""
    inner = Table(
        [[Paragraph(str(points), _TACTIC_POINTS_STYLE)], [Paragraph(tr("PTS DE<br/>VICTOIRE"), _TACTIC_POINTS_LABEL_STYLE)]],
        colWidths=[width],
    )
    inner.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    box = Table([[inner]], colWidths=[width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_POINTS_GOLD)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return box


def _sub_tactic_block(sub: SubTactic, width: float) -> Table:
    """Un encadré par sous-tactique (Échauffourée/Frappe/Domination) : nom +
    pastille de type à gauche, pastille de points de victoire à droite —
    même schéma « contenu + badge dans sa propre colonne » que les cartes
    d'unité/de règle, décliné à l'échelle de la carte entière plutôt que
    d'une seule aptitude."""
    kind_bg, kind_fg = _TACTIC_KIND_COLORS.get(sub.kind, (_BADGE_NEUTRAL, "#eaf1f8"))
    points_col = 22 * mm
    left_width = width - points_col
    # `block` (plus bas) peint 7+6pt de marge autour de sa colonne de gauche
    # — `left`, construite ici avec une largeur fixe, doit s'y caler *après*
    # déduction de cette marge, sans quoi son contenu (notamment la ligne
    # nom+condition) déborde dans la colonne de la pastille de points voisine
    # (même bug que `_ability_group_body` avait déjà rencontré, cf. son
    # commentaire — même cause, même correctif).
    left_content_width = left_width - 13
    kind_col = 26 * mm
    name_col = left_content_width - kind_col

    header = Table(
        [[_pill(tr(sub.kind.upper()), kind_bg, kind_fg), _safe_paragraph(f"<b>{sub.name}</b>", _TACTIC_NAME_STYLE)]],
        colWidths=[kind_col, name_col],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # pas de ligne d'ambiance (`sub.flavor`, gardé dans le JSON) : les
    # cartes ne portent que les règles (demande explicite de l'utilisateur).
    left = Table(
        [[header], [_safe_paragraph(sub.condition, _TACTIC_COND_STYLE)]],
        colWidths=[left_content_width],
    )
    left.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (0, 1), 1), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
    ]))

    block = Table([[left, _points_badge(sub.points, points_col - 4 * mm)]], colWidths=[left_width, points_col])
    block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.7, _STEEL_LINE),
        ("LEFTPADDING", (0, 0), (0, -1), 7), ("RIGHTPADDING", (0, 0), (0, -1), 6),
        ("LEFTPADDING", (1, 0), (1, -1), 2), ("RIGHTPADDING", (1, 0), (1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return block


def render_tactic_card(card: TacticCard, width: float = 188 * mm) -> Flowable:
    """Carte de tactique de bataille — remplace la copie de page PDF
    (`Manuel du général/MdG26-27 Tactiques.pdf`) par un rendu « maison »
    verbatim (texte français transcrit à la main, `tactic_cards.py`). Plus
    large que les cartes d'unité/de règle (`width` par défaut = la largeur
    utile d'une page A4 portrait) : elle n'est jamais mise en paire, cf.
    `assembly._build_tactic_cards_pdf` qui les empile simplement, assez
    compactes pour que les 2 tactiques citées par une liste tiennent
    normalement sur une seule page."""
    rows: list[list] = []
    styles: list[tuple] = []

    header_cell = [
        Paragraph(card.title_fr, _TACTIC_HEAD_STYLE),
        Paragraph(f"CARTE DE TACTIQUE {card.number} · {card.name_en}", _ROLE_STYLE),
    ] if not card.english else [
        Paragraph(card.name_en, _TACTIC_HEAD_STYLE),
        Paragraph(f"BATTLE TACTIC CARD {card.number}", _ROLE_STYLE),
    ]
    rows.append([header_cell])
    styles += [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161a2b")),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LEFTPADDING", (0, 0), (-1, 0), 8),
    ]

    # pas de ligne d'ambiance (`card.flavor`, gardé dans le JSON) — cf.
    # `_sub_tactic_block`.

    if card.special_rule:
        special_box = Table(
            [[_pill(tr("RÈGLE SPÉCIALE"), _BADGE_NEUTRAL, "#eaf1f8")], [_safe_paragraph(card.special_rule, _TACTIC_SPECIAL_STYLE)]],
            colWidths=[width - 16],
        )
        special_box.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 3),
            ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
        ]))
        rows.append([special_box])
        r = len(rows) - 1
        styles += [
            ("LEFTPADDING", (0, r), (-1, r), 8), ("RIGHTPADDING", (0, r), (-1, r), 8),
            ("TOPPADDING", (0, r), (-1, r), 5), ("BOTTOMPADDING", (0, r), (-1, r), 5),
            ("LINEBELOW", (0, r), (-1, r), 0.5, _STEEL_LINE),
        ]

    for sub in card.sub_tactics:
        rows.append([_sub_tactic_block(sub, width - 16)])
        r = len(rows) - 1
        styles += [
            ("LEFTPADDING", (0, r), (-1, r), 8), ("RIGHTPADDING", (0, r), (-1, r), 8),
            ("TOPPADDING", (0, r), (-1, r), 4), ("BOTTOMPADDING", (0, r), (-1, r), 4),
        ]

    card_table = Table(rows, colWidths=[width])
    card_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *styles,
    ]))
    return card_table

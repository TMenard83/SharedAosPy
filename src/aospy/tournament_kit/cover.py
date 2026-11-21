"""Couverture du roster : liste mise en forme, non-trouvés, légendes des pictos et des pastilles."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..pdf_theme import GOLD, NIGHT_BLUE, STEEL, today_str
from .assembly import (
    _META,
    _REGIMENT,
    _SHEET_PADDING,
    _TITLE,
    _WARNING,
    _draw_page_bg,
    _FitToFrame,
    _wrap_in_sheet,
)
from .list_parser import ParsedList
from .render.pills import cast_badge_legend, pill_legend
from .render.text import tr

#: Ordre d'apparition des cartes de profil dans le PDF (après les Héros,
#: toute base confondue, toujours en tête) — demande explicite de
#: l'utilisateur. Wahapedia combine base + rôle dans un seul champ `role`
#: (ex. `"Cavalry Hero"`, `"War Machine"`), d'où le test par sous-chaîne
#: plutôt qu'une correspondance exacte dans `_role_rank`.
_ROLE_ORDER = ("infantry", "cavalry", "beast", "monster", "war machine")


def _role_rank(role: str) -> int:
    """Rang de tri d'une carte de profil : Héros (0, toute base confondue)
    d'abord, puis `_ROLE_ORDER` dans l'ordre. Un rôle qui ne matche ni "hero"
    ni aucune entrée de `_ROLE_ORDER` (Faction Terrain, manifestation
    invocable...) reste en dernier plutôt que de forcer un classement
    arbitraire — `list.sort` étant stable, l'ordre relatif au sein d'un même
    rang reste celui de la liste (régiment du général, puis régiment 1, 2...)."""
    role_l = (role or "").lower()
    if "hero" in role_l:
        return 0
    for i, key in enumerate(_ROLE_ORDER, start=1):
        if key in role_l:
            return i
    return len(_ROLE_ORDER) + 1


def _unit_row(name: str, points: int, options: list[str]) -> str:
    text = f"<b>{name}</b> — {points} pts"
    if options:
        text += "<br/><font size=8 color='#4a4536'>" + ", ".join(options) + "</font>"
    return text


def _build_cover_pdf(
    parsed: ParsedList,
    units_unmatched: list[str],
    rules_unmatched: list[str],
    wahapedia_used: list[str],
    badge_shapes: frozenset[str] = frozenset(),
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=15 * mm,
        title=parsed.title,
    )
    #: largeur dispo pour le contenu une fois la case blanche (`_wrap_in_sheet`)
    #: posée autour, sa propre marge intérieure (`_SHEET_PADDING`) déduite des
    #: deux côtés — les tables imbriquées (lignes d'unité) doivent s'y caler,
    #: pas à `doc.width` (largeur du cadre de page, plus large que la case).
    content_width = doc.width - 2 * _SHEET_PADDING
    story = [Paragraph(parsed.title, _TITLE)]

    meta_lines = [parsed.faction]
    if parsed.allegiance:
        meta_lines.append(parsed.allegiance)
    if parsed.drops is not None:
        meta_lines.append(tr(f"Drops : {parsed.drops}"))
    if parsed.spell_lore:
        meta_lines.append(tr(f"Domaine de sorts : {parsed.spell_lore}"))
    if parsed.prayer_lore:
        meta_lines.append(tr(f"Domaine de prières : {parsed.prayer_lore}"))
    if parsed.manifestation_lore:
        meta_lines.append(tr(f"Domaine de manifestations : {parsed.manifestation_lore}"))
    story.append(Paragraph(" · ".join(meta_lines), _META))

    if parsed.battle_tactic_cards:
        story.append(Paragraph(f"<b>{tr('Battle Tactic Cards :')}</b> " + ", ".join(parsed.battle_tactic_cards), _META))

    style = ParagraphStyle("kit_cell", fontName="Times-Roman", fontSize=9.5, leading=13, textColor=NIGHT_BLUE)
    for regiment in parsed.regiments:
        story.append(Paragraph(regiment.title, _REGIMENT))
        rows = [[Paragraph(_unit_row(u.name, u.points, u.options), style)] for u in regiment.units]
        if rows:
            table = Table(rows, colWidths=[content_width])
            table.setStyle(
                TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.6, GOLD),
                        ("INNERGRID", (0, 0), (-1, -1), 0.4, GOLD),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(table)

    if parsed.regiments_of_renown:
        story.append(Paragraph("Regiments of Renown", _REGIMENT))
        rows = [[Paragraph(_unit_row(ror.name, ror.points, ror.units), style)] for ror in parsed.regiments_of_renown]
        table = Table(rows, colWidths=[content_width])
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, GOLD),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, GOLD),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)

    if parsed.faction_terrain:
        story.append(Paragraph("Faction Terrain", _REGIMENT))
        story.append(Paragraph(", ".join(parsed.faction_terrain), style))

    if units_unmatched:
        story.append(
            Paragraph(
                tr("⚠ Profil non trouvé (ni battletome, ni Wahapedia) pour : ") + ", ".join(units_unmatched),
                _WARNING,
            )
        )
    if rules_unmatched:
        story.append(
            Paragraph(
                tr("⚠ Règle non trouvée (ni battletome, ni Wahapedia) pour : ")
                + ", ".join(tr(r) for r in rules_unmatched),
                _WARNING,
            )
        )
    if wahapedia_used:
        story.append(
            Paragraph(
                tr("ℹ Complété en anglais via Wahapedia (voir annexe en fin de document) : ")
                + ", ".join(tr(w) for w in wahapedia_used),
                ParagraphStyle(
                    "kit_info", fontName="Times-Italic", fontSize=8.5, leading=12, textColor=STEEL, spaceBefore=8
                ),
            )
        )

    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            tr("Généré le ") + f"{today_str()} — aospy roster pdf",
            ParagraphStyle("kit_footer", fontName="Times-Italic", fontSize=8, textColor=STEEL),
        )
    )

    # légende des pictos (cercle sort, losange prière...) dessinés dans le
    # reste du PDF — demande de l'utilisateur, dans sa propre case sous celle
    # de la liste plutôt que mêlée à celle-ci
    sheets = [_wrap_in_sheet(story, doc.width)]
    legend = cast_badge_legend(badge_shapes)
    pills = pill_legend()
    if legend or pills:
        legend_style = ParagraphStyle(
            "kit_legend", fontName="Times-Roman", fontSize=9, leading=12, textColor=NIGHT_BLUE
        )
        legend_title = ParagraphStyle("kit_legend_title", parent=_REGIMENT, spaceBefore=0)
        legend_story: list = [Paragraph(tr("Légende des pictos"), legend_title)]
        if legend:
            table = Table(
                [[badge, Paragraph(text, legend_style)] for badge, text in legend],
                colWidths=[22, content_width - 22],
            )
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("ALIGN", (0, 0), (0, -1), "CENTER"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 1),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ]
                )
            )
            legend_story.append(table)
        if pills:
            # pastilles d'exemple à gauche (largeur de la plus large rangée),
            # explication à droite — mêmes familles/couleurs que les cartes
            pill_col = max(width for _row, width, _text in pills) + 6
            pill_text_style = ParagraphStyle("kit_legend_pill", parent=legend_style, fontSize=8.5, leading=10)
            legend_story.append(Spacer(1, 4))
            # une `Table` par ligne : chacune devient une ligne de la case
            # (`_wrap_in_sheet`), qui peut alors se couper entre deux pages
            for row, _width, text in pills:
                line = Table([[row, Paragraph(text, pill_text_style)]], colWidths=[pill_col, content_width - pill_col])
                line.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ALIGN", (0, 0), (0, -1), "LEFT"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 2),
                            ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                        ]
                    )
                )
                legend_story.append(line)
        sheets += [Spacer(1, 10), _wrap_in_sheet(legend_story, doc.width)]

    # liste + légende toujours ensemble en page 1 (demande de l'utilisateur) :
    # réduites uniformément juste assez pour tenir quand la liste est longue
    doc.build([_FitToFrame(sheets)], onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()

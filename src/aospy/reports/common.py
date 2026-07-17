"""Charte graphique partagée par les registres PDF « TM » (mise en page inspirée
d'Age of Sigmar). Factorise ce qui était dupliqué à l'identique entre les
modules cost_*/best_*/combat_* : palette, styles de paragraphe, décors de page,
badge d'alliance et gabarit de tableau classé/médaillé."""
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Flowable, Paragraph,
)

OLD_ENGLISH_FONT = "Times-Bold"

PAGE_W, PAGE_H = landscape(A4)

INK_BLACK    = colors.HexColor("#0b0d13")
NIGHT_BLUE   = colors.HexColor("#161a2b")
GOLD         = colors.HexColor("#b8912f")
GOLD_BRIGHT  = colors.HexColor("#f0cf6b")
GOLD_DIM     = colors.HexColor("#8a6d24")
PARCHMENT    = colors.HexColor("#f3ead6")
PARCHMENT_2  = colors.HexColor("#e9dcc0")
STEEL        = colors.HexColor("#4a4536")
BLOOD_GREEN  = colors.HexColor("#2f6b32")
BLOOD_RED    = colors.HexColor("#8c1f1f")

ALLIANCE_BG = {
    "Order":       colors.HexColor("#1c3f6e"),
    "Chaos":       colors.HexColor("#5e1414"),
    "Death":       colors.HexColor("#33184a"),
    "Destruction": colors.HexColor("#33421a"),
}
ALLIANCE_FG = {
    "Order":       colors.HexColor("#cfe3ff"),
    "Chaos":       colors.HexColor("#ffd7d7"),
    "Death":       colors.HexColor("#e6d2ff"),
    "Destruction": colors.HexColor("#ddeec2"),
}
ALLIANCE_ABBR = {
    "Order": "ORDRE", "Chaos": "CHAOS", "Death": "MORT", "Destruction": "DESTR.",
}

MARGIN = 10 * mm
TOP_MARGIN = 23 * mm
BOTTOM_MARGIN = 15 * mm

RANK_MEDALS = {1: colors.HexColor("#f0cf6b"), 2: colors.HexColor("#d8d8d8"), 3: colors.HexColor("#d1a05a")}

# ----------------------------------------------------------------------------
# Styles de paragraphe
# ----------------------------------------------------------------------------
cover_title = ParagraphStyle(
    "cover_title", fontName=OLD_ENGLISH_FONT, fontSize=40, leading=46,
    textColor=GOLD_BRIGHT, alignment=TA_CENTER, spaceAfter=4,
)
cover_subtitle = ParagraphStyle(
    "cover_subtitle", fontName="Times-Italic", fontSize=15, leading=20,
    textColor=PARCHMENT, alignment=TA_CENTER, spaceBefore=6,
)
cover_meta = ParagraphStyle(
    "cover_meta", fontName="Times-Roman", fontSize=10.5, leading=15,
    textColor=GOLD, alignment=TA_CENTER, spaceBefore=18,
)
cover_body = ParagraphStyle(
    "cover_body", fontName="Times-Roman", fontSize=10.5, leading=15,
    textColor=PARCHMENT_2, alignment=TA_LEFT, spaceBefore=8,
)
section_title = ParagraphStyle(
    "section_title", fontName=OLD_ENGLISH_FONT, fontSize=24, leading=28,
    textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceAfter=2,
)
section_note = ParagraphStyle(
    "section_note", fontName="Times-Italic", fontSize=9.5, leading=13,
    textColor=STEEL, spaceAfter=8,
)
subhead = ParagraphStyle(
    "subhead", fontName="Times-Bold", fontSize=11, leading=14,
    textColor=NIGHT_BLUE, spaceBefore=6, spaceAfter=4,
)
#: Corps de texte pour les pages "Data" (fond parchemin clair) — contrairement à
#: `cover_body` (texte clair, prévu pour le fond nuit de la couverture), qui
#: deviendrait illisible sur ce fond.
body_text = ParagraphStyle(
    "body_text", fontName="Times-Roman", fontSize=9.5, leading=13.5,
    textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceBefore=4, spaceAfter=6,
)


def alliance_badge(alliance: str) -> str:
    return ALLIANCE_ABBR.get(alliance, alliance[:4].upper())


class SectionMarker(Flowable):
    """Flowable invisible qui met à jour le titre de section utilisé par l'en-tête courant."""
    def __init__(self, doc, title):
        super().__init__()
        self.doc = doc
        self.title = title

    def wrap(self, aw, ah):
        return (0, 0)

    def draw(self):
        self.doc.section_title = self.title


# ----------------------------------------------------------------------------
# Décors de page
# ----------------------------------------------------------------------------

def _corner_ornaments(c, m):
    c.setFillColor(GOLD)
    for x, y in [(m, m), (PAGE_W - m, m), (m, PAGE_H - m), (PAGE_W - m, PAGE_H - m)]:
        c.circle(x, y, 1.6 * mm, fill=1, stroke=0)


def draw_cover_bg(c, doc):
    c.saveState()
    c.setFillColor(INK_BLACK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    m = 9 * mm
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.6)
    c.rect(m, m, PAGE_W - 2 * m, PAGE_H - 2 * m, fill=0, stroke=1)
    c.setStrokeColor(GOLD_DIM)
    c.setLineWidth(0.6)
    c.rect(m + 3 * mm, m + 3 * mm, PAGE_W - 2 * m - 6 * mm, PAGE_H - 2 * m - 6 * mm, fill=0, stroke=1)
    _corner_ornaments(c, m)
    c.setFillColor(STEEL)
    c.setFont("Times-Italic", 8)
    c.drawCentredString(PAGE_W / 2, m + 2 * mm, f"— {doc.page} —")
    c.restoreState()


def make_draw_data_bg(band_text: str):
    """`band_text` : libellé fixe affiché à gauche du bandeau supérieur (le titre
    de section courant, mis à jour par SectionMarker, s'affiche à droite)."""

    def draw_data_bg(c, doc):
        c.saveState()
        c.setFillColor(PARCHMENT)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        m = 6 * mm
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.3)
        c.rect(m, m, PAGE_W - 2 * m, PAGE_H - 2 * m, fill=0, stroke=1)
        c.setStrokeColor(GOLD_DIM)
        c.setLineWidth(0.5)
        c.rect(m + 2 * mm, m + 2 * mm, PAGE_W - 2 * m - 4 * mm, PAGE_H - 2 * m - 4 * mm, fill=0, stroke=1)
        _corner_ornaments(c, m)

        band_h = 10 * mm
        c.setFillColor(NIGHT_BLUE)
        c.rect(m, PAGE_H - m - band_h, PAGE_W - 2 * m, band_h, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.setLineWidth(0.6)
        c.line(m, PAGE_H - m - band_h, PAGE_W - m, PAGE_H - m - band_h)
        c.setFont("Times-Bold", 10.5)
        c.setFillColor(GOLD_BRIGHT)
        c.drawString(m + 5 * mm, PAGE_H - m - band_h + 3.2 * mm, band_text)
        c.setFont("Times-Italic", 9)
        c.setFillColor(GOLD)
        c.drawRightString(PAGE_W - m - 5 * mm, PAGE_H - m - band_h + 3.2 * mm, getattr(doc, "section_title", ""))

        c.setFillColor(STEEL)
        c.setFont("Times-Italic", 8)
        c.drawCentredString(PAGE_W / 2, m + 2 * mm, f"— Folio {doc.page} —")
        c.restoreState()

    return draw_data_bg


def build_document(out_path: str, title: str, band_text: str, author: str = "TM") -> BaseDocTemplate:
    """Crée le BaseDocTemplate avec les deux gabarits de page (Cover / Data)
    communs aux registres. `band_text` est le libellé fixe du bandeau (ex.
    « AGE OF SIGMAR · ... · ÉD. TM »)."""
    doc = BaseDocTemplate(out_path, pagesize=landscape(A4), title=title, author=author)
    doc.section_title = ""
    cover_frame = Frame(24 * mm, 24 * mm, PAGE_W - 48 * mm, PAGE_H - 48 * mm, id="cover")
    data_frame = Frame(MARGIN, BOTTOM_MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - TOP_MARGIN - BOTTOM_MARGIN, id="data")
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=draw_cover_bg),
        PageTemplate(id="Data", frames=[data_frame], onPage=make_draw_data_bg(band_text)),
    ])
    return doc


def today_str() -> str:
    return datetime.now().strftime("%d/%m/%Y à %Hh%M")


# ----------------------------------------------------------------------------
# Tableau classé (rang / ... / alliance colorée / éventuelles colonnes colorées)
# ----------------------------------------------------------------------------

def ranked_table(header, col_widths, rows, fmt_row, alliance_of, colored_cols=(), font_size=7.6, start_rank=1, ranks=None):
    """`fmt_row(rank, row) -> list[str]` formate une ligne de données.
    `alliance_of(row) -> str` donne l'alliance (pour le badge coloré, colonne 3).
    `colored_cols` : liste de `(col_idx, color_fn(row) -> Color)` pour les
    colonnes dont le texte doit être coloré/mis en gras selon la valeur (ex.
    ROI, résidu, score).
    `ranks` : rang explicite par ligne (ex. rang d'un registre global dont `rows`
    n'est qu'un extrait filtré) — prime sur `start_rank + i` si fourni, pour le
    numéro affiché (fmt_row) comme pour le médaillage top 1/2/3.
    """
    if ranks is None:
        ranks = [start_rank + i for i in range(len(rows))]
    data = [header] + [fmt_row(rank, r) for rank, r in zip(ranks, rows)]
    #: Colonne 1 (nom) : seule colonne à largeur de texte non bornée (noms de
    #: profil libres, parfois longs — ex. "Hearthguard Berzerkers with
    #: Flamestrike Poleaxes") — enveloppée dans un `Paragraph` pour un retour à
    #: la ligne automatique dans sa largeur de colonne, plutôt que de déborder
    #: sur la colonne "Armée" voisine comme le ferait une chaîne brute.
    name_style = ParagraphStyle(
        "table_name", fontName="Times-Roman", fontSize=font_size, leading=font_size * 1.15,
        textColor=colors.black, alignment=TA_LEFT,
    )
    for row in data[1:]:
        row[1] = Paragraph(row[1], name_style)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NIGHT_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), GOLD_BRIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PARCHMENT, PARCHMENT_2]),
        ("GRID", (0, 0), (-1, -1), 0.35, GOLD_DIM),
        ("BOX", (0, 0), (-1, -1), 0.9, GOLD),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, r in enumerate(rows):
        row_idx = i + 1
        alliance = alliance_of(r)
        style.append(("BACKGROUND", (3, row_idx), (3, row_idx), ALLIANCE_BG[alliance]))
        style.append(("TEXTCOLOR", (3, row_idx), (3, row_idx), ALLIANCE_FG[alliance]))
        style.append(("FONTNAME", (3, row_idx), (3, row_idx), "Times-Bold"))
        for col_idx, color_fn in colored_cols:
            style.append(("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), color_fn(r)))
            style.append(("FONTNAME", (col_idx, row_idx), (col_idx, row_idx), "Times-Bold"))
        rank = ranks[i]
        if rank in RANK_MEDALS:
            style.append(("BACKGROUND", (0, row_idx), (0, row_idx), RANK_MEDALS[rank]))
            style.append(("FONTNAME", (0, row_idx), (0, row_idx), "Times-Bold"))
    t.setStyle(TableStyle(style))
    return t

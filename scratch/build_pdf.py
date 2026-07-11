"""Génère la synthèse PDF (mise en page inspirée d'Age of Sigmar) des résultats de combat
par unité — liste complète, pas de Top N."""
import json
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    NextPageTemplate, PageBreak, Flowable, KeepTogether,
)

# ----------------------------------------------------------------------------
# Polices
# ----------------------------------------------------------------------------
pdfmetrics.registerFont(TTFont("OldEnglish", "C:/Windows/Fonts/OLDENGL.TTF"))

PAGE_W, PAGE_H = landscape(A4)

# ----------------------------------------------------------------------------
# Palette "grimdark tome"
# ----------------------------------------------------------------------------
INK_BLACK    = colors.HexColor("#0b0d13")
NIGHT_BLUE   = colors.HexColor("#161a2b")
GOLD         = colors.HexColor("#b8912f")
GOLD_BRIGHT  = colors.HexColor("#f0cf6b")
GOLD_DIM     = colors.HexColor("#8a6d24")
PARCHMENT    = colors.HexColor("#f3ead6")
PARCHMENT_2  = colors.HexColor("#e9dcc0")
PARCHMENT_3  = colors.HexColor("#ded0ac")
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

TOP_N = 25
BOTTOM_N = 10

# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
with open("scratch/per_unit_charged.json", "r", encoding="utf-8") as f:
    charged = json.load(f)
with open("scratch/per_unit_nocharge.json", "r", encoding="utf-8") as f:
    nocharge = json.load(f)

# ----------------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------------
styles = getSampleStyleSheet()

cover_title = ParagraphStyle(
    "cover_title", fontName="OldEnglish", fontSize=42, leading=48,
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
    "section_title", fontName="OldEnglish", fontSize=24, leading=28,
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

HEADER = ["#", "Unité", "Armée", "All.", "Pts", "Héros",
          "ROI moy.", "Pts net moy.", "Médiane ROI", "% positif", "ROI min", "ROI max"]
COL_WIDTHS = [10*mm, 55*mm, 42*mm, 15*mm, 12*mm, 12*mm,
              20*mm, 24*mm, 20*mm, 18*mm, 18*mm, 18*mm]


def alliance_badge(alliance: str) -> str:
    return ALLIANCE_ABBR.get(alliance, alliance[:4].upper())


def fmt_row(rank, r):
    return [
        str(rank),
        r["name"],
        r["army"],
        alliance_badge(r["grand_alliance"]),
        str(r["points"]),
        "Oui" if r["is_hero"] else "",
        f"{r['avg_roi_pct']:+.1f}%",
        f"{r['avg_pts_net']:+.1f}",
        f"{r['median_roi_pct']:+.1f}%",
        f"{r['pct_positive']:.0f}%",
        f"{r['min_roi_pct']:+.1f}%",
        f"{r['max_roi_pct']:+.1f}%",
    ]


RANK_MEDALS = {1: colors.HexColor("#f0cf6b"), 2: colors.HexColor("#d8d8d8"), 3: colors.HexColor("#d1a05a")}


def make_table(rows, start_rank=1):
    data = [HEADER] + [fmt_row(start_rank + i, r) for i, r in enumerate(rows)]
    t = Table(data, colWidths=COL_WIDTHS, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NIGHT_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), GOLD_BRIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
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
        style.append(("BACKGROUND", (3, row_idx), (3, row_idx), ALLIANCE_BG[r["grand_alliance"]]))
        style.append(("TEXTCOLOR", (3, row_idx), (3, row_idx), ALLIANCE_FG[r["grand_alliance"]]))
        style.append(("FONTNAME", (3, row_idx), (3, row_idx), "Times-Bold"))
        roi_color = BLOOD_GREEN if r["avg_roi_pct"] >= 0 else BLOOD_RED
        style.append(("TEXTCOLOR", (6, row_idx), (6, row_idx), roi_color))
        style.append(("FONTNAME", (6, row_idx), (6, row_idx), "Times-Bold"))
        rank = start_rank + i
        if rank in RANK_MEDALS:
            style.append(("BACKGROUND", (0, row_idx), (0, row_idx), RANK_MEDALS[rank]))
            style.append(("FONTNAME", (0, row_idx), (0, row_idx), "Times-Bold"))
    t.setStyle(TableStyle(style))
    return t


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


def scenario_flowables(doc, title, rows, note):
    story = [Paragraph(title, section_title)]
    story.append(Paragraph(note, section_note))
    story.append(Paragraph(
        f"{len(rows)} unités classées par ROI moyen décroissant — liste complète (aucune coupe).",
        subhead,
    ))
    story.append(Spacer(1, 2))
    story.append(make_table(rows, start_rank=1))
    return story


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
    c.drawString(m + 5 * mm, PAGE_H - m - band_h + 3.2 * mm, "AGE OF SIGMAR  ·  SYNTHÈSE DES COMBATS PAR UNITÉ")
    c.setFont("Times-Italic", 9)
    c.setFillColor(GOLD)
    c.drawRightString(PAGE_W - m - 5 * mm, PAGE_H - m - band_h + 3.2 * mm, getattr(doc, "section_title", ""))

    c.setFillColor(STEEL)
    c.setFont("Times-Italic", 8)
    c.drawCentredString(PAGE_W / 2, m + 2 * mm, f"— Folio {doc.page} —")
    c.restoreState()


# ----------------------------------------------------------------------------
# Document
# ----------------------------------------------------------------------------
doc = BaseDocTemplate(
    "scratch/AoS_synthese_combats_par_unite.pdf",
    pagesize=landscape(A4),
    title="Age of Sigmar — Synthèse des combats par unité",
    author="AoSPy",
)
doc.section_title = ""

cover_frame = Frame(24*mm, 24*mm, PAGE_W - 48*mm, PAGE_H - 48*mm, id="cover")
data_frame = Frame(MARGIN, BOTTOM_MARGIN, PAGE_W - 2*MARGIN, PAGE_H - TOP_MARGIN - BOTTOM_MARGIN, id="data")

doc.addPageTemplates([
    PageTemplate(id="Cover", frames=[cover_frame], onPage=draw_cover_bg),
    PageTemplate(id="Data", frames=[data_frame], onPage=draw_data_bg),
])

story = []

SCENARIO_1_TITLE = "Scénario I — L'Assaut (attaquant chargé)"
SCENARIO_2_TITLE = "Scénario II — La Mêlée (sans charge)"

# --- Page de garde ---
story.append(Spacer(1, 26*mm))
story.append(Paragraph("Compendium des Duels", cover_title))
story.append(Paragraph("Synthèse des combats par unité — 27 armées, 896 unités", cover_subtitle))
story.append(Spacer(1, 8*mm))
story.append(Paragraph(f"Registre établi le {date.today().strftime('%d/%m/%Y')}", cover_meta))
story.append(Spacer(1, 10*mm))
story.append(Paragraph(
    "<b>Méthode :</b> chaque unité attaquante (héros inclus) a été confrontée en duel d'un round "
    "à toutes les unités des autres armées — dégât espéré, sans renforcement, contre l'ensemble du méta "
    "(896 unités). Pour chaque unité sont calculés : le ROI moyen (retour sur investissement en points), "
    "les points nets moyens, la médiane du ROI, le pourcentage de duels rentables, ainsi que le ROI minimum "
    "et maximum observés.<br/><br/>"
    "<b>Pts net</b> = valeur en points détruite chez l'adversaire − valeur en points perdue par l'attaquant "
    "(pondérée par les points de vie). <b>ROI</b> = pts net / coût en points de l'unité attaquante.<br/><br/>"
    "Deux scénarios sont détaillés dans ce registre : l'unité attaquante charge (+1 attaque en mêlée), "
    "ou aucune charge n'est portée. Les classements ci-après recensent <b>l'intégralité des 896 unités</b>, "
    "sans troncature.",
    cover_body,
))
story.append(NextPageTemplate("Data"))
story.append(SectionMarker(doc, SCENARIO_1_TITLE))
story.append(PageBreak())

story += scenario_flowables(
    doc, SCENARIO_1_TITLE, charged,
    "L'unité attaquante bénéficie du bonus de charge (+1 attaque en mêlée) ; le défenseur ne charge pas.",
)
story.append(SectionMarker(doc, SCENARIO_2_TITLE))
story.append(PageBreak())
story += scenario_flowables(
    doc, SCENARIO_2_TITLE, nocharge,
    "Aucun des deux camps ne bénéficie du bonus de charge (combat prolongé ou unité déjà engagée).",
)

doc.build(story)
print("PDF genere: scratch/AoS_synthese_combats_par_unite.pdf")

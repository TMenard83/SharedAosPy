"""Conversion de fichiers Markdown (sorties `aospy l3`, fiches) en un PDF (reportlab, extra `[roster]`).

Gère : titres #..####, paragraphes, listes à puces / numérotées (indentées), tableaux, blocs ```,
séparateurs ---, **gras**, *italique*, `code`, liens [texte](url) réduits à leur texte.
Plusieurs entrées = un PDF, saut de page entre fichiers, signets par titre.
Polices Noto Sans si présentes (repli Helvetica / Courier).
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_DIRS = [Path("/run/host/fonts/truetype/noto"), Path("/usr/share/fonts/truetype/noto")]


def _register_fonts() -> tuple[str, str]:
    d = next((p for p in FONT_DIRS if (p / "NotoSans-Regular.ttf").exists()), None)
    if d is None:
        return "Helvetica", "Courier"
    for name, f in [("NS", "Regular"), ("NS-B", "Bold"), ("NS-I", "Italic"), ("NS-BI", "BoldItalic")]:
        pdfmetrics.registerFont(TTFont(name, str(d / f"NotoSans-{f}.ttf")))
    pdfmetrics.registerFontFamily("NS", normal="NS", bold="NS-B", italic="NS-I", boldItalic="NS-BI")
    mono = "Courier"
    if (d / "NotoSansMono-Regular.ttf").exists():
        pdfmetrics.registerFont(TTFont("NSM", str(d / "NotoSansMono-Regular.ttf")))
        mono = "NSM"
    elif (d / "NotoMono-Regular.ttf").exists():
        pdfmetrics.registerFont(TTFont("NSM", str(d / "NotoMono-Regular.ttf")))
        mono = "NSM"
    return "NS", mono


FONT, MONO = _register_fonts()
ACCENT = colors.HexColor("#3b4a6b")

BASE = ParagraphStyle("base", fontName=FONT, fontSize=9.5, leading=12.5, alignment=TA_LEFT, spaceAfter=4)
H = {
    1: ParagraphStyle("h1", parent=BASE, fontSize=16, leading=20, textColor=ACCENT, spaceBefore=4, spaceAfter=8),
    2: ParagraphStyle("h2", parent=BASE, fontSize=13, leading=16, textColor=ACCENT, spaceBefore=10, spaceAfter=5),
    3: ParagraphStyle("h3", parent=BASE, fontSize=11, leading=14, textColor=ACCENT, spaceBefore=8, spaceAfter=4),
    4: ParagraphStyle("h4", parent=BASE, fontSize=10, leading=13, spaceBefore=6, spaceAfter=3),
}
CODE = ParagraphStyle(
    "code", parent=BASE, fontName=MONO, fontSize=7.5, leading=9.5, backColor=colors.HexColor("#f2f2f2")
)


def inline(text: str) -> str:
    """Markdown en ligne → mini-HTML reportlab."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    codes: list[str] = []

    def keep_code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f'<font face="{MONO}">{codes[int(m.group(1))]}</font>', text)
    return text


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def make_table(rows: list[list[str]], avail: float) -> Table:
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    size = 8.5 if ncol <= 6 else 7.5 if ncol <= 9 else 6.6 if ncol <= 12 else 5.8
    st = ParagraphStyle("cell", parent=BASE, fontSize=size, leading=size * 1.22, spaceAfter=0)
    sth = ParagraphStyle("cellh", parent=st, fontName=f"{FONT}-B" if FONT == "NS" else "Helvetica-Bold",
                         textColor=colors.white)
    # largeurs : proportionnelles à la longueur de texte (bornées), ramenées à la largeur dispo
    plain = [[re.sub(r"\*\*|`|\[|\]\([^)]*\)", "", c) for c in r] for r in rows]
    need = []
    for j in range(ncol):
        longest = max(len(r[j]) for r in plain)
        words = max((len(w) for r in plain for w in r[j].split()), default=1)
        need.append(max(min(longest, 60), words, 3))
    total = sum(need)
    widths = [avail * n / total for n in need]
    data = [[Paragraph(inline(c), sth if i == 0 else st) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8bcc6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f5f9")))
    t.setStyle(TableStyle(style))
    return t


class Doc(SimpleDocTemplate):
    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and getattr(f, "_bm_level", None) is not None:
            key = f"bm{id(f)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f.getPlainText()[:90], key, level=f._bm_level)


def md_to_flowables(md: str, avail: float) -> list:
    out: list = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []
    bm_base = 0

    def flush():
        if para:
            out.append(Paragraph(inline(" ".join(para)), BASE))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                block.append(lines[j])
                j += 1
            out.append(Preformatted("\n".join(block), CODE))
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush()
            lvl = min(len(m.group(1)), 4)
            p = Paragraph(inline(m.group(2)), H[lvl])
            p._bm_level = bm_base + lvl - 1 if lvl <= 3 else None
            out.append(p)
            i += 1
            continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                c = _cells(lines[i])
                if not all(re.fullmatch(r":?-{2,}:?", x) for x in c if x):
                    rows.append(c)
                elif not any(c):
                    rows.append(c)
                i += 1
            if rows:
                out.append(make_table(rows, avail))
                out.append(Spacer(1, 5))
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush()
            out.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceBefore=4, spaceAfter=4))
            i += 1
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush()
            indent = len(m.group(1).replace("\t", "    ")) // 2
            bullet = "•" if m.group(2) in "-*+" else m.group(2)
            text = m.group(3)
            j = i + 1
            while j < len(lines) and lines[j].strip() and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[j]) \
                    and not lines[j].strip().startswith(("|", "#", "```")) and lines[j].startswith(" "):
                text += " " + lines[j].strip()
                j += 1
            st = ParagraphStyle("li", parent=BASE, leftIndent=12 + 12 * indent, bulletIndent=2 + 12 * indent,
                                spaceAfter=1.5)
            out.append(Paragraph(inline(text), st, bulletText=bullet))
            i = j
            continue
        if s.startswith(">"):
            flush()
            st = ParagraphStyle("q", parent=BASE, leftIndent=10, textColor=colors.HexColor("#444444"))
            out.append(Paragraph(inline(s.lstrip("> ")), st))
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        para.append(s)
        i += 1
    flush()
    return out


def build(out_pdf: Path, inputs: list[Path], paysage: bool = False, titre: str | None = None) -> Path:
    size = landscape(A4) if paysage else A4
    margin = 1.3 * cm
    doc = Doc(str(out_pdf), pagesize=size, leftMargin=margin, rightMargin=margin, topMargin=margin,
              bottomMargin=1.5 * cm, title=titre or out_pdf.stem)
    avail = size[0] - 2 * margin
    story: list = []
    for k, f in enumerate(inputs):
        if k:
            story.append(PageBreak())
        story.extend(md_to_flowables(f.read_text(encoding="utf-8"), avail))

    label = titre or out_pdf.stem

    def footer(canv, d):
        canv.saveState()
        canv.setFont(FONT, 7)
        canv.setFillColor(colors.grey)
        canv.drawString(margin, 0.8 * cm, label)
        canv.drawRightString(size[0] - margin, 0.8 * cm, f"{d.page}")
        canv.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out_pdf

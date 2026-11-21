"""Assemblage du PDF : fond de page, feuilles de cartes, PDF de chaque section (cartes de règles, de tactique, de warscroll, annexe Wahapedia), copie de pages (pypdf), pages de scénario, étiquettes et numéros de page."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..pdf_theme import GOLD_DIM, NIGHT_BLUE, STEEL
from .render.cards import build_warscroll_cards_flow
from .render.layout import _FULL_PAGE_HEIGHT
from .render.text import clean_html, tr
from .render.theme import CARD_TITLE_FONT, PAGE_BG
from .sources.wahapedia_lookup import (
    AbilityEntry,
    RegimentOfRenownData,
    WarscrollData,
)

#: Marge des pages « cartes » (règles/tactiques/warscrolls) — volontairement
#: plus fine que les 18mm de la couverture/annexe (texte suivi, a besoin de
#: respirer) : plus de surface utile pour les cartes elles-mêmes, l'objectif
#: qui a fait réduire cette marge de moitié (elle était à 11mm).
_CARD_PAGE_MARGIN = 5.5 * mm

#: Largeur utile d'une page A4 portrait avec `_CARD_PAGE_MARGIN` de chaque
#: côté — la marge n'a été réduite que pour dégager cette largeur-là aux
#: cartes elles-mêmes, donc toute carte qui reste seule sur sa ligne
#: (règles, tactique) doit s'y caler entièrement plutôt que de laisser un
#: vide à droite.
_CARD_PAGE_WIDTH = A4[0] - 2 * _CARD_PAGE_MARGIN

#: Largeur de la carte de règles fusionnée — occupe toute la largeur utile
#: (elle reste seule sur sa ligne, cf. `_build_rule_cards_pdf`) : sur 2
#: colonnes par bandeau de phase (`render/cards.render_rule_card`), une
#: carte à 130mm serrait ces colonnes bien plus qu'il n'était nécessaire —
#: la conserver à 130mm en avait fait un choix arbitraire) plutôt qu'un vrai
#: usage de la place disponible.
_RULE_CARD_WIDTH = _CARD_PAGE_WIDTH

#: Largeur des cartes de tactique de bataille — jamais mises en paire
#: (contrairement aux cartes de warscroll), juste empilées, assez compactes
#: pour que les 2 tactiques citées par une liste tiennent normalement sur
#: une seule page.
_TACTIC_CARD_WIDTH = _CARD_PAGE_WIDTH

#: Largeur d'une carte de profil d'unité — 2 par ligne (`pack_cards_two_columns`),
#: donc calée sur la moitié de la largeur utile moins l'écart entre les 2
#: (même `gap` que `render/cards.build_warscroll_cards_flow`) plutôt qu'une
#: valeur fixe (88mm) choisie sans lien avec cette largeur — céder toute la
#: place disponible aux cartes plutôt que de laisser un vide à droite.
_UNIT_CARD_GAP = 5 * mm
_UNIT_CARD_WIDTH = (_CARD_PAGE_WIDTH - _UNIT_CARD_GAP) / 2

#: police du titre de la liste — Cinzel Bold, la même police "tome" que les
#: titres de carte (`render/theme.CARD_TITLE_FONT`) plutôt que
#: `OLD_ENGLISH_FONT` (Times-Bold) utilisé avant : demande explicite de
#: l'utilisateur, pour une cohérence visuelle titre de liste / titre de carte.
_TITLE = ParagraphStyle("kit_title", fontName=CARD_TITLE_FONT, fontSize=20, leading=24, textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceAfter=2)
_META = ParagraphStyle("kit_meta", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=STEEL, alignment=TA_LEFT, spaceAfter=10)
_REGIMENT = ParagraphStyle("kit_regiment", fontName="Times-Bold", fontSize=12, leading=15, textColor=GOLD_DIM, alignment=TA_LEFT, spaceBefore=10, spaceAfter=3)
_WARNING = ParagraphStyle("kit_warning", fontName="Times-Bold", fontSize=9.5, leading=13, textColor=STEEL, alignment=TA_LEFT, spaceBefore=14)
_EN_BANNER = ParagraphStyle("kit_en_banner", fontName="Times-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#8c1f1f"), alignment=TA_LEFT, spaceAfter=2)
_EN_SUBBANNER = ParagraphStyle("kit_en_subbanner", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=STEEL, alignment=TA_LEFT, spaceAfter=12)
_EN_SECTION = ParagraphStyle("kit_en_section", fontName="Times-Bold", fontSize=13, leading=17, textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceBefore=12, spaceAfter=4)
_EN_SUBSECTION = ParagraphStyle("kit_en_subsection", fontName="Times-Bold", fontSize=10.5, leading=14, textColor=GOLD_DIM, alignment=TA_LEFT, spaceBefore=8, spaceAfter=3)
_EN_BODY = ParagraphStyle("kit_en_body", fontName="Times-Roman", fontSize=9, leading=12.5, textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceAfter=6)
_EN_LEGEND = ParagraphStyle("kit_en_legend", fontName="Times-Italic", fontSize=8.5, leading=12, textColor=STEEL, alignment=TA_LEFT, spaceAfter=4)


def _strip_all_tags(text: str) -> str:
    """Retire tout balisage — y compris une balise tronquée en plein milieu
    (donnée source corrompue, sans `>` de fermeture jusqu'à la fin du champ),
    en supprimant aussi tout `<`/`>` résiduel isolé pour rester un texte brut
    valide (sans quoi reportlab tenterait encore de le parser comme du XML)."""
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.replace("<", " ").replace(">", " ")
    return re.sub(r"\s+", " ", text).strip()


def _safe_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Comme `Paragraph(text, style)`, mais tolérant : `data/wahapedia/*.csv`
    est une donnée externe scrapée, parfois corrompue (ex. une balise HTML
    tronquée en plein milieu d'un champ) — plutôt que de faire planter toute
    la génération du PDF pour une seule entrée abîmée, on retombe sur le
    texte brut (tags retirés) pour cette entrée-là."""
    try:
        return Paragraph(text, style)
    except Exception:
        return Paragraph(_strip_all_tags(text), style)




#: texture pierre du fond de page — générée par
#: `scripts/generate_stone_texture.py` (procédurale plutôt que téléchargée :
#: même raisonnement que `Cinzel-Bold.ttf`/`warscroll_card.py`, pas de
#: licence à auditer). `ImageReader` construit une seule fois au niveau
#: module ; repli silencieux sur un aplat `PAGE_BG` (même teinte) si le
#: fichier venait à manquer (ex. install sans les données du paquet) — même
#: schéma que le repli police de `warscroll_card.py`.
_STONE_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "stone_texture.jpg"
try:
    _STONE_TEXTURE = ImageReader(str(_STONE_TEXTURE_PATH))
except Exception:
    _STONE_TEXTURE = None


def _draw_page_bg(c, doc) -> None:
    """Peint le fond de chaque page du kit (couverture, cartes, annexe) :
    texture pierre pâle sur toute la page (`_STONE_TEXTURE`). Rien d'autre
    ici — le fond blanc qui porte le texte est désormais une case ajustée au
    contenu (`_wrap_in_sheet` pour la couverture/l'annexe, la carte
    elle-même pour les pages de cartes), jamais un grand rectangle peint sur
    toute la hauteur de la page indépendamment de ce que le contenu occupe
    réellement : cette dernière approche laissait un vide énorme sous un
    contenu court (ex. une petite liste sur la couverture) — signalé par
    l'utilisateur."""
    c.saveState()
    page_w, page_h = doc.pagesize
    if _STONE_TEXTURE is not None:
        c.drawImage(_STONE_TEXTURE, 0, 0, width=page_w, height=page_h, preserveAspectRatio=False)
    else:
        c.setFillColor(PAGE_BG)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    c.restoreState()


#: marge intérieure (haut/bas/gauche/droite) de la case blanche que
#: `_wrap_in_sheet` bâtit autour du texte de couverture/d'annexe.
_SHEET_PADDING = 14


def _wrap_in_sheet(story: list, width: float) -> Table:
    """Enveloppe un `story` (liste de flowables déjà construits) dans une
    seule case à fond blanc/bordure dorée, ajustée exactement à la hauteur
    du contenu plutôt qu'un rectangle peint sur toute la page (cf.
    `_draw_page_bg`) : chaque élément de `story` devient sa propre ligne
    d'un `Table` à une colonne — un `Table` se scinde nativement entre pages
    quand son contenu dépasse une page (contrairement à un flowable unique
    imbriqué dans une seule cellule), donc reste valable même pour une
    longue annexe, pas seulement une couverture tenant sur une page."""
    rows = [[item] for item in story]
    n = len(rows)
    box = Table(rows, colWidths=[width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, GOLD_DIM),
        ("LEFTPADDING", (0, 0), (-1, -1), _SHEET_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), _SHEET_PADDING),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), _SHEET_PADDING),
        ("BOTTOMPADDING", (0, n - 1), (0, n - 1), _SHEET_PADDING),
    ]))
    return box


class _FitToFrame(Flowable):
    """Empile `flowables` et les réduit uniformément (jamais agrandis) pour
    tenir dans la hauteur disponible du cadre — la page de garde (liste +
    légende des pictos) tient ainsi toujours sur une seule page, centrée
    horizontalement."""

    def __init__(self, flowables: list):
        super().__init__()
        self._flowables = flowables
        self._sizes: list[tuple[float, float]] = []
        self._scale = 1.0

    def wrap(self, avail_width, avail_height):
        self._sizes = [f.wrap(avail_width, 1e6) for f in self._flowables]
        natural = sum(h for _w, h in self._sizes)
        self._scale = min(1.0, avail_height / natural) if natural else 1.0
        self._avail_width = avail_width
        self.width, self.height = avail_width, natural * self._scale
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        content_width = max((w for w, _h in self._sizes), default=0)
        canvas.translate((self._avail_width - content_width * self._scale) / 2, 0)
        canvas.scale(self._scale, self._scale)
        y = self.height / self._scale
        for flowable, (_w, h) in zip(self._flowables, self._sizes):
            y -= h
            flowable.drawOn(canvas, 0, y)
        canvas.restoreState()


#: Les pages copiées depuis les battletomes/Manuel du général sont des scans
#: aplatis (une seule image ~1865x2472 par page, cf. le traitement anti-copie
#: documenté dans tournament_kit/README.md) : `writer.add_page` les recopie telles quelles,
#: soit ~1 Mo/page rien qu'en JPEG déjà compressé — largement plus que
#: nécessaire pour une page de règles lue à l'écran ou imprimée en A4. On les
#: redimensionne/recompresse après coup (~150-250 Ko/page), ce qui a divisé
#: par 30-40 la taille des PDF de tournoi générés (plusieurs Mo -> quelques
#: centaines de Ko) sans perte de lisibilité perceptible.
_COPIED_PAGE_MAX_DIM = 1600
_COPIED_PAGE_JPEG_QUALITY = 65


def _compress_page_images(page) -> None:
    for img_file in page.images:
        pil_image = img_file.image
        scale = min(1.0, _COPIED_PAGE_MAX_DIM / max(pil_image.size))
        if scale >= 1.0:
            continue
        new_size = (round(pil_image.width * scale), round(pil_image.height * scale))
        resized = pil_image.convert("RGB").resize(new_size, Image.LANCZOS)
        img_file.replace(resized, quality=_COPIED_PAGE_JPEG_QUALITY)


#: Cartes de scénario du Manuel du Général 2026-27 (12 scans, format carte,
#: sans couche texte), ajoutées à la fin d'une seconde version des PDF
#: `*-split-simple`, `(…-split-simple-scenar)` (demande de l'utilisateur),
#: 4 par page A4 (`_append_scenario_pages`).
DEFAULT_SCENARIOS_FILE = Path("data/Manuel du général/MdG26-27 Scenarii.pdf")
_SCENARIO_GAP = 4 * mm


def scenario_variant_path(out_path: Path) -> Path:
    """`<liste> (fr-split-simple).pdf` -> `<liste> (fr-split-simple-scenar).pdf`."""
    stem = out_path.stem
    stem = stem[:-1] + "-scenar)" if stem.endswith(")") else stem + " (scenar)"
    return out_path.with_name(stem + out_path.suffix)


def _append_scenario_pages(writer: PdfWriter, path: Path) -> None:
    """Ajoute les cartes de `path`, 4 par page A4 (2 × 2), réduites juste
    assez pour tenir (≈ 88 %, lisibles) et centrées ; images recompressées
    comme toute page copiée (`_compress_page_images`). Fichier absent : rien."""
    if not path.exists():
        return
    cards = PdfWriter()
    for page in PdfReader(str(path)).pages:
        cards.add_page(page)
        _compress_page_images(cards.pages[-1])
    page_w, page_h = A4
    margin = _CARD_PAGE_MARGIN
    for start in range(0, len(cards.pages), 4):
        sheet = writer.add_blank_page(width=page_w, height=page_h)
        for k, card in enumerate(cards.pages[start:start + 4]):
            # La carte occupe la TrimBox (pages A4 avec carte centrée) ; sans
            # TrimBox, pypdf renvoie la CropBox/MediaBox, soit la page entière.
            box = card.trimbox
            cw, ch = float(box.width), float(box.height)
            scale = min(
                (page_w - 2 * margin - _SCENARIO_GAP) / 2 / cw, (page_h - 2 * margin - _SCENARIO_GAP) / 2 / ch,
            )
            block_w, block_h = 2 * cw * scale + _SCENARIO_GAP, 2 * ch * scale + _SCENARIO_GAP
            x0, y0 = (page_w - block_w) / 2, (page_h - block_h) / 2
            col, row = k % 2, k // 2
            x = x0 + col * (cw * scale + _SCENARIO_GAP)
            y = y0 + (1 - row) * (ch * scale + _SCENARIO_GAP)
            sheet.merge_transformed_page(
                card,
                Transformation().translate(-float(box.left), -float(box.bottom)).scale(scale).translate(x, y),
            )


def _append_pages(writer: PdfWriter, reader: PdfReader, seen_pages: set[int], sections: list[tuple[str, list[int]]]) -> None:
    for _label, pages in sections:
        for page_num in pages:
            if page_num in seen_pages:
                continue
            seen_pages.add(page_num)
            writer.add_page(reader.pages[page_num])
            _compress_page_images(writer.pages[-1])


def _render_ability_entries(story: list, entries: list[AbilityEntry]) -> None:
    for entry in entries:
        story.append(_safe_paragraph(entry.name, _EN_SUBSECTION))
        if entry.legend:
            story.append(_safe_paragraph(clean_html(entry.legend), _EN_LEGEND))
        story.append(_safe_paragraph(clean_html(entry.description), _EN_BODY))


def _build_wahapedia_appendix_pdf(
    wahapedia_lore_blocks: list[tuple[str, list[AbilityEntry]]],
    renown_army: tuple[str, dict[str, list[AbilityEntry]]] | None,
    regiments_of_renown: list[tuple[str, RegimentOfRenownData | None]],
) -> bytes | None:
    """Repli anglais pour ce qui n'a pas de carte/page dédiée : domaines de
    sorts/manifestations génériques, règles d'armée de renom, Regiments of
    Renown à plusieurs membres (un seul membre : son aptitude rejoint plutôt
    la carte de cette unité, cf. `build_roster_pdf`). Les profils d'unité
    eux-mêmes ne passent plus par ici — ils sont rendus en carte maison
    (`warscroll_card.py`), plus de page de battletome copiée ni de bloc de
    texte anglais pour un profil d'unité."""
    if not (wahapedia_lore_blocks or renown_army or regiments_of_renown):
        return None

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=15 * mm,
        title="Annexe Wahapedia (EN)",
    )
    story: list = [
        Paragraph(tr("ANNEXE — CONTENU WAHAPEDIA (ANGLAIS)"), _EN_BANNER),
        Paragraph(tr(
            "Ce qui suit n'existe dans aucun des PDF fournis (battletomes, Manuel du général) : "
            "domaines de sorts/manifestations génériques, règles d'armée de renom, Régiments de Renom. "
            "Repris tel quel depuis data/wahapedia/ (Wahapedia, en anglais) — non traduit pour éviter tout contresens sur des règles de jeu."
        ), _EN_SUBBANNER),
    ]

    for label, entries in wahapedia_lore_blocks:
        story.append(Paragraph(label, _EN_SECTION))
        _render_ability_entries(story, entries)

    if renown_army is not None:
        renown_name, grouped = renown_army
        story.append(Paragraph(f"{renown_name} — Army of Renown Rules", _EN_SECTION))
        for category, entries in grouped.items():
            story.append(Paragraph(category, _EN_SUBSECTION))
            _render_ability_entries(story, entries)

    for ror_name, ror_data in regiments_of_renown:
        story.append(Paragraph(f"Regiment of Renown — {ror_name}", _EN_SECTION))
        if ror_data is None:
            story.append(Paragraph("⚠ Non trouvé dans Wahapedia non plus.", _WARNING))
            continue
        if ror_data.legend:
            story.append(_safe_paragraph(clean_html(ror_data.legend), _EN_LEGEND))
        if ror_data.composition:
            story.append(_safe_paragraph("Composition : " + ", ".join(clean_html(c) for c in ror_data.composition), _EN_BODY))
        _render_ability_entries(story, ror_data.abilities)

    doc.build([_wrap_in_sheet(story, doc.width)], onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()


#: hauteur réservée en haut de page à l'en-tête discret des pages de tour du
#: mode `fr-split` (`_build_rule_cards_pdf(..., page_label=...)`). Était à
#: 9mm (libellé à ~6mm du bord) : l'imprimante de l'utilisateur coupait le
#: libellé à mi-hauteur, d'où le décalage de tout le contenu de 5mm vers le bas.
_PAGE_LABEL_MARGIN = 14 * mm


def _draw_page_label(c, doc, label: str) -> None:
    """En-tête discret (petites capitales bleu nuit, centrées, filet doré de
    part et d'autre) dans la marge haute d'une page de carte de tour du mode
    `fr-split` — « Mon tour »/« Tour de l'adversaire » : les 2 cartes ont les
    mêmes bandeaux de phase, ce repère dit d'un coup d'œil sur quelle page on
    est sans remonter jusqu'au titre de la carte (demande de l'utilisateur)."""
    c.saveState()
    page_w, page_h = doc.pagesize
    text = label.upper()
    font, size = "Helvetica-Bold", 7
    y = page_h - _PAGE_LABEL_MARGIN + 3 * mm
    text_w = c.stringWidth(text, font, size)
    c.setFont(font, size)
    c.setFillColor(NIGHT_BLUE)
    c.drawCentredString(page_w / 2, y, text)
    c.setStrokeColor(GOLD_DIM)
    c.setLineWidth(0.5)
    gap, rule = 3 * mm, 25 * mm
    mid_y = y + size * 0.35
    c.line(page_w / 2 - text_w / 2 - gap - rule, mid_y, page_w / 2 - text_w / 2 - gap, mid_y)
    c.line(page_w / 2 + text_w / 2 + gap, mid_y, page_w / 2 + text_w / 2 + gap + rule, mid_y)
    c.restoreState()


def _pad_to_odd_page(writer: PdfWriter) -> None:
    """Ajoute une page blanche si la prochaine page serait paire, pour qu'une
    section démarre sur une page impaire (recto) à l'impression recto-verso —
    mode `fr-split` : « Tour de l'adversaire » et les warscrolls (demande
    explicite de l'utilisateur)."""
    if len(writer.pages) % 2 == 1:
        first = writer.pages[0].mediabox
        writer.add_blank_page(width=first.width, height=first.height)


#: hauteur de la ligne de base du numéro de page, depuis le bas de la page :
#: sous le contenu des pages de cartes (`_CARD_PAGE_MARGIN`, 5.5mm).
_PAGE_NUMBER_Y = 2.2 * mm


def _stamp_page_numbers(writer: PdfWriter) -> None:
    """Numéro « n / total » centré en bas de chaque page (demande de
    l'utilisateur), posé après l'assemblage : chaque section est un mini-PDF
    séparé, seule la numérotation finale est la bonne. Une page blanche de
    recto-verso (`_pad_to_odd_page`, sans contenu) compte mais reste vierge."""
    total = len(writer.pages)
    buf = BytesIO()
    first = writer.pages[0].mediabox
    c = rl_canvas.Canvas(buf, pagesize=(float(first.width), float(first.height)))
    for i in range(total):
        c.setFont("Helvetica", 6.5)
        c.setFillColor(STEEL)
        c.drawCentredString(float(first.width) / 2, _PAGE_NUMBER_Y, f"{i + 1} / {total}")
        c.showPage()
    c.save()
    overlay = PdfReader(BytesIO(buf.getvalue()))
    for i, page in enumerate(writer.pages):
        if "/Contents" not in page:
            continue
        page.merge_page(overlay.pages[i])


def _build_rule_cards_pdf(cards: list, page_label: str | None = None, label_margin: bool = False) -> bytes | None:
    """Empile les cartes de règle (Traits de Bataille/Formation/Traits
    Héroïques/Artefacts) en pile simple, sans les grouper 2 par ligne comme
    les cartes de warscroll : leur longueur varie trop (1 aptitude pour une
    formation, 9 pour des traits héroïques) pour qu'un `KeepTogether` sur une
    paire reste pertinent — une carte trop longue pour une page tiendrait la
    carte voisine, plus courte, en otage sur la page précédente.
    `label_margin` : même marge haute que les pages de tour du mode
    `fr-split` (`_PAGE_LABEL_MARGIN`), sans le libellé — carte « Aptitudes »
    des modes non-split (demande de l'utilisateur)."""
    if not cards:
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_CARD_PAGE_MARGIN, rightMargin=_CARD_PAGE_MARGIN,
        topMargin=_PAGE_LABEL_MARGIN if page_label or label_margin else _CARD_PAGE_MARGIN, bottomMargin=_CARD_PAGE_MARGIN,
        title="Règles de faction (cartes)",
    )
    story: list = []
    for card in cards:
        if story:
            # avant chaque carte sauf la première : un `Spacer` de fin qui ne
            # rentre plus dans l'espace restant part seul sur une page neuve
            # — page blanche en fin de PDF (cf. `pack_cards_two_columns`).
            story.append(Spacer(1, 5 * mm))
        # une carte sectionnée (`render_rule_card(..., sectioned=True)`) est
        # une liste de flowables, chaque bandeau de phase pouvant se couper
        story.extend(card if isinstance(card, list) else [card])

    def on_page(c, d) -> None:
        _draw_page_bg(c, d)
        if page_label:
            _draw_page_label(c, d, page_label)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _tactic_cards_block(cards: list, min_scale: float | None = None) -> Flowable | None:
    """Toutes les cartes de tactique citées dans un seul `KeepTogether` :
    toujours sur la même page (demande explicite de l'utilisateur), quitte
    à partir en page suivante si la place restante ne suffit pas. Sans texte
    d'ambiance (`render_tactic_card`), 2 cartes tiennent largement sur une
    page. Avec `min_scale`, le bloc se réduit jusqu'à cette échelle pour
    tenir dans la place restante plutôt que de changer de page
    (`_ShrinkToFitTogether`)."""
    if not cards:
        return None
    flow: list = []
    for card in cards:
        if flow:
            flow.append(Spacer(1, 6 * mm))
        flow.append(card)
    return _ShrinkToFitTogether(flow, min_scale) if min_scale is not None else KeepTogether(flow)


#: Échelle minimale à laquelle le bloc des cartes de tactique peut être
#: réduit pour tenir sur la page de « Fin de tour » (mode `fr-split`,
#: `_ShrinkToFitTogether`) — en deçà, le texte deviendrait trop petit : le
#: bloc part alors en page suivante, à taille normale.
_TACTIC_MIN_SCALE = 0.85


class _ShrinkToFitTogether(Flowable):
    """`KeepTogether` qui, avant de partir en page suivante, tente de tenir
    dans la place restante en se réduisant (au plus jusqu'à `min_scale`,
    centré horizontalement) — cartes de tactique du mode `fr-split`, posées
    sur la même page que le bandeau « Fin de tour » de « Mon tour » dès que
    c'est possible (demande de l'utilisateur)."""

    def __init__(self, content: list, min_scale: float):
        super().__init__()
        self.content = content
        self.min_scale = min_scale
        self.scale = 1.0

    def _natural(self, avail_width: float) -> tuple[float, float, list[float]]:
        sizes = [f.wrap(avail_width, 0xFFFF) for f in self.content]
        return max(w for w, _h in sizes), sum(h for _w, h in sizes), [h for _w, h in sizes]

    def wrap(self, availWidth, availHeight):
        self._avail_width = availWidth
        width, height, self._heights = self._natural(availWidth)
        self.scale = 1.0
        if height > availHeight and height * self.min_scale <= availHeight:
            self.scale = availHeight / height
        self.width, self.height = availWidth, height * self.scale
        return self.width, self.height

    def split(self, availWidth, availHeight):
        # ne tient même pas réduit : page suivante, à taille normale (comme
        # `KeepTogether`) ; déjà en haut de page, on laisse couper.
        if availHeight < _FULL_PAGE_HEIGHT:
            return []
        return list(self.content)

    def draw(self):
        c = self.canv
        c.saveState()
        content_width = max(f.wrap(self._avail_width, 0xFFFF)[0] for f in self.content)
        c.translate((self._avail_width - content_width * self.scale) / 2, 0)
        c.scale(self.scale, self.scale)
        y = sum(self._heights)
        for f, h in zip(self.content, self._heights):
            y -= h
            f.drawOn(c, 0, y)
        c.restoreState()


def _build_tactic_cards_pdf(cards: list) -> bytes | None:
    """Les cartes de tactique de bataille citées, toutes sur la même page
    (`_tactic_cards_block`)."""
    if not cards:
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_CARD_PAGE_MARGIN, rightMargin=_CARD_PAGE_MARGIN, topMargin=_CARD_PAGE_MARGIN, bottomMargin=_CARD_PAGE_MARGIN,
        title="Cartes de tactique de bataille",
    )
    doc.build([_tactic_cards_block(cards)], onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()


def _build_warscroll_cards_pdf(warscrolls: list[WarscrollData], regiment_notes: dict[str, str]) -> bytes | None:
    if not warscrolls:
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_CARD_PAGE_MARGIN, rightMargin=_CARD_PAGE_MARGIN, topMargin=_CARD_PAGE_MARGIN, bottomMargin=_CARD_PAGE_MARGIN,
        title="Profils d'unité (cartes)",
    )
    doc.build(build_warscroll_cards_flow(warscrolls, width=_UNIT_CARD_WIDTH, gap=_UNIT_CARD_GAP, regiment_notes=regiment_notes), onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()

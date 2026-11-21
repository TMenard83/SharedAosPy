"""Logique partagée par combat_unites.py/combat_heros.py — même source
(`repository.get_ranking_pool`, lu en direct dans `unit_benchmark`), même tableau à 5 indicateurs, seul
le filtre troupe/héros et le texte (French, propre à chaque rôle) varient. Ce
module porte la mécanique (chargement, tri, mise en page PDF) commune ; les
fichiers combat_unites.py/combat_heros.py ne gardent que leur texte et
appellent `build()`."""

from reportlab.lib.units import mm
from reportlab.platypus import NextPageTemplate, PageBreak, Paragraph, Spacer

from ..persistence import db, repository
from .common import (
    BLOOD_GREEN,
    BLOOD_RED,
    SectionMarker,
    alliance_badge,
    body_text,
    build_document,
    cover_body,
    cover_meta,
    cover_subtitle,
    cover_title,
    ranked_table,
    section_note,
    section_title,
    subhead,
    today_str,
)

HEADER = [
    "#",
    None,
    "Armée",
    "All.",
    "Pts",
    "ROI Stabilité\n(95)",
    "ROI Fiabilité\n(66)",
    "ROI Explosivité\n(20)",
    "ROI Moyen",
    "Pts net moy.",
    "% positif",
]
COL_WIDTHS = [w * mm for w in (10, 54, 38, 14, 12, 20, 20, 20, 20, 24, 18)]


def fmt_row(rank, r):
    return [
        str(rank),
        r["name"],
        r["army"],
        alliance_badge(r["grand_alliance"]),
        str(r["points"]),
        f"{r['roi_floor95_pct']:+.1f}%",
        f"{r['roi_floor66_pct']:+.1f}%",
        f"{r['roi_floor20_pct']:+.1f}%",
        f"{r['avg_floor_roi_pct']:+.1f}%",
        f"{r['avg_pts_net']:+.1f}",
        f"{r['pct_positive']:.0f}%",
    ]


def roi_color(r):
    return BLOOD_GREEN if r["avg_floor_roi_pct"] >= 0 else BLOOD_RED


def build(
    *,
    is_hero: bool,
    label: str,
    out_path: str,
    band_text: str,
    cover_title_label: str,
    cover_subtitle_template: str,
    cover_body_html: str,
    method_section_marker: str,
    method_section_note: str,
    method_paragraphs_html: list[str],
    data_section_title: str,
    data_section_note: str,
    table_count_template: str,
) -> None:
    """`cover_body_html`/`method_paragraphs_html` sont fournis verbatim par
    l'appelant (texte propre au rôle) ; `cover_subtitle_template`/
    `table_count_template` n'ont qu'un trou `{n}` (et `{n_armies}` pour le
    premier) pour le décompte."""
    con = db.connect()
    all_rows = repository.get_ranking_pool(con)
    con.close()
    rows = [r for r in all_rows if r["is_hero"] == is_hero]
    rows.sort(key=lambda r: r["avg_floor_roi_pct"], reverse=True)
    n_rows = len(rows)
    n_armies = len({r["army"] for r in rows})

    header = [label if h is None else h for h in HEADER]

    doc = build_document(out_path, f"Age of Sigmar — {cover_title_label} (TM)", band_text)

    story = []
    story.append(Spacer(1, 26 * mm))
    story.append(Paragraph("Compendium des Duels", cover_title))
    story.append(
        Paragraph(
            cover_subtitle_template.format(n_armies=n_armies, n=n_rows),
            cover_subtitle,
        )
    )
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(cover_body_html.format(n=n_rows), cover_body))

    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, method_section_marker))
    story.append(PageBreak())
    story.append(Paragraph("Méthode", section_title))
    story.append(Paragraph(method_section_note, section_note))
    story.append(Spacer(1, 2 * mm))
    for p in method_paragraphs_html:
        story.append(Paragraph(p, body_text))

    story.append(SectionMarker(doc, data_section_title))
    story.append(PageBreak())
    story.append(Paragraph(data_section_title, section_title))
    story.append(Paragraph(data_section_note, section_note))
    story.append(Paragraph(table_count_template.format(n=n_rows), subhead))
    story.append(Spacer(1, 2))
    story.append(
        ranked_table(header, COL_WIDTHS, rows, fmt_row, lambda r: r["grand_alliance"], colored_cols=[(8, roi_color)])
    )

    doc.build(story)
    print("PDF genere:", out_path)

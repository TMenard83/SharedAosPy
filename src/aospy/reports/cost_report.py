"""Logique partagée par cost_unites.py/cost_heros.py : les deux ajustent le
MÊME modèle factoriel (toute la population, héros + troupes — voir la
docstring de cost_heros.py pour le comparatif de R² qui a motivé l'abandon de
`fit_segmented`) et n'en lisent qu'un sous-ensemble filtré par rôle. Seul le
texte (French, propre à chaque rôle) et quelques libellés varient : ce module
porte la mécanique (ajustement, filtrage, mise en page PDF) commune ; les
fichiers cost_unites.py/cost_heros.py ne gardent que leur texte et appellent
`build()`."""

from reportlab.lib.units import mm
from reportlab.platypus import NextPageTemplate, PageBreak, Paragraph, Spacer

from ..analysis.cost import cost_model
from ..persistence import db, repository
from .common import (
    BLOOD_GREEN,
    BLOOD_RED,
    SectionMarker,
    alliance_badge,
    build_document,
    cover_body,
    cover_meta,
    cover_subtitle,
    cover_title,
    ranked_table,
    section_note,
    subhead,
    today_str,
)
from .cost_common import coef_table

MIN_PREDICTED = 40.0


def build(
    *,
    is_hero: bool,
    label: str,
    out_path: str,
    band_text: str,
    cover_title_suffix: str,
    cover_subtitle_template: str,
    section_title_coef: str,
    section_title: str,
    method_body_html: str,
    coef_note_html: str,
    table_note_html: str,
    table_count_template: str,
) -> None:
    """`label` : libellé colonne ("Unité"/"Héros"). Les textes (`*_html`) et les
    gabarits `*_template` (un seul trou, `{n}`, pour le décompte — les accords
    de genre français "unités classées"/"héros classés" ne sont pas les mêmes,
    donc ce module ne reconstruit pas la phrase lui-même) sont fournis verbatim
    par l'appelant : ce module ne touche pas au contenu, seulement à la
    mécanique qui l'entoure."""
    con = db.connect()
    frame = cost_model.feature_frame(con)
    result = cost_model.fit_cost_model_factorial(con, frame=frame.copy())
    role_ids = set(frame.loc[frame["is_hero"] == is_hero, "unit_id"])
    pool = [r for r in result.residuals if r.predicted >= MIN_PREDICTED and r.unit_id in role_ids]
    undercosted = sorted(pool, key=lambda r: r.residual_pct)
    armies = {a.id: a for a in repository.list_armies(con)}
    con.close()

    header = ["#", label, "Armée", "All.", "Pts réels", "Pts prédits", "Résidu", "Résidu %"]
    col_widths = [w * mm for w in (10, 65, 48, 18, 22, 24, 22, 22)]

    def alliance_of(r):
        army = armies.get(r.army_id)
        return army.grand_alliance if army else "Order"

    def fmt_row(rank, r):
        army = armies.get(r.army_id)
        return [
            str(rank),
            r.name,
            army.name if army else "?",
            alliance_badge(alliance_of(r)),
            str(r.points),
            f"{r.predicted:.1f}",
            f"{r.residual:+.1f}",
            f"{r.residual_pct:+.0f}%",
        ]

    def resid_color(r):
        # résidu négatif = sous-coté = bonne affaire (vert) ; positif = sur-coté (rouge)
        return BLOOD_GREEN if r.residual < 0 else BLOOD_RED

    doc = build_document(out_path, f"Age of Sigmar — {cover_title_suffix} (TM)", band_text)

    story = []
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Registre des Anomalies de Coût", cover_title))
    story.append(Paragraph(cover_subtitle_template.format(n=len(undercosted)), cover_subtitle))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            method_body_html.format(
                r=result.r_squared**0.5,
                r2=result.r_squared,
                adj_r2=result.adj_r_squared,
                n=result.n_obs,
                min_predicted=MIN_PREDICTED,
            ),
            cover_body,
        )
    )

    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, section_title_coef))
    story.append(PageBreak())
    story.append(Paragraph(section_title_coef, section_title))
    story.append(Paragraph(coef_note_html, section_note))
    story.append(Spacer(1, 2 * mm))
    story.append(coef_table(result))

    story.append(SectionMarker(doc, section_title))
    story.append(PageBreak())
    story.append(Paragraph(section_title, section_title))
    story.append(Paragraph(table_note_html, section_note))
    story.append(Paragraph(table_count_template.format(n=len(undercosted)), subhead))
    story.append(Spacer(1, 2))
    story.append(
        ranked_table(
            header,
            col_widths,
            undercosted,
            fmt_row,
            alliance_of,
            colored_cols=[(6, resid_color), (7, resid_color)],
            font_size=8,
        )
    )

    doc.build(story)
    print("PDF genere:", out_path)

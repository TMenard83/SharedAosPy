"""Logique partagée par best_unites.py/best_heros.py : les deux croisent le
même registre de combat (`repository.get_ranking_pool`, lu en direct) et un
modèle de coût factoriel ajusté séparément sur leur population (troupe ou
héros), avec la même formule de score (cf. analysis/cost/scoring.py::combined_score). Ce
module porte la mécanique (jointure, z-scores, mise en page PDF) commune ;
`compute_ranked()` est aussi réutilisé directement par best_by_faction.py.
Les fichiers best_unites.py/best_heros.py ne gardent que leur texte et
appellent `render()`."""
import statistics

from reportlab.lib.units import mm
from reportlab.platypus import NextPageTemplate, PageBreak, Paragraph, Spacer

from ..analysis.cost import cost_model
from ..analysis.cost.scoring import combined_score
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

MIN_PREDICTED = 40.0
#: Poids de l'indicateur (z_roi) relativement à la sous-cotation (z_undercost)
#: dans le score combiné — surpondère la performance en combat.
ROI_WEIGHT = 2.0
#: Poids du terme de pénalité de déséquilibre (cf. `analysis/cost/scoring.py::combined_score`)
#: relativement à la moyenne pondérée — empêche un excès sur un indicateur de
#: compenser entièrement une faiblesse sur l'autre (ex. Namarti Reavers, très
#: sous-cotés mais médiocres en combat, se classaient 3e sans ce terme).
IMBALANCE_WEIGHT = 1.0
#: Poids de l'impact absolu (z-score de ``avg_pts_net``, non normalisé par le
#: coût) dans le score combiné — sans cet axe, deux unités au même ROI% et au
#: même résidu se valent quel que soit leur impact réel en partie, alors qu'une
#: unité pas chère y arrive mécaniquement plus vite qu'une unité chère (ROI% et
#: résidu sont tous deux normalisés par les points). Ex. Bloodcrushers (130 pts,
#: pts_net moyen +22.6) devançait Revenant Draconith (180 pts, pts_net moyen
#: +30.0, donc un impact réel supérieur) uniquement parce que son ROI% relatif
#: à son coût plus faible était meilleur.
IMPACT_WEIGHT = 1.0

HEADER_TEMPLATE = ["#", None, "Armée", "All.", "Pts", "ROI Moyen", "Résidu coût %", "Impact net", "Score combiné"]
COL_WIDTHS = [w * mm for w in (10, 56, 40, 14, 13, 24, 24, 22, 24)]


def compute_ranked(is_hero: bool) -> list[dict]:
    """Classement complet, toutes armées confondues, avec le rang global stocké
    dans chaque ligne (clé ``rank``) — c'est ce rang, pas la position dans une
    liste éventuellement filtrée, que `render()` affiche en colonne ``#``."""
    con = db.connect()
    combat_rows = repository.get_ranking_pool(con)
    combat_by_id = {r["unit_id"]: r for r in combat_rows if r["is_hero"] == is_hero}
    frame = cost_model.feature_frame(con)
    role_frame = frame.query("is_hero == @is_hero").copy()
    cost_result = cost_model.fit_cost_model_factorial(con, frame=role_frame)
    con.close()

    pool = [
        r for r in cost_result.residuals
        if r.predicted >= MIN_PREDICTED and r.unit_id in combat_by_id
    ]

    roi_values = [combat_by_id[r.unit_id]["avg_floor_roi_pct"] for r in pool]
    resid_values = [r.residual_pct for r in pool]
    impact_values = [combat_by_id[r.unit_id]["avg_pts_net"] for r in pool]
    roi_mean, roi_std = statistics.mean(roi_values), statistics.pstdev(roi_values)
    resid_mean, resid_std = statistics.mean(resid_values), statistics.pstdev(resid_values)
    impact_mean, impact_std = statistics.mean(impact_values), statistics.pstdev(impact_values)

    def z(value, mean, std):
        return (value - mean) / std if std else 0.0

    joined = []
    for r in pool:
        c = combat_by_id[r.unit_id]
        z_roi = z(c["avg_floor_roi_pct"], roi_mean, roi_std)
        z_undercost = -z(r.residual_pct, resid_mean, resid_std)  # un résidu négatif profite au score
        z_impact = z(c["avg_pts_net"], impact_mean, impact_std)
        joined.append({
            "name": c["name"], "army": c["army"], "grand_alliance": c["grand_alliance"],
            "points": c["points"], "avg_floor_roi_pct": c["avg_floor_roi_pct"],
            "residual_pct": r.residual_pct, "avg_pts_net": c["avg_pts_net"],
            "score": combined_score(
                [(z_roi, ROI_WEIGHT), (z_undercost, 1.0), (z_impact, IMPACT_WEIGHT)],
                IMBALANCE_WEIGHT,
            ),
        })
    joined.sort(key=lambda r: r["score"], reverse=True)
    for rank, r in enumerate(joined, start=1):
        r["rank"] = rank
    return joined


def fmt_row(rank, r):
    return [
        str(rank), r["name"], r["army"], alliance_badge(r["grand_alliance"]), str(r["points"]),
        f"{r['avg_floor_roi_pct']:+.1f}%", f"{r['residual_pct']:+.0f}%",
        f"{r['avg_pts_net']:+.1f}", f"{r['score']:+.2f}",
    ]


def score_color(r):
    return BLOOD_GREEN if r["score"] >= 0 else BLOOD_RED


def render(
    joined: list[dict],
    out_path: str,
    *,
    label: str,
    band_text: str,
    cover_title_doc: str,
    cover_subtitle_plain_template: str,
    cover_subtitle_faction_template: str,
    cover_body_intro_html: str,
    cover_body_plain_template: str,
    cover_body_faction_template: str,
    method_section_marker: str,
    method_paragraphs_html: list[str],
    data_section_title: str,
    data_section_note: str,
    table_count_template: str,
    faction: str | None = None,
    universe_n: int = 0,
) -> None:
    """Rend `joined` (classement complet, ou extrait pré-filtré par faction) en
    PDF. Quand `faction` est fourni, le sous-titre/la note mentionnent
    l'extrait et `universe_n` (taille du registre global) ; la colonne ``#``
    affiche toujours ``r["rank"]`` (rang global), jamais la position dans
    `joined`. Les textes (`*_html`) et gabarits (`*_template`) sont fournis
    verbatim par l'appelant (texte propre au rôle)."""
    n_units = len(joined)
    n_armies = len({r["army"] for r in joined})

    doc = build_document(out_path, cover_title_doc, band_text)

    story = []
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph("Panthéon des Champions", cover_title))
    if faction:
        story.append(Paragraph(
            cover_subtitle_faction_template.format(faction=faction, n=n_units, universe_n=universe_n),
            cover_subtitle,
        ))
    else:
        story.append(Paragraph(
            cover_subtitle_plain_template.format(n_armies=n_armies, n=n_units),
            cover_subtitle,
        ))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
    story.append(Spacer(1, 10 * mm))
    tail = (
        cover_body_faction_template.format(faction=faction, n=n_units, universe_n=universe_n)
        if faction else
        cover_body_plain_template.format(n=n_units)
    )
    story.append(Paragraph(cover_body_intro_html + tail, cover_body))

    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, method_section_marker))
    story.append(PageBreak())
    story.append(Paragraph("Méthode", section_title))
    story.append(Paragraph(
        "Construction des trois indicateurs croisés dans ce registre, puis du score combiné qui en résulte.",
        section_note,
    ))
    story.append(Spacer(1, 2 * mm))
    for p in method_paragraphs_html:
        story.append(Paragraph(
            p.format(min_predicted=MIN_PREDICTED, roi_weight=ROI_WEIGHT, imbalance_weight=IMBALANCE_WEIGHT),
            body_text,
        ))

    story.append(SectionMarker(doc, data_section_title))
    story.append(PageBreak())
    story.append(Paragraph(data_section_title, section_title))
    story.append(Paragraph(data_section_note, section_note))
    story.append(Paragraph(table_count_template.format(n=n_units), subhead))
    story.append(Spacer(1, 2))
    header = [label if h is None else h for h in HEADER_TEMPLATE]
    story.append(ranked_table(header, COL_WIDTHS, joined, fmt_row, lambda r: r["grand_alliance"],
                              colored_cols=[(8, score_color)], ranks=[r["rank"] for r in joined]))

    doc.build(story)
    print("PDF genere:", out_path)

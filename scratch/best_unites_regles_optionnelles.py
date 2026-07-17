"""Panthéon des Champions — Unités, édition « règles optionnelles ».

Miroir de `aospy.reports.best_unites` (croise combat × coût, z-scores,
score combiné), mais la moitié « combat » vient du scénario --charge none
avec les 2 règles optionnelles actives (tir double + seuil de charge 30%,
cf. scratch/aggregate_regles_optionnelles.py) au lieu du scénario standard
« sans charge » édition TM, lue au plancher pessimiste 66% de confiance (au
lieu de 80% côté édition TM). Le plan de coût (résidu factoriel) est inchangé
— les règles optionnelles ne touchent que les duels, pas le modèle de coût.
Réutilise `aospy.reports.common` (charte graphique) et `aospy.analysis.cost_model`
tels quels ; n'adapte que les sources de données et les textes de méthode.
"""
import json
import statistics

import duckdb
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from aospy.analysis import cost_model
from aospy.reports.common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead,
)

DB_PATH = "scratch/aospy_two_rules.duckdb"
COMBAT_JSON = "scratch/output/essai_regles_optionnelles/per_unit_regles_floor66.json"
OUT_PATH = "scratch/output/essai_regles_optionnelles/AoS_unites_best_regles_optionnelles.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  MEILLEURES UNITÉS (COMBAT × COÛT)  ·  RÈGLES OPTIONNELLES"
SECTION_TITLE = "Panthéon des Champions — Unités (règles optionnelles)"

MIN_PREDICTED = 40.0
#: Pondération du terme ROI dans le score combiné (score = ROI_WEIGHT·z_roi −
#: z_résidu) — > 1 fait pencher le classement vers le dégât plutôt que la
#: sous-cotation ; 1.25 ne reclassait quasiment rien, essai à 2.0.
ROI_WEIGHT = 2.0
HEADER = ["#", "Unité", "Armée", "All.", "Pts", "ROI moy.", "Résidu coût %", "Score combiné"]
COL_WIDTHS = [w * mm for w in (10, 62, 45, 15, 14, 26, 26, 24)]


def compute_ranked() -> list[dict]:
    with open(COMBAT_JSON, "r", encoding="utf-8") as f:
        combat_rows = json.load(f)
    combat_by_id = {r["unit_id"]: r for r in combat_rows if not r["is_hero"]}

    con = duckdb.connect(DB_PATH, read_only=True)
    frame = cost_model.feature_frame(con)
    troupe_frame = frame.query("is_hero == False").copy()
    cost_result = cost_model.fit_cost_model_factorial(con, frame=troupe_frame)
    con.close()

    pool = [
        r for r in cost_result.residuals
        if r.predicted >= MIN_PREDICTED and r.unit_id in combat_by_id
    ]

    roi_values = [combat_by_id[r.unit_id]["avg_roi_pct"] for r in pool]
    resid_values = [r.residual_pct for r in pool]
    roi_mean, roi_std = statistics.mean(roi_values), statistics.pstdev(roi_values)
    resid_mean, resid_std = statistics.mean(resid_values), statistics.pstdev(resid_values)

    def z(value, mean, std):
        return (value - mean) / std if std else 0.0

    joined = []
    for r in pool:
        c = combat_by_id[r.unit_id]
        z_roi = z(c["avg_roi_pct"], roi_mean, roi_std)
        z_resid = z(r.residual_pct, resid_mean, resid_std)
        joined.append({
            "name": c["name"], "army": c["army"], "grand_alliance": c["grand_alliance"],
            "points": c["points"], "avg_roi_pct": c["avg_roi_pct"],
            "residual_pct": r.residual_pct, "score": ROI_WEIGHT * z_roi - z_resid,
        })
    joined.sort(key=lambda r: r["score"], reverse=True)
    for rank, r in enumerate(joined, start=1):
        r["rank"] = rank
    return joined


def fmt_row(rank, r):
    return [
        str(rank), r["name"], r["army"], alliance_badge(r["grand_alliance"]), str(r["points"]),
        f"{r['avg_roi_pct']:+.1f}%", f"{r['residual_pct']:+.0f}%", f"{r['score']:+.2f}",
    ]


def score_color(r):
    return BLOOD_GREEN if r["score"] >= 0 else BLOOD_RED


def render(joined: list[dict], out_path: str) -> None:
    n_units = len(joined)
    n_armies = len({r["army"] for r in joined})

    doc = build_document(
        out_path, "Age of Sigmar — Meilleures unités, combat × coût (règles optionnelles)", BAND_TEXT,
    )

    story = []
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Panthéon des Champions", cover_title))
    story.append(Paragraph(
        f"Unités de troupe, avec règles optionnelles — {n_armies} armées, {n_units} unités", cover_subtitle,
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"Registre établi le {today_str()}", cover_meta))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "<b>Méthode :</b> ce registre croise le <i>Compendium des Duels — Unités</i>, calculé avec les "
        "<b>2 règles optionnelles actives</b> et <b>aucune charge déclarée par défaut</b> "
        "(<tt>--charge none</tt> — la charge ne se déclenche plus que via les conditions géométriques des "
        "règles elles-mêmes), et le <i>Registre des Anomalies de Coût — Unités</i> (résidu d'un plan "
        "d'expérience factoriel ajusté sur les troupes, inchangé : les règles optionnelles ne modifient que "
        "les duels, pas le modèle de coût) — les deux sur les mêmes unités, jointes par identifiant interne. "
        f"Les unités dont la prédiction de coût est trop faible (&lt; {MIN_PREDICTED:.0f} pts, résidu relatif "
        "peu fiable) sont écartées.<br/><br/>"
        "<b>Règle « tir double »</b> : entre les deux unités, celle qui a la plus petite portée à distance "
        "(0 si mêlée pure) est réputée chargeuse. Si son Move + charge (+ course, si autorisée) ne couvre pas "
        "la portée de l'autre camp, celui-ci tire deux fois (profils à distance uniquement).<br/>"
        "<b>Règle « seuil de charge 30% »</b> : une unité est considérée chargée — et bénéficie du bonus "
        "intrinsèque <i>Charge (+N)</i> d'une arme — seulement si son Move dépasse celui du défenseur de plus "
        "de 30%, déduit du seul écart de Move (aucune charge déclarée manuellement).<br/><br/>"
        "<b>Pourquoi croiser :</b> un bon ROI seul peut simplement signaler une unité déjà chère et donc "
        "« normale » côté prix. Une forte sous-cotation seule ne dit rien de l'efficacité réelle en combat. "
        "Une unité vraiment excellente cumule les deux : elle gagne ses duels <i>et</i> coûte moins cher que "
        "ce que son profil justifierait.<br/><br/>"
        f"<b>Score combiné</b> = {ROI_WEIGHT:g} × z-score du ROI moyen − z-score du résidu de coût relatif "
        "(un résidu négatif profite donc au score), calculés sur la population des unités de troupe communes "
        f"aux deux registres. Pondération ROI × {ROI_WEIGHT:g} (essai) : le dégât pèse plus que la "
        "sous-cotation dans le classement.<br/><br/>"
        f"{n_units} unités classées par score décroissant — liste complète (aucune coupe).",
        cover_body,
    ))
    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, SECTION_TITLE))
    story.append(PageBreak())

    story.append(Paragraph(SECTION_TITLE, section_title))
    story.append(Paragraph(
        "Triées par score combiné décroissant (meilleur compromis performance/coût en tête).",
        section_note,
    ))
    story.append(Paragraph(f"{n_units} unités.", subhead))
    story.append(Spacer(1, 2))
    story.append(ranked_table(HEADER, COL_WIDTHS, joined, fmt_row, lambda r: r["grand_alliance"],
                              colored_cols=[(7, score_color)], ranks=[r["rank"] for r in joined]))

    doc.build(story)
    print("PDF genere:", out_path)


if __name__ == "__main__":
    render(compute_ranked(), OUT_PATH)

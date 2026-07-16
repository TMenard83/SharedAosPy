"""Croise, pour les héros, le registre de combat (scratch/per_unit_nocharge_TM.json)
et le registre de coût (plan d'expérience factoriel ajusté sur les héros, cf.
cost_heros.py) pour produire un classement des « meilleurs » héros.

`compute_ranked()`/`render()` sont réutilisés par `best_by_faction.py` pour produire,
par faction, un extrait filtré de ce même classement (rang global conservé, pas de
renumérotation locale).

Pendant : best_unites.py (même méthode, plan de coût troupes séparé)."""
import json
import statistics

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from ..persistence import db
from ..analysis import cost_model
from .common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead,
)

MIN_PREDICTED = 40.0
OUT_PATH = "scratch/output/AoS_heros_best_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  MEILLEURS HÉROS (COMBAT × COÛT)  ·  ÉD. TM"
SECTION_TITLE = "Panthéon des Champions — Héros"

HEADER = ["#", "Héros", "Armée", "All.", "Pts", "ROI moy.", "Résidu coût %", "Score combiné"]
COL_WIDTHS = [w * mm for w in (10, 62, 45, 15, 14, 26, 26, 24)]


def compute_ranked() -> list[dict]:
    """Classement complet, toutes armées confondues, avec le rang global stocké
    dans chaque ligne (clé ``rank``) — c'est ce rang, pas la position dans une
    liste éventuellement filtrée, que `render()` affiche en colonne ``#``."""
    with open("scratch/per_unit_nocharge_TM.json", "r", encoding="utf-8") as f:
        combat_rows = json.load(f)
    combat_by_id = {r["unit_id"]: r for r in combat_rows if r["is_hero"]}

    con = db.connect()
    frame = cost_model.feature_frame(con)
    hero_frame = frame.query("is_hero == True").copy()
    cost_result = cost_model.fit_cost_model_factorial(con, frame=hero_frame)
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
            "residual_pct": r.residual_pct, "score": z_roi - z_resid,
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


def render(joined: list[dict], out_path: str, *, faction: str | None = None, universe_n: int = 0) -> None:
    """Rend `joined` (classement complet, ou extrait pré-filtré par faction) en PDF.
    Quand `faction` est fourni, le sous-titre/la note mentionnent l'extrait et
    `universe_n` (taille du registre global) ; la colonne ``#`` affiche toujours
    ``r["rank"]`` (rang global), jamais la position dans `joined`."""
    n_units = len(joined)
    n_armies = len({r["army"] for r in joined})

    doc = build_document(out_path, "Age of Sigmar — Meilleurs héros, combat × coût (TM)", BAND_TEXT)

    story = []
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph("Panthéon des Champions", cover_title))
    if faction:
        story.append(Paragraph(
            f"Héros — {faction} — {n_units} héros (extrait du registre global, {universe_n} héros) — édition TM",
            cover_subtitle,
        ))
    else:
        story.append(Paragraph(
            f"Héros — {n_armies} armées, {n_units} héros — édition TM",
            cover_subtitle,
        ))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "<b>Méthode :</b> ce registre croise le <i>Compendium des Duels — Héros</i> (performance en "
        "combat, scénario sans charge, ROI moyen en lecture asymétrique — dégât infligé au plancher 80% "
        "de confiance, dégât encaissé à l'espérance) et le <i>Registre des "
        "Anomalies de Coût — Héros</i> (résidu d'un plan d'expérience factoriel ajusté séparément sur les "
        "héros) — les deux sur les mêmes héros, joints par identifiant interne. Les héros dont la "
        f"prédiction de coût est trop faible (&lt; {MIN_PREDICTED:.0f} pts, résidu relatif peu fiable) sont "
        "écartés, comme dans le registre des coûts. Voir <i>Panthéon des Champions — Unités</i> pour le "
        "pendant troupes, dont le plan de coût est ajusté indépendamment.<br/><br/>"
        "<b>Pourquoi croiser :</b> un bon ROI seul peut simplement signaler un héros déjà cher et donc "
        "« normal » côté prix. Une forte sous-cotation seule ne dit rien de l'efficacité réelle en "
        "combat. Un héros vraiment excellent cumule les deux : il gagne ses duels <i>et</i> coûte moins "
        "cher que ce que son profil justifierait.<br/><br/>"
        "<b>Score combiné</b> = z-score du ROI moyen − z-score du résidu de coût relatif (un résidu négatif "
        "profite donc au score). Les z-scores sont calculés sur la population des héros communs aux deux "
        "registres, chaque quantité étant centrée-réduite (moyenne 0, écart-type 1). Un score de +1 signifie "
        "un héros un écart-type au-dessus de la moyenne sur ce critère combiné — pas une grandeur physique "
        "en soi, un simple outil de tri.<br/><br/>"
        "<i>Rappel : le ROI de combat d'un héros ne mesure qu'un duel d'un round en un contre un — il ne "
        "capture ni les sorts/prières, ni les aptitudes de commandement, ni les buffs apportés à d'autres "
        "unités (voir le <i>Compendium des Duels — Héros</i>).</i><br/><br/>"
        + (
            f"Extrait filtré sur {faction} — {n_units} héros. La colonne <b>#</b> conserve le rang du "
            f"registre global ({universe_n} héros toutes armées confondues), pas un reclassement local."
            if faction else
            f"{n_units} héros classés par score décroissant — liste complète (aucune coupe)."
        ),
        cover_body,
    ))
    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, SECTION_TITLE))
    story.append(PageBreak())

    story.append(Paragraph(SECTION_TITLE, section_title))
    story.append(Paragraph(
        "Triés par score combiné décroissant (meilleur compromis performance/coût en tête).",
        section_note,
    ))
    story.append(Paragraph(f"{n_units} héros.", subhead))
    story.append(Spacer(1, 2))
    story.append(ranked_table(HEADER, COL_WIDTHS, joined, fmt_row, lambda r: r["grand_alliance"],
                              colored_cols=[(7, score_color)], ranks=[r["rank"] for r in joined]))

    doc.build(story)
    print("PDF genere:", out_path)


if __name__ == "__main__":
    render(compute_ranked(), OUT_PATH)

"""Croise, pour les héros, le registre de combat (scratch/per_unit_nocharge_floor66_TM.json)
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
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead, body_text,
)
from .cost_common import combined_score

MIN_PREDICTED = 40.0
#: Poids de l'indicateur (z_roi) relativement à la sous-cotation (z_undercost)
#: dans le score combiné — surpondère la performance en combat.
ROI_WEIGHT = 2.0
#: Poids du terme de pénalité de déséquilibre (cf. `cost_common.combined_score`)
#: relativement à la moyenne pondérée — empêche un excès sur un indicateur de
#: compenser entièrement une faiblesse sur l'autre. Voir best_unites.py (même
#: méthode) pour le cas d'usage qui a motivé ce terme (Namarti Reavers).
IMBALANCE_WEIGHT = 1.0
#: Poids de l'impact absolu (z-score de ``avg_pts_net``, non normalisé par le
#: coût) dans le score combiné. Voir best_unites.py (même méthode) pour le cas
#: d'usage qui a motivé ce terme (Bloodcrushers/Khainite Shadowstalkers devant
#: des unités à impact réel supérieur, uniquement parce que leur ROI% relatif à
#: leur coût plus faible était meilleur).
IMPACT_WEIGHT = 1.0
OUT_PATH = "scratch/output/AoS_heros_best_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  MEILLEURS HÉROS (COMBAT × COÛT)  ·  ÉD. TM"
SECTION_TITLE = "Panthéon des Champions — Héros"

HEADER = ["#", "Héros", "Armée", "All.", "Pts", "ROI Moyen", "Résidu coût %", "Impact net", "Score combiné"]
COL_WIDTHS = [w * mm for w in (10, 56, 40, 14, 13, 24, 24, 22, 24)]


def compute_ranked() -> list[dict]:
    """Classement complet, toutes armées confondues, avec le rang global stocké
    dans chaque ligne (clé ``rank``) — c'est ce rang, pas la position dans une
    liste éventuellement filtrée, que `render()` affiche en colonne ``#``."""
    with open("scratch/per_unit_nocharge_floor66_TM.json", "r", encoding="utf-8") as f:
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
        "Ce registre croise trois indicateurs indépendants — performance en combat, sous-cotation et "
        "impact réel en partie — en un score unique, pour distinguer les héros <i>vraiment</i> excellents "
        "de ceux qui ne brillent que sur un seul de ces axes. La construction détaillée de chaque "
        "indicateur est donnée page suivante.<br/><br/>"
        + (
            f"Extrait filtré sur {faction} — {n_units} héros. La colonne <b>#</b> conserve le rang du "
            f"registre global ({universe_n} héros toutes armées confondues), pas un reclassement local."
            if faction else
            f"{n_units} héros classés par score décroissant — liste complète (aucune coupe)."
        ),
        cover_body,
    ))

    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, "Méthode — Héros"))
    story.append(PageBreak())
    story.append(Paragraph("Méthode", section_title))
    story.append(Paragraph(
        "Construction des trois indicateurs croisés dans ce registre, puis du score combiné qui en résulte.",
        section_note,
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "<b>Sources</b><br/>Ce registre croise deux évaluations indépendantes du même héros : le "
        "<i>Compendium des Duels — Héros</i> (performance en combat) et le <i>Registre des Anomalies de "
        "Coût — Héros</i> (écart entre coût réel et coût prédit), joints par identifiant interne. Les "
        f"héros dont la prédiction de coût est trop faible (&lt; {MIN_PREDICTED:.0f} pts — un dénominateur "
        "proche de zéro rendrait le résidu relatif peu fiable) sont écartés, comme dans le registre des "
        "coûts lui-même. Voir <i>Panthéon des Champions — Unités</i> pour le pendant troupes, dont le "
        "modèle de coût est ajusté indépendamment — héros et troupes suivent des logiques de prix "
        "différentes.",
        body_text,
    ))
    story.append(Paragraph(
        "<b>1. ROI Moyen</b> — performance brute en combat, sans référence au coût.<br/>Chaque héros "
        "attaquant est confronté en duel d'un round, sans charge et sans renforcement, à toutes les unités "
        "des autres armées, troupes et héros confondus côté défenseur (voir <i>Compendium des Duels — "
        "Héros</i> pour le détail). Pour chaque duel, ROI = pts net / coût en points de l'attaquant, où "
        "pts net = pts détruits chez le défenseur − pts perdus par l'attaquant. La lecture est "
        "volontairement asymétrique : le dégât infligé (A→B) est lu au plancher pessimiste atteint 66% du "
        "temps — une posture prudente à l'attaque — le dégât encaissé en retour (B→A) à l'espérance — une "
        "riposte typique, pas un pire cas. On retient, sur l'ensemble de ces duels, la moyenne de trois "
        "quantiles de la distribution du ROI (planchers Stabilité/Fiabilité/Explosivité, 5e/34e/80e "
        "percentile — voir <i>Compendium des Duels — Héros</i> pour le détail) plutôt que la moyenne brute "
        "du ROI : un seul matchup extrême, très bon ou très mauvais, ne peut alors pas à lui seul tirer "
        "l'indicateur d'un héros par ailleurs quelconque. <i>Rappel : un duel d'un round en un contre un ne "
        "capture ni les sorts/prières, ni les aptitudes de commandement, ni les buffs apportés à d'autres "
        "unités de l'armée — ce ROI Moyen mesure la seule ligne d'armes du héros, pas sa valeur tactique "
        "globale.</i>",
        body_text,
    ))
    story.append(Paragraph(
        "<b>2. Sous-cotation</b> — écart entre ce que le héros coûte réellement et ce qu'il devrait coûter "
        "d'après son profil de combat.<br/>Une régression linéaire (OLS) est ajustée séparément sur les "
        "héros : les points sont expliqués par un plan d'expérience factoriel — dégâts contre trois "
        "défenseurs synthétiques (save 6+, save 4+, et save 2+ dont le carré capte un rendement croissant "
        "au-delà d'un certain seuil), PV effectifs (PV totaux normalisés par la probabilité qu'un coup "
        "passe à la fois la sauvegarde et le ward — une durabilité multiplicative, pas trois effets "
        "additifs séparés), mouvement, contrôle, niveau de sorcier/prêtre et bonus de charge, croisés avec "
        "des facteurs catégoriels (armée, mix d'armement, type d'unité, vol, mot-clé UNIQUE, type de Crit "
        "dominant) — voir <i>cost_model.py</i>/<i>features.py</i> pour le détail des variables, et le "
        "<i>Registre des Anomalies de Coût — Héros</i> pour les coefficients et la qualité d'ajustement. "
        "Résidu = points réels − points prédits ; un résidu <i>négatif</i> signifie que le héros coûte "
        "moins que ne le justifierait son profil (sous-coté, bonne affaire), positif l'inverse. C'est le "
        "résidu <i>relatif</i> (résidu / prédiction) qui est utilisé ici, pour comparer équitablement des "
        "héros de gammes de points différentes.",
        body_text,
    ))
    story.append(Paragraph(
        "<b>3. Impact absolu</b> — combien de points le héros fait réellement basculer en partie, sans "
        "référence à son propre coût.<br/>C'est la moyenne brute des pts net sur l'ensemble des duels — "
        "pas la médiane, et surtout <i>non normalisée</i> par le coût de l'attaquant, contrairement au ROI "
        "et au résidu, tous deux relatifs. Sans cet axe, deux héros au ROI et au résidu identiques se "
        "valent quel que soit leur impact réel en partie : un héros pas cher y arrive mécaniquement plus "
        "vite qu'un héros cher au même profil d'efficacité, puisque ROI et résidu sont l'un et l'autre "
        "divisés par les points du héros.",
        body_text,
    ))
    story.append(Paragraph(
        "<b>4. Score combiné</b> — synthétise les trois indicateurs en un seul critère de tri, sans "
        "laisser aucun des trois dominer les deux autres.<br/>Chacun est centré-réduit (z-score, moyenne "
        "0, écart-type 1) sur la population des héros communs aux deux registres, pour les rendre "
        "comparables malgré des échelles différentes (pourcentage de ROI, pourcentage de résidu, points "
        f"nets bruts). Le score = moyenne pondérée (ROI Moyen ×{ROI_WEIGHT:.0f}, sous-cotation ×1, "
        "impact absolu ×1) de ces trois z-scores, <i>moins</i> un terme de pénalité "
        f"(poids {IMBALANCE_WEIGHT:.1f}) proportionnel à leur semi-déviation pondérée <i>vers le bas</i> — "
        "seules les composantes en dessous de la moyenne pondérée comptent dans la pénalité, à la façon "
        "d'un ratio de Sortino. Sans ce terme, la moyenne serait pleinement compensatoire : un excès sur un "
        "seul axe — par exemple une très forte sous-cotation — pourrait à lui seul propulser en tête un "
        "héros médiocre sur les deux autres. La pénalité coûte des points à toute composante faible par "
        "rapport aux deux autres, sans jamais rogner sur un axe où le héros excelle, ce qui favorise les "
        "profils équilibrés sur les profils extrêmes d'un seul côté. Un score de +1 signifie un héros un "
        "écart-type au-dessus de la moyenne sur ce critère combiné — pas une grandeur physique en soi, un "
        "simple outil de tri.",
        body_text,
    ))

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
                              colored_cols=[(8, score_color)], ranks=[r["rank"] for r in joined]))

    doc.build(story)
    print("PDF genere:", out_path)


if __name__ == "__main__":
    render(compute_ranked(), OUT_PATH)

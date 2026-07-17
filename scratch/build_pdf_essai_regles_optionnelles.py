"""Génère la synthèse PDF des combats par unité, édition « règles optionnelles »
— liste complète, pas de Top N. Miroir de `aospy.reports.combat_unites`, mais
la source vient du scénario --charge none avec les 2 règles optionnelles
actives (tir double + seuil de charge 30%, cf.
scratch/aggregate_regles_optionnelles.py) au lieu du scénario standard
« sans charge » édition TM, et lue au plancher pessimiste 66% de confiance
(au lieu de 80% côté édition TM — lecture plus permissive). Réutilise
`aospy.reports.common` (charte graphique) tel quel ; n'adapte que la source
de données et les textes de méthode. Pendant du "best" :
scratch/best_unites_regles_optionnelles.py.
"""
import json

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from aospy.reports.common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead,
)

COMBAT_JSON = "scratch/output/essai_regles_optionnelles/per_unit_regles_floor66.json"
OUT_PATH = "scratch/output/essai_regles_optionnelles/AoS_unites_duels_regles_optionnelles.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  SYNTHÈSE DES COMBATS PAR UNITÉ  ·  RÈGLES OPTIONNELLES"
SECTION_TITLE = "Compendium des Duels — Unités (règles optionnelles)"

with open(COMBAT_JSON, "r", encoding="utf-8") as f:
    all_rows = json.load(f)
rows = [r for r in all_rows if not r["is_hero"]]

N_UNITS = len(rows)
N_ARMIES = len({r["army"] for r in rows})

HEADER = ["#", "Unité", "Armée", "All.", "Pts",
          "ROI moy.", "Pts net moy.", "Médiane ROI", "% positif", "ROI min", "ROI max"]
COL_WIDTHS = [w * mm for w in (10, 60, 45, 15, 14, 22, 26, 22, 20, 20, 20)]


def fmt_row(rank, r):
    return [
        str(rank),
        r["name"],
        r["army"],
        alliance_badge(r["grand_alliance"]),
        str(r["points"]),
        f"{r['avg_roi_pct']:+.1f}%",
        f"{r['avg_pts_net']:+.1f}",
        f"{r['median_roi_pct']:+.1f}%",
        f"{r['pct_positive']:.0f}%",
        f"{r['min_roi_pct']:+.1f}%",
        f"{r['max_roi_pct']:+.1f}%",
    ]


def roi_color(r):
    return BLOOD_GREEN if r["avg_roi_pct"] >= 0 else BLOOD_RED


doc = build_document(OUT_PATH, "Age of Sigmar — Synthèse des combats par unité (règles optionnelles)", BAND_TEXT)

story = []
story.append(Spacer(1, 26 * mm))
story.append(Paragraph("Compendium des Duels", cover_title))
story.append(Paragraph(
    f"Unités de troupe — {N_ARMIES} armées, {N_UNITS} unités — règles optionnelles",
    cover_subtitle,
))
story.append(Spacer(1, 8 * mm))
story.append(Paragraph(f"Registre établi le {today_str()} — Règles optionnelles", cover_meta))
story.append(Spacer(1, 10 * mm))
story.append(Paragraph(
    "<b>Méthode :</b> chaque unité de troupe attaquante a été confrontée en duel d'un round à toutes "
    f"les unités des autres armées, sans renforcement, <b>aucune charge déclarée par défaut</b> "
    "(<tt>--charge none</tt>) — la charge ne se déclenche plus que via les conditions géométriques des "
    "2 règles optionnelles elles-mêmes (Move/portée). Pour chaque unité sont calculés : le ROI moyen "
    "(retour sur investissement en points), les points nets moyens, la médiane du ROI, le pourcentage "
    "de duels rentables, ainsi que le ROI minimum et maximum observés.<br/><br/>"
    "<b>Règle de dégâts — lecture asymétrique :</b> le dégât infligé par l'unité attaquante (A→B) est lu "
    "au plancher pessimiste atteint 66% du temps (<i>moyenne − 0,4125·écart-type</i>) — une lecture plus "
    "permissive que le plancher 80% de l'édition TM. Le dégât encaissé en retour (B→A) est lu à "
    "l'espérance brute (moyenne) — une riposte « typique », pas un pire cas.<br/><br/>"
    "<b>Pts net</b> = pts détruits chez l'adversaire (au plancher 66%) − pts perdus par l'attaquant (à la "
    "moyenne). <b>ROI</b> = pts net / coût en points de l'unité attaquante.<br/><br/>"
    "<b>Règle « tir double »</b> : entre les deux unités, celle qui a la plus petite portée à distance "
    "(0 si mêlée pure) est réputée chargeuse. Si son Move + charge (+ course, si autorisée) ne couvre pas "
    "la portée de l'autre camp, celui-ci tire deux fois (profils à distance uniquement).<br/>"
    "<b>Règle « seuil de charge 30% »</b> : une unité est considérée chargée — et bénéficie du bonus "
    "intrinsèque <i>Charge (+N)</i> d'une arme — seulement si son Move dépasse celui du défenseur de plus "
    "de 30%, déduit du seul écart de Move (aucune charge déclarée manuellement).<br/><br/>"
    f"<b>{N_UNITS} unités classées</b> par ROI moyen décroissant — liste complète (aucune coupe).",
    cover_body,
))
story.append(NextPageTemplate("Data"))
story.append(SectionMarker(doc, SECTION_TITLE))
story.append(PageBreak())

story.append(Paragraph(SECTION_TITLE, section_title))
story.append(Paragraph(
    "Aucune charge déclarée par défaut ; la charge est entièrement déduite des stats par les 2 règles "
    "optionnelles (tir double + seuil de charge 30%) elles-mêmes.",
    section_note,
))
story.append(Paragraph(f"{N_UNITS} unités classées par ROI moyen décroissant.", subhead))
story.append(Spacer(1, 2))
story.append(ranked_table(HEADER, COL_WIDTHS, rows, fmt_row, lambda r: r["grand_alliance"],
                          colored_cols=[(5, roi_color)]))

doc.build(story)
print("PDF genere:", OUT_PATH)

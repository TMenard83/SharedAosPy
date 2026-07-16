"""Génère la synthèse PDF des combats par unité de troupe (hors héros) —
liste complète, pas de Top N. Voir combat_heros.py pour le pendant
héros. Source : scratch/per_unit_nocharge_TM.json (reports/aggregate.py)."""
import json

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from .common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead,
)

OUT_PATH = "scratch/output/AoS_unites_duels_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  SYNTHÈSE DES COMBATS PAR UNITÉ  ·  ÉD. TM"
SECTION_TITLE = "Compendium des Duels — Unités"

with open("scratch/per_unit_nocharge_TM.json", "r", encoding="utf-8") as f:
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


doc = build_document(OUT_PATH, "Age of Sigmar — Synthèse des combats par unité (TM)", BAND_TEXT)

story = []
story.append(Spacer(1, 26 * mm))
story.append(Paragraph("Compendium des Duels", cover_title))
story.append(Paragraph(
    f"Unités de troupe — {N_ARMIES} armées, {N_UNITS} unités — édition TM",
    cover_subtitle,
))
story.append(Spacer(1, 8 * mm))
story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
story.append(Spacer(1, 10 * mm))
story.append(Paragraph(
    "<b>Méthode :</b> chaque unité de troupe attaquante a été confrontée en duel d'un round à toutes "
    f"les unités des autres armées (héros compris côté défenseur), sans renforcement, sans charge — "
    "voir le registre séparé <i>Panthéon des Héros</i> pour les unités héros en tant qu'attaquantes. "
    "Pour chaque unité sont calculés : le ROI moyen (retour sur investissement en points), les points "
    "nets moyens, la médiane du ROI, le pourcentage de duels rentables, ainsi que le ROI minimum et "
    "maximum observés.<br/><br/>"
    "<b>Règle de dégâts — lecture asymétrique :</b> le dégât infligé par l'unité attaquante (A→B) est lu "
    "au plancher pessimiste atteint 80% du temps (<i>moyenne − 0,8416·écart-type</i>) — ce qu'on peut "
    "raisonnablement « garantir » en attaquant. Le dégât encaissé en retour (B→A) est lu à l'espérance "
    "brute (moyenne) — une riposte « typique », pas un pire cas. Cette asymétrie reflète une posture "
    "prudente à l'attaque, réaliste en défense.<br/><br/>"
    "<b>Pts net</b> = pts détruits chez l'adversaire (au plancher 80%) − pts perdus par l'attaquant (à la "
    "moyenne). <b>ROI</b> = pts net / coût en points de l'unité attaquante.<br/><br/>"
    "Aucun bonus de charge universel n'existe en AoS4 — seuls certains profils d'arme (typiquement de "
    "la cavalerie) portent un bonus propre à leur texte d'aptitude (le plus souvent <i>Charge (+1 "
    "Dégât)</i>) ; ce registre ne modélise donc que le scénario sans charge, qui ne diffère du scénario "
    "chargé que pour cette poignée de profils.<br/><br/>"
    f"<b>{N_UNITS} unités classées</b> par ROI moyen décroissant — liste complète (aucune coupe).<br/><br/>"
    "<i>Note : Beasts of Chaos et Bonesplitterz ne comptent aucune unité — profils Warhammer Legends, "
    "exclus de l'import.</i>",
    cover_body,
))
story.append(NextPageTemplate("Data"))
story.append(SectionMarker(doc, SECTION_TITLE))
story.append(PageBreak())

story.append(Paragraph(SECTION_TITLE, section_title))
story.append(Paragraph(
    "L'unité attaquante ne charge pas (combat prolongé ou unité déjà engagée) ; le défenseur non plus.",
    section_note,
))
story.append(Paragraph(f"{N_UNITS} unités classées par ROI moyen décroissant.", subhead))
story.append(Spacer(1, 2))
story.append(ranked_table(HEADER, COL_WIDTHS, rows, fmt_row, lambda r: r["grand_alliance"],
                          colored_cols=[(5, roi_color)]))

doc.build(story)
print("PDF genere:", OUT_PATH)

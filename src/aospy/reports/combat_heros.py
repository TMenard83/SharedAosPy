"""Génère la synthèse PDF des combats par héros (unité attaquante is_hero) —
liste complète, pas de Top N. Pendant de combat_unites.py.
Source : scratch/per_unit_nocharge_floor66_TM.json (reports/aggregate.py, --include-heroes)."""
import json

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from .common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead, body_text,
)

OUT_PATH = "scratch/output/AoS_heros_duels_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  SYNTHÈSE DES COMBATS PAR HÉROS  ·  ÉD. TM"
SECTION_TITLE = "Compendium des Duels — Héros"

with open("scratch/per_unit_nocharge_floor66_TM.json", "r", encoding="utf-8") as f:
    all_rows = json.load(f)
rows = [r for r in all_rows if r["is_hero"]]
rows.sort(key=lambda r: r["avg_floor_roi_pct"], reverse=True)

N_UNITS = len(rows)
N_ARMIES = len({r["army"] for r in rows})

HEADER = ["#", "Héros", "Armée", "All.", "Pts",
          "ROI Stabilité\n(95)", "ROI Fiabilité\n(66)", "ROI Explosivité\n(20)", "ROI Moyen",
          "Pts net moy.", "% positif"]
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


doc = build_document(OUT_PATH, "Age of Sigmar — Synthèse des combats par héros (TM)", BAND_TEXT)

story = []
story.append(Spacer(1, 26 * mm))
story.append(Paragraph("Compendium des Duels", cover_title))
story.append(Paragraph(
    f"Héros — {N_ARMIES} armées, {N_UNITS} héros — édition TM",
    cover_subtitle,
))
story.append(Spacer(1, 8 * mm))
story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
story.append(Spacer(1, 10 * mm))
story.append(Paragraph(
    "Ce registre confronte chaque héros attaquant, en duel d'un round, à toutes les unités des autres "
    "armées — cinq indicateurs indépendants en résultent, décrits en détail page suivante. La construction "
    "du duel lui-même (asymétrie du dégât, absence de charge) y est également détaillée.<br/><br/>"
    f"<b>{N_UNITS} héros classés</b> par ROI Moyen décroissant — liste complète (aucune coupe).",
    cover_body,
))

story.append(NextPageTemplate("Data"))
story.append(SectionMarker(doc, "Méthode — Héros"))
story.append(PageBreak())
story.append(Paragraph("Méthode", section_title))
story.append(Paragraph(
    "Construction du duel, puis des cinq indicateurs qui en sont tirés pour chaque héros.",
    section_note,
))
story.append(Spacer(1, 2 * mm))
story.append(Paragraph(
    "<b>Protocole du duel</b><br/>Chaque héros attaquant est confronté en duel d'un round, sans charge et "
    "sans renforcement, à toutes les unités des autres armées, troupes et héros confondus côté défenseur "
    "— voir <i>Compendium des Duels — Unités</i> pour le pendant troupes en tant qu'attaquantes. La lecture "
    "du dégât est volontairement asymétrique : le dégât infligé par le héros (A→B) est lu au plancher "
    "pessimiste atteint 66% du temps (<i>lu directement sur la distribution exacte des dégâts, par "
    "convolution — pas une approximation gaussienne</i>) — une posture prudente à "
    "l'attaque, ce qu'on peut raisonnablement « garantir » — tandis que le dégât encaissé en retour (B→A) "
    "est lu à l'espérance brute (moyenne) — une riposte typique, pas un pire cas. <b>Pts net</b> = pts "
    "détruits chez le défenseur (à ce plancher 66%) − pts perdus par l'attaquant (à la moyenne). <b>ROI</b> "
    "= pts net / coût en points du héros attaquant. Aucun bonus de charge universel n'existe en AoS4 — "
    "seuls certains profils d'arme portent un bonus propre à leur texte d'aptitude (typiquement <i>Charge "
    "(+1 Dégât)</i> sur de la cavalerie). Ce registre ne <i>déclare</i> aucune charge, mais deux règles "
    "optionnelles, actives par défaut, peuvent malgré tout en simuler les effets : le <i>seuil de charge</i> "
    "déduit l'état chargé du seul écart de Move — l'attaquant est réputé chargé (bonus d'arme inclus) dès "
    "que son Move dépasse celui du défenseur de plus de 30%, sans qu'aucune charge n'ait été demandée — et "
    "le <i>tir double</i> multiplie par 1,5 le dégât à distance du camp le plus véloce des deux si l'autre, "
    "plus court de portée, ne peut le rejoindre même en chargeant. Un héros rapide ou véloce à distance peut "
    "donc bénéficier d'un bonus dans ce registre malgré le « sans charge » du protocole. <i>Rappel : un duel "
    "d'un round en un "
    "contre un ne capture ni les sorts/prières, ni les aptitudes de commandement, ni les buffs apportés à "
    "d'autres unités de l'armée — ces cinq indicateurs mesurent la seule ligne d'armes du héros, pas sa "
    "valeur tactique globale.</i>",
    body_text,
))
story.append(Paragraph(
    "<b>1. ROI Moyen</b> — critère de tri de ce registre.<br/>Moyenne simple des trois planchers ROI "
    "Stabilité / Fiabilité / Explosivité décrits au point 2 — chacun un quantile de la distribution du ROI "
    "sur l'ensemble des duels du héros contre le champ défenseur, à un seuil différent (5e / 34e / 80e "
    "percentile). Un résumé unique de cette distribution, sans se reposer sur un seul de ces trois seuils "
    "isolément : un seul matchup extrême, très bon ou très mauvais, pèse ainsi moins lourd que dans une "
    "moyenne brute du ROI (non retenue ici) sur l'indicateur d'un héros par ailleurs quelconque.",
    body_text,
))
story.append(Paragraph(
    "<b>2. ROI Stabilité / Fiabilité / Explosivité</b> — trois seuils de cette même distribution, à titre "
    "indicatif.<br/>Un axe orthogonal au plancher 66% du dégât A→B ci-dessus : ce dernier lit le dégât "
    "<i>à l'intérieur</i> d'un seul duel (variance des dés), ces trois quantiles lisent le ROI <i>entre</i> "
    "les duels (variance du champ défenseur). Stabilité est le 5e percentile (dépassé dans 95% des duels — "
    "un pire cas quasi-garanti, y compris contre le pire matchup du champ défenseur), Fiabilité est le 34e "
    "percentile (dépassé dans 66% des duels — un plancher pessimiste plus permissif, sur lequel on peut "
    "compter dans la majorité des matchups), Explosivité est le 80e percentile (dépassé dans seulement 20% "
    "des duels — un plafond optimiste, atteint face à des matchups favorables). Un héros dont les trois "
    "valeurs sont proches performe de façon constante ; un grand écart entre Stabilité et Explosivité "
    "trahit un héros à matchups très polarisés — excellent contre certains profils, faible contre d'autres "
    "— que le seul ROI Moyen ne révèle pas.",
    body_text,
))
story.append(Paragraph(
    "<b>3. Pts net moyen</b> — impact absolu, sans référence au coût du héros.<br/>La moyenne brute des "
    "pts net sur l'ensemble des duels — pas la médiane, et surtout non normalisée par le coût de "
    "l'attaquant, contrairement au ROI. Deux héros au ROI identique n'ont pas nécessairement le même "
    "impact réel en partie : un héros pas cher atteint mécaniquement le même ROI% avec un pts net plus "
    "faible qu'un héros cher au même profil d'efficacité, puisque le ROI est lui-même divisé par les "
    "points du héros. Voir <i>Panthéon des Champions — Héros</i>, dont le score combiné retient cet axe "
    "comme composante à part entière.",
    body_text,
))
story.append(Paragraph(
    "<b>4. % positif</b> — proportion des duels rentables.<br/>Pourcentage des duels contre le champ "
    "défenseur où le pts net est strictement positif (le héros « gagne » l'échange en points). Un "
    "complément au ROI Moyen : deux héros à ROI Moyen comparable peuvent avoir un profil de risque "
    "très différent — l'un rentable dans l'écrasante majorité de ses matchups, l'autre ne compensant des "
    "défaites fréquentes que par quelques très bons résultats.",
    body_text,
))

story.append(SectionMarker(doc, SECTION_TITLE))
story.append(PageBreak())

story.append(Paragraph(SECTION_TITLE, section_title))
story.append(Paragraph(
    "Le héros attaquant ne charge pas (combat prolongé ou unité déjà engagée) ; le défenseur non plus.",
    section_note,
))
story.append(Paragraph(f"{N_UNITS} héros classés par ROI Moyen décroissant.", subhead))
story.append(Spacer(1, 2))
story.append(ranked_table(HEADER, COL_WIDTHS, rows, fmt_row, lambda r: r["grand_alliance"],
                          colored_cols=[(8, roi_color)]))

doc.build(story)
print("PDF genere:", OUT_PATH)

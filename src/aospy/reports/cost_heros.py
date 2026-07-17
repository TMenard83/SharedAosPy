"""Génère le PDF des héros classés par écart au coût, d'après le plan
d'expérience factoriel ajusté sur TOUTE la population (héros + troupes,
`cost_model.fit_cost_model_factorial`) avec des termes d'interaction
`C(is_hero):...`. Pendant de cost_unites.py, qui utilise le même
modèle — voir sa docstring pour la justification de ce choix face à deux
régressions séparées (`fit_segmented`)."""
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from ..persistence import db, repository
from ..analysis import cost_model
from .common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead,
)
from .cost_common import coef_table

MIN_PREDICTED = 40.0
OUT_PATH = "scratch/output/AoS_heros_prix_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  HÉROS SOUS-COTÉS  ·  ÉD. TM"

con = db.connect()
frame = cost_model.feature_frame(con)
result = cost_model.fit_cost_model_factorial(con, frame=frame.copy())
hero_ids = set(frame.loc[frame["is_hero"], "unit_id"])
pool = [r for r in result.residuals if r.predicted >= MIN_PREDICTED and r.unit_id in hero_ids]
undercosted = sorted(pool, key=lambda r: r.residual_pct)
armies = {a.id: a for a in repository.list_armies(con)}
con.close()

HEADER = ["#", "Héros", "Armée", "All.", "Pts réels", "Pts prédits", "Résidu", "Résidu %"]
COL_WIDTHS = [w * mm for w in (10, 65, 48, 18, 22, 24, 22, 22)]


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
    return BLOOD_GREEN if r.residual < 0 else BLOOD_RED


doc = build_document(OUT_PATH, "Age of Sigmar — Héros les plus sous-cotés (TM)", BAND_TEXT)

SECTION_TITLE_COEF = "Coefficients du Modèle — Héros"
SECTION_TITLE = "Registre des Anomalies de Coût — Héros"

story = []
story.append(Spacer(1, 12 * mm))
story.append(Paragraph("Registre des Anomalies de Coût", cover_title))
story.append(Paragraph(
    f"Héros — les {len(undercosted)} héros classés par écart au coût — édition TM",
    cover_subtitle,
))
story.append(Spacer(1, 6 * mm))
story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
story.append(Spacer(1, 6 * mm))
story.append(Paragraph(
    "<b>Méthode :</b> régression linéaire (OLS) des points sur un plan d'expérience factoriel — "
    "variables continues (taille d'unité et son carré, dégât à distance vs aucune save, dégât perçant vs save 2+ "
    "et son carré, bonus de dégât de charge, PV effectifs [PV totaux "
    "normalisés par la probabilité qu'un coup passe la save ET le ward, la save nue étant dégradée d'un "
    "Rend représentatif de 1 — moyenne observée sur les profils d'arme de la base — puisque cette "
    "caractéristique n'a pas d'attaquant précis ; le Ward, jamais modifié par le Rend, reste nu], "
    "contrôle, niveau de "
    "sorcier/prêtre Wizard(N)/Priest(N)) — le mouvement et l'irrégularité du dégât vs save 4+ ont été retirés "
    "par élimination arrière (aucun effet-prix détectable une fois les autres prédicteurs présents, cf. "
    "<i>analysis/experiments/backward_elimination.py</i>) — croisées avec des facteurs catégoriels (armée d'appartenance, "
    "rôle héros/troupe, mix d'armement mêlée/distance/mixte, type d'unité infanterie/cavalerie/monstre/"
    "machine de guerre/bête, mot-clé de vol, UNIQUE, type de Crit dominant) — voir "
    "<i>features.py</i>/<i>cost_model.py</i>, <i>fit_cost_model_factorial</i>. Le pool de dégâts brut "
    "(avant save/ward) ne retient que sa composante à distance : la composante mêlée s'est révélée sans "
    "effet-prix propre une fois les autres prédicteurs présents (cf. "
    "<i>analysis/experiments/melee_ranged_split.py</i>) et a été retirée. "
    "<b>Ce modèle est ajusté sur l'ensemble héros + troupes en une seule régression</b>, avec un terme "
    "d'interaction <i>Héros × PV effectifs</i> qui laisse le prix de la durabilité varier selon le rôle "
    "— sans dupliquer tous les autres facteurs (armée, armement, type…) dans deux régressions distinctes. "
    "Un essai des deux régressions "
    "séparées (<i>fit_segmented</i>) a été écarté : sur cette base, il dégrade le R² côté troupes "
    "(0,82 contre 0,91 pour le modèle unique) sans gain côté héros — deux populations plus petites "
    "estiment moins bien les ~25 coefficients d'armée que la population complète. Cette page ne "
    "présente donc que les héros, mais le tableau de coefficients page suivante est celui du modèle "
    "unique — identique à celui du registre <i>Anomalies de Coût — Unités</i>. Base BattleScribe "
    "(<i>aospy import bsdata --all</i>), plus à jour actuellement que la source Wahapedia. "
    f"R = {result.r_squared**0.5:.3f}, R² = {result.r_squared:.3f}, "
    f"R² ajusté = {result.adj_r_squared:.3f}, n = {result.n_obs} unités (héros + troupes).<br/><br/>"
    "<b>Prudence :</b> certaines armées comptent très peu de héros importés — leur coefficient d'armée "
    "a alors un fort effet de levier et est moins fiable que celui d'une faction bien peuplée en "
    "héros.<br/><br/>"
    "<b>Résidu</b> = points réels − points prédits par le modèle. Un résidu négatif signifie que le "
    "héros coûte <i>moins</i> que ce que son profil de combat justifierait — une sous-cotation, donc "
    "une bonne affaire en points ; un résidu positif signifie l'inverse (sur-cotation). Le classement "
    "ci-après trie sur le résidu <i>relatif</i> (résidu / prédiction), pour comparer équitablement des "
    "héros de gammes de points différentes ; les héros dont la prédiction est trop faible "
    f"(&lt; {MIN_PREDICTED:.0f} pts, dénominateur peu fiable) sont écartés.<br/><br/>"
    "Le détail des coefficients est donné page suivante.",
    cover_body,
))

story.append(NextPageTemplate("Data"))
story.append(SectionMarker(doc, SECTION_TITLE_COEF))
story.append(PageBreak())
story.append(Paragraph(SECTION_TITLE_COEF, section_title))
story.append(Paragraph(
    "Points par unité de caractéristique, ceteris paribus ; les facteurs catégoriels sont exprimés par "
    "rapport à une modalité de référence. « Rôle : Héros » est le supplément de base pour un héros "
    "(toutes autres caractéristiques égales) ; « Héros × PV effectifs » module, en plus, le prix de la "
    "durabilité spécifiquement pour les héros.",
    section_note,
))
story.append(Spacer(1, 2 * mm))
story.append(coef_table(result))

story.append(SectionMarker(doc, SECTION_TITLE))
story.append(PageBreak())
story.append(Paragraph(SECTION_TITLE, section_title))
story.append(Paragraph(
    "Tous les héros, triés par résidu relatif croissant (le plus négatif en tête, les meilleures "
    "affaires en points) jusqu'au plus sur-coté en fin de tableau.",
    section_note,
))
story.append(Paragraph(f"{len(undercosted)} héros.", subhead))
story.append(Spacer(1, 2))
story.append(ranked_table(HEADER, COL_WIDTHS, undercosted, fmt_row, alliance_of,
                          colored_cols=[(6, resid_color), (7, resid_color)], font_size=8))

doc.build(story)
print("PDF genere:", OUT_PATH)

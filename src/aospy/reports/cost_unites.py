"""Génère le PDF des unités de troupe (hors héros) classées par écart au coût,
d'après le plan d'expérience factoriel ajusté sur TOUTE la population (héros +
troupes, `cost_model.fit_cost_model_factorial`) avec des termes d'interaction
`C(is_hero):...`. Pendant de cost_heros.py, qui utilise le même
modèle : une régression unique évite de dupliquer les facteurs communs
(armée, armement, type…) dans deux régressions séparées — voir
`cost_heros.py` pour le comparatif de R² qui a motivé
l'abandon de `fit_segmented` (deux régressions indépendantes) pour ce plan
factoriel unique."""
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
OUT_PATH = "scratch/output/AoS_unites_prix_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  UNITÉS SOUS-COTÉES  ·  ÉD. TM"

con = db.connect()
frame = cost_model.feature_frame(con)
result = cost_model.fit_cost_model_factorial(con, frame=frame.copy())
troupe_ids = set(frame.loc[~frame["is_hero"], "unit_id"])
pool = [r for r in result.residuals if r.predicted >= MIN_PREDICTED and r.unit_id in troupe_ids]
undercosted = sorted(pool, key=lambda r: r.residual_pct)
armies = {a.id: a for a in repository.list_armies(con)}
con.close()

HEADER = ["#", "Unité", "Armée", "All.", "Pts réels", "Pts prédits", "Résidu", "Résidu %"]
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
    # résidu négatif = sous-coté = bonne affaire (vert) ; positif = sur-coté (rouge)
    return BLOOD_GREEN if r.residual < 0 else BLOOD_RED


doc = build_document(OUT_PATH, "Age of Sigmar — Unités les plus sous-cotées (TM)", BAND_TEXT)

SECTION_TITLE_COEF = "Coefficients du Modèle — Unités"
SECTION_TITLE = "Registre des Anomalies de Coût — Unités"

story = []
story.append(Spacer(1, 12 * mm))
story.append(Paragraph("Registre des Anomalies de Coût", cover_title))
story.append(Paragraph(
    f"Unités de troupe — les {len(undercosted)} unités classées par écart au coût — édition TM",
    cover_subtitle,
))
story.append(Spacer(1, 6 * mm))
story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
story.append(Spacer(1, 6 * mm))
story.append(Paragraph(
    "<b>Méthode :</b> régression linéaire (OLS) des points sur un plan d'expérience factoriel — "
    "variables continues (dégâts contre trois défenseurs synthétiques : aucune save, save 4+, save 2+, "
    "points de vie totaux, sauvegarde, ward, mouvement, contrôle, taille d'unité, niveau de sorcier/"
    "prêtre Wizard(N)/Priest(N)) croisées avec des facteurs catégoriels (armée d'appartenance, rôle "
    "héros/troupe, mix d'armement mêlée/distance/mixte, type d'unité infanterie/cavalerie/monstre/"
    "machine de guerre/bête, mot-clé de vol, UNIQUE, type de Crit dominant) — voir "
    "<i>features.py</i>/<i>cost_model.py</i>, <i>fit_cost_model_factorial</i>. "
    "<b>Ce modèle est ajusté sur l'ensemble héros + troupes en une seule régression</b>, avec des "
    "termes d'interaction <i>Héros × dégât vs aucune save</i> et <i>Héros × PV totaux</i> qui laissent "
    "le prix des dégâts et de la durabilité varier selon le rôle, sans dupliquer tous les autres "
    "facteurs (armée, armement, type…) dans deux régressions distinctes. Un essai de deux régressions "
    "séparées héros/troupes (<i>fit_segmented</i>) a été écarté : sur cette base, il dégrade nettement "
    "le R² côté troupes (0,82 contre 0,91 pour le modèle unique) — une population de 353 unités estime "
    "moins bien les ~25 coefficients d'armée que la population complète de 712. Cette page ne présente "
    "que les unités de troupe, mais le tableau de coefficients page suivante est celui du modèle "
    "unique — identique à celui du registre <i>Anomalies de Coût — Héros</i>. Base BattleScribe "
    "(<i>aospy import bsdata --all</i>), plus à jour actuellement que la source Wahapedia. "
    f"R = {result.r_squared**0.5:.3f}, R² = {result.r_squared:.3f}, "
    f"R² ajusté = {result.adj_r_squared:.3f}, n = {result.n_obs} unités (héros + troupes).<br/><br/>"
    "<b>Résidu</b> = points réels − points prédits par le modèle. Un résidu négatif signifie que "
    "l'unité coûte <i>moins</i> que ce que son profil de combat justifierait — une sous-cotation, donc "
    "une bonne affaire en points ; un résidu positif signifie l'inverse (sur-cotation). Le classement "
    "ci-après trie sur le résidu <i>relatif</i> (résidu / prédiction), pour comparer équitablement des "
    "unités de gammes de points différentes ; les unités dont la prédiction est trop faible "
    f"(&lt; {MIN_PREDICTED:.0f} pts, dénominateur peu fiable) sont écartées.<br/><br/>"
    "Le détail des coefficients est donné page suivante.",
    cover_body,
))

story.append(NextPageTemplate("Data"))
story.append(SectionMarker(doc, SECTION_TITLE_COEF))
story.append(PageBreak())
story.append(Paragraph(SECTION_TITLE_COEF, section_title))
story.append(Paragraph(
    "Points par unité de caractéristique, ceteris paribus ; les facteurs catégoriels sont exprimés par "
    "rapport à une modalité de référence.",
    section_note,
))
story.append(Spacer(1, 2 * mm))
story.append(coef_table(result))

story.append(SectionMarker(doc, SECTION_TITLE))
story.append(PageBreak())
story.append(Paragraph(SECTION_TITLE, section_title))
story.append(Paragraph(
    "Toutes les unités de troupe, triées par résidu relatif croissant (le plus négatif en tête, les "
    "meilleures affaires en points) jusqu'au plus sur-coté en fin de tableau.",
    section_note,
))
story.append(Paragraph(f"{len(undercosted)} unités.", subhead))
story.append(Spacer(1, 2))
story.append(ranked_table(HEADER, COL_WIDTHS, undercosted, fmt_row, alliance_of,
                          colored_cols=[(6, resid_color), (7, resid_color)], font_size=8))

doc.build(story)
print("PDF genere:", OUT_PATH)

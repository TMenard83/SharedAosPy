"""Décline le « Panthéon des Champions » (best_heros.py/best_unites.py) par
faction : un PDF par armée dans `scratch/output/<armée>/`, mêlant héros et
unités de troupe dans un seul classement trié par score combiné — les deux
registres partagent la même formule de score (mêmes poids ROI_WEIGHT/
IMBALANCE_WEIGHT/IMPACT_WEIGHT, cf. best_heros.py/best_unites.py), seul le
modèle de coût sous-jacent diffère (régression ajustée séparément sur chaque
population), donc les scores restent comparables entre les deux.

Contrairement aux registres globaux (rang = position dans LE classement
héros ou LE classement unités), la colonne ``#`` ici est un rang *local* : la
position dans ce classement mixte propre à la faction, recalculé après fusion
— un rang global héros et un rang global unités viennent d'espaces de
classement différents, les juxtaposer sans fusion n'aurait pas de sens."""
import os

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, NextPageTemplate, PageBreak

from . import best_heros, best_unites
from .common import (
    build_document, ranked_table, SectionMarker, today_str,
    alliance_badge, BLOOD_GREEN, BLOOD_RED,
    cover_title, cover_subtitle, cover_meta, cover_body, section_title, section_note, subhead, body_text,
)

BAND_TEXT = "AGE OF SIGMAR  ·  MEILLEURS PROFILS (COMBAT × COÛT)  ·  ÉD. TM"
SECTION_TITLE = "Panthéon des Champions"
OUT_FILENAME = "AoS_meilleurs_TM.pdf"

HEADER = ["#", "Nom", "Type", "Armée", "All.", "Pts", "ROI Moyen", "Résidu coût %", "Impact net", "Score combiné"]
COL_WIDTHS = [w * mm for w in (9, 48, 15, 34, 13, 12, 21, 22, 20, 22)]


def fmt_row(rank, r):
    return [
        str(rank), r["name"], r["kind"], r["army"], alliance_badge(r["grand_alliance"]), str(r["points"]),
        f"{r['avg_floor_roi_pct']:+.1f}%", f"{r['residual_pct']:+.0f}%",
        f"{r['avg_pts_net']:+.1f}", f"{r['score']:+.2f}",
    ]


def score_color(r):
    return BLOOD_GREEN if r["score"] >= 0 else BLOOD_RED


def _combined_for_faction(hero_rows: list[dict], unit_rows: list[dict], faction: str) -> list[dict]:
    combined = [dict(r, kind="Héros") for r in hero_rows if r["army"] == faction]
    combined += [dict(r, kind="Unité") for r in unit_rows if r["army"] == faction]
    combined.sort(key=lambda r: r["score"], reverse=True)
    for rank, r in enumerate(combined, start=1):
        r["rank"] = rank
    return combined


def render(joined: list[dict], out_path: str, *, faction: str, universe_heroes: int, universe_units: int) -> None:
    n_profiles = len(joined)
    n_heroes = sum(1 for r in joined if r["kind"] == "Héros")
    n_units = n_profiles - n_heroes

    doc = build_document(out_path, f"Age of Sigmar — {faction}, meilleurs profils (TM)", BAND_TEXT)

    story = []
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph("Panthéon des Champions", cover_title))
    story.append(Paragraph(
        f"{faction} — {n_profiles} profils ({n_heroes} héros, {n_units} unités de troupe) — édition TM",
        cover_subtitle,
    ))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"Registre établi le {today_str()} — Édition TM", cover_meta))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "Ce registre croise trois indicateurs indépendants — performance en combat, sous-cotation et "
        "impact réel en partie — en un score unique, pour distinguer les profils <i>vraiment</i> "
        "excellents de ceux qui ne brillent que sur un seul de ces axes. Héros et unités de troupe sont "
        "mêlés dans un seul classement : les deux suivent la même formule de score (mêmes poids), même si "
        "leur modèle de coût sous-jacent est ajusté séparément (logiques de prix différentes). La "
        "construction détaillée de chaque indicateur est donnée page suivante.<br/><br/>"
        f"Extrait de {faction} sur les deux registres globaux — {universe_heroes} héros et "
        f"{universe_units} unités de troupe toutes armées confondues. La colonne <b>#</b> est un rang "
        "<i>local</i> à ce classement mixte, pas le rang du registre global d'origine.",
        cover_body,
    ))

    story.append(NextPageTemplate("Data"))
    story.append(SectionMarker(doc, "Méthode"))
    story.append(PageBreak())
    story.append(Paragraph("Méthode", section_title))
    story.append(Paragraph(
        "Construction des trois indicateurs croisés dans ce registre, puis du score combiné qui en résulte.",
        section_note,
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "<b>Sources</b><br/>Ce registre croise deux évaluations indépendantes de chaque profil : le "
        "<i>Compendium des Duels</i> (performance en combat) et le <i>Registre des Anomalies de Coût</i> "
        "(écart entre coût réel et coût prédit), joints par identifiant interne. Le modèle de coût est "
        "ajusté séparément sur les héros et sur les unités de troupe — voir <i>Panthéon des Champions — "
        "Héros</i>/<i>Unités</i> (registres globaux) pour le détail complet de chaque régression. Les "
        f"profils dont la prédiction de coût est trop faible (&lt; {best_heros.MIN_PREDICTED:.0f} pts — un "
        "dénominateur proche de zéro rendrait le résidu relatif peu fiable) sont écartés, comme dans les "
        "registres de coût eux-mêmes.",
        body_text,
    ))
    story.append(Paragraph(
        "<b>1. ROI Moyen</b> — performance brute en combat, sans référence au coût.<br/>Chaque attaquant "
        "est confronté en duel d'un round, sans charge et sans renforcement, à toutes les unités des autres "
        "armées, troupes et héros confondus côté défenseur. Pour chaque duel, ROI = pts net / coût en "
        "points de l'attaquant, où pts net = pts détruits chez le défenseur − pts perdus par l'attaquant. "
        "La lecture est volontairement asymétrique : le dégât infligé (A→B) est lu au plancher pessimiste "
        "atteint 66% du temps — une posture prudente à l'attaque — le dégât encaissé en retour (B→A) à "
        "l'espérance — une riposte typique, pas un pire cas. On retient, sur l'ensemble de ces duels, la "
        "moyenne de trois quantiles de la distribution du ROI (planchers Stabilité/Fiabilité/Explosivité, "
        "5e/34e/80e percentile) plutôt que la moyenne brute du ROI : un seul matchup extrême, très bon ou "
        "très mauvais, ne peut alors pas à lui seul tirer l'indicateur d'un profil par ailleurs quelconque. "
        "<i>Rappel : un duel d'un round en un contre un ne capture ni les sorts/prières, ni les aptitudes de "
        "commandement, ni les buffs apportés à d'autres unités de l'armée — ce ROI Moyen mesure la seule "
        "ligne d'armes du profil, pas sa valeur tactique globale.</i>",
        body_text,
    ))
    story.append(Paragraph(
        "<b>2. Sous-cotation</b> — écart entre ce que le profil coûte réellement et ce qu'il devrait coûter "
        "d'après son profil de combat.<br/>Une régression linéaire (OLS) est ajustée séparément sur les "
        "héros et sur les unités de troupe : les points sont expliqués par un plan d'expérience factoriel — "
        "dégâts contre trois défenseurs synthétiques (save 6+, save 4+, et save 2+ dont le carré capte un "
        "rendement croissant au-delà d'un certain seuil), PV effectifs, mouvement, contrôle, niveau de "
        "sorcier/prêtre et bonus de charge, croisés avec des facteurs catégoriels (armée, mix d'armement, "
        "type d'unité, vol, mot-clé UNIQUE, type de Crit dominant) — voir <i>cost_model.py</i>/"
        "<i>features.py</i> pour le détail des variables. Résidu = points réels − points prédits ; un "
        "résidu <i>négatif</i> signifie que le profil coûte moins que ne le justifierait son profil de "
        "combat (sous-coté, bonne affaire), positif l'inverse. C'est le résidu <i>relatif</i> (résidu / "
        "prédiction) qui est utilisé ici, pour comparer équitablement des profils de gammes de points "
        "différentes.",
        body_text,
    ))
    story.append(Paragraph(
        "<b>3. Impact absolu</b> — combien de points le profil fait réellement basculer en partie, sans "
        "référence à son propre coût.<br/>C'est la moyenne brute des pts net sur l'ensemble des duels — "
        "pas la médiane, et surtout <i>non normalisée</i> par le coût de l'attaquant, contrairement au ROI "
        "et au résidu, tous deux relatifs. Sans cet axe, deux profils au ROI et au résidu identiques se "
        "valent quel que soit leur impact réel en partie : un profil pas cher y arrive mécaniquement plus "
        "vite qu'un profil cher au même profil d'efficacité, puisque ROI et résidu sont l'un et l'autre "
        "divisés par les points.",
        body_text,
    ))
    story.append(Paragraph(
        "<b>4. Score combiné</b> — synthétise les trois indicateurs en un seul critère de tri, sans "
        "laisser aucun des trois dominer les deux autres.<br/>Chacun est centré-réduit (z-score, moyenne "
        "0, écart-type 1) séparément sur la population des héros et sur celle des unités de troupe (chacune "
        "commune aux deux registres croisés), pour les rendre comparables malgré des échelles différentes "
        "(pourcentage de ROI, pourcentage de résidu, points nets bruts) — héros et unités de troupe "
        "utilisent ensuite exactement la même formule de pondération, ce qui permet de les mêler dans ce "
        f"classement unique. Le score = moyenne pondérée (ROI Moyen ×{best_heros.ROI_WEIGHT:.0f}, "
        "sous-cotation ×1, impact absolu ×1) de ces trois z-scores, <i>moins</i> un terme de pénalité "
        f"(poids {best_heros.IMBALANCE_WEIGHT:.1f}) proportionnel à leur semi-déviation pondérée <i>vers le "
        "bas</i> — seules les composantes en dessous de la moyenne pondérée comptent dans la pénalité, à la "
        "façon d'un ratio de Sortino. Sans ce terme, la moyenne serait pleinement compensatoire : un excès "
        "sur un seul axe — par exemple une très forte sous-cotation — pourrait à lui seul propulser en tête "
        "un profil médiocre sur les deux autres. La pénalité coûte des points à toute composante faible par "
        "rapport aux deux autres, sans jamais rogner sur un axe où le profil excelle, ce qui favorise les "
        "profils équilibrés sur les profils extrêmes d'un seul côté. Un score de +1 signifie un profil un "
        "écart-type au-dessus de la moyenne (de sa propre population héros/troupe) sur ce critère combiné — "
        "pas une grandeur physique en soi, un simple outil de tri.",
        body_text,
    ))

    story.append(SectionMarker(doc, SECTION_TITLE))
    story.append(PageBreak())
    story.append(Paragraph(SECTION_TITLE, section_title))
    story.append(Paragraph(
        "Héros et unités de troupe mêlés, triés par score combiné décroissant (meilleur compromis "
        "performance/coût en tête).",
        section_note,
    ))
    story.append(Paragraph(f"{n_profiles} profils.", subhead))
    story.append(Spacer(1, 2))
    story.append(ranked_table(HEADER, COL_WIDTHS, joined, fmt_row, lambda r: r["grand_alliance"],
                              colored_cols=[(9, score_color)], ranks=[r["rank"] for r in joined]))

    doc.build(story)
    print("PDF genere:", out_path)


def _write_by_faction(hero_ranked: list[dict], unit_ranked: list[dict]) -> None:
    factions = {r["army"] for r in hero_ranked} | {r["army"] for r in unit_ranked}
    for faction in factions:
        joined = _combined_for_faction(hero_ranked, unit_ranked, faction)
        out_dir = os.path.join("scratch", "output", faction)
        os.makedirs(out_dir, exist_ok=True)
        render(
            joined, os.path.join(out_dir, OUT_FILENAME), faction=faction,
            universe_heroes=len(hero_ranked), universe_units=len(unit_ranked),
        )


_write_by_faction(best_heros.compute_ranked(), best_unites.compute_ranked())

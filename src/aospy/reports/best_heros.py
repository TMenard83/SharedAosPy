"""Croise, pour les héros, le registre de combat (`repository.get_ranking_pool`)
et le registre de coût (plan d'expérience factoriel ajusté sur les héros, cf.
cost_heros.py) pour produire un classement des « meilleurs » héros.

`compute_ranked()` (dans best_report.py) est réutilisé par `best_by_faction.py`
pour produire, par faction, un extrait filtré de ce même classement (rang
global conservé, pas de renumérotation locale).

Pendant : best_unites.py (même méthode, plan de coût troupes séparé). Mécanique
partagée via best_report.py — ce fichier ne garde que le texte propre aux
héros."""
from . import best_report
from .best_report import compute_ranked

OUT_PATH = "scratch/output/best_unit/AoS_heros_best_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  MEILLEURS HÉROS (COMBAT × COÛT)  ·  ÉD. TM"
SECTION_TITLE = "Panthéon des Champions — Héros"

COVER_BODY_INTRO_HTML = (
    "Ce registre croise trois indicateurs indépendants — performance en combat, sous-cotation et "
    "impact réel en partie — en un score unique, pour distinguer les héros <i>vraiment</i> excellents "
    "de ceux qui ne brillent que sur un seul de ces axes. La construction détaillée de chaque "
    "indicateur est donnée page suivante.<br/><br/>"
)
COVER_BODY_PLAIN_TEMPLATE = "{n} héros classés par score décroissant — liste complète (aucune coupe)."
COVER_BODY_FACTION_TEMPLATE = (
    "Extrait filtré sur {faction} — {n} héros. La colonne <b>#</b> conserve le rang du "
    "registre global ({universe_n} héros toutes armées confondues), pas un reclassement local."
)
METHOD_PARAGRAPHS_HTML = [
    "<b>Sources</b><br/>Ce registre croise deux évaluations indépendantes du même héros : le "
    "<i>Compendium des Duels — Héros</i> (performance en combat) et le <i>Registre des Anomalies de "
    "Coût — Héros</i> (écart entre coût réel et coût prédit), joints par identifiant interne. Les "
    "héros dont la prédiction de coût est trop faible (&lt; {min_predicted:.0f} pts — un dénominateur "
    "proche de zéro rendrait le résidu relatif peu fiable) sont écartés, comme dans le registre des "
    "coûts lui-même. Voir <i>Panthéon des Champions — Unités</i> pour le pendant troupes, dont le "
    "modèle de coût est ajusté indépendamment — héros et troupes suivent des logiques de prix "
    "différentes.",
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
    "<b>3. Impact absolu</b> — combien de points le héros fait réellement basculer en partie, sans "
    "référence à son propre coût.<br/>C'est la moyenne brute des pts net sur l'ensemble des duels — "
    "pas la médiane, et surtout <i>non normalisée</i> par le coût de l'attaquant, contrairement au ROI "
    "et au résidu, tous deux relatifs. Sans cet axe, deux héros au ROI et au résidu identiques se "
    "valent quel que soit leur impact réel en partie : un héros pas cher y arrive mécaniquement plus "
    "vite qu'un héros cher au même profil d'efficacité, puisque ROI et résidu sont l'un et l'autre "
    "divisés par les points du héros.",
    "<b>4. Score combiné</b> — synthétise les trois indicateurs en un seul critère de tri, sans "
    "laisser aucun des trois dominer les deux autres.<br/>Chacun est centré-réduit (z-score, moyenne "
    "0, écart-type 1) sur la population des héros communs aux deux registres, pour les rendre "
    "comparables malgré des échelles différentes (pourcentage de ROI, pourcentage de résidu, points "
    "nets bruts). Le score = moyenne pondérée (ROI Moyen ×{roi_weight:.0f}, sous-cotation ×1, "
    "impact absolu ×1) de ces trois z-scores, <i>moins</i> un terme de pénalité "
    "(poids {imbalance_weight:.1f}) proportionnel à leur semi-déviation pondérée <i>vers le bas</i> — "
    "seules les composantes en dessous de la moyenne pondérée comptent dans la pénalité, à la façon "
    "d'un ratio de Sortino. Sans ce terme, la moyenne serait pleinement compensatoire : un excès sur un "
    "seul axe — par exemple une très forte sous-cotation — pourrait à lui seul propulser en tête un "
    "héros médiocre sur les deux autres. La pénalité coûte des points à toute composante faible par "
    "rapport aux deux autres, sans jamais rogner sur un axe où le héros excelle, ce qui favorise les "
    "profils équilibrés sur les profils extrêmes d'un seul côté. Un score de +1 signifie un héros un "
    "écart-type au-dessus de la moyenne sur ce critère combiné — pas une grandeur physique en soi, un "
    "simple outil de tri.",
]


def render(joined: list[dict], out_path: str, *, faction: str | None = None, universe_n: int = 0) -> None:
    best_report.render(
        joined, out_path,
        label="Héros",
        band_text=BAND_TEXT,
        cover_title_doc="Age of Sigmar — Meilleurs héros, combat × coût (TM)",
        cover_subtitle_plain_template="Héros — {n_armies} armées, {n} héros — édition TM",
        cover_subtitle_faction_template=(
            "Héros — {faction} — {n} héros (extrait du registre global, {universe_n} héros) — édition TM"
        ),
        cover_body_intro_html=COVER_BODY_INTRO_HTML,
        cover_body_plain_template=COVER_BODY_PLAIN_TEMPLATE,
        cover_body_faction_template=COVER_BODY_FACTION_TEMPLATE,
        method_section_marker="Méthode — Héros",
        method_paragraphs_html=METHOD_PARAGRAPHS_HTML,
        data_section_title=SECTION_TITLE,
        data_section_note="Triés par score combiné décroissant (meilleur compromis performance/coût en tête).",
        table_count_template="{n} héros.",
        faction=faction,
        universe_n=universe_n,
    )


if __name__ == "__main__":
    render(compute_ranked(is_hero=True), OUT_PATH)

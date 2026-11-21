"""Croise, pour les unités de troupe (hors héros), le registre de combat
(`repository.get_ranking_pool`) et le registre de coût (plan d'expérience
factoriel ajusté sur les troupes, cf. cost_unites.py) pour produire
un classement des « meilleures » unités : celles qui performent bien en duel
*et* sont sous-cotées par rapport à ce que leur profil justifie.

`compute_ranked()` (dans best_report.py) est réutilisé par `best_by_faction.py`
pour produire, par faction, un extrait filtré de ce même classement (rang
global conservé, pas de renumérotation locale).

Pendant : best_heros.py (même méthode, plan de coût héros séparé). Mécanique
partagée via best_report.py — ce fichier ne garde que le texte propre aux
unités de troupe."""
from . import best_report
from .best_report import compute_ranked

OUT_PATH = "scratch/output/best_unit/AoS_unites_best_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  MEILLEURES UNITÉS (COMBAT × COÛT)  ·  ÉD. TM"
SECTION_TITLE = "Panthéon des Champions — Unités"

COVER_BODY_INTRO_HTML = (
    "Ce registre croise trois indicateurs indépendants — performance en combat, sous-cotation et "
    "impact réel en partie — en un score unique, pour distinguer les unités <i>vraiment</i> "
    "excellentes de celles qui ne brillent que sur un seul de ces axes. La construction détaillée de "
    "chaque indicateur est donnée page suivante.<br/><br/>"
)
COVER_BODY_PLAIN_TEMPLATE = "{n} unités classées par score décroissant — liste complète (aucune coupe)."
COVER_BODY_FACTION_TEMPLATE = (
    "Extrait filtré sur {faction} — {n} unités. La colonne <b>#</b> conserve le rang du "
    "registre global ({universe_n} unités toutes armées confondues), pas un reclassement local."
)
METHOD_PARAGRAPHS_HTML = [
    "<b>Sources</b><br/>Ce registre croise deux évaluations indépendantes de la même unité de troupe : "
    "le <i>Compendium des Duels — Unités</i> (performance en combat) et le <i>Registre des Anomalies "
    "de Coût — Unités</i> (écart entre coût réel et coût prédit), jointes par identifiant interne. Les "
    "unités dont la prédiction de coût est trop faible (&lt; {min_predicted:.0f} pts — un dénominateur "
    "proche de zéro rendrait le résidu relatif peu fiable) sont écartées, comme dans le registre des "
    "coûts lui-même. Voir <i>Panthéon des Champions — Héros</i> pour le pendant héros, dont le modèle "
    "de coût est ajusté indépendamment — héros et troupes suivent des logiques de prix différentes.",
    "<b>1. ROI Moyen</b> — performance brute en combat, sans référence au coût.<br/>Chaque unité "
    "de troupe attaquante est confrontée en duel d'un round, sans charge et sans renforcement, à "
    "toutes les unités des autres armées, héros compris côté défenseur (voir <i>Compendium des Duels "
    "— Unités</i> pour le détail). Pour chaque duel, ROI = pts net / coût en points de l'attaquant, où "
    "pts net = pts détruits chez le défenseur − pts perdus par l'attaquant. La lecture est "
    "volontairement asymétrique : le dégât infligé (A→B) est lu au plancher pessimiste atteint 66% du "
    "temps — une posture prudente à l'attaque — le dégât encaissé en retour (B→A) à l'espérance — une "
    "riposte typique, pas un pire cas. On retient, sur l'ensemble de ces duels, la moyenne de trois "
    "quantiles de la distribution du ROI (planchers Stabilité/Fiabilité/Explosivité, 5e/34e/80e "
    "percentile — voir <i>Compendium des Duels — Unités</i> pour le détail) plutôt que la moyenne brute "
    "du ROI : un seul matchup extrême, très bon ou très mauvais, ne peut alors pas à lui seul tirer "
    "l'indicateur d'une unité par ailleurs quelconque.",
    "<b>2. Sous-cotation</b> — écart entre ce que l'unité coûte réellement et ce qu'elle devrait "
    "coûter d'après son profil de combat.<br/>Une régression linéaire (OLS) est ajustée séparément sur "
    "les unités de troupe : les points sont expliqués par un plan d'expérience factoriel — dégâts "
    "contre trois défenseurs synthétiques (save 6+, save 4+, et save 2+ dont le carré capte un "
    "rendement croissant au-delà d'un certain seuil), PV effectifs (PV totaux normalisés par la "
    "probabilité qu'un coup passe à la fois la sauvegarde et le ward — une durabilité multiplicative, "
    "pas trois effets additifs séparés), mouvement, contrôle, niveau de sorcier/prêtre et bonus de "
    "charge, croisés avec des facteurs catégoriels (armée, mix d'armement, type d'unité, vol, mot-clé "
    "UNIQUE, type de Crit dominant) — voir <i>cost_model.py</i>/<i>features.py</i> pour le détail des "
    "variables, et le <i>Registre des Anomalies de Coût — Unités</i> pour les coefficients et la "
    "qualité d'ajustement. Résidu = points réels − points prédits ; un résidu <i>négatif</i> signifie "
    "que l'unité coûte moins que ne le justifierait son profil (sous-cotée, bonne affaire), positif "
    "l'inverse. C'est le résidu <i>relatif</i> (résidu / prédiction) qui est utilisé ici, pour comparer "
    "équitablement des unités de gammes de points différentes.",
    "<b>3. Impact absolu</b> — combien de points l'unité fait réellement basculer en partie, sans "
    "référence à son propre coût.<br/>C'est la moyenne brute des pts net sur l'ensemble des duels — "
    "pas la médiane, et surtout <i>non normalisée</i> par le coût de l'attaquant, contrairement au ROI "
    "et au résidu, tous deux relatifs. Sans cet axe, deux unités au ROI et au résidu identiques se "
    "valent quel que soit leur impact réel en partie : une unité pas chère y arrive mécaniquement plus "
    "vite qu'une unité chère au même profil d'efficacité, puisque ROI et résidu sont l'un et l'autre "
    "divisés par les points de l'unité. C'est cet axe qui, par exemple, replace Revenant Draconith "
    "(180 pts, impact moyen +30 pts) devant des unités moins chères à ROI supérieur mais à impact réel "
    "plus modeste.",
    "<b>4. Score combiné</b> — synthétise les trois indicateurs en un seul critère de tri, sans "
    "laisser aucun des trois dominer les deux autres.<br/>Chacun est centré-réduit (z-score, moyenne "
    "0, écart-type 1) sur la population des unités de troupe communes aux deux registres, pour les "
    "rendre comparables malgré des échelles différentes (pourcentage de ROI, pourcentage de résidu, "
    "points nets bruts). Le score = moyenne pondérée (ROI Moyen ×{roi_weight:.0f}, sous-cotation "
    "×1, impact absolu ×1) de ces trois z-scores, <i>moins</i> un terme de pénalité "
    "(poids {imbalance_weight:.1f}) proportionnel à leur semi-déviation pondérée <i>vers le bas</i> — "
    "seules les composantes en dessous de la moyenne pondérée comptent dans la pénalité, à la façon "
    "d'un ratio de Sortino. Sans ce terme, la moyenne serait pleinement compensatoire : un excès sur un "
    "seul axe — par exemple une très forte sous-cotation — pourrait à lui seul propulser en tête une "
    "unité médiocre sur les deux autres. La pénalité coûte des points à toute composante faible par "
    "rapport aux deux autres, sans jamais rogner sur un axe où l'unité excelle, ce qui favorise les "
    "profils équilibrés sur les profils extrêmes d'un seul côté. Un score de +1 signifie une unité un "
    "écart-type au-dessus de la moyenne sur ce critère combiné — pas une grandeur physique en soi, un "
    "simple outil de tri.",
]


def render(joined: list[dict], out_path: str, *, faction: str | None = None, universe_n: int = 0) -> None:
    best_report.render(
        joined, out_path,
        label="Unité",
        band_text=BAND_TEXT,
        cover_title_doc="Age of Sigmar — Meilleures unités, combat × coût (TM)",
        cover_subtitle_plain_template="Unités de troupe — {n_armies} armées, {n} unités — édition TM",
        cover_subtitle_faction_template=(
            "Unités de troupe — {faction} — {n} unités (extrait du registre global, {universe_n} unités) "
            "— édition TM"
        ),
        cover_body_intro_html=COVER_BODY_INTRO_HTML,
        cover_body_plain_template=COVER_BODY_PLAIN_TEMPLATE,
        cover_body_faction_template=COVER_BODY_FACTION_TEMPLATE,
        method_section_marker="Méthode — Unités",
        method_paragraphs_html=METHOD_PARAGRAPHS_HTML,
        data_section_title=SECTION_TITLE,
        data_section_note="Triées par score combiné décroissant (meilleur compromis performance/coût en tête).",
        table_count_template="{n} unités.",
        faction=faction,
        universe_n=universe_n,
    )


if __name__ == "__main__":
    render(compute_ranked(is_hero=False), OUT_PATH)

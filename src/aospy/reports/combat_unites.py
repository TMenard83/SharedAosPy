"""Génère la synthèse PDF des combats par unité de troupe (hors héros) —
liste complète, pas de Top N. Voir combat_heros.py pour le pendant
héros. Source : `repository.get_ranking_pool` (`unit_benchmark`).
Mécanique (chargement, tri, mise en page) partagée avec combat_heros.py via
combat_report.py — ce fichier ne porte que le texte propre aux unités de
troupe."""
from .combat_report import build

OUT_PATH = "scratch/output/best_unit/AoS_unites_duels_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  SYNTHÈSE DES COMBATS PAR UNITÉ  ·  ÉD. TM"

COVER_BODY_HTML = (
    "Ce registre confronte chaque unité de troupe attaquante, en duel d'un round, à toutes les unités des "
    "autres armées — cinq indicateurs indépendants en résultent, décrits en détail page suivante. La "
    "construction du duel lui-même (asymétrie du dégât, absence de charge) y est également détaillée."
    "<br/><br/><b>{n} unités classées</b> par ROI Moyen décroissant — liste complète (aucune "
    "coupe).<br/><br/>"
    "<i>Note : Beasts of Chaos et Bonesplitterz ne comptent aucune unité — profils Warhammer Legends, "
    "exclus de l'import.</i>"
)
METHOD_PARAGRAPHS_HTML = [
    "<b>Protocole du duel</b><br/>Chaque unité de troupe attaquante est confrontée en duel d'un round, "
    "sans charge et sans renforcement, à toutes les unités des autres armées, héros compris côté "
    "défenseur — voir <i>Compendium des Duels — Héros</i> pour le pendant héros en tant qu'attaquants. La "
    "lecture du dégât est volontairement asymétrique : le dégât infligé par l'unité (A→B) est lu au "
    "plancher pessimiste atteint 66% du temps (<i>lu directement sur la distribution exacte des dégâts, "
    "par convolution — pas une approximation gaussienne</i>) — une posture prudente "
    "à l'attaque, ce qu'on peut raisonnablement « garantir » — tandis que le dégât encaissé en retour "
    "(B→A) est lu à l'espérance brute (moyenne) — une riposte typique, pas un pire cas. <b>Pts net</b> = "
    "pts détruits chez le défenseur (à ce plancher 66%) − pts perdus par l'attaquant (à la moyenne). "
    "<b>ROI</b> = pts net / coût en points de l'unité attaquante. Aucun bonus de charge universel n'existe "
    "en AoS4 — seuls certains profils d'arme (typiquement de la cavalerie) portent un bonus propre à leur "
    "texte d'aptitude (le plus souvent <i>Charge (+1 Dégât)</i>). Ce registre ne <i>déclare</i> aucune "
    "charge, mais deux règles optionnelles, actives par défaut, peuvent malgré tout en simuler les effets : "
    "le <i>seuil de charge</i> déduit l'état chargé du seul écart de Move — l'attaquant est réputé chargé "
    "(bonus d'arme inclus) dès que son Move dépasse celui du défenseur de plus de 30%, sans qu'aucune charge "
    "n'ait été demandée — et le <i>tir double</i> multiplie par 1,5 le dégât à distance du camp le plus "
    "véloce des deux si l'autre, plus court de portée, ne peut le rejoindre même en chargeant. Une unité "
    "rapide ou véloce à distance peut donc bénéficier d'un bonus dans ce registre malgré le « sans charge » "
    "du protocole.",
    "<b>1. ROI Moyen</b> — critère de tri de ce registre.<br/>Moyenne simple des trois planchers ROI "
    "Stabilité / Fiabilité / Explosivité décrits au point 2 — chacun un quantile de la distribution du ROI "
    "sur l'ensemble des duels de l'unité contre le champ défenseur, à un seuil différent (5e / 34e / 80e "
    "percentile). Un résumé unique de cette distribution, sans se reposer sur un seul de ces trois seuils "
    "isolément : un seul matchup extrême, très bon ou très mauvais, pèse ainsi moins lourd que dans une "
    "moyenne brute du ROI (non retenue ici) sur l'indicateur d'une unité par ailleurs quelconque.",
    "<b>2. ROI Stabilité / Fiabilité / Explosivité</b> — trois seuils de cette même distribution, à titre "
    "indicatif.<br/>Un axe orthogonal au plancher 66% du dégât A→B ci-dessus : ce dernier lit le dégât "
    "<i>à l'intérieur</i> d'un seul duel (variance des dés), ces trois quantiles lisent le ROI <i>entre</i> "
    "les duels (variance du champ défenseur). Stabilité est le 5e percentile (dépassé dans 95% des duels — "
    "un pire cas quasi-garanti, y compris contre le pire matchup du champ défenseur), Fiabilité est le 34e "
    "percentile (dépassé dans 66% des duels — un plancher pessimiste plus permissif, sur lequel on peut "
    "compter dans la majorité des matchups), Explosivité est le 80e percentile (dépassé dans seulement 20% "
    "des duels — un plafond optimiste, atteint face à des matchups favorables). Une unité dont les trois "
    "valeurs sont proches performe de façon constante ; un grand écart entre Stabilité et Explosivité trahit "
    "une unité à matchups très polarisés — excellente contre certains profils, faible contre d'autres — que "
    "le seul ROI Moyen ne révèle pas.",
    "<b>3. Pts net moyen</b> — impact absolu, sans référence au coût de l'unité.<br/>La moyenne brute des "
    "pts net sur l'ensemble des duels — pas la médiane, et surtout non normalisée par le coût de "
    "l'attaquant, contrairement au ROI. Deux unités au ROI identique n'ont pas nécessairement le même "
    "impact réel en partie : une unité pas chère atteint mécaniquement le même ROI% avec un pts net plus "
    "faible qu'une unité chère au même profil d'efficacité, puisque le ROI est lui-même divisé par les "
    "points de l'unité. Voir <i>Panthéon des Champions — Unités</i>, dont le score combiné retient cet "
    "axe comme composante à part entière.",
    "<b>4. % positif</b> — proportion des duels rentables.<br/>Pourcentage des duels contre le champ "
    "défenseur où le pts net est strictement positif (l'unité « gagne » l'échange en points). Un "
    "complément au ROI Moyen : deux unités à ROI Moyen comparable peuvent avoir un profil de risque "
    "très différent — l'une rentable dans l'écrasante majorité de ses matchups, l'autre ne compensant des "
    "défaites fréquentes que par quelques très bons résultats.",
]

if __name__ == "__main__":
    build(
        is_hero=False,
        label="Unité",
        out_path=OUT_PATH,
        band_text=BAND_TEXT,
        cover_title_label="Synthèse des combats par unité",
        cover_subtitle_template="Unités de troupe — {n_armies} armées, {n} unités — édition TM",
        cover_body_html=COVER_BODY_HTML,
        method_section_marker="Méthode — Unités",
        method_section_note="Construction du duel, puis des cinq indicateurs qui en sont tirés pour chaque unité.",
        method_paragraphs_html=METHOD_PARAGRAPHS_HTML,
        data_section_title="Compendium des Duels — Unités",
        data_section_note=(
            "L'unité attaquante ne charge pas (combat prolongé ou unité déjà engagée) ; le défenseur non plus."
        ),
        table_count_template="{n} unités classées par ROI Moyen décroissant.",
    )

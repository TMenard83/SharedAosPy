"""Génère la synthèse PDF des combats par héros (unité attaquante is_hero) —
liste complète, pas de Top N. Pendant de combat_unites.py.
Source : `repository.get_ranking_pool` (`unit_benchmark` peuplée avec --include-heroes).
Mécanique (chargement, tri, mise en page) partagée avec combat_unites.py via
combat_report.py — ce fichier ne porte que le texte propre aux héros."""

from .combat_report import build

OUT_PATH = "scratch/output/best_unit/AoS_heros_duels_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  SYNTHÈSE DES COMBATS PAR HÉROS  ·  ÉD. TM"

COVER_BODY_HTML = (
    "Ce registre confronte chaque héros attaquant, en duel d'un round, à toutes les unités des autres "
    "armées — cinq indicateurs indépendants en résultent, décrits en détail page suivante. La construction "
    "du duel lui-même (asymétrie du dégât, absence de charge) y est également détaillée.<br/><br/>"
    "<b>{n} héros classés</b> par ROI Moyen décroissant — liste complète (aucune coupe)."
)
METHOD_PARAGRAPHS_HTML = [
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
    "<b>1. ROI Moyen</b> — critère de tri de ce registre.<br/>Moyenne simple des trois planchers ROI "
    "Stabilité / Fiabilité / Explosivité décrits au point 2 — chacun un quantile de la distribution du ROI "
    "sur l'ensemble des duels du héros contre le champ défenseur, à un seuil différent (5e / 34e / 80e "
    "percentile). Un résumé unique de cette distribution, sans se reposer sur un seul de ces trois seuils "
    "isolément : un seul matchup extrême, très bon ou très mauvais, ne peut alors pas à lui seul tirer "
    "l'indicateur d'un héros par ailleurs quelconque.",
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
    "<b>3. Pts net moyen</b> — impact absolu, sans référence au coût du héros.<br/>La moyenne brute des "
    "pts net sur l'ensemble des duels — pas la médiane, et surtout non normalisée par le coût de "
    "l'attaquant, contrairement au ROI. Deux héros au ROI identique n'ont pas nécessairement le même "
    "impact réel en partie : un héros pas cher atteint mécaniquement le même ROI% avec un pts net plus "
    "faible qu'un héros cher au même profil d'efficacité, puisque le ROI est lui-même divisé par les "
    "points du héros.",
    "<b>4. % positif</b> — proportion des duels rentables.<br/>Pourcentage des duels contre le champ "
    "défenseur où le pts net est strictement positif (le héros « gagne » l'échange en points). Un "
    "complément au ROI Moyen : deux héros à ROI Moyen comparable peuvent avoir un profil de risque "
    "très différent — l'un rentable dans l'écrasante majorité de ses matchups, l'autre ne compensant des "
    "défaites fréquentes que par quelques très bons résultats.",
]

if __name__ == "__main__":
    build(
        is_hero=True,
        label="Héros",
        out_path=OUT_PATH,
        band_text=BAND_TEXT,
        cover_title_label="Synthèse des combats par héros",
        cover_subtitle_template="Héros — {n_armies} armées, {n} héros — édition TM",
        cover_body_html=COVER_BODY_HTML,
        method_section_marker="Méthode — Héros",
        method_section_note="Construction du duel, puis des cinq indicateurs qui en sont tirés pour chaque héros.",
        method_paragraphs_html=METHOD_PARAGRAPHS_HTML,
        data_section_title="Compendium des Duels — Héros",
        data_section_note=(
            "Le héros attaquant ne charge pas (combat prolongé ou unité déjà engagée) ; le défenseur non plus."
        ),
        table_count_template="{n} héros classés par ROI Moyen décroissant.",
    )

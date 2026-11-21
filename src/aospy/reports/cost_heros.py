"""Génère le PDF des héros classés par écart au coût, d'après le plan
d'expérience factoriel ajusté sur TOUTE la population (héros + troupes,
`cost_model.fit_cost_model_factorial`) avec des termes d'interaction
`C(is_hero):...`. Pendant de cost_unites.py, qui utilise le même
modèle — voir sa docstring pour la justification de ce choix face à deux
régressions séparées (`fit_segmented`). Mécanique (ajustement, mise en page)
partagée avec cost_unites.py via cost_report.py — ce fichier ne porte que le
texte propre aux héros."""
from .cost_report import build

OUT_PATH = "scratch/output/best_unit/AoS_heros_prix_TM.pdf"
BAND_TEXT = "AGE OF SIGMAR  ·  HÉROS SOUS-COTÉS  ·  ÉD. TM"

METHOD_BODY_HTML = (
    "<b>Méthode :</b> régression linéaire (OLS) des points sur un plan d'expérience factoriel — "
    "variables continues (taille d'unité et son carré, dégât à distance vs aucune save, dégât perçant vs save 2+ "
    "et son carré, bonus de dégât de charge, PV effectifs [PV totaux "
    "normalisés par la probabilité qu'un coup passe la save ET le ward, la save nue étant dégradée d'un "
    "Rend représentatif de 1 — moyenne observée sur les profils d'arme de la base — puisque cette "
    "caractéristique n'a pas d'attaquant précis ; le Ward, jamais modifié par le Rend, reste nu], "
    "contrôle, niveau de "
    "sorcier/prêtre Wizard(N)/Priest(N)) — le mouvement et l'irrégularité du dégât vs save 4+ ont été retirés "
    "par élimination arrière (aucun effet-prix détectable une fois les autres prédicteurs présents, cf. "
    "<i>analysis/cost/experiments/backward_elimination.py</i>) — croisées avec des facteurs catégoriels (armée d'appartenance, "
    "rôle héros/troupe, mix d'armement mêlée/distance/mixte, type d'unité infanterie/cavalerie/monstre/"
    "machine de guerre/bête, mot-clé de vol, UNIQUE, type de Crit dominant) — voir "
    "<i>features.py</i>/<i>cost_model.py</i>, <i>fit_cost_model_factorial</i>. Le pool de dégâts brut "
    "(avant save/ward) ne retient que sa composante à distance : la composante mêlée s'est révélée sans "
    "effet-prix propre une fois les autres prédicteurs présents (cf. "
    "<i>analysis/cost/experiments/melee_ranged_split.py</i>) et a été retirée. "
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
    "R = {r:.3f}, R² = {r2:.3f}, "
    "R² ajusté = {adj_r2:.3f}, n = {n} unités (héros + troupes).<br/><br/>"
    "<b>Prudence :</b> certaines armées comptent très peu de héros importés — leur coefficient d'armée "
    "a alors un fort effet de levier et est moins fiable que celui d'une faction bien peuplée en "
    "héros.<br/><br/>"
    "<b>Résidu</b> = points réels − points prédits par le modèle. Un résidu négatif signifie que le "
    "héros coûte <i>moins</i> que ce que son profil de combat justifierait — une sous-cotation, donc "
    "une bonne affaire en points ; un résidu positif signifie l'inverse (sur-cotation). Le classement "
    "ci-après trie sur le résidu <i>relatif</i> (résidu / prédiction), pour comparer équitablement des "
    "héros de gammes de points différentes ; les héros dont la prédiction est trop faible "
    "(&lt; {min_predicted:.0f} pts, dénominateur peu fiable) sont écartés.<br/><br/>"
    "Le détail des coefficients est donné page suivante."
)
COEF_NOTE_HTML = (
    "Points par unité de caractéristique, ceteris paribus ; les facteurs catégoriels sont exprimés par "
    "rapport à une modalité de référence. « Rôle : Héros » est le supplément de base pour un héros "
    "(toutes autres caractéristiques égales) ; « Héros × PV effectifs » module, en plus, le prix de la "
    "durabilité spécifiquement pour les héros."
)
TABLE_NOTE_HTML = (
    "Tous les héros, triés par résidu relatif croissant (le plus négatif en tête, les meilleures "
    "affaires en points) jusqu'au plus sur-coté en fin de tableau."
)

if __name__ == "__main__":
    build(
        is_hero=True,
        label="Héros",
        out_path=OUT_PATH,
        band_text=BAND_TEXT,
        cover_title_suffix="Héros les plus sous-cotées",
        cover_subtitle_template="Héros — les {n} héros classés par écart au coût — édition TM",
        section_title_coef="Coefficients du Modèle — Héros",
        section_title="Registre des Anomalies de Coût — Héros",
        method_body_html=METHOD_BODY_HTML,
        coef_note_html=COEF_NOTE_HTML,
        table_note_html=TABLE_NOTE_HTML,
        table_count_template="{n} héros.",
    )

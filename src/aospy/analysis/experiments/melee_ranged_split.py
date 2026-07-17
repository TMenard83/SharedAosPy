"""Essai (concluant, adopté) : scinder le pool de dégâts bruts (avant save/ward) en deux
pools symétriques mêlée/tir plutôt que de traiter le tir comme un delta sur un
total déjà mêlée+tir.

Avant cet essai, `cost_model.MODEL_FEATURES` portait `dmg_vs_save6` (total
mêlée+tir) : le pool mêlée n'existait donc qu'implicitement
(`dmg_vs_save6 - dmg_ranged_vs_save6`), les deux étant mécaniquement colinéaires
(le second est un sous-ensemble du premier). Hypothèse testée : reparamétrer en
deux pools disjoints `dmg_melee_vs_save6`/`dmg_ranged_vs_save6`, laissés à l'OLS
pour estimer leurs coefficients respectifs.

Résultat : une fois scindé, le pool mêlée (`dmg_melee_vs_save6`) n'a aucun
effet-prix distinguable de zéro (probablement déjà absorbé par `dmg_vs_save2`/
`effective_wounds`), alors que le pool tir (`dmg_ranged_vs_save6`) reste
significatif. Retirer entièrement le pool mêlée du modèle (garder
`dmg_ranged_vs_save6` seul) laisse le R² ajusté inchangé, voire légèrement
meilleur — c'est l'état officiel actuel de `cost_model.MODEL_FEATURES`.

Ce script fige donc explicitement la variante « avant » (`dmg_vs_save6` seul,
sans passer par `dmg_ranged_vs_save6`) plutôt que de la dériver de
`cost_model.MODEL_FEATURES`, qui porte déjà la conclusion adoptée — sinon la
comparaison deviendrait un no-op une fois le changement en place.
"""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

FEATURES_OFFICIAL = cost_model.MODEL_FEATURES  # officiel actuel : dmg_ranged_vs_save6 seul (mêlée droppé)
FEATURES_MERGED = tuple(
    "dmg_vs_save6" if f == "dmg_ranged_vs_save6" else f for f in FEATURES_OFFICIAL
)  # variante « avant » : un seul pool mêlée+tir, comme avant cet essai
FEATURES_SPLIT = FEATURES_OFFICIAL + ("dmg_melee_vs_save6",)  # variante écartée : les deux pools séparés

model_merged = cost_model.fit_cost_model_factorial(features=FEATURES_MERGED, frame=frame.copy())
model_official = cost_model.fit_cost_model_factorial(features=FEATURES_OFFICIAL, frame=frame.copy())
model_split = cost_model.fit_cost_model_factorial(features=FEATURES_SPLIT, frame=frame.copy())

print(f"Modèle A (dmg_vs_save6 seul, avant cet essai)                  : R² = {model_merged.r_squared:.4f}  R² ajusté = {model_merged.adj_r_squared:.4f}")
print(f"Modèle B (dmg_ranged_vs_save6 seul, officiel actuel)           : R² = {model_official.r_squared:.4f}  R² ajusté = {model_official.adj_r_squared:.4f}  (gain {model_official.adj_r_squared - model_merged.adj_r_squared:+.4f})")
print(f"Modèle C (dmg_melee_vs_save6 + dmg_ranged_vs_save6, scindé)    : R² = {model_split.r_squared:.4f}  R² ajusté = {model_split.adj_r_squared:.4f}  (gain {model_split.adj_r_squared - model_merged.adj_r_squared:+.4f})")
print()

for label, model in [("A", model_merged), ("B", model_official), ("C", model_split)]:
    print(f"-- Modèle {label} : coefficients dmg_vs_save6 / dmg_melee_vs_save6 / dmg_ranged_vs_save6 --")
    for c in model.coefficients:
        if c.name in ("dmg_vs_save6", "dmg_melee_vs_save6", "dmg_ranged_vs_save6"):
            print(f"  {c.name:20s} {c.coef:+8.2f}  p={c.p_value:.3f}")
    print()

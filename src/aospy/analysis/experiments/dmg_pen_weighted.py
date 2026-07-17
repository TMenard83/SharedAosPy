"""Essai (concluant, adopté) : remplacer `dmg_pen` (ratio sans dimension
dmg_vs_save2/dmg_vs_save6) par `dmg_vs_save2` (dégât absolu contre une save 2+), qui EST
déjà, par construction, la "moyenne des dommages × pénétration" suggérée —
dmg_vs_save6 × dmg_pen == dmg_vs_save2 exactement, mais calculé directement par le moteur
de combat (chaîne hit/wound/save/ward) plutôt que reconstruit après coup par un ratio. La
différence n'est pas cosmétique : le ratio est aveugle à la magnitude (un profil à dégât nul
avec 100% de rend obtient le même dmg_pen qu'un profil à gros dégât avec 100% de rend), alors
que dmg_vs_save2 grandit avec les deux à la fois — plus fidèle à ce que GW valorise en points.

`cost_model.MODEL_FEATURES` utilise déjà `dmg_vs_save2` : ce script dérive donc la variante
`dmg_pen` (ratio, écartée) à partir du jeu officiel actuel plutôt que l'inverse, pour que la
comparaison reste valide indépendamment des évolutions futures de MODEL_FEATURES."""
from aospy.persistence import db
from aospy.analysis import cost_model

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

FEATURES_WEIGHTED = cost_model.MODEL_FEATURES  # officiel actuel : dmg_vs_save2
FEATURES_RATIO = tuple(
    "dmg_pen" if f == "dmg_vs_save2" else f for f in FEATURES_WEIGHTED
)  # variante écartée : ratio sans dimension
FEATURES_BOTH = FEATURES_WEIGHTED + ("dmg_pen",)  # essai bonus : garder les deux

model_ratio = cost_model.fit_cost_model_factorial(features=FEATURES_RATIO, frame=frame.copy())
model_weighted = cost_model.fit_cost_model_factorial(features=FEATURES_WEIGHTED, frame=frame.copy())
model_both = cost_model.fit_cost_model_factorial(features=FEATURES_BOTH, frame=frame.copy())

print(f"Modèle A (dmg_pen, ratio, écarté)           : R = {model_ratio.r_squared**0.5:.4f}  R² = {model_ratio.r_squared:.4f}  R² ajusté = {model_ratio.adj_r_squared:.4f}")
print(f"Modèle B (dmg_vs_save2, officiel actuel)     : R = {model_weighted.r_squared**0.5:.4f}  R² = {model_weighted.r_squared:.4f}  R² ajusté = {model_weighted.adj_r_squared:.4f}")
print(f"Modèle C (dmg_pen + dmg_vs_save2, les deux) : R = {model_both.r_squared**0.5:.4f}  R² = {model_both.r_squared:.4f}  R² ajusté = {model_both.adj_r_squared:.4f}")
print()
print(f"Gain R² ajusté (B vs A) : {model_weighted.adj_r_squared - model_ratio.adj_r_squared:+.4f}")
print(f"Gain R² ajusté (C vs A) : {model_both.adj_r_squared - model_ratio.adj_r_squared:+.4f}")
print()

for label, model in [("A", model_ratio), ("B", model_weighted), ("C", model_both)]:
    print(f"-- Modèle {label} : coefficients dmg_pen / dmg_vs_save2 --")
    for c in model.coefficients:
        if c.name in ("dmg_pen", "dmg_vs_save2", "dmg_vs_save6"):
            print(f"  {c.name:20s} {c.coef:+8.2f}  p={c.p_value:.3f}")

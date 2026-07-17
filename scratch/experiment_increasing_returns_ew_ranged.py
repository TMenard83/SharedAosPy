"""Essai (écarté) : `dmg_vs_save2_sq` capte des rendements croissants sur le pool perçant
(cf. `analysis/experiments/durability_and_saturation.py`, adopté). Question : le même
phénomène existe-t-il sur `effective_wounds` (durabilité) ou `dmg_ranged_vs_save6` (pool
brut tir, isolé récemment — `analysis/experiments/melee_ranged_split.py`) ?

Résultat : non, dans les deux cas. Ni `effective_wounds_sq` (p=0.68, y compris avec une
interaction héros sur le carré, p=0.55/0.33) ni `dmg_ranged_vs_save6_sq` (p=0.84) ne sont
significatifs, et le R² ajusté n'y gagne rien (-0.0001 dans les deux cas — une variance
perdue par le degré de liberté supplémentaire, sans gain de pouvoir explicatif). Le
rendement croissant sur `dmg_vs_save2` semble donc spécifique au pool perçant, pas un
phénomène général applicable à tout indicateur continu du modèle.

Écarté : ni `effective_wounds_sq` ni `dmg_ranged_vs_save6_sq` n'entrent dans
`cost_model.MODEL_FEATURES`."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

frame["effective_wounds_sq"] = frame["effective_wounds"] ** 2
frame["dmg_ranged_vs_save6_sq"] = frame["dmg_ranged_vs_save6"] ** 2

FEATURES_A = cost_model.MODEL_FEATURES  # officiel
FEATURES_EW = FEATURES_A + ("effective_wounds_sq",)
FEATURES_RANGED = FEATURES_A + ("dmg_ranged_vs_save6_sq",)
INTER_EW = cost_model.FACTORIAL_INTERACTIONS + ("C(is_hero):effective_wounds_sq",)

model_a = cost_model.fit_cost_model_factorial(features=FEATURES_A, frame=frame.copy())
model_ew = cost_model.fit_cost_model_factorial(features=FEATURES_EW, frame=frame.copy())
model_ew_hero = cost_model.fit_cost_model_factorial(features=FEATURES_EW, interactions=INTER_EW, frame=frame.copy())
model_ranged = cost_model.fit_cost_model_factorial(features=FEATURES_RANGED, frame=frame.copy())

print(f"A (officiel)                                    : R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"+ effective_wounds_sq                           : R² = {model_ew.r_squared:.4f}  R² ajusté = {model_ew.adj_r_squared:.4f}  (gain {model_ew.adj_r_squared - model_a.adj_r_squared:+.4f})")
print(f"+ effective_wounds_sq + interaction héros sur sq: R² = {model_ew_hero.r_squared:.4f}  R² ajusté = {model_ew_hero.adj_r_squared:.4f}  (gain {model_ew_hero.adj_r_squared - model_a.adj_r_squared:+.4f})")
print(f"+ dmg_ranged_vs_save6_sq                        : R² = {model_ranged.r_squared:.4f}  R² ajusté = {model_ranged.adj_r_squared:.4f}  (gain {model_ranged.adj_r_squared - model_a.adj_r_squared:+.4f})")
print()

for label, model in [("+ ew_sq", model_ew), ("+ ew_sq + hero", model_ew_hero), ("+ ranged_sq", model_ranged)]:
    print(f"-- {label} --")
    for c in model.coefficients:
        if "_sq" in c.name:
            print(f"  {c.name:45s} {c.coef:+10.5f}  p={c.p_value:.3f}")
    print()

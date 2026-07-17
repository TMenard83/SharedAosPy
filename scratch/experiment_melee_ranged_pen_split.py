"""Essai (écarté) : même hypothèse que `analysis/experiments/melee_ranged_split.py`
(pool brut, adopté), appliquée cette fois au pool *perçant* (`dmg_vs_save2`, sonde
save 2+). Question : le tir mérite-t-il un coefficient propre sur l'axe perçant aussi,
via `dmg_melee_vs_save2`/`dmg_ranged_vs_save2` (`features.py`) ?

Résultat : contrairement au pool brut (où le pool mêlée s'est révélé sans effet-prix
et le pool tir significatif), sur l'axe perçant **ni l'un ni l'autre** des deux pools
scindés n'atteint la significativité isolément (dmg_melee_vs_save2 p=0.28,
dmg_ranged_vs_save2 p=0.12-0.23 selon la variante) — la magnitude perçante y est déjà
essentiellement portée par `dmg_vs_save2_sq` (terme quadratique, p<0.001), qui reste
combiné dans cet essai. Le R² ajusté ne bouge pas (±0.0000, attendu : la scission est
un changement de base tant que les deux composantes restent dans le modèle).

Écarté : garder `dmg_vs_save2` combiné dans `cost_model.MODEL_FEATURES` plutôt que de
le scinder — pas de gain, et une scission ajouterait un prédicteur non significatif
sans bénéfice interprétatif clair (à la différence du pool brut)."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

FEATURES_BEFORE = cost_model.MODEL_FEATURES  # officiel actuel : dmg_vs_save2 combiné
FEATURES_SPLIT = tuple(
    "dmg_melee_vs_save2" if f == "dmg_vs_save2" else f for f in FEATURES_BEFORE
) + ("dmg_ranged_vs_save2",)  # variante testée : dmg_vs_save2 remplacé par les deux pools
FEATURES_DROP_MELEE_PEN = tuple(f for f in FEATURES_SPLIT if f != "dmg_melee_vs_save2")
# variante bonus : et si, comme pour le pool brut, le pool mêlée perçant est lui aussi
# éliminable une fois les autres prédicteurs (dmg_ranged_vs_save6, effective_wounds, ...)
# déjà dans le modèle ?

model_before = cost_model.fit_cost_model_factorial(features=FEATURES_BEFORE, frame=frame.copy())
model_split = cost_model.fit_cost_model_factorial(features=FEATURES_SPLIT, frame=frame.copy())
model_drop_melee = cost_model.fit_cost_model_factorial(features=FEATURES_DROP_MELEE_PEN, frame=frame.copy())

print(f"Modèle A (dmg_vs_save2 combiné, officiel actuel)                 : R² = {model_before.r_squared:.4f}  R² ajusté = {model_before.adj_r_squared:.4f}")
print(f"Modèle B (dmg_melee_vs_save2 + dmg_ranged_vs_save2, scindé)      : R² = {model_split.r_squared:.4f}  R² ajusté = {model_split.adj_r_squared:.4f}  (gain {model_split.adj_r_squared - model_before.adj_r_squared:+.4f})")
print(f"Modèle C (dmg_ranged_vs_save2 seul, pool mêlée perçant retiré)   : R² = {model_drop_melee.r_squared:.4f}  R² ajusté = {model_drop_melee.adj_r_squared:.4f}  (gain {model_drop_melee.adj_r_squared - model_before.adj_r_squared:+.4f})")
print()

for label, model in [("A", model_before), ("B", model_split), ("C", model_drop_melee)]:
    print(f"-- Modèle {label} : coefficients de l'axe perçant --")
    for c in model.coefficients:
        if c.name in ("dmg_vs_save2", "dmg_melee_vs_save2", "dmg_ranged_vs_save2", "dmg_vs_save2_sq"):
            print(f"  {c.name:20s} {c.coef:+8.2f}  p={c.p_value:.3f}")
    print()

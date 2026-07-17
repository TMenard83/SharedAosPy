"""Essai (écarté) : `control` (contrôle PAR MODÈLE, feature actuelle de
`cost_model.MODEL_FEATURES`) sous-estime-t-il le contrôle réel d'une unité à plusieurs
modèles ? En AoS4, le score de Contrôle se cumule par modèle sur un objectif — une unité de
10 modèles à Contrôle 1 vaut donc 10 en contrôle total, pas 1. `wounds_total` (health×models)
fait déjà ce calcul pour les PV ; `control` ne le fait pas pour le contrôle.

Deuxième variante testée : pour les BEAST (mots-clés BEAST, cf. `features._unit_type`),
forcer le contrôle total à 1 quel que soit l'effectif de l'escouade — hypothèse que GW ne
valorise pas le contrôle des unités BEAST comme celui des autres types (beaucoup de BEAST
ont un profil "horde jetable" où le contrôle n'est pas l'axe de coût dominant).

Résultat : les deux variantes dégradent le R² ajusté par rapport à `control` par modèle
(0.9223 → 0.9182 pour `control_total` brut, → 0.9167 avec le forçage BEAST à 1 — encore
pire, malgré l'intuition narrative). GW semble donc bel et bien facturer le contrôle par
modèle et non le total d'escouade — peut-être parce qu'un objectif ne peut être contrôlé
que par un nombre limité de modèles à portée, rendant le contrôle total peu représentatif
de l'usage réel en jeu.

Écarté : `control` (par modèle) reste le prédicteur dans `cost_model.MODEL_FEATURES`.
N'écrit rien dans cost_model.py/features.py."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

frame["control_total"] = frame["control"] * frame["unit_size"]
frame["control_beast1"] = frame.apply(
    lambda r: 1.0 if r["unit_type"] == "BEAST" else r["control_total"], axis=1,
)

FEATURES_A = cost_model.MODEL_FEATURES  # officiel actuel : control (par modèle)
FEATURES_B = tuple("control_total" if f == "control" else f for f in cost_model.MODEL_FEATURES)
FEATURES_C = tuple("control_beast1" if f == "control" else f for f in cost_model.MODEL_FEATURES)

model_a = cost_model.fit_cost_model_factorial(features=FEATURES_A, frame=frame.copy())
model_b = cost_model.fit_cost_model_factorial(features=FEATURES_B, frame=frame.copy())
model_c = cost_model.fit_cost_model_factorial(features=FEATURES_C, frame=frame.copy())

print(f"Modèle A (control, par modèle, officiel actuel)        : R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle B (control_total = control × unit_size)         : R² = {model_b.r_squared:.4f}  R² ajusté = {model_b.adj_r_squared:.4f}")
print(f"Modèle C (control_total, sauf BEAST forcé à 1)         : R² = {model_c.r_squared:.4f}  R² ajusté = {model_c.adj_r_squared:.4f}")
print()
print(f"Gain R² ajusté (B vs A) : {model_b.adj_r_squared - model_a.adj_r_squared:+.4f}")
print(f"Gain R² ajusté (C vs A) : {model_c.adj_r_squared - model_a.adj_r_squared:+.4f}")
print(f"Gain R² ajusté (C vs B) : {model_c.adj_r_squared - model_b.adj_r_squared:+.4f}")
print()

for label, model in [("A", model_a), ("B", model_b), ("C", model_c)]:
    print(f"-- Modèle {label} : coefficient contrôle --")
    for c in model.coefficients:
        if "control" in c.name:
            print(f"  {c.name:20s} {c.coef:+8.2f}  p={c.p_value:.3f}")

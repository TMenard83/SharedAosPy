"""Essai (concluant, adopté) : ajouter le mot-clé `UNIQUE` (personnage nommé) comme facteur
catégoriel. Idée : les personnages nommés portent souvent une prime narrative/de règles
indépendante de leur profil de combat brut — un proxy imparfait mais gratuit (déjà dans
Unit.keywords) pour une partie de l'axe "utilité/aptitudes" qu'aospy ne modélise pas
autrement (pas de texte d'aptitude par unité en base, cf. la note de features.py — un
Wizard/Priest est le seul cas où ce texte est structuré).
Risque anticipé : `UNIQUE` est très corrélé à `is_hero` (quasi tous les uniques sont des
héros) donc son effet propre pourrait ne pas ressortir proprement.

`cost_model.CATEGORICAL_FEATURES` inclut déjà `is_unique` : ce script dérive donc le
contre-exemple "sans is_unique" à partir du jeu officiel actuel plutôt que l'inverse, pour
que la comparaison reste valide indépendamment des évolutions futures de CATEGORICAL_FEATURES
(l'ajouter une deuxième fois au jeu déjà officiel ferait planter l'ajustement, terme dupliqué)."""
from aospy.persistence import db
from aospy.analysis import cost_model

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

print(f"Unités UNIQUE dans le jeu d'entraînement : {frame['is_unique'].sum()} / {len(frame)}")
print(f"  dont héros : {frame[frame['is_unique']]['is_hero'].sum()} / {frame['is_unique'].sum()}")
print(f"Corrélation is_unique / is_hero : {frame['is_unique'].astype(float).corr(frame['is_hero'].astype(float)):.3f}")
print()

cats_before = [c for c in cost_model.CATEGORICAL_FEATURES if c != "is_unique"]
model_a = cost_model.fit_cost_model_factorial(categorical=cats_before, frame=frame.copy())  # contre-exemple, sans is_unique
model_g = cost_model.fit_cost_model_factorial(frame=frame.copy())  # officiel actuel, + is_unique

print(f"Modèle A (contre-exemple, sans is_unique) : R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle G (officiel actuel, + is_unique)    : R² = {model_g.r_squared:.4f}  R² ajusté = {model_g.adj_r_squared:.4f}")
print(f"Gain R² ajusté : {model_g.adj_r_squared - model_a.adj_r_squared:+.4f}")
print()

for c in model_g.coefficients:
    if "unique" in c.name.lower():
        print(f"  {c.name:30s} {c.coef:+8.2f}  p={c.p_value:.3f}")

# Essai bonus : interaction is_unique x dmg_vs_save2, si UNIQUE porte surtout
# une prime sur des unités déjà performantes en dégât plutôt qu'un forfait fixe.
inter_h = list(cost_model.FACTORIAL_INTERACTIONS) + ["C(is_unique):dmg_vs_save2"]
model_h = cost_model.fit_cost_model_factorial(interactions=inter_h, frame=frame.copy())  # officiel + interaction
print()
print(f"Modèle H (officiel + is_unique x dmg_vs_save2) : R² = {model_h.r_squared:.4f}  R² ajusté = {model_h.adj_r_squared:.4f}")
print(f"Gain R² ajusté (H vs A) : {model_h.adj_r_squared - model_a.adj_r_squared:+.4f}")
for c in model_h.coefficients:
    if "unique" in c.name.lower():
        print(f"  {c.name:30s} {c.coef:+8.2f}  p={c.p_value:.3f}")

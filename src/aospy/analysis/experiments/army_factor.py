"""Essai (concluant, adopté) : le facteur `grand_alliance` (4 modalités) apportait-il moins
qu'un facteur plus fin par armée/faction (~27 modalités) ? Comparaison R²/R² ajusté des deux
variantes, sans toucher à cost_model.py/features.py (rien n'est modifié côté modèle "officiel"
par ce script).

`cost_model.CATEGORICAL_FEATURES` utilise déjà `army_name` : ce script dérive donc la variante
`grand_alliance` (contre-exemple historique) à partir du jeu officiel actuel plutôt que
l'inverse, pour que la comparaison reste valide indépendamment des évolutions futures de
CATEGORICAL_FEATURES. `army_name`/`grand_alliance` sont déjà deux champs natifs de
`UnitFeatures` (résolus par `all_features`), pas besoin de les recalculer via `repository`."""
from aospy.persistence import db
from aospy.analysis import cost_model

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

import statsmodels.formula.api as smf
from statsmodels.stats.anova import anova_lm

feats = [f for f in cost_model.MODEL_FEATURES if frame[f].astype(float).std() > 0]

# --- Modèle B (officiel actuel) : army_name (~27 modalités) -----------------
cats_b = [c for c in cost_model.CATEGORICAL_FEATURES if frame[c].nunique() > 1]
inter = []
for term in cost_model.FACTORIAL_INTERACTIONS:
    cat_part, _, cont_part = term.partition(":")
    cat_name = cat_part[len("C(") : -1]
    if cat_name in cats_b and cont_part in feats:
        inter.append(term)
terms_b = feats + [f"C({c})" for c in cats_b] + inter
formula_b = "points ~ " + " + ".join(terms_b)
model_b = smf.ols(formula_b, data=frame).fit()

# --- Modèle A' (contre-exemple historique) : army_name -> grand_alliance ----
cats_a_prime = ["grand_alliance" if c == "army_name" else c for c in cats_b]
terms_a_prime = feats + [f"C({c})" for c in cats_a_prime] + inter
formula_a_prime = "points ~ " + " + ".join(terms_a_prime)
model_a_prime = smf.ols(formula_a_prime, data=frame).fit()

print(f"Modèle A' (grand_alliance, 4 modalités, contre-exemple) : R² = {model_a_prime.rsquared:.4f}  R² ajusté = {model_a_prime.rsquared_adj:.4f}  n_params = {len(model_a_prime.params)}")
print(f"Modèle B (army_name, {frame['army_name'].nunique()} modalités, officiel actuel)   : R² = {model_b.rsquared:.4f}  R² ajusté = {model_b.rsquared_adj:.4f}  n_params = {len(model_b.params)}")
print()
print(f"Gain de R² (brut)     : {model_b.rsquared - model_a_prime.rsquared:+.4f}")
print(f"Gain de R² ajusté     : {model_b.rsquared_adj - model_a_prime.rsquared_adj:+.4f}")
print()

# F-test emboîté : army_name (officiel) apporte-t-il un gain de complexité
# statistiquement significatif par rapport à grand_alliance, à features égales ?
# Nested au sens statistique : chaque armée appartient à une seule alliance, donc
# les colonnes indicatrices de grand_alliance sont une combinaison linéaire de
# celles d'army_name.
comparison = anova_lm(model_a_prime, model_b)
print("F-test emboîté (grand_alliance -> army_name, à features égales) :")
print(comparison)
print()

print("Coefficients par armée (vs modalité de référence), triés par effet :")
army_coefs = sorted(
    ((name, model_b.params[name], model_b.pvalues[name]) for name in model_b.params.index if name.startswith("C(army_name)")),
    key=lambda t: t[1],
)
for name, coef, p in army_coefs:
    army = name.split("T.")[1].rstrip("]")
    sig = "*" if p < 0.05 else " "
    print(f"  {army:28s} {coef:+7.1f} pts  (p={p:.3f}){sig}")

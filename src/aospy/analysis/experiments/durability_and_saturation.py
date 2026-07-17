"""Essai (concluant, adopté) : deux changements testés ensemble sur la même feature
frame, tous deux motivés par la même question — le modèle de coût traite-t-il certains
effets comme additifs/linéaires alors qu'ils sont en réalité multiplicatifs/à seuil ?

1. ``effective_wounds`` remplace le trio ``wounds_total``/``save_num``/``ward_num``. Ces
   trois stats ne jouent pas un rôle additif indépendant en jeu : une unité à beaucoup de
   PV mais save nulle meurt aussi vite qu'une unité à peu de PV bien protégée — ce que
   trois coefficients linéaires séparés ne peuvent pas capter (leur somme reste additive
   quels que soient les coefficients). ``effective_wounds = wounds_total / P(un coup passe
   la save ET le ward)`` combine les trois en un seul indice multiplicatif : "nombre de
   coups qu'il faut effectivement porter pour tuer l'unité".
2. ``dmg_vs_save2_sq`` (terme quadratique de ``dmg_vs_save2``) : hypothèse que GW valorise
   un dégât perçant croissant plus que proportionnellement au-delà d'un certain seuil
   (rendements croissants, pas décroissants), que le terme linéaire seul sous-estime.

`cost_model.MODEL_FEATURES`/`FACTORIAL_INTERACTIONS` incluent déjà les deux : ce script
dérive donc le contre-exemple "avant adoption" (wounds_total/save_num/ward_num séparés,
pas de terme quadratique, interaction héros sur wounds_total) à partir du jeu officiel
actuel plutôt que l'inverse, pour que la comparaison reste valide indépendamment des
évolutions futures de MODEL_FEATURES."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

FEATURES_BEFORE = tuple(
    ("wounds_total", "save_num", "ward_num") if f == "effective_wounds" else (f,)
    for f in cost_model.MODEL_FEATURES
    if f != "dmg_vs_save2_sq"
)
FEATURES_BEFORE = tuple(x for group in FEATURES_BEFORE for x in group)  # aplatit
INTERACTIONS_BEFORE = tuple(
    "C(is_hero):wounds_total" if t == "C(is_hero):effective_wounds" else t
    for t in cost_model.FACTORIAL_INTERACTIONS
)

FEATURES_ONLY_EW = tuple(f for f in FEATURES_BEFORE if f not in ("wounds_total", "save_num", "ward_num")) + (
    "effective_wounds",
)
FEATURES_ONLY_SQ = FEATURES_BEFORE + ("dmg_vs_save2_sq",)

model_a = cost_model.fit_cost_model_factorial(
    features=FEATURES_BEFORE, interactions=INTERACTIONS_BEFORE, frame=frame.copy(),
)  # avant adoption : wounds_total/save_num/ward_num séparés, pas de terme quadratique
model_b = cost_model.fit_cost_model_factorial(
    features=FEATURES_ONLY_EW, interactions=cost_model.FACTORIAL_INTERACTIONS, frame=frame.copy(),
)  # + effective_wounds seul (remplace le trio)
model_c = cost_model.fit_cost_model_factorial(
    features=FEATURES_ONLY_SQ, interactions=INTERACTIONS_BEFORE, frame=frame.copy(),
)  # + dmg_vs_save2_sq seul (trio inchangé)
model_d = cost_model.fit_cost_model_factorial(frame=frame.copy())  # officiel actuel : les deux combinés

print(f"Modèle A (avant adoption, trio wounds/save/ward, pas de terme quadratique) : R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle B (+ effective_wounds seul)                                         : R² = {model_b.r_squared:.4f}  R² ajusté = {model_b.adj_r_squared:.4f}  (gain {model_b.adj_r_squared - model_a.adj_r_squared:+.4f})")
print(f"Modèle C (+ dmg_vs_save2_sq seul)                                          : R² = {model_c.r_squared:.4f}  R² ajusté = {model_c.adj_r_squared:.4f}  (gain {model_c.adj_r_squared - model_a.adj_r_squared:+.4f})")
print(f"Modèle D (officiel actuel, les deux + interaction héros sur effective_wounds) : R² = {model_d.r_squared:.4f}  R² ajusté = {model_d.adj_r_squared:.4f}  (gain {model_d.adj_r_squared - model_a.adj_r_squared:+.4f})")
print()

for label, model in [("A", model_a), ("B", model_b), ("C", model_c), ("D", model_d)]:
    print(f"-- Modèle {label} : coefficients concernés --")
    for c in model.coefficients:
        if any(k in c.name for k in ("wounds_total", "save_num", "ward_num", "effective_wounds", "dmg_vs_save2")):
            print(f"  {c.name:35s} {c.coef:+9.3f}  p={c.p_value:.3f}")
    print()

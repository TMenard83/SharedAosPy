"""Essai (concluant, adopté) : remplacer `control` par son écart à la règle tacite de GW.

Idée (utilisateur, 2026-11-19) : le contrôle n'est pas une caractéristique recherchée ; GW
l'attribue selon le profil (infanterie légère 1, grosse infanterie 2, héros 2, monstre 5…) et
ne fait payer que l'écart — le bonus des figurines épiques (Archaon, Kragnos, Cogforts : 10-15)
ou de quelques leaders nommés, et un rabais pour les profils sous la règle (héros montés à 10
PV et contrôle 2). La règle est `features.expected_control`.

Contre-exemple dérivé du jeu officiel actuel (`control_bonus`/`control_deficit` remplacés par
`control`), pour que la comparaison reste valide si `MODEL_FEATURES` évolue.
"""
from aospy.analysis.cost import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con).reset_index(drop=True)
con.close()

print(f"Au contrôle attendu : {(frame.control == frame.control_expected).mean():.1%} des {len(frame)} unités"
      f" — bonus : {(frame.control_bonus > 0).sum()}, déficit : {(frame.control_deficit > 0).sum()}")

official = list(cost_model.MODEL_FEATURES)
raw = [f for f in official if f not in ("control_bonus", "control_deficit")] + ["control"]
expected_too = official + ["control_expected"]
for label, feats in [("A. contrôle brut (ancien)", raw),
                     ("B. bonus + déficit (officiel)", official),
                     ("C. B + contrôle attendu", expected_too)]:
    r = cost_model.fit_cost_model_factorial(features=feats, frame=frame.copy())
    coefs = {c.name: c for c in r.coefficients}
    shown = "  ".join(f"{k}={coefs[k].coef:+.1f}(p={coefs[k].p_value:.3f})"
                      for k in ("control", "control_bonus", "control_deficit", "control_expected") if k in coefs)
    print(f"{label:<32} R²={r.r_squared:.4f}  R² ajusté={r.adj_r_squared:.4f}  {shown}")

top = frame.assign(over=frame.control - frame.control_expected)
print("\nBonus de contrôle (hors épiques ≥ 10) :")
print(top[(top.over > 0) & (top.control < 10)][["name", "army_name", "control", "control_expected"]]
      .drop_duplicates("name").to_string(index=False))

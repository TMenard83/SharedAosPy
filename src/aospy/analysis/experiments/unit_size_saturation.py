"""Essai (concluant, adopté) : balayage de rendements croissants (terme quadratique) sur tous
les indicateurs numériques principaux du modèle de coût — hors `dmg_vs_save2_sq` (déjà un
carré adopté) et `effective_wounds`/`dmg_ranged_vs_save6` (déjà testés et écartés, cf.
`scratch/experiment_increasing_returns_ew_ranged.py`).

Un seul signal réel : `unit_size_sq` (p=0.002, gain R² ajusté +0.0009), robuste au retrait
des 5 unités à la taille la plus extrême (20 modèles — Clanrats, Plague Monks, Crypt Ghouls,
Zombies, Moonclan Shootas ; coefficient stable en magnitude, p=0.012 rogné). Tous les autres
candidats (`dmg_cv_vs_save4`, `charge_bonus_save2`, `move`, `control`, `wizard_level`,
`priest_level`) sont écartés (p > 0.17, gain R² ajusté nul ou négatif).

Lecture : une fois `unit_size_sq` ajouté, le coefficient linéaire de `unit_size` devient
franchement négatif (rabais de volume marqué sur les petites/moyennes tailles), compensé par
le carré positif au-delà d'une dizaine de modèles — GW semble facturer une prime sur les très
grosses hordes (contrôle d'objectif, difficulté à les effacer), pas seulement un rabais
continu. `cost_model.MODEL_FEATURES` utilise déjà `unit_size_sq` : ce script dérive donc la
variante « avant adoption » (`unit_size` seul) à partir du jeu officiel actuel plutôt que
l'inverse."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

FEATURES_BEFORE = tuple(f for f in cost_model.MODEL_FEATURES if f != "unit_size_sq")  # avant adoption
FEATURES_AFTER = cost_model.MODEL_FEATURES  # officiel actuel

model_before = cost_model.fit_cost_model_factorial(features=FEATURES_BEFORE, frame=frame.copy())
model_after = cost_model.fit_cost_model_factorial(features=FEATURES_AFTER, frame=frame.copy())

print(f"Avant (unit_size seul)      : R² = {model_before.r_squared:.4f}  R² ajusté = {model_before.adj_r_squared:.4f}")
print(f"Après (+ unit_size_sq)      : R² = {model_after.r_squared:.4f}  R² ajusté = {model_after.adj_r_squared:.4f}  (gain {model_after.adj_r_squared - model_before.adj_r_squared:+.4f})")
print()
for label, model in [("avant", model_before), ("après", model_after)]:
    print(f"-- {label} --")
    for c in model.coefficients:
        if "unit_size" in c.name:
            print(f"  {c.name:20s} {c.coef:+9.4f}  p={c.p_value:.3f}")
    print()

print("-- Robustesse : retrait des 5 unités à la plus grosse taille --")
frame_trim = frame.drop(index=frame.nlargest(5, "unit_size").index).reset_index(drop=True)
model_trim = cost_model.fit_cost_model_factorial(features=FEATURES_AFTER, frame=frame_trim.copy())
for c in model_trim.coefficients:
    if "unit_size" in c.name:
        print(f"  {c.name:20s} {c.coef:+9.4f}  p={c.p_value:.3f}")

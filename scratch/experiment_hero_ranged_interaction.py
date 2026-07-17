"""Essai (écarté, fragile) : ``C(is_hero):dmg_ranged_vs_save6`` — l'effet-prix du pool
tir est-il différent pour un héros que pour une troupe ? Motivé par
`analysis/experiments/melee_ranged_split.py` où l'ajout de cette interaction donnait le
meilleur R² ajusté testé (0.9173 → 0.9178) avec un coefficient borderline significatif
(p=0.050).

Trois angles pour juger la robustesse plutôt que le seul p-value du modèle combiné :

1. **Modèle factoriel, interaction seule** : gain R² ajusté minuscule (+0.0003), p=0.050
   pile à la limite conventionnelle.
2. **Régressions séparées héros/troupe** (`fit_segmented`, tous les coefficients libres,
   pas seulement celui-ci) : contraste net et cohérent avec l'intuition narrative — héros
   +0.77 (p=0.521, non significatif), troupe +3.30 (p<0.001, très significatif). Un héros
   payé pour sa durabilité/ses aptitudes ne voit pas son prix bouger avec son pool de tir ;
   une troupe, si.
3. **Robustesse aux points de levier** : en retirant les 3 unités au pool tir le plus élevé
   de chaque segment (6 unités sur 762), le contraste segmenté tient bon (héros -0.03
   p=0.981, troupe +2.66 p<0.001) — MAIS l'interaction du modèle combiné, elle, s'effondre
   (p=0.050 → p=0.185). Le test joint (une différence de deux coefficients) a moins de
   puissance que les deux régressions séparées et est sensible à une poignée d'unités à
   fort pool tir.

Conclusion : le motif narratif (« le tir compte moins pour le prix d'un héros ») est réel
et se voit clairement en régressions séparées, mais **le test statistique dans le modèle
combiné n'est pas assez robuste pour être adopté comme coefficient officiel** — gain de R²
négligeable, p à la limite, et qui disparaît sous un test de sensibilité modeste. Écarté de
`cost_model.FACTORIAL_INTERACTIONS` en l'état ; à revisiter si la base d'unités importées
grandit (plus de puissance statistique) plutôt que de forcer l'adoption maintenant."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

INTER_A = cost_model.FACTORIAL_INTERACTIONS  # officiel actuel
INTER_B = INTER_A + ("C(is_hero):dmg_ranged_vs_save6",)  # variante testée

model_a = cost_model.fit_cost_model_factorial(interactions=INTER_A, frame=frame.copy())
model_b = cost_model.fit_cost_model_factorial(interactions=INTER_B, frame=frame.copy())

print(f"Modèle A (officiel)                         : R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle B (+ C(is_hero):dmg_ranged_vs_save6) : R² = {model_b.r_squared:.4f}  R² ajusté = {model_b.adj_r_squared:.4f}  (gain {model_b.adj_r_squared - model_a.adj_r_squared:+.4f})")
print()
for c in model_b.coefficients:
    if "ranged" in c.name and "weapon_mix" not in c.name:
        print(f"  {c.name:40s} {c.coef:+9.3f}  p={c.p_value:.3f}")
print()

print("-- Régressions séparées héros/troupe (fit_segmented), jeu complet --")
for name, res in cost_model.fit_segmented(frame=frame.copy()).items():
    for c in res.coefficients:
        if c.name == "dmg_ranged_vs_save6":
            print(f"  {name:8s} n={res.n_obs:3d}  {c.name:25s} {c.coef:+8.3f}  p={c.p_value:.3f}")
print()

print("-- Robustesse : retrait des 3 unités à plus fort pool tir par segment --")
top_hero = frame[frame["is_hero"]].nlargest(3, "dmg_ranged_vs_save6").index
top_troupe = frame[~frame["is_hero"]].nlargest(3, "dmg_ranged_vs_save6").index
frame_trimmed = frame.drop(index=list(top_hero) + list(top_troupe)).reset_index(drop=True)

model_b_trim = cost_model.fit_cost_model_factorial(interactions=INTER_B, frame=frame_trimmed.copy())
print("Modèle B (rogné) :")
for c in model_b_trim.coefficients:
    if "ranged" in c.name and "weapon_mix" not in c.name:
        print(f"  {c.name:40s} {c.coef:+9.3f}  p={c.p_value:.3f}")
print()
print("Régressions séparées (rognées) :")
for name, res in cost_model.fit_segmented(frame=frame_trimmed.copy()).items():
    for c in res.coefficients:
        if c.name == "dmg_ranged_vs_save6":
            print(f"  {name:8s} n={res.n_obs:3d}  {c.name:25s} {c.coef:+8.3f}  p={c.p_value:.3f}")

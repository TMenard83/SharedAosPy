"""Essai : remplacer les features de dégât moyen (dmg_vs_save2/4/nosave,
dmg_ranged_vs_nosave) par leur plancher de confiance à 95 % (combat.damage_floor95
= moyenne − 1.6449·σ, même formule que `--floor95` sur les benchmarks), pour voir
si un dégât "pessimiste" prédit mieux les points que le dégât moyen actuel.
`dmg_cv_vs_save4` (irrégularité) est laissée inchangée pour isoler l'effet du seul
remplacement du point d'estimation — sinon la variance serait comptée deux fois.
N'écrit rien dans cost_model.py/features.py : comparaison ad hoc uniquement.
"""
import dataclasses

from aospy import combat, db, cost_model, repository
from aospy.features import _NO_MODS, _PROBE_NOSAVE, _PROBE_SAVE2, _ranged_only, compute_features

con = db.connect()
armies = {a.id: a for a in repository.list_armies(con)}
by_army = repository.load_all_units_with_weapons(con)
con.close()

rows_mean, rows_floor95 = [], []
for units in by_army.values():
    for unit in units:
        if unit.points <= 0:
            continue
        base = compute_features(unit)
        army = armies.get(unit.army_id)
        base = dataclasses.replace(
            base,
            grand_alliance=army.grand_alliance if army else "Order",
            army_name=army.name if army else "?",
        )
        rows_mean.append(base)

        mean2, _v2, std2 = combat.unit_damage_moments(unit, unit.models, _PROBE_SAVE2, _NO_MODS)
        mean_nosave, _vn, std_nosave = combat.unit_damage_moments(unit, unit.models, _PROBE_NOSAVE, _NO_MODS)
        ranged_unit = _ranged_only(unit)
        if ranged_unit.weapons:
            mean_r, _vr, std_r = combat.unit_damage_moments(ranged_unit, unit.models, _PROBE_NOSAVE, _NO_MODS)
            floor_ranged = combat.damage_floor95(mean_r, std_r)
        else:
            floor_ranged = 0.0

        floor2 = combat.damage_floor95(mean2, std2)
        floor_nosave = combat.damage_floor95(mean_nosave, std_nosave)
        floor_pen = (floor2 / floor_nosave) if floor_nosave > 0 else 0.0

        rows_floor95.append(dataclasses.replace(
            base,
            dmg_vs_save2=floor2,
            dmg_vs_nosave=floor_nosave,
            dmg_ranged_vs_nosave=floor_ranged,
            dmg_pen=floor_pen,
        ))

frame_mean = cost_model.feature_frame(features=rows_mean)
frame_floor95 = cost_model.feature_frame(features=rows_floor95)

model_mean = cost_model.fit_cost_model_factorial(frame=frame_mean)
model_floor95 = cost_model.fit_cost_model_factorial(frame=frame_floor95)

print(f"Modèle A (dégât moyen, actuel)   : R = {model_mean.r_squared**0.5:.4f}  R² = {model_mean.r_squared:.4f}  R² ajusté = {model_mean.adj_r_squared:.4f}  n = {model_mean.n_obs}")
print(f"Modèle B (plancher 95%, essai)   : R = {model_floor95.r_squared**0.5:.4f}  R² = {model_floor95.r_squared:.4f}  R² ajusté = {model_floor95.adj_r_squared:.4f}  n = {model_floor95.n_obs}")
print()
print(f"Gain de R² (brut)  : {model_floor95.r_squared - model_mean.r_squared:+.4f}")
print(f"Gain de R² ajusté  : {model_floor95.adj_r_squared - model_mean.adj_r_squared:+.4f}")
print()

by_name_mean = {c.name: c for c in model_mean.coefficients}
by_name_floor = {c.name: c for c in model_floor95.coefficients}
dmg_related = [n for n in by_name_mean if n in by_name_floor and ("dmg" in n)]
print("Coefficients des features de dégât (moyenne vs plancher 95%) :")
for n in dmg_related:
    a, b = by_name_mean[n], by_name_floor[n]
    print(f"  {n:35s} moyenne: {a.coef:+8.2f} (p={a.p_value:.3f})   floor95: {b.coef:+8.2f} (p={b.p_value:.3f})")

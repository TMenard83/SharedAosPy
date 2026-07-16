"""Essai : reprendre `dmg_pen_lineavg` (experiment_dmg_pen_lineavg.py, moyenne à
poids égal entre lignes d'attaque — perdant, R² ajusté 0.8725 < officiel 0.8765) mais
pondérer la moyenne par le nombre d'attaques de chaque ligne (`total_attacks` =
(weapon.attacks + bonus.attacks) × porteurs effectifs), au lieu d'une moyenne simple.
Objectif : corriger le défaut identifié — une ligne à 1 porteur pesait autant qu'une
ligne à 9 porteurs dans la moyenne simple ; ici chaque ligne pèse selon son propre
volume d'attaques, plus proche d'une pondération par "poids réel dans l'action".

dmg_pen_lineavg_w = Σ_i(attacks_i × dmg_save2_i) / Σ_i(attacks_i)

N'écrit rien dans cost_model.py/features.py : comparaison ad hoc uniquement.
"""
from aospy import db, cost_model, repository
from aospy.combat import _effective_counts, _intrinsic_bonus, expected_weapon_damage
from aospy.features import _NO_MODS, _PROBE_NOSAVE, _PROBE_SAVE2

con = db.connect()
frame = cost_model.feature_frame(con)
by_army = repository.load_all_units_with_weapons(con)
con.close()
frame = frame.reset_index(drop=True)


def line_avg_dmg_pen_weighted(unit) -> float:
    counts = _effective_counts(unit, unit.models)
    weighted_sum, total_weight = 0.0, 0.0
    for w, c in zip(unit.weapons, counts, strict=True):
        if c <= 0:
            continue
        bonus = _intrinsic_bonus(w.abilities, charged=False, defender_keywords=frozenset())
        total_attacks = (w.attacks + bonus.attacks) * c
        if total_attacks <= 0:
            continue
        dmg_nosave = expected_weapon_damage(w, c, _PROBE_NOSAVE, _NO_MODS)
        dmg_save2 = expected_weapon_damage(w, c, _PROBE_SAVE2, _NO_MODS)
        pen = (dmg_save2 / dmg_nosave) if dmg_nosave > 0 else 0.0
        product = dmg_nosave * pen  # == dmg_save2 de la ligne
        weighted_sum += total_attacks * product
        total_weight += total_attacks
    return weighted_sum / total_weight if total_weight > 0 else 0.0


lineavg_w_by_unit_id = {
    unit.id: line_avg_dmg_pen_weighted(unit)
    for units in by_army.values()
    for unit in units
}
frame["dmg_pen_lineavg_w"] = frame["unit_id"].map(lineavg_w_by_unit_id)

FEATURES_A = cost_model.MODEL_FEATURES  # officiel actuel : ... dmg_pen (ratio, somme) ...
FEATURES_B = tuple("dmg_vs_save2" if f == "dmg_pen" else f for f in cost_model.MODEL_FEATURES)
FEATURES_F = tuple("dmg_pen_lineavg_w" if f == "dmg_pen" else f for f in cost_model.MODEL_FEATURES)

model_a = cost_model.fit_cost_model_factorial(features=FEATURES_A, frame=frame.copy())
model_b = cost_model.fit_cost_model_factorial(features=FEATURES_B, frame=frame.copy())
model_f = cost_model.fit_cost_model_factorial(features=FEATURES_F, frame=frame.copy())

print(f"Modèle A (dmg_pen, ratio/somme, officiel)        : R = {model_a.r_squared**0.5:.4f}  R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle B (dmg_vs_save2, somme pondérée)          : R = {model_b.r_squared**0.5:.4f}  R² = {model_b.r_squared:.4f}  R² ajusté = {model_b.adj_r_squared:.4f}")
print(f"Modèle F (dmg_pen_lineavg_w, moyenne pondérée attaques): R = {model_f.r_squared**0.5:.4f}  R² = {model_f.r_squared:.4f}  R² ajusté = {model_f.adj_r_squared:.4f}")
print()
print(f"Gain R² ajusté (F vs A) : {model_f.adj_r_squared - model_a.adj_r_squared:+.4f}")
print(f"Gain R² ajusté (F vs B) : {model_f.adj_r_squared - model_b.adj_r_squared:+.4f}")
print()
for c in model_f.coefficients:
    if "dmg" in c.name:
        print(f"  {c.name:20s} {c.coef:+8.2f}  p={c.p_value:.3f}")

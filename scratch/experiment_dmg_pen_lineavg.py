"""Essai : `dmg_pen_lineavg` = moyenne, PAR PROFIL D'ARME ("ligne d'attaque"), du
produit (dégât moyen de la ligne × pénétration de la ligne), plutôt que le ratio
unitaire actuel `dmg_pen` (sur la SOMME des lignes) ou `dmg_vs_save2` (déjà testé
dans experiment_dmg_pen_weighted.py, lui aussi une somme sur les lignes).

Différence avec dmg_vs_save2 : dmg_vs_save2 = somme_lignes(dmg_nosave_i × pen_i)
pondère chaque ligne par son poids réel dans le dégât total (une ligne à 9 porteurs
pèse plus qu'une ligne à 1 porteur). dmg_pen_lineavg = moyenne_lignes(dmg_nosave_i ×
pen_i) donne un poids égal à chaque profil d'arme distinct, indépendamment du nombre
de porteurs — une mesure de la "qualité de pénétration typique de l'arsenal" plutôt
que du dégât total pondéré.
N'écrit rien dans cost_model.py/features.py : comparaison ad hoc uniquement.
"""
from aospy import db, cost_model, repository
from aospy.combat import _effective_counts, expected_weapon_damage
from aospy.features import _NO_MODS, _PROBE_NOSAVE, _PROBE_SAVE2

con = db.connect()
frame = cost_model.feature_frame(con)
by_army = repository.load_all_units_with_weapons(con)
con.close()
frame = frame.reset_index(drop=True)


def line_avg_dmg_pen(unit) -> float:
    counts = _effective_counts(unit, unit.models)
    products = []
    for w, c in zip(unit.weapons, counts, strict=True):
        if c <= 0:
            continue
        dmg_nosave = expected_weapon_damage(w, c, _PROBE_NOSAVE, _NO_MODS)
        dmg_save2 = expected_weapon_damage(w, c, _PROBE_SAVE2, _NO_MODS)
        pen = (dmg_save2 / dmg_nosave) if dmg_nosave > 0 else 0.0
        products.append(dmg_nosave * pen)  # == dmg_save2 de la ligne, gardé explicite pour lisibilité
    return sum(products) / len(products) if products else 0.0


lineavg_by_unit_id = {
    unit.id: line_avg_dmg_pen(unit)
    for units in by_army.values()
    for unit in units
}
frame["dmg_pen_lineavg"] = frame["unit_id"].map(lineavg_by_unit_id)

FEATURES_A = cost_model.MODEL_FEATURES  # officiel actuel : ... dmg_pen (ratio, somme) ...
FEATURES_B = tuple("dmg_vs_save2" if f == "dmg_pen" else f for f in cost_model.MODEL_FEATURES)
FEATURES_E = tuple("dmg_pen_lineavg" if f == "dmg_pen" else f for f in cost_model.MODEL_FEATURES)

model_a = cost_model.fit_cost_model_factorial(features=FEATURES_A, frame=frame.copy())
model_b = cost_model.fit_cost_model_factorial(features=FEATURES_B, frame=frame.copy())
model_e = cost_model.fit_cost_model_factorial(features=FEATURES_E, frame=frame.copy())

print(f"Modèle A (dmg_pen, ratio/somme, officiel)   : R = {model_a.r_squared**0.5:.4f}  R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle B (dmg_vs_save2, somme pondérée)     : R = {model_b.r_squared**0.5:.4f}  R² = {model_b.r_squared:.4f}  R² ajusté = {model_b.adj_r_squared:.4f}")
print(f"Modèle E (dmg_pen_lineavg, moyenne par ligne): R = {model_e.r_squared**0.5:.4f}  R² = {model_e.r_squared:.4f}  R² ajusté = {model_e.adj_r_squared:.4f}")
print()
print(f"Gain R² ajusté (E vs A) : {model_e.adj_r_squared - model_a.adj_r_squared:+.4f}")
print(f"Gain R² ajusté (E vs B) : {model_e.adj_r_squared - model_b.adj_r_squared:+.4f}")
print()
for c in model_e.coefficients:
    if "dmg" in c.name:
        print(f"  {c.name:20s} {c.coef:+8.2f}  p={c.p_value:.3f}")

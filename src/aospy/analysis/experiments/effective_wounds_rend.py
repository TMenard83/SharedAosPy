"""Essai (concluant, adopté) : `_effective_wounds` (features.py) supposait jusqu'ici un Rend
nul pour calculer la probabilité de succès de la save — optimiste, puisque `combat.py`
dégrade toujours la save réelle d'un attaquant par `defender.save + weapon.rend` et que la
quasi-totalité des profils d'arme de la base portent du Rend. Le Ward, lui, n'a besoin
d'aucun ajustement analogue : contrairement à la save, il n'est jamais modifié par le Rend
(règle AoS core) — seule la composante save de `effective_wounds` était donc biaisée.

`effective_wounds` n'a pas d'attaquant précis (c'est une caractéristique du seul défenseur),
donc pas de vrai Rend à appliquer : ce script teste un Rend "représentatif" constant, balayé
de 0 à 3, contre le Rend moyen réellement observé sur les profils d'arme importés (0,98
mêlée / 1,05 tir, pondéré par nombre de profils) pour vérifier que l'optimum statistique
coïncide avec ce qu'on observe dans les données plutôt que d'être un choix arbitraire.

`features._REPRESENTATIVE_REND` vaut déjà 1 (l'optimum ci-dessous) : ce script dérive donc la
variante "avant adoption" (Rend 0) en recalculant `effective_wounds` à la main depuis les
champs bruts (`wounds_total`/`save_num`/`ward_num`, déjà dans `UnitFeatures`) plutôt que
l'inverse, pour rester valide si `_REPRESENTATIVE_REND` change à l'avenir."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)


def _effective_wounds(wounds_total, save_num, ward_num, rend):
    save_eff = min(save_num + rend, 7)
    p_save = max(0.0, (7 - save_eff) / 6.0)
    p_ward = max(0.0, (7 - ward_num) / 6.0) if ward_num <= 6 else 0.0
    p_fail = (1 - p_save) * (1 - p_ward)
    return wounds_total / p_fail if p_fail > 0 else wounds_total * 6.0


for rend in (0, 1, 2, 3):
    col = f"ew_rend{rend}"
    frame[col] = frame.apply(
        lambda r, rend=rend: _effective_wounds(r["wounds_total"], r["save_num"], r["ward_num"], rend), axis=1,
    )
    feats = tuple(col if f == "effective_wounds" else f for f in cost_model.MODEL_FEATURES)
    inter = tuple(t.replace("effective_wounds", col) for t in cost_model.FACTORIAL_INTERACTIONS)
    model = cost_model.fit_cost_model_factorial(features=feats, interactions=inter, frame=frame.copy())
    marker = "  <- officiel (adopté)" if rend == 1 else ""
    print(f"Rend supposé = {rend}  :  R² = {model.r_squared:.4f}  R² ajusté = {model.adj_r_squared:.4f}{marker}")

print()
print("Rend moyen observé sur les profils d'arme de la base (pondéré par nombre de profils) :")
import duckdb  # noqa: E402
from aospy.persistence import repository  # noqa: E402
from collections import Counter  # noqa: E402

con = db.connect()
by_army = repository.load_all_units_with_weapons(con)
con.close()
rend_by_kind: dict[str, Counter] = {"melee": Counter(), "ranged": Counter()}
for units in by_army.values():
    for u in units:
        for w in u.weapons:
            rend_by_kind[w.kind][w.rend or 0] += 1
for kind, counter in rend_by_kind.items():
    total = sum(counter.values())
    avg = sum(r * n for r, n in counter.items()) / total
    print(f"  {kind:8s} moyenne = {avg:.2f}  (n={total} profils, répartition {dict(sorted(counter.items()))})")

"""Essai (concluant, adopté) : élimination arrière pas-à-pas sur l'ensemble des prédicteurs
du modèle de coût (`MODEL_FEATURES` + `CATEGORICAL_FEATURES`) — à chaque étape, retirer le
prédicteur dont le retrait dégrade le moins le R² ajusté (ou l'améliore), tant qu'un tel
retrait existe. Plus fiable qu'un retrait "un par un" isolé (chaque candidat testé seul contre
le modèle complet) : deux prédicteurs peuvent chacun sembler individuellement peu coûteux à
retirer, tout en étant, ensemble, irremplaçables (ils captent une part de signal partagée que
ni l'un ni l'autre ne capte plus une fois l'autre parti).

Verdict : seuls deux prédicteurs sont de purs poids morts, retirables sans aucune perte —
`dmg_cv_vs_save4` (irrégularité du dégât vs save 4+) et `move` (mouvement). Une fois les deux
partis, plus rien d'autre ne peut être retiré sans dégrader le R² ajusté : `dmg_vs_save2`,
`weapon_mix`, `unit_type`, `is_unique` (repérés comme candidats en test isolé) redeviennent
nécessaires — leur contribution individuelle est faible mais pas nulle une fois les vrais
doublons éliminés.

`cost_model.MODEL_FEATURES` a déjà retiré `dmg_cv_vs_save4`/`move` : ce script dérive donc la
variante « avant élimination » (les deux réintégrés) à partir du jeu officiel actuel plutôt
que l'inverse."""
from aospy.analysis import cost_model
from aospy.persistence import db

con = db.connect()
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)


def _fit(feats, cats, inter):
    return cost_model.fit_cost_model_factorial(
        features=tuple(feats), categorical=tuple(cats), interactions=tuple(inter), frame=frame.copy(),
    )


FEATS_BEFORE = list(cost_model.MODEL_FEATURES) + ["dmg_cv_vs_save4", "move"]  # avant élimination
CATS = list(cost_model.CATEGORICAL_FEATURES)
INTER = list(cost_model.FACTORIAL_INTERACTIONS)

model_before = _fit(FEATS_BEFORE, CATS, INTER)
model_after = _fit(cost_model.MODEL_FEATURES, CATS, INTER)

print(f"Avant élimination (+ dmg_cv_vs_save4, + move) : R² = {model_before.r_squared:.4f}  R² ajusté = {model_before.adj_r_squared:.4f}")
print(f"Après élimination (officiel actuel)            : R² = {model_after.r_squared:.4f}  R² ajusté = {model_after.adj_r_squared:.4f}  (gain {model_after.adj_r_squared - model_before.adj_r_squared:+.4f})")
print()

print("-- Recherche pas-à-pas complète (log), depuis le jeu 'avant élimination' --")
feats, cats, inter = list(FEATS_BEFORE), list(CATS), list(INTER)
current = _fit(feats, cats, inter)
print(f"Départ : R² ajusté = {current.adj_r_squared:.4f}  ({len(feats)} continues + {len(cats)} catégoriels)")
while True:
    candidates = []
    for f in feats:
        f2 = [x for x in feats if x != f]
        i2 = [t for t in inter if f not in t]
        candidates.append(("cont", f, _fit(f2, cats, i2).adj_r_squared))
    for c in cats:
        c2 = [x for x in cats if x != c]
        i2 = [t for t in inter if not t.startswith(f"C({c})")]
        candidates.append(("cat", c, _fit(feats, c2, i2).adj_r_squared))
    kind, name, new_adj = max(candidates, key=lambda x: x[2])
    if new_adj < current.adj_r_squared:
        break
    if kind == "cont":
        feats.remove(name)
        inter = [t for t in inter if name not in t]
    else:
        cats.remove(name)
        inter = [t for t in inter if not t.startswith(f"C({name})")]
    current = _fit(feats, cats, inter)
    print(f"  retiré {kind:5s} {name:22s} -> R² ajusté = {current.adj_r_squared:.4f}")

print()
print(f"Modèle final : {len(feats)} continues + {len(cats)} catégoriels, R² ajusté = {current.adj_r_squared:.4f}")

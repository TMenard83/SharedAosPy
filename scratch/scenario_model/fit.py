"""Ajustement des poids de carte par ridge (vers les poids curés), validation croisée liste par liste."""
import json, sys
import numpy as np
from harness import HAND, LISTS, sm
raws = json.load(open("scratch/output/scen_feats.json"))["raws"]
P = sorted(raws)
def Z(k):
    v = np.array([raws[p][k] for p in P]); return (v - v.mean()) / (v.std() or 1)
COMP = {
 "A": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["mobilite", "frappe", "vol"],
  "imp": ["degats"], "act": ["activations"], "tir": ["tir"]},
 "B": {
  "obj": ["ctrl_eff", "durabilite", "apt_objectifs", "models"],
  "mob": ["n_fast", "fast9", "vol", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "D": {
  "obj": ["ctrl_eff", "durabilite", "apt_objectifs", "models"],
  "mob": ["n_fast", "fast9", "vol"], "frap": ["frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "E": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["n_fast", "fast9", "vol"], "frap": ["frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "F": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["n_fast", "fast9", "vol", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "G": {
  "obj": ["ctrl_eff", "durabilite", "apt_objectifs"],
  "mob": ["n_fast", "fast9", "vol", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "H": {
  "obj": ["ctrl_eff", "durabilite", "apt_objectifs", "models"],
  "mob": ["n_fast", "fast9", "vol", "frappe"],
  "imp": ["degats"], "act": ["activations"], "tir": ["tir"]},
 "I": {
  "obj": ["ctrl_eff", "durabilite", "apt_objectifs", "models"],
  "mob": ["mobilite", "frappe", "vol"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "J": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["n_fast", "vol", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "K": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["fast9", "vol", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "L": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["n_fast", "vol", "frappe"],
  "imp": ["degats"], "act": ["activations"], "tir": ["tir"]},
 "M": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["n_fast", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
 "C": {
  "obj": ["controle", "durabilite", "apt_objectifs"],
  "mob": ["fast9", "n_fast", "frappe"],
  "imp": ["degats", "clear"], "act": ["activations"], "tir": ["tir"]},
}[sys.argv[1] if len(sys.argv) > 1 else "B"]
names = list(COMP)
X = np.stack([np.mean([Z(k) for k in ks], axis=0) for ks in COMP.values()], axis=1)
X = (X - X.mean(0)) / X.std(0)
idx = {p: i for i, p in enumerate(P)}
cards = sorted({k for p in HAND for k in HAND[p]})
scen, _ = sm.load_models()
# prior : poids curés actuels projetés sur les composantes
def prior(card):
    w = scen[card].weights
    return np.array([sum(w.get(k, 0) for k in ks) / 1.0 for ks in COMP.values()])
THR = [(0.9, 2), (0.3, 1), (-0.3 + 1e-9, 0), (-0.9 + 1e-9, -1)]
def note(v): return next((n for t, n in THR if v >= t), -2)
def predict(W):
    out = {}
    for c in cards:
        s = X @ W[c]; s = (s - s.mean()) / (s.std() or 1)
        out[c] = s
    return out
def fit(train_players, lam, gscale):
    W = {}
    for c in cards:
        ps = [p for p in train_players if c in HAND[p]]
        Xc = X[[idx[p] for p in ps]]; y = np.array([HAND[p][c] for p in ps], float)
        y = y - y.mean()  # pas de décalage par carte (somme nulle sur la ligue)
        pr = prior(c); pr = pr / (np.linalg.norm(pr) or 1) * gscale
        A = Xc.T @ Xc + lam * np.eye(len(names)); b = Xc.T @ y + lam * pr
        W[c] = np.linalg.solve(A, b)
    return W
def score(pred, players):
    pairs = [(HAND[p][c], note(pred[c][idx[p]]), p) for p in players for c in HAND[p] if c in pred]
    h = np.array([a for a, _, _ in pairs]); m = np.array([b for _, b, _ in pairs])
    # intra-liste
    hc = h.astype(float).copy(); mc = m.astype(float).copy()
    for p in set(q for *_, q in pairs):
        ii = [i for i, x in enumerate(pairs) if x[2] == p]; hc[ii] -= hc[ii].mean(); mc[ii] -= mc[ii].mean()
    return dict(same=(h == m).mean(), near=(abs(h - m) <= 1).mean(), r=np.corrcoef(h, m)[0, 1],
                rin=np.corrcoef(hc, mc)[0, 1])
hp = [p for p in P if p in HAND]
base = {c: prior(c) for c in cards}
print("prior (poids curés projetés) :", {k: round(v, 3) for k, v in score(predict(base), hp).items()})
for lam in [0.3, 1, 3, 10, 30, 100]:
    for g in [0.5, 1.0]:
        preds = {c: np.zeros(len(P)) for c in cards}
        cvp = []
        for p in hp:  # leave-one-list-out
            W = fit([q for q in hp if q != p], lam, g)
            pr = predict(W)
            cvp.append((p, {c: pr[c] for c in cards}))
        # assemble : pour chaque liste sa prédiction hors échantillon
        pairs_pred = {c: np.zeros(len(P)) for c in cards}
        for p, pr in cvp:
            for c in cards: pairs_pred[c][idx[p]] = pr[c][idx[p]]
        s = score(pairs_pred, hp)
        print(f"lam={lam:5} g={g} CV :", {k: round(v, 3) for k, v in s.items()})
lam = float(sys.argv[2]) if len(sys.argv) > 2 else 3
W = fit(hp, lam, 1.0)
print("\nin-sample lam", lam, {k: round(v, 3) for k, v in score(predict(W), hp).items()})
for c in cards: print(f"  {c:20s}", " ".join(f"{n}={w:+.2f}" for n, w in zip(names, W[c])), "| prior", " ".join(f"{x:+.1f}" for x in prior(c)))

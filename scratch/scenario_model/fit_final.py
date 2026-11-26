"""Poids finaux : ridge (λ=3) sur 5 composantes, vers les poids curés ; écrit les poids par indicateur."""
import json, sys
import numpy as np
import harness as H
from harness import HAND, LISTS, sm
pl = H.pool()
P = sorted(pl)
COMP = {"obj": ["controle", "durabilite", "apt_objectifs"], "mob": ["rapides", "part_rapide", "vol", "frappe"],
        "imp": ["degats", "nettoyage"], "act": ["activations"], "tir": ["tir"]}
Zm = {k: np.array([pl[p].z[k] for p in P]) for k in sm.INDICATORS}
raw = {c: np.mean([Zm[k] for k in ks], axis=0) for c, ks in COMP.items()}
sd = {c: raw[c].std() for c in COMP}
X = np.stack([raw[c] / sd[c] for c in COMP], axis=1)
idx = {p: i for i, p in enumerate(P)}
d0 = json.load(open("scratch/scenario_model/modele_scenarios_2026-11-25.json"))
cent = sm.centered_weights(d0["scenarios"], d0["_centrage"])
cards = list(d0["scenarios"])
def prior(c):
    w = cent[c]; v = np.array([sum(w.get(k, 0) for k in ks) for ks in COMP.values()]); return v / (np.linalg.norm(v) or 1)
lam = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
hp = [p for p in P if p in HAND]
out = {}
for c in cards:
    ps = [p for p in hp if c in HAND[p]]
    Xc = X[[idx[p] for p in ps]]; y = np.array([HAND[p][c] for p in ps], float); y -= y.mean()
    W = np.linalg.solve(Xc.T @ Xc + lam * np.eye(len(COMP)), Xc.T @ y + lam * prior(c))
    mw = {}
    for (comp, ks), w in zip(COMP.items(), W):
        for k in ks: mw[k] = mw.get(k, 0) + w / (len(ks) * sd[comp])
    s = 2.0 / max(abs(v) for v in mw.values())
    out[c] = {k: round(v * s * 4) / 4 for k, v in sorted(mw.items(), key=lambda kv: -abs(kv[1])) if round(v * s * 4)}
json.dump(out, open("scratch/output/scen_weights.json", "w"), ensure_ascii=False, indent=1)
for c, w in out.items(): print(f"{c:20s}", w)

"""Banc d'essai du modèle de scénario : listes en cache, notes à la main, métriques."""
import json, math, pickle, sys
from pathlib import Path
from aospy.l3 import scenario_model as sm

LISTS = pickle.load(open("scratch/output/scenario_lists.pkl", "rb"))
NOTES = json.loads((sm.DATA / "notes_scenarios.json").read_text(encoding="utf-8"))
HAND = {p: {k: sm.NUM[v[0]] for k, v in j["notes"].items()} for t in NOTES["equipes"].values() for p, j in t["joueurs"].items()}

def pool(raw_fn=sm.raw_indicators):
    return sm.standardize({p: raw_fn(al) for p, al in LISTS.items()})

def metrics(scen, pl, verbose=False):
    pairs = [(HAND[p][k], sm.NUM[sm.evaluate(scen[k], pl[p], pl).note], p, k)
             for p in LISTS if p in HAND for k in scen if k in HAND[p]]
    n = len(pairs); h = [a for a, *_ in pairs]; m = [b for _, b, *_ in pairs]
    mh, mm = sum(h)/n, sum(m)/n
    cov = sum((a-mh)*(b-mm) for a, b in zip(h, m)); r = cov / (sum((a-mh)**2 for a in h)**.5 * sum((b-mm)**2 for b in m)**.5)
    out = dict(n=n, same=sum(a == b for a, b in zip(h, m))/n, near=sum(abs(a-b) <= 1 for a, b in zip(h, m))/n, r=r, mh=mh, mm=mm,
               mae=sum(abs(a-b) for a, b in zip(h, m))/n)
    return out, pairs

def fmt(o):
    return f"n={o['n']} identiques {o['same']:.0%} à un cran {o['near']:.0%} r={o['r']:+.2f} mae={o['mae']:.2f} (main {o['mh']:+.2f}, modèle {o['mm']:+.2f})"

if __name__ == "__main__":
    scen, _ = sm.load_models()
    pl = pool()
    o, pairs = metrics(scen, pl)
    print(fmt(o))
    print("listes notées :", sorted({p for _, _, p, _ in pairs}))

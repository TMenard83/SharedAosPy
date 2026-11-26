import sys
from harness import *
scen, _ = sm.load_models(); pl = pool()
NJ = {p: j for t in NOTES["equipes"].values() for p, j in t["joueurs"].items()}
for spec in sys.argv[1:]:
    p, *cs = spec.split(":")
    z = pl[p].z
    print(f"\n## {p} ({LISTS[p].faction}) — " + " ".join(f"{k}={z[k]:+.1f}" for k in ("controle","activations","durabilite","degats","nettoyage","rapides","part_rapide","vol","frappe","tir")))
    for c in cs or NJ[p]["notes"]:
        c = next(k for k in scen if k.startswith(c))
        r = sm.evaluate(scen[c], pl[p], pl)
        h = NJ[p]["notes"].get(c, ["?", ""])
        print(f"- {c}: main {h[0]} / modèle {r.note} ({r.value:+.2f}; {', '.join(f'{k} {v:+.1f}' for k, v in r.top)}) — {h[1][:330]}")

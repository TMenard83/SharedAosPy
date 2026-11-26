from harness import *
from collections import Counter
import numpy as np
scen, _ = sm.load_models(); pl = pool()
S = {2:"++",1:"+",0:"=",-1:"−",-2:"−−"}
vals = [(HAND[p][k], sm.evaluate(scen[k], pl[p], pl).value, p) for p in pl if p in HAND for k in scen if k in HAND[p]]
print("main :", Counter(S[h] for h, _, _ in vals))
for s in [1.0, 0.85, 0.7, 0.6, 0.5]:
    for off in [0.0, 0.3]:
        m = [sm.NUM[sm.note_of(v * s + off)] for _, v, _ in vals]; h = [x for x, _, _ in vals]
        hc = np.array(h, float); mc = np.array(m, float)
        for p in set(q for *_, q in vals):
            ii = [i for i, x in enumerate(vals) if x[2] == p]; hc[ii] -= hc[ii].mean(); mc[ii] -= mc[ii].mean()
        print(f"s={s} off={off} identiques {np.mean(np.array(h)==np.array(m)):.0%} à un cran {np.mean(abs(np.array(h)-np.array(m))<=1):.0%} "
              f"r={np.corrcoef(h,m)[0,1]:+.2f} r_intra={np.corrcoef(hc,mc)[0,1]:+.2f} mae={np.mean(abs(np.array(h)-np.array(m))):.2f}",
              Counter(S[x] for x in m) if off == 0 else "")

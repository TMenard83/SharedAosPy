from harness import *
from collections import defaultdict
scen, _ = sm.load_models(); pl = pool()
o, pairs = metrics(scen, pl)
S = {2:"++",1:"+",0:"=",-1:"−",-2:"−−"}
byp = defaultdict(list)
for h, m, p, k in pairs: byp[p].append((k, h, m))
print("Shadow :", [(k, S[h], S[m]) for k, h, m in byp["Shadow"]])
rows = sorted(byp.items(), key=lambda kv: -sum(abs(h-m) for _, h, m in kv[1]) / len(kv[1]))
for p, v in rows[:12]:
    lm_h = sum(h for _, h, _ in v)/len(v); lm_m = sum(m for _, _, m in v)/len(v)
    print(f"{p:14s} {LISTS[p].faction[:28]:28s} mae {sum(abs(h-m) for _, h, m in v)/len(v):.2f} moy main {lm_h:+.1f} modèle {lm_m:+.1f} |",
          " ".join(f"{k[:8]}:{S[h]}/{S[m]}" for k, h, m in v if abs(h-m) >= 2))

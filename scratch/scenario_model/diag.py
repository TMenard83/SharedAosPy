from harness import *
from collections import defaultdict
scen, _ = sm.load_models(); pl = pool()
o, pairs = metrics(scen, pl)
# décomposition main : part entre listes / intra-liste
byp = defaultdict(list); byk = defaultdict(list)
for h, m, p, k in pairs: byp[p].append((h, m)); byk[k].append((h, m))
def corr(xs):
    a=[x for x,_ in xs]; b=[y for _,y in xs]; n=len(xs); ma=sum(a)/n; mb=sum(b)/n
    sa=sum((x-ma)**2 for x in a)**.5; sb=sum((y-mb)**2 for y in b)**.5
    return sum((x-ma)*(y-mb) for x,y in xs)/(sa*sb) if sa and sb else float('nan')
tot = sum((h-o['mh'])**2 for h,*_ in pairs)
between = sum(len(v)*(sum(h for h,_ in v)/len(v)-o['mh'])**2 for v in byp.values())
print(f"variance main entre listes {between/tot:.0%}")
lm = [(sum(h for h,_ in v)/len(v), sum(m for _,m in v)/len(v)) for v in byp.values()]
print(f"corr moyennes par liste {corr(lm):+.2f}")
within = [(h - sum(x for x,_ in byp[p])/len(byp[p]), m - sum(y for _,y in byp[p])/len(byp[p])) for h,m,p,k in pairs]
print(f"corr intra-liste {corr(within):+.2f}")
print("par carte : n, moy main, moy modèle, corr")
for k,v in byk.items(): print(f"  {k:20s} {len(v):3d} {sum(h for h,_ in v)/len(v):+.2f} {sum(m for _,m in v)/len(v):+.2f} {corr(v):+.2f}")

from harness import *
from feats import feats
from collections import defaultdict
raws = {p: feats(al) for p, al in LISTS.items()}
keys = list(next(iter(raws.values())))
def z(k):
    v=[raws[p][k] for p in raws]; mu=sum(v)/len(v); sd=(sum((x-mu)**2 for x in v)/len(v))**.5 or 1
    return {p:(raws[p][k]-mu)/sd for p in raws}
Z={k:z(k) for k in keys}
import json; json.dump({"raws":raws}, open("scratch/output/scen_feats.json","w"))
cards = sorted({k for p in HAND for k in HAND[p]})
# corr intra-liste : note main centrée par liste vs z
def corr(a,b):
    n=len(a); ma=sum(a)/n; mb=sum(b)/n; sa=sum((x-ma)**2 for x in a)**.5; sb=sum((y-mb)**2 for y in b)**.5
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/(sa*sb) if sa and sb else 0
print("corr. par carte (note main brute vs z indicateur)")
print(f"{'':12s}"+"".join(f"{c[:7]:>8s}" for c in cards)+"  moyL")
lm={p:sum(HAND[p].values())/len(HAND[p]) for p in HAND}
for k in keys:
    row=[]
    for c in cards:
        ps=[p for p in HAND if c in HAND[p] and p in Z[k]]
        row.append(corr([HAND[p][c] for p in ps],[Z[k][p] for p in ps]))
    ps=list(HAND)
    print(f"{k:12s}"+"".join(f"{x:+8.2f}" for x in row)+f"{corr([lm[p] for p in ps],[Z[k][p] for p in ps]):+6.2f}")

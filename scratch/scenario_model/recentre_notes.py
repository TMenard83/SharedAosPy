"""Recentre les notes à la main de notes_scenarios.json (2026-11-26, validé par l'utilisateur).

Convention : une note se lit par rapport aux 54 listes de la ligue sur cette carte. Par carte : l'ordre des listes
vient de la main (égalités départagées par le modèle), on ne bouge que le nombre de crans qui amène la
moyenne de la main sur celle du modèle (mêmes listes), en commençant par les plus gros écarts main − modèle ;
une note ne bouge que d'un cran au plus. --write écrit le fichier (copie de l'original à côté).
"""
import json, shutil, sys
from collections import Counter
from aospy.l3 import scenario_model as sm, tactics

F = sm.DATA / "notes_scenarios.json"
INV = {v: k for k, v in sm.NUM.items()}
N = json.loads(F.read_text(encoding="utf-8"))
hand = {p: j for T in N["equipes"].values() for p, j in T["joueurs"].items()}
scen, _ = sm.load_models()
pool = tactics.load_pool()
pool = pool[0] if isinstance(pool, tuple) else pool
changes = []
for k, m in scen.items():
    rows = [(p, sm.NUM[j["notes"][k][0]], sm.evaluate(m, pool[p], pool).value) for p, j in hand.items() if k in j["notes"]]
    mm = sum(sm.NUM[sm.note_of(v)] for _, _, v in rows) / len(rows)
    shift = round(sum(h for _, h, _ in rows) - mm * len(rows))  # crans à retirer (> 0) ou ajouter (< 0)
    sign = -1 if shift > 0 else 1
    cand = sorted(rows, key=lambda r: sign * (r[1] - r[2]))  # plus gros écart main − modèle d'abord
    for p, h, v in cand[: abs(shift)]:
        changes.append((k, p, h, h + sign, v))
by = Counter((c[0], c[3] - c[2]) for c in changes)
for k in scen:
    rows = [sm.NUM[j["notes"][k][0]] for j in hand.values() if k in j["notes"]]
    d = sum(c[3] - c[2] for c in changes if c[0] == k)
    print(f"{k:22} n={len(rows):2} moyenne {sum(rows)/len(rows):+.2f} → {(sum(rows)+d)/len(rows):+.2f}  (−1 : {by[(k,-1)]}, +1 : {by[(k,1)]})")
print("notes changées :", len(changes), "sur", sum(len(j['notes']) for j in hand.values()))
for c in changes:
    print(f"  {c[0]} | {c[1]} : {INV[c[2]]} → {INV[c[3]]} (modèle {c[4]:+.1f})")
if "--write" in sys.argv:
    shutil.copy(F, F.with_name("notes_scenarios.main_2026-11-26.json"))
    for k, p, h, new, v in changes:
        hand[p]["notes"][k][0] = INV[new]
    F.write_text(json.dumps(N, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("écrit", F)

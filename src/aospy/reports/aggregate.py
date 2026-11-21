"""Exporte en JSON (facultatif) le pool de classement que les registres lisent en
direct (`repository.get_ranking_pool`) : unit_benchmark agrégé par unité (scénario
sans charge *déclarée*, édition TM), héros compris (aospy unit benchmark-all
--charge none --attacker-mode floor66 --defender-mode mean --include-heroes).
Les registres combat_*/best_* n'ont plus besoin de ce fichier ; il sert à
consulter ou archiver un instantané. Le scénario « attaquant chargé »
(`--charge a/both`) est abandonné : en AoS4 la charge ne donne de bonus que via
un texte d'aptitude propre à certains profils d'arme, donc la quasi-totalité des
unités ne voient aucune différence entre les deux scénarios (cf. orchestration/README.md, « Side modifiers »).
Cela dit, deux règles optionnelles de `DuelRules` — `rule-charge-threshold` et
`rule-double-shoot` — restent actives par défaut sur ce run malgré `--charge
none` : la première déduit l'état chargé (et son bonus d'arme) du seul écart de
Move entre attaquant et défenseur, indépendamment de `--charge` ; la seconde
double le dégât à distance du camp le plus véloce quand l'autre, plus court de
portée, ne peut le rejoindre. Un attaquant rapide ou véloce à distance peut donc
voir un bonus s'appliquer malgré le « sans charge » du scénario (cf.
`orchestration/benchmark.py::DuelRules`/`_mods`).

Édition TM : dégât infligé (A→B) lu au plancher pessimiste 66% de confiance
(damage_floor66 — ce qu'on peut « garantir » en attaquant), dégât encaissé en
retour (B→A) lu à l'espérance (moyenne — riposte « typique », pas pire cas).
Lecture asymétrique délibérée : pts_destroyed/pts_lost/pts_net/roi héritent
donc chacun d'un niveau de confiance différent selon le sens du duel.

`roi_floor95_pct`/`roi_floor66_pct`/`roi_floor20_pct` sont trois quantiles de la
distribution du ROI *entre duels* d'une même unité (quantile_cont sur `b.roi`,
aux seuils 5e/34e/80e percentile) — un axe orthogonal au plancher
`attacker_mode='floor66'` ci-dessus, qui lit le dégât *à l'intérieur* d'un seul
duel (distribution exacte des dés, par convolution — cf. `engine/combat.py::distribution_floor`,
pas une approximation gaussienne) : Stabilité (floor95, pire cas quasi-garanti),
Fiabilité (floor66, plancher pessimiste plus permissif), Explosivité (floor20,
plafond optimiste). `avg_floor_roi_pct` (moyenne simple des trois, pas le ROI
moyen brut `avg_roi_pct`) est le critère de tri des registres de combat
(combat_unites.py/combat_heros.py) et sert aussi de composante « combat » z_roi
au score combiné de best_unites.py/best_heros.py (cf. `analysis/cost/scoring.combined_score`)."""
import json

from ..persistence import db, repository

OUT_PATH = "scratch/output/per_unit_nocharge_floor66_TM.json"

con = db.connect()
data = sorted(repository.get_ranking_pool(con), key=lambda r: r["avg_floor_roi_pct"], reverse=True)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print(OUT_PATH, len(data), "unites (dont",
      sum(1 for r in data if r["is_hero"]), "heros)")

con.close()

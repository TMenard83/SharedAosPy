"""Agrège unit_benchmark (scénario sans charge *déclarée*, édition TM) en un JSON
par unité, héros compris (aospy unit benchmark-all --charge none --attacker-mode
floor66 --defender-mode mean --include-heroes). Le scénario « attaquant chargé »
(`--charge a/both`) est abandonné : en AoS4 la charge ne donne de bonus que via
un texte d'aptitude propre à certains profils d'arme, donc la quasi-totalité des
unités ne voient aucune différence entre les deux scénarios (cf. CLAUDE.md).
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
au score combiné de best_unites.py/best_heros.py (cf. cost_common.combined_score)."""
import json

from ..persistence import db

con = db.connect()

QUERY = """
with agg as (
    select
        u.id as unit_id,
        u.name as name,
        a.name as army,
        a.grand_alliance as grand_alliance,
        u.points as points,
        u.is_hero as is_hero,
        avg(b.roi) * 100.0 as avg_roi_pct,
        avg(b.pts_net) as avg_pts_net,
        100.0 * avg(case when b.roi > 0 then 1.0 else 0.0 end) as pct_positive,
        quantile_cont(b.roi, 0.05) * 100.0 as roi_floor95_pct,
        quantile_cont(b.roi, 0.34) * 100.0 as roi_floor66_pct,
        quantile_cont(b.roi, 0.80) * 100.0 as roi_floor20_pct
    from unit_benchmark b
    join unit u on u.id = b.attacker_id
    join army a on a.id = u.army_id
    where b.attacker_charged = false and b.defender_charged = false
      and b.attacker_mode = 'floor66' and b.defender_mode = 'mean'
    group by u.id, u.name, a.name, a.grand_alliance, u.points, u.is_hero
)
select
    *,
    (roi_floor95_pct + roi_floor66_pct + roi_floor20_pct) / 3.0 as avg_floor_roi_pct
from agg
order by avg_floor_roi_pct desc
"""

rows = con.execute(QUERY).fetchall()
cols = ["unit_id", "name", "army", "grand_alliance", "points", "is_hero",
        "avg_roi_pct", "avg_pts_net", "pct_positive",
        "roi_floor95_pct", "roi_floor66_pct", "roi_floor20_pct", "avg_floor_roi_pct"]
data = [dict(zip(cols, r)) for r in rows]
OUT_PATH = "scratch/per_unit_nocharge_floor66_TM.json"
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print(OUT_PATH, len(data), "unites (dont",
      sum(1 for r in data if r["is_hero"]), "heros)")

con.close()

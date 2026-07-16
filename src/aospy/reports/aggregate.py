"""Agrège unit_benchmark (scénario sans charge, édition TM) en un JSON par
unité, héros compris (aospy unit benchmark-all --charge none --attacker-mode
floor80 --defender-mode mean --include-heroes). Le scénario « attaquant chargé »
est abandonné : en AoS4 la charge ne donne de bonus que via un texte d'aptitude
propre à certains profils d'arme, donc la quasi-totalité des unités ne voient
aucune différence entre les deux scénarios (cf. CLAUDE.md).

Édition TM : dégât infligé (A→B) lu au plancher pessimiste 80% de confiance
(damage_floor80 — ce qu'on peut « garantir » en attaquant), dégât encaissé en
retour (B→A) lu à l'espérance (moyenne — riposte « typique », pas pire cas).
Lecture asymétrique délibérée : pts_destroyed/pts_lost/pts_net/roi héritent
donc chacun d'un niveau de confiance différent selon le sens du duel."""
import json

from ..persistence import db

con = db.connect()

QUERY = """
select
    u.id as unit_id,
    u.name as name,
    a.name as army,
    a.grand_alliance as grand_alliance,
    u.points as points,
    u.is_hero as is_hero,
    avg(b.roi) * 100.0 as avg_roi_pct,
    avg(b.pts_net) as avg_pts_net,
    median(b.roi) * 100.0 as median_roi_pct,
    100.0 * avg(case when b.roi > 0 then 1.0 else 0.0 end) as pct_positive,
    min(b.roi) * 100.0 as min_roi_pct,
    max(b.roi) * 100.0 as max_roi_pct
from unit_benchmark b
join unit u on u.id = b.attacker_id
join army a on a.id = u.army_id
where b.attacker_charged = false and b.defender_charged = false
  and b.attacker_mode = 'floor80' and b.defender_mode = 'mean'
group by u.id, u.name, a.name, a.grand_alliance, u.points, u.is_hero
order by avg_roi_pct desc
"""

rows = con.execute(QUERY).fetchall()
cols = ["unit_id", "name", "army", "grand_alliance", "points", "is_hero",
        "avg_roi_pct", "avg_pts_net", "median_roi_pct", "pct_positive",
        "min_roi_pct", "max_roi_pct"]
data = [dict(zip(cols, r)) for r in rows]
with open("scratch/per_unit_nocharge_TM.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("per_unit_nocharge_TM.json", len(data), "unites (dont",
      sum(1 for r in data if r["is_hero"]), "heros)")

con.close()

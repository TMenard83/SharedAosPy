"""Agrège unit_benchmark (scratch/aospy_two_rules.duckdb — scénario --charge
none, tir double + seuil de charge 30% actifs, plancher 66% attaquant /
espérance défenseur) en un JSON par unité, miroir de
`aospy.reports.aggregate` mais sur le scénario des 2 règles optionnelles au
lieu du scénario standard "sans charge" édition TM. Plancher 66% (au lieu de
80% côté édition TM) : lecture pessimiste plus permissive, cf.
`engine/combat.py::damage_floor66`."""
import json

import duckdb

DB_PATH = "scratch/aospy_two_rules.duckdb"
OUT_PATH = "scratch/output/essai_regles_optionnelles/per_unit_regles_floor66.json"

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
where b.attacker_mode = 'floor66' and b.defender_mode = 'mean'
group by u.id, u.name, a.name, a.grand_alliance, u.points, u.is_hero
order by avg_roi_pct desc
"""

con = duckdb.connect(DB_PATH, read_only=True)
rows = con.execute(QUERY).fetchall()
cols = [d[0] for d in con.description]
con.close()

data = [dict(zip(cols, r)) for r in rows]
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
print(OUT_PATH, len(data), "unites (dont", sum(1 for r in data if r["is_hero"]), "heros)")

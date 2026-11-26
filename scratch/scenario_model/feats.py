"""Indicateurs candidats (bruts) pour le modèle de scénario."""
import math
from aospy.domain.models import Unit
from aospy.l3 import scenario_model as sm
from aospy.l3.matchups import _ward_fail, unit_damage

CONT = Unit(name="contesteur", army_id=0, move=5, save=4, health=2, control=1, models=5, points=120)  # 10 PV, Sv4+
ELITE = Unit(name="élite", army_id=0, move=5, save=3, health=4, control=1, models=3, points=180)  # 12 PV, Sv3+
CONT_EHP = 10 / (1 - 0)  # PV

def eff_move(e):
    return e.unit.move + (2.0 if "FLY" in e.unit.keywords else 0.0)

def feats(al):
    r = sm.raw_indicators(al)
    pts = al.points or 1
    clear = clear_e = 0.0; dmg_c = 0.0
    for e in al.entries:
        d, _, _ = unit_damage(e.unit, e.models, CONT)
        de, _, _ = unit_damage(e.unit, e.models, ELITE)
        dmg_c += d
        clear += min(1.0, d / 10)
        clear_e += min(1.0, de / 12)
    fast = [e for e in al.entries if eff_move(e) >= 9]
    r.update(
        fast9=sum(e.points for e in fast) / pts,
        fast12=sum(e.points for e in al.entries if eff_move(e) >= 12) / pts,
        n_fast=float(len(fast)),
        avg_move=al.avg_move,
        ctrl_fast=math.log(1 + sum(e.unit.control * e.models for e in fast)),
        ctrl_eff=math.log(al.control_eff + 1),
        clear=clear, clear_e=clear_e,
        dmg_c=math.log(dmg_c + 1),
        monsters=float(al.monsters),
        big=float(max((e.points for e in al.entries), default=0)) / pts,  # concentration (Death Star)
        models=math.log(sum(e.models for e in al.entries)),
        plan=float(al.plan),
        apt=al.apt,
    )
    return r

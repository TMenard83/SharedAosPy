"""Mesurer l'effet d'un changement de règles d'aptitudes sur les mariages châssis × aptitude (couche 3).

Outil de travail des grilles de mariage (`analysis/layers/marriage.py`), utilisable sans session Claude :

    tm-aospy-mariages check [--family soin] [-n 15]   # copie la base, rejoue analyze + encounter build, compare
    tm-aospy-mariages snap OUT.json [--db X]          # instantané JSON des mariages et des aptitudes
    tm-aospy-mariages diff A.json B.json [--family X] [-n 15]
    tm-aospy-mariages dump FAMILLE [--db X]           # couples d'une famille : texte, effets, porteurs

`check` travaille sur une copie (scratch/output/marriage_check.duckdb, supprimée à la fin) : la base
`data/aospy.duckdb` n'est pas modifiée. Pour l'appliquer : `aospy ability analyze` puis `aospy encounter build`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "aospy.duckdb"
WORK = ROOT / "scratch" / "output"


def snapshot(db: Path) -> dict:
    c = duckdb.connect(str(db), read_only=True)
    mar = {}
    for uid, aid, ab, un, fam, expo, d, s, f, a, r, m in c.execute(
        """SELECT m.unit_id, m.ability_uid, m.ability_name, u.name, m.family, m.exposure, m.p_trigger, m.survival,
                  m.tempo, m.amplification, m.role_fit, m.marriage
           FROM ability_marriage m JOIN unit u ON u.id = m.unit_id"""
    ).fetchall():
        mar[f"{uid}|{aid}"] = dict(ability=ab, unit=un, family=fam, expo=expo, D=d, S=s, F=f, A=a, R=r, marriage=m)
    abil = {
        u: dict(name=n, family=f, verdict=v, power=p)
        for u, n, f, v, p in c.execute("SELECT uid, name, family, verdict, power FROM ability").fetchall()
    }
    c.close()
    return {"marriage": mar, "ability": abil}


def _fmt(r: dict) -> str:
    return (
        f"{r['family'][:10]:10} {r['expo']:7} D{r['D']:.2f} S{r['S']:.2f} F{r['F']:.2f} "
        f"A{r['A']:.2f} R{r['R']:.2f} M{r['marriage']:.3f}"
    )


def diff(a: dict, b: dict, family: str | None = None, n: int = 15) -> None:
    ma, mb = a["marriage"], b["marriage"]
    print(f"mariages {len(ma)} -> {len(mb)} | ajoutés {len(set(mb) - set(ma))}, retirés {len(set(ma) - set(mb))}")
    common = [k for k in set(ma) & set(mb) if not family or family in (ma[k]["family"], mb[k]["family"])]
    ch = [
        (mb[k]["marriage"] - ma[k]["marriage"], ma[k], mb[k])
        for k in common
        if abs(mb[k]["marriage"] - ma[k]["marriage"]) > 1e-3 or ma[k]["family"] != mb[k]["family"]
        or ma[k]["expo"] != mb[k]["expo"]
    ]
    if family:
        moved = [k for k in common if ma[k]["family"] != mb[k]["family"]]
        stay = [k for k in common if k not in moved]
        print(f"famille {family} : {len(common)} couples, {len(moved)} changent de famille "
              f"{dict(Counter((ma[k]['family'], mb[k]['family']) for k in moved))}")
        if stay:
            up = sum(mb[k]["marriage"] > ma[k]["marriage"] + 1e-3 for k in stay)
            dn = sum(mb[k]["marriage"] < ma[k]["marriage"] - 1e-3 for k in stay)
            avg = lambda m: sum(m[k]["marriage"] for k in stay) / len(stay)  # noqa: E731
            print(f"  restés {len(stay)} : moyenne {avg(ma):.3f} -> {avg(mb):.3f}, {up} hausses, {dn} baisses")
    print("changés", len(ch))
    ch.sort(key=lambda t: t[0])
    for label, part in (("BAISSES", ch[:n]), ("HAUSSES", [t for t in ch[::-1][:n] if t[0] > 0])):
        print("==", label)
        for d, x, y in part:
            print(f"{d:+.3f} {y['ability'][:28]:28} | {y['unit'][:26]:26} | {_fmt(x)} -> {_fmt(y)}")
    va, vb = a["ability"], b["ability"]
    dv = [
        (va[k], vb[k])
        for k in set(va) & set(vb)
        if va[k]["verdict"] != vb[k]["verdict"]
        or abs((va[k]["power"] or 0) - (vb[k]["power"] or 0)) > 1e-3
        or va[k]["family"] != vb[k]["family"]
    ]
    print("aptitudes changées (verdict/puissance/famille) :", len(dv))
    for x, y in dv[:40]:
        print(f"  {y['name'][:34]:34} {x['family']}->{y['family']} {x['verdict']}->{y['verdict']} "
              f"{x['power']}->{y['power']}")


def dump(db: Path, family: str) -> None:
    c = duckdb.connect(str(db), read_only=True)
    abil = c.execute(
        """SELECT DISTINCT a.uid, a.name, a.faction_id, a.verdict, a.power, a.scope, a.range_inches, a.frequency,
                  a.turn_side, coalesce(a.condition_text,''), coalesce(a.declare_text,''), coalesce(a.effect_text,'')
           FROM ability a JOIN ability_marriage m ON m.ability_uid = a.uid WHERE m.family = ?
           ORDER BY a.faction_id, a.name""",
        [family],
    ).fetchall()
    f = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))  # noqa: E731
    print("# P: porteur, Move, exposition, D, S, mariage, rang off., rang déf., allonge, part de mêlée")
    for uid, name, fac, verd, pw, scope, rng, freq, ts, cond, decl, eff in abil:
        print(f"### {name} [{fac}] uid={uid} {verd} P{pw} scope={scope} rng={rng} freq={freq} tour={ts}")
        print(f"  TXT: {cond} || {decl} || {eff}")
        for e in c.execute(
            """SELECT seq, kind, stat, value, side, detail, weapon_scope, requires, target_condition, duration, family
               FROM ability_effect WHERE ability_uid = ? ORDER BY seq""",
            [uid],
        ).fetchall():
            print("  E:", "|".join("" if v is None else str(v) for v in e))
        for r in c.execute(
            """SELECT u.name, u.move, m.exposure, m.p_trigger, m.survival, m.marriage, r.off_pct_rank, r.def_pct_rank,
                      r.reach_in, ch.share_melee
               FROM ability_marriage m JOIN unit u ON u.id = m.unit_id
               LEFT JOIN unit_realized r ON r.unit_id = m.unit_id LEFT JOIN unit_chassis ch ON ch.unit_id = m.unit_id
               WHERE m.ability_uid = ? ORDER BY m.marriage""",
            [uid],
        ).fetchall():
            print("  P:", " ".join(f(v) for v in r))
    c.close()


def check(db: Path, family: str | None, n: int) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    work = WORK / "marriage_check.duckdb"
    shutil.copy(db, work)
    try:
        before = snapshot(work)
        aospy = [sys.executable, "-m", "aospy", "--db", str(work)]
        for cmd in (["ability", "analyze"], ["encounter", "build"]):
            out = subprocess.run(aospy + cmd, capture_output=True, text=True, cwd=ROOT, check=True)
            print(out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "")
        diff(before, snapshot(work), family, n)
    finally:
        for p in (work, work.with_suffix(".duckdb.wal")):
            p.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="copie la base, rejoue analyze + encounter build, compare")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--family")
    p.add_argument("-n", type=int, default=15)
    p = sub.add_parser("snap", help="instantané JSON")
    p.add_argument("out", type=Path)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p = sub.add_parser("diff", help="compare deux instantanés")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--family")
    p.add_argument("-n", type=int, default=15)
    p = sub.add_parser("dump", help="couples d'une famille")
    p.add_argument("family")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    if args.cmd == "check":
        check(args.db, args.family, args.n)
    elif args.cmd == "snap":
        args.out.write_text(json.dumps(snapshot(args.db)))
    elif args.cmd == "diff":
        diff(json.loads(args.a.read_text()), json.loads(args.b.read_text()), args.family, args.n)
    else:
        dump(args.db, args.family)


if __name__ == "__main__":
    main()

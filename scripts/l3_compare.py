"""Instantanés et comparatifs des grilles de matchups L3 Centre 2026-27 (aller).

Avant de toucher à la méthode, aux notes de plan ou aux ajustements, prendre un instantané ;
après, comparer. Les instantanés sont durables (pas dans un dossier temporaire) :
`data/2026-27 L3 Aller/Matchups/instantanés/<nom>.json`.

  l3_compare.py snapshot <nom> [--note "..."]   enregistre grilles Melusior/Vae Victis + score ligue
  l3_compare.py list                            liste les instantanés
  l3_compare.py diff <avant> [<après>]          écarts (après = état actuel si omis), sortie courte
  l3_compare.py diff <avant> [<après>] --md     écrit aussi `Matchups/Comparatif <avant> → <après>.md`
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l3_diag as dg  # noqa: E402
import l3_matchups as mx  # noqa: E402

SNAP = mx.FOLDER / "Matchups" / "instantanés"


def current() -> dict:
    lists, adj, cache = dg.load()
    stats = dg.league(lists, adj, cache)
    order = sorted(lists, key=lambda p: -stats[p][0])
    grids = {}
    for team, rounds in mx.SCHEDULE.items():
        grids[team] = {}
        for i, opp in enumerate(rounds, 1):
            if opp is None:
                continue
            grids[team][f"Ronde {i} — {opp}"] = {
                p: {q: mx.evaluate(lists[p], lists[q], adj, cache).score for q in mx._TEAMS[opp]}
                for p in mx._TEAMS[team]}
    return {"date": datetime.now().isoformat(timespec="minutes"), "grids": grids,
            "league": {p: {"score": round(stats[p][0], 2), "rang": order.index(p) + 1} for p in lists}}


def load(name: str) -> dict:
    return json.loads((SNAP / f"{name}.json").read_text(encoding="utf-8"))


def f(x) -> str:
    return f"+{x}" if x > 0 else str(x)


def diff(a: dict, b: dict, name_a: str, name_b: str) -> list[str]:
    out = [f"# Comparatif {name_a} → {name_b}", ""]
    if a.get("note") or b.get("note"):
        out += [f"*{name_a}* : {a.get('note', '')}  ", f"*{name_b}* : {b.get('note', '')}", ""]
    for team, rounds in b["grids"].items():
        out += [f"## {team}", "", "| Joueur | Moy. avant | Moy. après | Écart |", "|---|---|---|---|"]
        players = next(iter(rounds.values())).keys()
        for p in players:
            va = [s for r in a["grids"][team].values() for s in r[p].values()]
            vb = [s for r in rounds.values() for s in r[p].values()]
            ma, mb = sum(va) / len(va), sum(vb) / len(vb)
            out.append(f"| {p} | {ma:+.1f} | {mb:+.1f} | {mb - ma:+.1f} |")
        out.append("")
        for rnd, rows in rounds.items():
            old = a["grids"][team].get(rnd, {})
            cells = [f"{p}–{q} {f(old[p][q])}→{f(s)}" for p, r in rows.items() for q, s in r.items()
                     if p in old and old[p][q] != s]
            ma = sum(s for r in old.values() for s in r.values()) / 36 if old else 0
            mb = sum(s for r in rows.values() for s in r.values()) / 36
            out.append(f"- **{rnd}** (moy. {ma:+.1f} → {mb:+.1f}) : " + ("; ".join(cells) or "aucun changement"))
        out.append("")
    moves = sorted(b["league"], key=lambda p: -abs(b["league"][p]["score"] - a["league"].get(p, {"score": 0})["score"]))
    out += ["## Ligue : plus gros mouvements", ""]
    for p in moves[:12]:
        la, lb = a["league"][p], b["league"][p]
        out.append(f"- {p} : {la['score']:+.1f} ({la['rang']}e) → {lb['score']:+.1f} ({lb['rang']}e)")
    return out + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("name")
    s.add_argument("--note", default="")
    sub.add_parser("list")
    d = sub.add_parser("diff")
    d.add_argument("before")
    d.add_argument("after", nargs="?")
    d.add_argument("--md", action="store_true")
    args = ap.parse_args()
    SNAP.mkdir(parents=True, exist_ok=True)
    if args.cmd == "snapshot":
        data = current()
        data["note"] = args.note
        path = SNAP / f"{args.name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("écrit :", path)
    elif args.cmd == "list":
        for path in sorted(SNAP.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            print(f"{path.stem:40s} {data['date']}  {data.get('note', '')}")
    else:
        a = load(args.before)
        b = load(args.after) if args.after else current()
        lines = diff(a, b, args.before, args.after or "actuel")
        print("\n".join(lines))
        if args.md:
            path = mx.FOLDER / "Matchups" / f"Comparatif {args.before} → {args.after or 'actuel'}.md"
            path.write_text("\n".join(lines), encoding="utf-8")
            print("écrit :", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

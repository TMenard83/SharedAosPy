"""`note_plan` calculée : régression des notes de plan validées (`Données/combos/<équipe>.json`) sur les indices
couche 4, avec validation croisée « un contre tous ».

Les 54 notes de plan (0-3) servent de jeu d'étalonnage. Indices par liste (`features`) : empilement et montée en
puissance (`l3.layer4`), assaut groupé, nombre de leviers (aptitudes qui rapportent sur un receveur), fiabilité des
donneurs, part de règles mortes, redondance (marteaux), rôles couverts et composantes (`analysis.layers.roles`).
Régression ridge sur indices centrés-réduits ; λ choisi par validation croisée (le score annoncé est donc un peu
optimiste). Sortie : accord exact, écart moyen, comparaison à la note constante majoritaire, et les écarts à relire.

usage : aospy l3 plan-note [--lam 1 3 10] [--show N] [--json fichier]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "data" / "2026-27 L3 Aller"

FEATURES = (
    "l4_value",  # ln(dégâts × montée) + ln(durabilité × montée)
    "off_time",  # ln montée en puissance offensive
    "assault_p2",  # P(≥ 2 charges) du meilleur assaut groupé
    "levers",  # ln(1 + aptitudes qui rapportent ≥ 5 % sur un receveur)
    "reliability",  # fiabilité moyenne des donneurs, pondérée par le gain
    "dead_share",  # part des aptitudes mortes
    "hammers",  # copies d'unités au rôle principal marteau
    "roles",  # rôles principaux distincts
    "components",  # composantes (château, aile rapide, deathstar, écran)
    "castle_wing",  # château lent + aile rapide
    "units",  # nombre d'unités (copies comprises)
)


def notes() -> dict[str, int]:
    out = {}
    for path in sorted((FOLDER / "Données" / "combos").glob("*.json")):
        for player, data in json.loads(path.read_text(encoding="utf-8")).items():
            if not player.startswith("_") and "note_plan" in data:
                out[player] = int(data["note_plan"])
    return out


def list_path(player: str) -> Path | None:
    hits = list((FOLDER / "Listes texte").glob(f"*/{player}.txt"))
    return hits[0] if hits else None


def features(rep) -> dict[str, float]:
    from ..analysis.layers.roles import components, unit_roles
    from .layer4 import indices_from_report

    ind = indices_from_report(rep)
    roles = unit_roles(rep)
    comps = components(rep, roles)
    gains: dict[str, float] = {}
    rel_num = rel_den = 0.0
    for m in rep.marriages:
        g = (m.off_gain_pct or 0.0) + (m.def_gain_pct or 0.0)
        if g >= 5:
            gains[m.ability] = max(gains.get(m.ability, 0.0), g)
            rel_num += m.giver * g
            rel_den += g
    kinds = {c.kind for c in comps}
    return {
        "l4_value": ind.value,
        "off_time": math.log(max(ind.off_time, 1e-6)),
        "assault_p2": ind.assault_p2,
        "levers": math.log1p(len(gains)),
        "reliability": rel_num / rel_den if rel_den else 1.0,
        "dead_share": len(rep.dead) / max(1, len(rep.abilities)),
        "hammers": float(sum(r.copies for r in roles if r.role == "marteau")),
        "roles": float(len({r.role for r in roles} - {"ajustement"})),
        "components": float(len(comps)),
        "castle_wing": float({"château lent", "aile rapide"} <= kinds),
        "units": float(sum(r.copies for r in roles)),
    }


# ----- ridge en Python pur (54 × 11) ---------------------------------------------


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


def fit(xs: list[list[float]], ys: list[float], lam: float):
    """Ridge sur indices centrés-réduits ; renvoie une fonction de prédiction et les coefficients (réduits)."""
    k = len(xs[0])
    mu = [sum(x[j] for x in xs) / len(xs) for j in range(k)]
    sd = [math.sqrt(sum((x[j] - mu[j]) ** 2 for x in xs) / len(xs)) or 1.0 for j in range(k)]
    z = [[(x[j] - mu[j]) / sd[j] for j in range(k)] for x in xs]
    ym = sum(ys) / len(ys)
    a = [[sum(r[i] * r[j] for r in z) + (lam if i == j else 0.0) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * (y - ym) for r, y in zip(z, ys)) for i in range(k)]
    w = _solve(a, b)

    def predict(x: list[float]) -> float:
        return ym + sum(wj * (xj - m) / s for wj, xj, m, s in zip(w, x, mu, sd))

    return predict, w


def loo(xs, ys, lam: float) -> list[float]:
    out = []
    for i in range(len(xs)):
        pred, _w = fit(xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:], lam)
        out.append(pred(xs[i]))
    return out


def _round(p: float) -> int:
    return int(min(3, max(0, math.floor(p + 0.5))))


def _spearman(a: list[float], b: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 0.0


def main(argv: list[str] | None = None) -> int:
    import duckdb

    from ..analysis.layers.listing import analyse_list
    from ..tournament_kit.list_parser import parse_list_file

    ap = argparse.ArgumentParser(prog="aospy l3 plan-note", description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(ROOT / "data" / "aospy.duckdb"))
    ap.add_argument("--lam", nargs="+", type=float, default=[1.0, 3.0, 10.0, 30.0])
    ap.add_argument("--show", type=int, default=54, help="écarts listés (les plus grands d'abord)")
    ap.add_argument("--json", type=Path, help="écrit indices, notes et prédictions dans ce fichier")
    args = ap.parse_args(argv)
    con = duckdb.connect(args.db, read_only=True)
    from ..analysis.layers.cascade import require_fresh

    require_fresh(con, 4)
    players, xs, ys = [], [], []
    for player, note in notes().items():
        path = list_path(player)
        if path is None:
            print(f"{player} : liste texte absente, ignorée")
            continue
        f = features(analyse_list(con, parse_list_file(path)))
        players.append(player)
        xs.append([f[k] for k in FEATURES])
        ys.append(float(note))
    n = len(ys)
    major = max(set(ys), key=ys.count)
    print(f"{n} listes notées ; note constante {major:.0f} : accord exact {ys.count(major) / n:.0%}, "
          f"écart moyen {sum(abs(y - major) for y in ys) / n:.2f}")
    best = None
    for lam in args.lam:
        p = loo(xs, ys, lam)
        exact = sum(_round(a) == b for a, b in zip(p, ys)) / n
        mae = sum(abs(_round(a) - b) for a, b in zip(p, ys)) / n
        rho = _spearman(p, ys)
        print(f"λ={lam:g} : accord exact {exact:.0%}, écart moyen {mae:.2f}, écarts ≥ 2 crans "
              f"{sum(abs(_round(a) - b) >= 2 for a, b in zip(p, ys))}, Spearman {rho:+.2f}")
        if best is None or (mae, -rho) < (best[1], -best[2]):
            best = (lam, mae, rho, p)
    lam, _mae, _rho, p = best
    _pred, w = fit(xs, ys, lam)
    print(f"\ncoefficients (λ={lam:g}, indices réduits, toutes les listes) :")
    for k, wk in sorted(zip(FEATURES, w), key=lambda t: -abs(t[1])):
        print(f"  {k:12} {wk:+.2f}")
    rows = sorted(zip(players, ys, p), key=lambda t: -abs(t[2] - t[1]))
    print(f"\nécarts (validation croisée, λ={lam:g}) : joueur, note validée, prédite (arrondie)")
    for pl, y, q in rows[: args.show]:
        if _round(q) != y:
            print(f"  {pl:16} {y:.0f}  {q:4.2f} ({_round(q)})")
    if args.json:
        args.json.write_text(json.dumps(
            [{"joueur": pl, "note": y, "prediction": q, **dict(zip(FEATURES, x))}
             for pl, y, q, x in zip(players, ys, p, xs)], ensure_ascii=False, indent=1), encoding="utf-8")
    return 0

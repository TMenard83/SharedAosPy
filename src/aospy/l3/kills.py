"""Matrice « qui tue qui » d'un match L3 : activations nécessaires à chaque unité pour retirer chaque unité adverse.

  aospy l3 qui-tue-qui --match A B              les deux matrices d'un match, à l'écran
  aospy l3 qui-tue-qui --team Melusior [--ronde N]   un fichier Markdown par ronde (36 paires),
                                                dans Matchups/Qui tue qui <équipe>/

Même calcul de dégâts que `matchups.attrition` (`pair_damage` : profils, règles d'armée BT_RULES,
mortelles d'aptitude, fiabilité, mélange chargé / chargé selon l'écart de mobilité), plus les buffs
de la liste lus par la couche 4 (`L4Indices.unit_off` / `unit_def`, « tout en place », cible unique
sur sa meilleure cible) : dégâts × multiplicateur offensif de l'attaquant, PV × multiplicateur
défensif de la cible. `--nu` retire les buffs (profils nus, comme `unit duel`).

Une case = PV effectifs de la cible / dégâts d'une activation (un round de l'unité entière) ;
≤ 1 : tue en une activation. Les buffs « tout en place » sont un plafond (tout le monde à portée).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from . import matchups as mx

MAX_SHOWN = 9.9  # au-delà : « — » (ne la traite pas)


@dataclass
class Cell:
    activations: float  # activations pour tuer (inf si aucun dégât)
    damage: float  # dégâts d'une activation, buffs compris
    charge: float  # probabilité que l'attaquant ait chargé


def _mult(al: mx.ArmyList, e: mx.Entry, kind: str) -> float:
    if al.l4 is None:
        return 1.0
    return getattr(al.l4, kind).get(e.unit.name, 1.0)


def groups(al: mx.ArmyList) -> list[tuple[mx.Entry, int]]:
    """Entrées identiques (même libellé, mêmes points) regroupées : (représentante, nombre), dans l'ordre."""
    out: dict[tuple, list] = {}
    for e in al.entries:
        out.setdefault((e.label, e.points), [e, 0])[1] += 1
    return [(e, n) for e, n in out.values()]


def _name(e: mx.Entry, n: int) -> str:
    return f"{n}× {e.label}" if n > 1 else e.label


def matrix(a: mx.ArmyList, b: mx.ArmyList, cache: dict, buffs: bool = True) -> list[list[Cell]]:
    """matrix[i][j] : groupe i de a contre groupe j de b (voir `groups`)."""
    rows = []
    for ea, _n in groups(a):
        off = _mult(a, ea, "unit_off") if buffs else 1.0
        row = []
        for eb, _m in groups(b):
            dmg, _r, _d, p = mx.pair_damage(ea, a, eb, b, cache)
            dmg *= off
            hp = eb.hp * (_mult(b, eb, "unit_def") if buffs else 1.0)
            row.append(Cell(hp / dmg if dmg > 0 else float("inf"), dmg, p))
        rows.append(row)
    return rows


def _fmt(x: float) -> str:
    if x > MAX_SHOWN:
        return "—"
    s = f"{x:.1f}".replace(".", ",")
    return f"**{s}**" if x <= 1.0 else s


def _mult_txt(al: mx.ArmyList, e: mx.Entry, buffs: bool, kinds=("unit_off", "unit_def")) -> str:
    if not buffs:
        return ""
    labels = {"unit_off": "att", "unit_def": "déf"}
    parts = [f"{labels[k]} ×{_mult(al, e, k):.2f}".replace(".", ",") for k in kinds if _mult(al, e, k) > 1.005]
    return f", {', '.join(parts)}" if parts else ""


def section(a: mx.ArmyList, b: mx.ArmyList, cache: dict, buffs: bool = True, level: str = "###") -> list[str]:
    """Matrice a → b, légende des colonnes, et lecture : meilleure réponse à chaque unité de b."""
    m = matrix(a, b, cache, buffs)
    ga, gb = groups(a), groups(b)
    out = [f"{level} {a.player} ({a.faction}) frappe {b.player} ({b.faction})", ""]
    out.append("| attaquant | " + " | ".join(str(j + 1) for j in range(len(gb))) + " |")
    out.append("|---|" + "---:|" * len(gb))
    for (ea, n), row in zip(ga, m, strict=True):
        head = f"{_name(ea, n)} ({ea.points}{_mult_txt(a, ea, buffs, ('unit_off',))})"
        out.append(f"| {head} | " + " | ".join(_fmt(c.activations) for c in row) + " |")
    out.append("")
    out.append("Cibles : " + " · ".join(
        f"{j + 1} = {_name(eb, n)} ({eb.points} pts, {eb.hp} PV{_mult_txt(b, eb, buffs, ('unit_def',))})"
        for j, (eb, n) in enumerate(gb)
    ))
    out.append("")
    out.append("Réponse à chaque cible (meilleures unités, activations) :")
    for j, (eb, n) in enumerate(gb):
        col = sorted((m[i][j].activations, ea.label) for i, (ea, _k) in enumerate(ga))
        best = [f"{lab} {_fmt(x)}" for x, lab in col[:2] if x <= MAX_SHOWN]
        out.append(f"- {_name(eb, n)} : {', '.join(best) if best else 'rien ne la traite'}")
    out.append("")
    return out


def match_text(a: mx.ArmyList, b: mx.ArmyList, cache: dict, buffs: bool = True, level: str = "###") -> list[str]:
    return section(a, b, cache, buffs, level) + section(b, a, cache, buffs, level)


def _header(buffs: bool) -> list[str]:
    mode = "buffs de la liste « tout en place » (couche 4)" if buffs else "profils nus (sans buffs de liste)"
    return [
        f"Case = activations (round complet de l'unité) pour retirer la cible ; **gras** ≤ 1 ; — : plus de "
        f"{MAX_SHOWN:g}. Dégâts de `attrition` (charge pondérée par la mobilité, fiabilité), {mode}. "
        "Généré par `aospy l3 qui-tue-qui`, ne pas éditer.",
        "",
    ]


def team_files(team: str, lists: dict, cache: dict, buffs: bool, ronde: int | None) -> dict[str, str]:
    ours = list(mx._TEAMS[team])
    files = {}
    for i, opp in enumerate(mx.SCHEDULE[team], 1):
        if opp is None or (ronde and i != ronde):
            continue
        lines = [f"# Qui tue qui — {team}, ronde {i} contre {opp}", "", *_header(buffs)]
        for p in ours:
            for q in mx._TEAMS[opp]:
                lines += [f"## {p} – {q}", ""] + match_text(lists[p], lists[q], cache, buffs)
        files[f"Matchups/Qui tue qui {team}/Ronde {i} - {opp}.md"] = "\n".join(lines)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 qui-tue-qui", description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--match", nargs=2, metavar=("A", "B"), help="deux joueurs : matrices à l'écran")
    g.add_argument("--team", choices=list(mx.SCHEDULE), help="toutes les paires de chaque ronde, en Markdown")
    ap.add_argument("--ronde", type=int, help="avec --team : une seule ronde (1-5)")
    ap.add_argument("--nu", action="store_true", help="sans les buffs de la liste (profils nus)")
    args = ap.parse_args(argv)
    from .diag import load

    lists, _adj, cache = load()
    buffs = not args.nu
    if args.match:
        a, b = args.match
        for p in (a, b):
            if p not in lists:
                print(f"joueur inconnu : {p}", file=sys.stderr)
                return 1
        print("\n".join(_header(buffs) + match_text(lists[a], lists[b], cache, buffs, level="##")))
        return 0
    for rel, text in team_files(args.team, lists, cache, buffs, args.ronde).items():
        path = mx.FOLDER / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print("écrit :", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

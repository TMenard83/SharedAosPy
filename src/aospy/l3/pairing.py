"""Solveur d'appariement AOSFF (L3 Centre 2026-27, aller) : équipes de 6, règlement §7.3.

Séquence (3 étapes, chaque révélation est simultanée) :
  1. map 1 : chaque paireur pose un défenseur ; chacun propose 2 attaquants contre le défenseur
     adverse ; chacun choisit lequel des 2 attaquants adverses affronte son défenseur (le
     défenseur choisit), l'autre retourne en main. Reste 4 listes de chaque côté.
  2. map 2 : idem, mais l'attaquant écarté devient le « rejeté » et la liste restée en main
     « l'oublié » ; map 3 : notre oublié contre leur rejeté, leur oublié contre notre rejeté.

Entrée : `pairing_scores.PairingInput` seul (score(nous, eux, map) en pts de victoire vus de
nous ; aujourd'hui grille du moteur + 2 pts par cran d'écart de note scénario + tactiques de
bataille, voir `l3/tactics.py`). Le solveur ne
lit aucun fichier. Score de ronde = somme des 6 parties (§9.2).

Chaque révélation simultanée est un jeu à somme nulle résolu par récurrence :
  * `mixte` (défaut, scipy requis — extra `[analysis]`) : valeur exacte, stratégies mixtes
    (probabilités de choix) ; c'est l'espérance si les deux camps jouent au mieux ;
  * `prudent` : stratégies pures, on suppose que l'adversaire voit notre choix (maximin) :
    plancher garanti quel que soit son jeu, si la grille est juste.

Pendant l'appariement, décrire ce qui est déjà révélé pour obtenir le coup suivant :
  --joue NOUS:EUX (parties déjà fixées, répétable), --def NOUS:EUX (défenseurs révélés),
  --att A,B:C,D (nos 2 attaquants : leurs 2 attaquants).

Usage : aospy l3 pairing --team Melusior --ronde 1 [--mode mixte|prudent] [--sans-notes] [--sans-tactiques]
"""

from __future__ import annotations

import argparse
from functools import lru_cache
from itertools import combinations

from aospy.text import fold_name

from .pairing_scores import build_input
from .scenarios import FILE_NAME

# --- jeux matriciels à somme nulle (valeur pour le joueur ligne, qui maximise) ---------------


def solve_pure(M):
    """Maximin en stratégies pures : (valeur, ligne choisie, colonne de meilleure réponse)."""
    i = max(range(len(M)), key=lambda r: min(M[r]))
    j = min(range(len(M[0])), key=lambda c: M[i][c])
    return M[i][j], _onehot(len(M), i), _onehot(len(M[0]), j)


def _onehot(n, i):
    return [1.0 if k == i else 0.0 for k in range(n)]


def solve_mixed(M):
    """Valeur exacte (stratégies mixtes) : (valeur, mélange ligne, mélange colonne)."""
    rows, cols = len(M), len(M[0])
    lo = max(min(r) for r in M)
    hi = min(max(M[i][j] for i in range(rows)) for j in range(cols))
    if lo >= hi - 1e-9:  # point selle : stratégies pures
        return solve_pure(M)
    if rows == 2 and cols == 2:
        (a, b), (c, d) = M
        den = a - b - c + d
        p, q = (d - c) / den, (d - b) / den
        return (a * d - b * c) / den, [p, 1 - p], [q, 1 - q]
    return _lp(M)


def _lp(M):
    import numpy as np
    from scipy.optimize import linprog

    A = np.asarray(M, dtype=float)
    shift = 1.0 - A.min()
    B = A + shift  # > 0 : valeur > 0
    rows, cols = B.shape
    # ligne : min sum(x) s.c. B^T x >= 1, x >= 0 ; valeur = 1/sum(x)
    r = linprog(np.ones(rows), A_ub=-B.T, b_ub=-np.ones(cols), bounds=(0, None), method="highs")
    c = linprog(-np.ones(cols), A_ub=B, b_ub=np.ones(rows), bounds=(0, None), method="highs")
    v = 1.0 / r.x.sum()
    return v - shift, list(r.x * v), list(c.x / c.x.sum())


# --- le jeu d'appariement --------------------------------------------------------------------


class Pairing:
    """Arbre de l'appariement d'une ronde, du point de vue de `ours`.

    `score(nous, eux, map)` : écart de PV prévu pour une partie sur une map (nom de carte).
    """

    def __init__(self, score, ours, theirs, maps, mode="mixte"):
        self.score, self.maps = score, list(maps)
        self.ours, self.theirs = list(ours), list(theirs)
        self.solve = solve_mixed if mode == "mixte" else solve_pure
        self.value = lru_cache(maxsize=None)(self._value)

    def val(self, p, q, m):
        return self.score(p, q, self.maps[m])

    # Y : choix simultané de l'attaquant adverse affronté par chaque défenseur
    def picks(self, U, T, d, e, A, B):
        """Matrice [b ∈ B (notre choix)][a ∈ A (leur choix)] et ses étiquettes."""
        s = 0 if len(U) == 6 else 1
        M = []
        for b in B:
            row = []
            for a in A:
                v = self.val(d, b, s) + self.val(a, e, s)
                if len(U) == 6:
                    v += self.value(U - {d, a}, T - {e, b})
                else:  # map 3 : notre oublié contre leur rejeté, leur oublié contre notre rejeté
                    (a2,) = set(A) - {a}
                    (b2,) = set(B) - {b}
                    (ou,) = U - {d} - set(A)
                    (ot,) = T - {e} - set(B)
                    v += self.val(ou, b2, 2) + self.val(a2, ot, 2)
                row.append(v)
            M.append(row)
        return M

    def attackers(self, U, T, d, e):
        """Matrice [nos paires A][leurs paires B] et les paires."""
        As = list(combinations(sorted(U - {d}), 2))
        Bs = list(combinations(sorted(T - {e}), 2))
        M = [[self.solve(self.picks(U, T, d, e, A, B))[0] for B in Bs] for A in As]
        return M, As, Bs

    def defenders(self, U, T):
        Ds, Es = sorted(U), sorted(T)
        M = [[self.solve(self.attackers(U, T, d, e)[0])[0] for e in Es] for d in Ds]
        return M, Ds, Es

    def _value(self, U, T):
        return self.solve(self.defenders(U, T)[0])[0]


# --- CLI -------------------------------------------------------------------------------------


def _find(name, pool):
    f = fold_name(name)
    hits = [p for p in pool if fold_name(p) == f] or [p for p in pool if fold_name(p).startswith(f)]
    if len(hits) != 1:
        raise SystemExit(f"« {name} » : {'ambigu' if hits else 'inconnu'} parmi {', '.join(sorted(pool))}")
    return hits[0]


def sgn(v):
    return f"{v:+.1f}".replace("-", "−")


def _table(title, labels_row, M, solver, col_labels):
    v, x, y = solver(M)
    head = "| Notre choix | Plancher (pire réponse) | Contre leur meilleur jeu | Proba. |"
    out = [title, "", head, "|---|---|---|---|"]
    order = sorted(range(len(M)), key=lambda i: -min(M[i]))
    for i in order:
        vs = sum(M[i][j] * y[j] for j in range(len(y)))
        worst = min(range(len(M[i])), key=lambda j: M[i][j])
        out.append(f"| {labels_row[i]} | {sgn(M[i][worst])} (si {col_labels[worst]}) | {sgn(vs)} | {x[i]:.0%} |")
    theirs = [f"{col_labels[j]} {y[j]:.0%}" for j in sorted(range(len(y)), key=lambda j: -y[j]) if y[j] > 0.005]
    out += ["", f"Valeur : {sgn(v)} · leur jeu attendu : {', '.join(theirs)}", ""]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 pairing", description=__doc__.split("\n")[0])
    ap.add_argument("--team", required=True, help="Melusior ou « Vae Victis Vernou »")
    ap.add_argument("--ronde", type=int, required=True, choices=range(1, 6))
    ap.add_argument("--mode", choices=["mixte", "prudent"], default="mixte")
    ap.add_argument("--sans-notes", action="store_true", help="grille seule, sans les notes scénario")
    ap.add_argument("--scenario", choices=["centre", "brut", "notes"], default="centre",
                    help="composante scénario : centre (aisance − moyenne de la liste, défaut), brut, notes (ancien)")
    ap.add_argument("--sans-tactiques", action="store_true", help="sans la correction tactiques de bataille")
    ap.add_argument("--joue",action="append", default=[], metavar="NOUS:EUX", help="partie déjà fixée")
    ap.add_argument("--def", dest="defs", metavar="NOUS:EUX", help="défenseurs révélés à l'étape en cours")
    ap.add_argument("--att", metavar="A,B:C,D", help="attaquants révélés : nos 2 : leurs 2")
    a = ap.parse_args(argv)

    team = _find(a.team, list(FILE_NAME))
    if a.mode == "mixte":
        try:
            import scipy  # noqa: F401
        except ImportError:
            raise SystemExit("Mode mixte : installer l'extra `[analysis]` (scipy), ou --mode prudent.") from None
    inp = build_input(team, a.ronde, notes=not a.sans_notes, tactics=not a.sans_tactiques, scenario=a.scenario)
    if inp is None:
        raise SystemExit(f"{team} ne joue pas la ronde {a.ronde} (BYE).")
    opp, maps, ours, theirs = inp.opponent, inp.maps, inp.ours, inp.theirs
    P = Pairing(inp.at, ours, theirs, maps, a.mode)
    solver = P.solve

    U, T = frozenset(ours), frozenset(theirs)
    fixed = 0.0
    for i, pair in enumerate(a.joue):
        p, q = pair.split(":")
        p, q = _find(p, U), _find(q, T)
        fixed += P.val(p, q, min(i // 2, 2))
        U, T = U - {p}, T - {q}
    if len(U) not in (6, 4):
        raise SystemExit("--joue : 0 ou 2 parties déjà fixées (une étape complète).")
    s = 0 if len(U) == 6 else 1

    out = [
        f"# Appariement {team} contre {opp} — ronde {a.ronde} ({a.mode})",
        "",
        f"Maps : {' · '.join(maps)} · score = grille"
        + ("" if a.sans_notes else f" + scénario ({a.scenario})")
        + ("" if a.sans_tactiques else " + tactiques de bataille (l3/tactics.py)"),
        "",
    ]
    if fixed or a.joue:
        out += [f"Parties fixées : {', '.join(a.joue)} ({sgn(fixed)})", ""]
    rest = P.value(U, T)
    detail = f" — dont parties restantes {sgn(rest)}" if a.joue else ""
    out += [f"**Valeur de la ronde** (somme des 6 parties) : {sgn(fixed + rest)}{detail}", ""]

    if not a.defs:
        M, Ds, Es = P.defenders(U, T)
        out += _table(f"## Étape {s + 1} (map {s + 1}, {maps[s]}) : notre défenseur", Ds, M, solver, Es)
    else:
        d, e = a.defs.split(":")
        d, e = _find(d, U), _find(e, T)
        if not a.att:
            M, As, Bs = P.attackers(U, T, d, e)
            title = f"## Nos 2 attaquants contre {e} (notre défenseur : {d})"
            out += _table(title, [" + ".join(x) for x in As], M, solver, [" + ".join(x) for x in Bs])
        else:
            mine, their = a.att.split(":")
            A = tuple(sorted(_find(x, U - {d}) for x in mine.split(",")))
            B = tuple(sorted(_find(x, T - {e}) for x in their.split(",")))
            M = P.picks(U, T, d, e, A, B)
            out += _table(f"## Qui affronte {d} ? (ils choisissent parmi {' / '.join(A)})", list(B), M, solver, list(A))
            if len(U) == 4:
                (ou,) = U - {d} - set(A)
                (ot,) = T - {e} - set(B)
                out += [f"Map 3 ({maps[2]}) : notre oublié {ou} contre leur rejeté ; "
                        f"leur oublié {ot} contre notre rejeté.", ""]
    out.append(
        "*Plancher : si l'adversaire devinait notre choix. Proba. : stratégie mixte optimale "
        "(jouer le choix tiré au sort selon ces probabilités rend notre coup imprévisible) ; "
        "en mode prudent, 100 % sur le meilleur plancher.*"
    )
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    main()

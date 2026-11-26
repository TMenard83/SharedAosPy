"""Robustesse de l'appariement : les cases pivot de la grille d'une ronde (L3 Centre 2026-27).

Une case = une paire (notre liste, leur liste), sur les 3 maps de la ronde (l'erreur de la grille du moteur porte
sur la paire, pas sur la carte). Pour chacune des 36 cases, on la bouge de −δ puis +δ (défaut 3 pts de victoire)
et on relance le solveur (`pairing.Pairing`, même entrée `pairing_scores.build_input`).

La question n'est pas « la valeur bouge-t-elle ? » (elle bouge mécaniquement avec la case) mais « le plan
tient-il ? ». Pour chaque déplacement, on rejoue la **stratégie de référence** de l'étape 1 (le mélange de
défenseurs conseillé sur la grille actuelle) dans la grille modifiée : le **regret** = valeur optimale de la grille
modifiée − valeur garantie par l'ancien mélange. Une case est **pivot** si son regret dépasse le seuil (défaut
0,5 pt de victoire) : si elle est fausse de δ, suivre le plan actuel coûte des points.

Les cases pivot sont celles à relire en fiche match (skill `match-analysis`) avant de croire le solveur.

Usage : aospy l3 robustesse --team Melusior --ronde 1 [--delta 3] [--seuil 0.5] [--mode mixte|prudent]
        [--sans-notes] [--sans-tactiques] [--tirages 200 [--graine 0]]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor

from .pairing import Pairing, _find, sgn
from .pairing_scores import build_input
from .scenarios import FILE_NAME


def step1(P: Pairing):
    """(matrice des défenseurs, nos défenseurs, valeur, notre mélange) de l'étape 1."""
    M, Ds, _ = P.defenders(frozenset(P.ours), frozenset(P.theirs))
    v, x, _ = P.solve(M)
    return M, Ds, v, x


def guaranteed(M, x):
    """Valeur garantie par le mélange `x` (pire réponse adverse)."""
    return min(sum(x[i] * M[i][j] for i in range(len(M))) for j in range(len(M[0])))


def _shifted(args):
    inp, mode, us, them, d, x0 = args

    def score(u, t, m):
        return inp.at(u, t, m) + (d if (u, t) == (us, them) else 0.0)

    M, Ds, v, x = step1(Pairing(score, inp.ours, inp.theirs, inp.maps, mode))
    best = max(range(len(Ds)), key=lambda k: x[k])
    return us, them, d, v, v - guaranteed(M, x0), Ds[best], x[best]


def pivots(inp, mode="mixte", delta=3.0):
    """Référence `(valeur, mélange {défenseur: proba})` et toutes les lignes
    `(nous, eux, δ, valeur, regret, défenseur le plus probable, proba)`, pivots d'abord."""
    _, Ds, v0, x0 = step1(Pairing(inp.at, inp.ours, inp.theirs, inp.maps, mode))
    jobs = [(inp, mode, us, them, d, x0) for us in inp.ours for them in inp.theirs for d in (-delta, delta)]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(_shifted, jobs))
    rows.sort(key=lambda r: -r[4])
    return (v0, {Ds[i]: x0[i] for i in range(len(Ds)) if x0[i] > 0.005}), rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 robustesse", description=__doc__.split("\n")[0])
    ap.add_argument("--team", required=True, help="Melusior ou « Vae Victis Vernou »")
    ap.add_argument("--ronde", type=int, required=True, choices=range(1, 6))
    ap.add_argument("--mode", choices=["mixte", "prudent"], default="mixte")
    ap.add_argument("--delta", type=float, default=3.0, help="déplacement d'une case, en pts de victoire (défaut 3)")
    ap.add_argument("--seuil", type=float, default=0.5,
                    help="regret (pts de victoire) qui rend une case pivot (défaut 0,5)")
    ap.add_argument("--sans-notes", action="store_true")
    ap.add_argument("--sans-tactiques", action="store_true")
    ap.add_argument("--tirages", type=int, default=0,
                    help="+ fourchette : N tirages de toute la grille bruitée selon la confiance (pairing_noise)")
    ap.add_argument("--graine", type=int, default=0, help="graine des tirages (défaut 0)")
    a = ap.parse_args(argv)

    team = _find(a.team, list(FILE_NAME))
    if a.mode == "mixte":
        try:
            import scipy  # noqa: F401
        except ImportError:
            raise SystemExit("Mode mixte : installer l'extra `[analysis]` (scipy), ou --mode prudent.") from None
    inp = build_input(team, a.ronde, notes=not a.sans_notes, tactics=not a.sans_tactiques)
    if inp is None:
        raise SystemExit(f"{team} ne joue pas la ronde {a.ronde} (BYE).")

    (v0, mix), rows = pivots(inp, a.mode, a.delta)
    plan = ", ".join(f"{d} {p:.0%}" for d, p in sorted(mix.items(), key=lambda t: -t[1]))
    piv = [r for r in rows if r[4] > a.seuil]
    out = [
        f"# Robustesse de l'appariement {team} contre {inp.opponent} — ronde {a.ronde} ({a.mode})",
        "",
        f"Maps : {' · '.join(inp.maps)} · chaque case (paire, 3 maps) bougée de ±{a.delta:g} pts de victoire",
        "",
        f"Référence : valeur de la ronde {sgn(v0)} · notre défenseur (étape 1) : {plan}",
        "",
    ]
    if not piv:
        worst = rows[0]
        out.append(f"Aucune case pivot (regret > {a.seuil:g}) : le plan tient à ±{a.delta:g} sur chaque case prise "
                   f"seule. Plus grand regret : {worst[0]} – {worst[1]} {sgn(worst[2])} → {worst[4]:.2f}.")
    else:
        out += [
            "| Case (nous – eux) | Score actuel (maps) | Si la case vaut | Regret du plan "
            "| Valeur de ronde | Nouveau défenseur |",
            "|---|---|---|---|---|---|",
        ]
        for us, them, d, v, reg, dfd, p in piv:
            cur = " / ".join(sgn(inp.at(us, them, m)) for m in inp.maps)
            out.append(f"| {us} – {them} | {cur} | {sgn(d)} | {reg:.1f} | {sgn(v)} ({sgn(v - v0)}) | {dfd} ({p:.0%}) |")
        n = len({(r[0], r[1]) for r in piv})
        out += ["", f"{n} case(s) pivot sur {len(inp.ours) * len(inp.theirs)} : à relire en fiche match "
                f"(skill `match-analysis`)."]
    out += [
        "",
        "*Une case seule bougée à la fois ; deux erreurs dans le même sens peuvent faire basculer un plan que "
        "chaque case seule ne fait pas bouger.*",
    ]
    if a.tirages > 0:
        from . import pairing_noise as pn
        from .tactics import hand_levels

        conf = pn.confidence()
        sig = pn.pair_sigmas(inp, conf, set(hand_levels()))
        ref, draws = pn.simulate(inp, sig, a.tirages, a.mode, a.graine)
        out += [""] + pn.report(inp, sig, conf, ref, draws, a.seuil, sgn)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    main()

"""Commande `cost` : fit/residuals (nécessite l'extra `[analysis]`)."""

from __future__ import annotations

import argparse

from ..persistence import repository
from .common import _connect


def cmd_cost_fit(args: argparse.Namespace) -> int:
    con = _connect(args)
    from ..analysis.cost import cost_model

    try:
        if args.segmented:
            results = cost_model.fit_segmented(con)
            for name, result in results.items():
                print(f"\n=== Segment : {name} ({result.n_obs} unités, R²={result.r_squared:.3f}) ===")
                print(f"  const                 : {result.intercept.coef:8.3f}  (p={result.intercept.p_value:.3f})")
                for c in result.coefficients:
                    print(f"  {c.name:<22}: {c.coef:8.3f}  (p={c.p_value:.3f})")
        else:
            result = cost_model.fit_cost_model(con)
            print(f"R²={result.r_squared:.3f}  R²ajusté={result.adj_r_squared:.3f}  n={result.n_obs}")
            print(f"  const                 : {result.intercept.coef:8.3f}  (p={result.intercept.p_value:.3f})")
            for c in result.coefficients:
                print(f"  {c.name:<22}: {c.coef:8.3f}  (p={c.p_value:.3f})")
    except ImportError:
        print("Le modèle de coût nécessite l'extra [analysis] : pip install -e '.[analysis]'")
        con.close()
        return 1
    con.close()
    return 0


def cmd_cost_residuals(args: argparse.Namespace) -> int:
    con = _connect(args)
    from ..analysis.cost import cost_model

    try:
        result = cost_model.fit_cost_model(con)
    except ImportError:
        print("Le modèle de coût nécessite l'extra [analysis] : pip install -e '.[analysis]'")
        con.close()
        return 1
    armies = {a.id: a.name for a in repository.list_armies(con)}
    pool = result.undercosted(n=args.top) if args.direction == "under" else result.overcosted(n=args.top)
    label = "sous-cotées" if args.direction == "under" else "sur-cotées"
    print(f"Top {len(pool)} unités {label} :")
    for r in pool:
        print(
            f"  {r.name:<28} [{armies.get(r.army_id, '?'):<20}]  pts={r.points:<5} "
            f"prédit={r.predicted:7.1f}  résidu={r.residual:+7.1f} ({r.residual_pct:+.0f}%)"
        )
    con.close()
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `cost` : fit/residuals (nécessite l'extra `[analysis]`)."""
    p_cost = sub.add_parser("cost", help="Modèle de coût (points ~ caractéristiques).")
    scst = p_cost.add_subparsers(dest="action", required=True)
    p = scst.add_parser("fit", help="Ajuste le modèle et affiche les coefficients.")
    p.add_argument("--segmented", action="store_true", help="Ajuste un modèle séparé par segment (hero/troupe).")
    p.set_defaults(func=cmd_cost_fit)
    p = scst.add_parser("residuals", help="Unités les plus sous/sur-cotées (résidu).")
    p.add_argument("--top", type=int, default=20, help="Nombre d'unités à afficher.")
    p.add_argument(
        "--direction",
        choices=["under", "over"],
        default="under",
        help="Sous-cotées (under, défaut) ou sur-cotées (over).",
    )
    p.set_defaults(func=cmd_cost_residuals)

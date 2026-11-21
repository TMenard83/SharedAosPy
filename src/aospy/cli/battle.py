"""Commande `battle` : simulation composition contre composition."""

from __future__ import annotations

import argparse

from ..orchestration.simulation import SideOptions, simulate_battle
from .common import _connect, _resolve_side
from .report import format_report


def cmd_battle_simulate(args: argparse.Namespace) -> int:
    con = _connect(args)
    opts_a = SideOptions(
        charged=_resolve_side(args.charge, "a"),
        all_out_attack=_resolve_side(args.aoa, "a"),
        all_out_defense=_resolve_side(args.aod, "a"),
    )
    opts_b = SideOptions(
        charged=_resolve_side(args.charge, "b"),
        all_out_attack=_resolve_side(args.aoa, "b"),
        all_out_defense=_resolve_side(args.aod, "b"),
    )
    report = simulate_battle(con, args.comp_a, args.comp_b, opts_a, opts_b)
    print(format_report(report))
    con.close()
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `battle` (simulation composition contre composition)."""
    p_battle = sub.add_parser("battle", help="Simulation d'affrontement.")
    sb = p_battle.add_subparsers(dest="action", required=True)
    p = sb.add_parser("simulate", help="Simule un combat entre 2 compositions.")
    p.add_argument("--a", dest="comp_a", type=int, required=True, help="ID composition A.")
    p.add_argument("--b", dest="comp_b", type=int, required=True, help="ID composition B.")
    p.add_argument(
        "--charge", choices=["a", "b", "both", "none"], default="both", help="Côté(s) qui charge (défaut: both)."
    )
    p.add_argument("--aoa", choices=["a", "b", "both", "none"], default="none", help="All-out Attack (+1 hit).")
    p.add_argument("--aod", choices=["a", "b", "both", "none"], default="none", help="All-out Defense (+1 save).")
    p.set_defaults(func=cmd_battle_simulate)

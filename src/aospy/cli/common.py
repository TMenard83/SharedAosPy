"""Outils partagés par les modules de commandes CLI (connexion DB, options de duel)."""

from __future__ import annotations

import argparse

from ..orchestration import benchmark as bench
from ..orchestration.simulation import SideOptions
from ..persistence import db, repository


def _connect(args: argparse.Namespace):
    return db.connect(args.db)


def _resolve_army_id(con, name: str) -> int:
    army = repository.get_army_by_name(con, name)
    if army is None or army.id is None:
        raise ValueError(f"armée inconnue: {name}")
    return army.id


def _resolve_side(flag_value: str, side: str) -> bool:
    return flag_value == side or flag_value == "both"


def _side_options(args: argparse.Namespace, side: str) -> SideOptions:
    return SideOptions(
        charged=_resolve_side(args.charge, side),
        all_out_attack=_resolve_side(args.aoa, side),
        all_out_defense=_resolve_side(args.aod, side),
        ran_and_charged=_resolve_side(args.ran_and_charged, side),
    )


def _duel_rules(args: argparse.Namespace) -> bench.DuelRules:
    return bench.DuelRules(
        double_shoot=args.rule_double_shoot,
        charge_move_threshold=args.rule_charge_threshold,
        charge_dist_in=args.charge_dist,
        run_dist_in=args.run_dist,
    )

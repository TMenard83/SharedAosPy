"""Commandes `init`, `reset` (fichier DuckDB) et `army` (liste des armées)."""

from __future__ import annotations

import argparse

from ..persistence import db, repository, seed
from .common import _connect


def cmd_init(args: argparse.Namespace) -> int:
    con = _connect(args)
    armies = seed.load_armies_from_json(con)
    print(f"Armées chargées : {len(armies)}")
    if not args.no_compositions:
        comps = seed.load_compositions_from_json(con)
        print(f"Compositions chargées : {len(comps)}")
    con.close()
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    db.reset(args.db)
    print(f"Base supprimée : {args.db}")
    return 0


def cmd_army_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    armies = repository.list_armies(con)
    if not armies:
        print("(aucune armée)")
    else:
        print(f"{'ID':<4} {'Nom':<30} Grand Alliance")
        for a in armies:
            print(f"{a.id:<4} {a.name:<30} {a.grand_alliance}")
    con.close()
    return 0


def _register_init_reset(sub: argparse._SubParsersAction) -> None:
    """Sous-commandes `init` et `reset` (gestion du fichier DuckDB)."""
    p = sub.add_parser("init", help="Initialise la DB et seed les données JSON.")
    p.add_argument("--no-compositions", action="store_true",
                   help="Ne charge pas data/json/compositions.json.")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("reset", help="Supprime la base existante.")
    p.set_defaults(func=cmd_reset)


def _register_army(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `army` (liste des armées)."""
    p_army = sub.add_parser("army", help="Commandes sur les armées.")
    sa = p_army.add_subparsers(dest="action", required=True)
    sa.add_parser("list", help="Liste les armées.").set_defaults(func=cmd_army_list)


def register(sub: argparse._SubParsersAction) -> None:
    _register_init_reset(sub)
    _register_army(sub)

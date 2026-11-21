"""CLI AoSPy — gestion des armées, unités et compositions.

Un module par groupe de sous-commandes (`db`, `unit`, `comp`, `battle`, `import_`, `cost`, `roster`,
`ability`, `chassis`, `encounter`, `l3`), chacun avec sa fonction `register(sub)` et ses `cmd_*` ;
ce module ne fait que les assembler. Outils partagés (connexion DB, options de duel) : `common.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..persistence.db import DEFAULT_DB_PATH
from . import ability, battle, chassis, comp, cost, db, encounter, import_, l3, roster, unit

#: Ordre d'enregistrement = ordre d'affichage dans `aospy --help`.
_GROUPS = (db, unit, comp, battle, import_, cost, roster, ability, chassis, encounter, l3)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aospy",
        description="Calcul de la force de combat d'armées Age of Sigmar.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Chemin du fichier DuckDB (défaut: {DEFAULT_DB_PATH}).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for group in _GROUPS:
        group.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # `parse_known_args` pour `aospy l3 …`, qui transmet ses arguments au module : `REMAINDER` refuse
    # un premier argument en `-`. Pour toute autre commande, même erreur que `parse_args`.
    args, unknown = parser.parse_known_args(argv)
    if getattr(args, "forward_unknown", False):
        args.forwarded = unknown
    elif unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    try:
        return int(args.func(args) or 0)
    except (ValueError, FileNotFoundError) as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

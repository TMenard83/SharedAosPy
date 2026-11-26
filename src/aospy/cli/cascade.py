"""Commande `cascade` : analyse en cascade couche 1 → 2 → 3 (→ 4 avec `--list`), cf. analysis/layers/cascade.py."""

from __future__ import annotations

import argparse

from .common import _connect


def _print_status(con, data_dir) -> None:
    from ..analysis.layers.cascade import LAYER_NAMES, status

    for s in status(con, data_dir):
        state = "à jour" if s.fresh else f"PÉRIMÉE — {s.reason}"
        built = f" [build {s.built_at}]" if s.built_at else ""
        print(f"  couche {s.layer} ({LAYER_NAMES[s.layer]}) : {state}{built}")


def cmd_cascade(args: argparse.Namespace) -> int:
    from ..analysis.layers.cascade import require_fresh, run_cascade

    con = _connect(args)
    try:
        if args.status:
            _print_status(con, args.data_dir)
            return 0
        done = run_cascade(con, start=1 if args.all else args.start, data_dir=args.data_dir)
        print("Couches reconstruites : " + (", ".join(map(str, done)) if done else "aucune (tout est à jour)."))
        _print_status(con, args.data_dir)
        require_fresh(con, 4, args.data_dir)
        for path in args.list or []:
            from ..l3.dossier import write_dossier

            out = args.out_root and f"{args.out_root}/{path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}"
            if out:
                stem, missing = write_dossier(con, path, out)
                print(f"— couche 4 : dossier écrit : {out}")
                for m in missing:
                    print(f"  ATTENTION unité non reconnue : {m}")
            else:
                from ..analysis.layers.listing import analyse_list
                from ..tournament_kit.list_parser import parse_list_file
                from .report import format_list_report

                print(f"— couche 4 : {path}")
                print(format_list_report(analyse_list(con, parse_list_file(path))))
    finally:
        con.close()
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "cascade",
        help="Analyse en cascade : reconstruit les couches périmées dans l'ordre 1 → 2 → 3, puis la couche 4 "
        "des listes données.",
    )
    p.add_argument("--status", action="store_true", help="Affiche l'état des couches sans rien reconstruire.")
    p.add_argument("--all", action="store_true", help="Reconstruit les couches 1 à 3 même à jour.")
    p.add_argument("--start", type=int, choices=(1, 2, 3), help="Reconstruit à partir de cette couche.")
    p.add_argument("--data-dir", default=None, help="Dossier des CSV Wahapedia (défaut : data/wahapedia).")
    p.add_argument("--list", action="append", help="Liste (export App) à analyser en couche 4 ; répétable.")
    p.add_argument("--out-root", help="Écrit un dossier `roster dossier` par liste sous ce dossier "
                   "(défaut : fiche couche 4 affichée).")
    p.set_defaults(func=cmd_cascade)

"""Commande `import` : bsdata/bsdata-list/wahapedia/wahapedia-list/verify."""

from __future__ import annotations

import argparse
from datetime import datetime

from ..importers import bsdata, wahapedia
from ..persistence import repository
from .common import _connect


def _apply_source_corrections(con) -> None:
    """Corrections d'erreurs de source (`data/json/source_corrections.json`) : elles l'emportent
    sur l'import, quelle que soit la source."""
    from ..importers.corrections import apply_unit_corrections

    missing = apply_unit_corrections(con)
    for m in missing:
        print(f"  correction de source sans unité en base : {m}")


def cmd_import_bsdata(args: argparse.Namespace) -> int:
    con = _connect(args)
    cutoff = datetime.now()
    if getattr(args, "all_armies", False):
        names = list(bsdata.KNOWN_ARMIES)
        totals = {"inserted": 0, "updated": 0, "skipped": 0, "legends": 0, "terrain": 0, "failed": 0}
        for name in names:
            print(f"→ {name}…", flush=True)
            try:
                s = bsdata.import_army(con, name)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  échec : {exc}")
                totals["failed"] += 1
                continue
            print(
                f"  insérées={s.inserted}  mises à jour={s.updated}  "
                f"ignorées={s.skipped_no_profile}  legends={s.skipped_legends}  terrain={s.skipped_terrain}"
            )
            totals["inserted"] += s.inserted
            totals["updated"] += s.updated
            totals["skipped"] += s.skipped_no_profile
            totals["legends"] += s.skipped_legends
            totals["terrain"] += s.skipped_terrain
        print(
            f"\nTotal : insérées={totals['inserted']}  "
            f"mises à jour={totals['updated']}  "
            f"ignorées={totals['skipped']}  legends={totals['legends']}  "
            f"terrain={totals['terrain']}  échecs={totals['failed']}"
        )
        if args.clean_stale:
            removed = repository.delete_units_imported_before(con, cutoff)
            print(f"Nettoyage : {removed} unités non retouchées supprimées.")
    else:
        print(f"Import en cours depuis BSData : {args.army}…")
        summary = bsdata.import_army(con, args.army)
        print(f"  insérées : {summary.inserted}")
        print(f"  mises à jour : {summary.updated}")
        print(f"  ignorées (profil absent) : {summary.skipped_no_profile}")
        print(f"  ignorées (Legends) : {summary.skipped_legends}")
        print(f"  ignorées (terrain) : {summary.skipped_terrain}")
        if args.clean_stale:
            army = repository.get_army_by_name(con, args.army)
            removed = repository.delete_units_imported_before(con, cutoff, army_id=army.id if army else None)
            print(f"Nettoyage : {removed} unités non retouchées supprimées.")
    _apply_source_corrections(con)
    con.close()
    return 0


def cmd_import_bsdata_list(args: argparse.Namespace) -> int:
    _ = args
    for name, (_main, _lib, alliance) in bsdata.KNOWN_ARMIES.items():
        print(f"  {name:<25} [{alliance}]")
    return 0


def cmd_import_wahapedia(args: argparse.Namespace) -> int:
    con = _connect(args)
    cutoff = datetime.now()
    if getattr(args, "all_factions", False):
        names = list(wahapedia.FACTION_GRAND_ALLIANCE)
        totals = {"inserted": 0, "updated": 0, "skipped": 0, "legends": 0, "failed": 0}
        for name in names:
            print(f"→ {name}…", flush=True)
            try:
                s = wahapedia.import_faction(con, name)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  échec : {exc}")
                totals["failed"] += 1
                continue
            print(
                f"  insérées={s.inserted}  mises à jour={s.updated}  "
                f"ignorées={s.skipped_no_points}  legends={s.skipped_legends}"
            )
            totals["inserted"] += s.inserted
            totals["updated"] += s.updated
            totals["skipped"] += s.skipped_no_points
            totals["legends"] += s.skipped_legends
        print(
            f"\nTotal : insérées={totals['inserted']}  "
            f"mises à jour={totals['updated']}  "
            f"ignorées={totals['skipped']}  legends={totals['legends']}  "
            f"échecs={totals['failed']}"
        )
        if args.clean_stale:
            removed = repository.delete_units_imported_before(con, cutoff)
            print(f"Nettoyage : {removed} unités non retouchées supprimées.")
    else:
        print(f"Import en cours depuis Wahapedia : {args.faction}…")
        summary = wahapedia.import_faction(con, args.faction)
        print(f"  insérées : {summary.inserted}")
        print(f"  mises à jour : {summary.updated}")
        print(f"  ignorées (sans coût) : {summary.skipped_no_points}")
        print(f"  ignorées (Legends) : {summary.skipped_legends}")
        if args.clean_stale:
            army = repository.get_army_by_name(con, args.faction)
            removed = repository.delete_units_imported_before(con, cutoff, army_id=army.id if army else None)
            print(f"Nettoyage : {removed} unités non retouchées supprimées.")
    _apply_source_corrections(con)
    con.close()
    return 0


def cmd_import_verify(args: argparse.Namespace) -> int:
    from ..importers.verify import verify_faction

    con = _connect(args)
    try:
        diffs = verify_faction(con, args.faction, args.bsdata_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(exc)
        con.close()
        return 1
    con.close()
    if not diffs:
        print(f"{args.faction} : aucun écart Wahapedia × BSData.")
        return 0
    print(f"{args.faction} : {len(diffs)} écarts Wahapedia × BSData (à trancher sur le scan) :")
    for d in diffs:
        print(f"  {d.unit:<40} {d.field:<28} Wahapedia={d.wahapedia:<14} BSData={d.bsdata}")
    return 0


def cmd_import_wahapedia_list(args: argparse.Namespace) -> int:
    _ = args
    for name, alliance in wahapedia.FACTION_GRAND_ALLIANCE.items():
        print(f"  {name:<25} [{alliance}]")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `import` : bsdata/bsdata-list/wahapedia/wahapedia-list."""
    p_import = sub.add_parser("import", help="Import de données externes.")
    si = p_import.add_subparsers(dest="action", required=True)
    p = si.add_parser("bsdata", help="Importe une armée depuis BSData (GitHub).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--army", help="Nom de l'armée (ex: 'Stormcast Eternals').")
    g.add_argument("--all", dest="all_armies", action="store_true", help="Importe toutes les armées connues.")
    p.add_argument(
        "--clean-stale", action="store_true", help="Purge après import les unités non retouchées (plus dans la source)."
    )
    p.set_defaults(func=cmd_import_bsdata)
    si.add_parser("bsdata-list", help="Liste les armées disponibles à l'import.").set_defaults(
        func=cmd_import_bsdata_list
    )
    p = si.add_parser("wahapedia", help="Importe une faction depuis les CSV Wahapedia.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--faction", help="Nom de la faction (ex: 'Stormcast Eternals').")
    g.add_argument("--all", dest="all_factions", action="store_true", help="Importe toutes les factions connues.")
    p.add_argument(
        "--clean-stale", action="store_true", help="Purge après import les unités non retouchées (plus dans la source)."
    )
    p.set_defaults(func=cmd_import_wahapedia)
    si.add_parser("wahapedia-list", help="Liste les factions disponibles à l'import Wahapedia.").set_defaults(
        func=cmd_import_wahapedia_list
    )
    p = si.add_parser(
        "verify",
        help="Compare Wahapedia (en base) et BSData (.cat local) pour une faction : "
        "écarts à trancher sur le scan, puis à consigner dans "
        "data/json/source_corrections.json.",
    )
    p.add_argument("--faction", required=True)
    p.add_argument("--bsdata-dir", default="data/bsdata", help="Dossier des .cat BSData (défaut data/bsdata).")
    p.set_defaults(func=cmd_import_verify)

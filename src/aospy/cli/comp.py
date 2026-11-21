"""Commande `comp` : list/show/create/add-unit/remove-entry/clone/delete."""

from __future__ import annotations

import argparse

from ..domain.models import Composition, CompositionUnit
from ..persistence import repository
from .common import _connect, _resolve_army_id


def cmd_comp_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    army_id = _resolve_army_id(con, args.army) if args.army else None
    comps = repository.list_compositions(con, army_id=army_id, kind=args.kind)
    if not comps:
        print("(aucune composition)")
    else:
        print(f"{'ID':<4} {'Armée':<22} {'Nom':<40} {'Kind':<10} {'Pts':>5}/{'Fmt':>4}")
        armies = {a.id: a.name for a in repository.list_armies(con)}
        for c in comps:
            print(f"{c.id:<4} {armies.get(c.army_id, '?'):<22} {c.name:<40} "
                  f"{c.kind:<10} {c.total_points:>5}/{c.format_points:>4}")
    con.close()
    return 0


def cmd_comp_show(args: argparse.Namespace) -> int:
    con = _connect(args)
    comp = repository.get_composition(con, args.comp_id)
    if comp is None:
        raise ValueError(f"composition introuvable: {args.comp_id}")
    armies = {a.id: a.name for a in repository.list_armies(con)}
    print(f"#{comp.id} — {comp.name}")
    print(f"  Armée       : {armies.get(comp.army_id, '?')}")
    print(f"  Type        : {comp.kind}")
    print(f"  Format      : {comp.format_points} pts")
    print(f"  Total       : {comp.total_points} pts"
          + ("  ⚠ dépassement" if comp.total_points > comp.format_points else ""))
    if comp.source:
        print(f"  Source      : {comp.source}")
    if comp.notes:
        print(f"  Notes       : {comp.notes}")
    print("  Entrées :")
    for e in comp.entries:
        unit = repository.get_unit(con, e.unit_id)
        uname = unit.name if unit else f"unit#{e.unit_id}"
        flags = []
        if e.reinforced:
            flags.append("renforcée")
        if e.is_general:
            flags.append("général")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(f"    - entry#{e.id} {uname}{suffix}")
        if e.heroic_trait_id or e.artefact_id:
            extras = []
            if e.heroic_trait_id:
                extras.append(f"trait#{e.heroic_trait_id}")
            if e.artefact_id:
                extras.append(f"artefact#{e.artefact_id}")
            print(f"        {' / '.join(extras)}")
    con.close()
    return 0


def cmd_comp_create(args: argparse.Namespace) -> int:
    con = _connect(args)
    army_id = _resolve_army_id(con, args.army)
    comp = Composition(
        army_id=army_id, name=args.name, kind=args.kind,
        format_points=args.format_points, source=args.source, notes=args.notes,
    )
    comp_id = repository.add_composition(con, comp)
    print(f"Composition créée : #{comp_id} — {args.name}")
    con.close()
    return 0


def cmd_comp_add_unit(args: argparse.Namespace) -> int:
    con = _connect(args)
    comp = repository.get_composition(con, args.comp_id)
    if comp is None:
        raise ValueError(f"composition introuvable: {args.comp_id}")
    units = {u.name: u for u in repository.list_units_for_army(con, comp.army_id)}
    unit = units.get(args.unit)
    if unit is None or unit.id is None:
        raise ValueError(f"unité '{args.unit}' introuvable pour cette armée")

    trait_id = None
    artefact_id = None
    if args.trait or args.artefact:
        if not args.general:
            raise ValueError("--trait / --artefact requièrent --general")
        if not unit.is_hero:
            raise ValueError(f"'{unit.name}' n'est pas un héros")
        if args.trait:
            t = repository.get_heroic_trait_by_name(con, comp.army_id, args.trait)
            if t is None:
                raise ValueError(f"trait héroïque inconnu: {args.trait}")
            trait_id = t.id
        if args.artefact:
            a = repository.get_artefact_by_name(con, comp.army_id, args.artefact)
            if a is None:
                raise ValueError(f"artefact inconnu: {args.artefact}")
            artefact_id = a.id

    if args.general:
        con.execute(
            "UPDATE composition_unit SET is_general = FALSE WHERE composition_id = ?",
            [args.comp_id],
        )

    entry_id = repository.add_composition_entry(
        con, args.comp_id, CompositionUnit(
            unit_id=unit.id, reinforced=args.reinforced, is_general=args.general,
            heroic_trait_id=trait_id, artefact_id=artefact_id,
        ),
    )
    refreshed = repository.get_composition(con, args.comp_id)
    print(f"Entrée ajoutée : entry#{entry_id} {unit.name}"
          + (" (renforcée)" if args.reinforced else ""))
    if refreshed and refreshed.total_points > refreshed.format_points:
        print(f"  ⚠ {refreshed.total_points} > {refreshed.format_points} pts")
    con.close()
    return 0


def cmd_comp_remove_entry(args: argparse.Namespace) -> int:
    con = _connect(args)
    ok = repository.remove_composition_entry(con, args.entry_id)
    if not ok:
        raise ValueError(f"entrée introuvable: {args.entry_id}")
    print(f"Entrée supprimée : entry#{args.entry_id}")
    con.close()
    return 0


def cmd_comp_clone(args: argparse.Namespace) -> int:
    con = _connect(args)
    new_id = repository.clone_composition(con, args.source_id, args.name)
    print(f"Composition clonée : #{args.source_id} -> #{new_id} ({args.name})")
    con.close()
    return 0


def cmd_comp_delete(args: argparse.Namespace) -> int:
    con = _connect(args)
    ok = repository.delete_composition(con, args.comp_id)
    if not ok:
        raise ValueError(f"composition introuvable: {args.comp_id}")
    print(f"Composition supprimée : #{args.comp_id}")
    con.close()
    return 0



def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `comp` : list/show/create/add-unit/remove-entry/clone/delete."""
    p_comp = sub.add_parser("comp", help="Commandes sur les compositions.")
    sc = p_comp.add_subparsers(dest="action", required=True)

    p = sc.add_parser("list", help="Liste les compositions.")
    p.add_argument("--army", help="Filtrer par nom d'armée.")
    p.add_argument("--kind", choices=["tournament", "custom"], help="Filtrer par type.")
    p.set_defaults(func=cmd_comp_list)

    p = sc.add_parser("show", help="Affiche le détail d'une composition.")
    p.add_argument("comp_id", type=int, help="ID de la composition.")
    p.set_defaults(func=cmd_comp_show)

    p = sc.add_parser("create", help="Crée une composition custom vide.")
    p.add_argument("--army", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--format-points", type=int, default=2000)
    p.add_argument("--kind", choices=["tournament", "custom"], default="custom")
    p.add_argument("--source")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_comp_create)

    p = sc.add_parser("add-unit", help="Ajoute une unité à une composition.")
    p.add_argument("--comp", dest="comp_id", type=int, required=True)
    p.add_argument("--unit", required=True, help="Nom de l'unité.")
    p.add_argument("--reinforced", action="store_true")
    p.add_argument("--general", action="store_true",
                   help="Désigne cette entrée comme général.")
    p.add_argument("--trait", help="Nom du trait héroïque (requiert --general).")
    p.add_argument("--artefact", help="Nom de l'artefact (requiert --general).")
    p.set_defaults(func=cmd_comp_add_unit)

    p = sc.add_parser("remove-entry", help="Retire une entrée d'une composition.")
    p.add_argument("--entry", dest="entry_id", type=int, required=True)
    p.set_defaults(func=cmd_comp_remove_entry)

    p = sc.add_parser("clone", help="Duplique une composition (en custom).")
    p.add_argument("--from", dest="source_id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_comp_clone)

    p = sc.add_parser("delete", help="Supprime une composition.")
    p.add_argument("comp_id", type=int)
    p.set_defaults(func=cmd_comp_delete)

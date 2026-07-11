"""Implémentations des commandes CLI AoSPy."""

from __future__ import annotations

import argparse

from . import benchmark as bench
from . import bsdata, db, repository, seed
from .models import Composition, CompositionUnit
from .report import format_benchmark, format_duel_detail, format_report
from .simulation import SideOptions, simulate_battle


def _connect(args: argparse.Namespace):
    return db.connect(args.db)


def _resolve_army_id(con, name: str) -> int:
    army = repository.get_army_by_name(con, name)
    if army is None or army.id is None:
        raise ValueError(f"armée inconnue: {name}")
    return army.id


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


def cmd_unit_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    army_id = _resolve_army_id(con, args.army)
    units = repository.list_units_for_army(con, army_id)
    print(f"{'ID':<4} {'Nom':<25} {'M':>2} {'Sv':>3} {'Hp':>3} {'Ctrl':>4} {'Pts':>5} Hero")
    for u in units:
        print(f"{u.id:<4} {u.name:<25} {u.move:>2} {u.save:>2}+ "
              f"{u.health:>3} {u.control:>4} {u.points:>5} {'X' if u.is_hero else ''}")
    con.close()
    return 0


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


def _resolve_side(flag_value: str, side: str) -> bool:
    return flag_value == side or flag_value == "both"


def _side_options(args: argparse.Namespace, side: str) -> SideOptions:
    return SideOptions(
        charged=_resolve_side(args.charge, side),
        all_out_attack=_resolve_side(args.aoa, side),
        all_out_defense=_resolve_side(args.aod, side),
    )


def cmd_unit_duel(args: argparse.Namespace) -> int:
    con = _connect(args)
    attacker, _ = bench.find_unit(con, args.attacker, args.attacker_army)
    defender, defender_army = bench.find_unit(con, args.defender, args.defender_army)
    result = bench.unit_duel(
        attacker, defender, defender_army,
        attacker_reinforced=args.attacker_reinforced,
        defender_reinforced=args.defender_reinforced,
        options_a=_side_options(args, "a"),
        options_b=_side_options(args, "b"),
    )
    print(format_duel_detail(result))
    con.close()
    return 0


def cmd_unit_benchmark_all(args: argparse.Namespace) -> int:
    con = _connect(args)
    if args.reset:
        removed = repository.clear_benchmark_results(con)
        print(f"Table unit_benchmark vidée : {removed} lignes supprimées.")
    opts_a = _side_options(args, "a")
    opts_b = _side_options(args, "b")

    def _progress(attacker_name: str, army_name: str, idx: int, total: int) -> None:
        print(f"[{idx:>4}/{total}] {attacker_name} [{army_name}]…", flush=True)

    summary = bench.run_all_benchmarks(
        con,
        options_a=opts_a, options_b=opts_b,
        include_heroes=args.include_heroes,
        progress=_progress if args.verbose else None,
    )
    print(
        f"\nTerminé : {summary.attackers} attaquants × défenseurs "
        f"= {summary.duels} duels persistés dans unit_benchmark."
    )
    con.close()
    return 0


def cmd_unit_benchmark(args: argparse.Namespace) -> int:
    con = _connect(args)
    attacker, attacker_army = bench.find_unit(con, args.attacker, args.attacker_army)
    exclude_id = None
    if not args.vs_army:
        a = repository.get_army_by_name(con, attacker_army)
        exclude_id = a.id if a else None
    results = bench.benchmark_attacker(
        con, attacker,
        attacker_reinforced=args.attacker_reinforced,
        defender_reinforced=args.defender_reinforced,
        exclude_army_id=exclude_id,
        target_army=args.vs_army,
        include_heroes=args.include_heroes,
        options_a=_side_options(args, "a"),
        options_b=_side_options(args, "b"),
    )
    label = f"{attacker.name} [{attacker_army}]"
    if args.attacker_reinforced:
        label += " (R)"
    print(format_benchmark(
        label, results, _side_options(args, "a"), _side_options(args, "b"),
        sort_by=args.sort_by, detail=args.detail, top=args.top,
    ))
    con.close()
    return 0


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


def cmd_import_bsdata(args: argparse.Namespace) -> int:
    con = _connect(args)
    if getattr(args, "all_armies", False):
        names = list(bsdata.KNOWN_ARMIES)
        totals = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0}
        for name in names:
            print(f"→ {name}…", flush=True)
            try:
                s = bsdata.import_army(con, name)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  échec : {exc}")
                totals["failed"] += 1
                continue
            print(f"  insérées={s.inserted}  mises à jour={s.updated}  "
                  f"ignorées={s.skipped_no_profile}")
            totals["inserted"] += s.inserted
            totals["updated"] += s.updated
            totals["skipped"] += s.skipped_no_profile
        print(f"\nTotal : insérées={totals['inserted']}  "
              f"mises à jour={totals['updated']}  "
              f"ignorées={totals['skipped']}  échecs={totals['failed']}")
    else:
        print(f"Import en cours depuis BSData : {args.army}…")
        summary = bsdata.import_army(con, args.army)
        print(f"  insérées : {summary.inserted}")
        print(f"  mises à jour : {summary.updated}")
        print(f"  ignorées (profil absent) : {summary.skipped_no_profile}")
    con.close()
    return 0


def cmd_import_bsdata_list(args: argparse.Namespace) -> int:
    _ = args
    for name, (_main, _lib, alliance) in bsdata.KNOWN_ARMIES.items():
        print(f"  {name:<25} [{alliance}]")
    return 0

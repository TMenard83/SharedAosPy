"""Implémentations des commandes CLI AoSPy."""

from __future__ import annotations

import argparse
from datetime import datetime

from ..domain.models import Composition, CompositionUnit, Unit
from ..engine.combat import CombatModifiers, distribution_floor, unit_damage_distribution, unit_damage_moments
from ..importers import bsdata, wahapedia
from ..orchestration import benchmark as bench
from ..orchestration.simulation import SideOptions, simulate_battle
from ..persistence import db, repository, seed
from .report import format_benchmark, format_duel_detail, format_report, format_unit_stats


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
        ran_and_charged=_resolve_side(args.ran_and_charged, side),
    )


def _duel_rules(args: argparse.Namespace) -> bench.DuelRules:
    return bench.DuelRules(
        double_shoot=args.rule_double_shoot,
        charge_move_threshold=args.rule_charge_threshold,
        charge_dist_in=args.charge_dist,
        run_dist_in=args.run_dist,
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
        mode_a=args.attacker_mode, mode_b=args.defender_mode,
        rules=_duel_rules(args),
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
        mode_a=args.attacker_mode, mode_b=args.defender_mode,
        rules=_duel_rules(args),
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
        mode_a=args.attacker_mode, mode_b=args.defender_mode,
        rules=_duel_rules(args),
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
            print(f"  insérées={s.inserted}  mises à jour={s.updated}  "
                  f"ignorées={s.skipped_no_profile}  legends={s.skipped_legends}  terrain={s.skipped_terrain}")
            totals["inserted"] += s.inserted
            totals["updated"] += s.updated
            totals["skipped"] += s.skipped_no_profile
            totals["legends"] += s.skipped_legends
            totals["terrain"] += s.skipped_terrain
        print(f"\nTotal : insérées={totals['inserted']}  "
              f"mises à jour={totals['updated']}  "
              f"ignorées={totals['skipped']}  legends={totals['legends']}  "
              f"terrain={totals['terrain']}  échecs={totals['failed']}")
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
            print(f"  insérées={s.inserted}  mises à jour={s.updated}  "
                  f"ignorées={s.skipped_no_points}  legends={s.skipped_legends}")
            totals["inserted"] += s.inserted
            totals["updated"] += s.updated
            totals["skipped"] += s.skipped_no_points
            totals["legends"] += s.skipped_legends
        print(f"\nTotal : insérées={totals['inserted']}  "
              f"mises à jour={totals['updated']}  "
              f"ignorées={totals['skipped']}  legends={totals['legends']}  "
              f"échecs={totals['failed']}")
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


#: Cibles standard pour `unit stats` : save 2+, save 4+, aucune save (7 = impossible).
_STATS_TARGETS: list[tuple[str, Unit]] = [
    (label, Unit(name="_probe", army_id=0, move=0, save=save, health=1, control=0, models=1, points=0))
    for label, save in (("Save 2+", 2), ("Save 4+", 4), ("Sans save", 7))
]


def cmd_unit_stats(args: argparse.Namespace) -> int:
    con = _connect(args)
    unit, army_name = bench.find_unit(con, args.attacker, args.attacker_army)
    mods = CombatModifiers(attacker_charged=args.charge)
    rows = []
    for label, target in _STATS_TARGETS:
        mean, _var, std = unit_damage_moments(unit, unit.models, target, mods)
        pmf = unit_damage_distribution(unit, unit.models, target, mods)
        rows.append((label, mean, std, distribution_floor(pmf, 0.95)))
    print(format_unit_stats(unit, army_name, rows, charged=args.charge))
    con.close()
    return 0


def cmd_cost_fit(args: argparse.Namespace) -> int:
    con = _connect(args)
    from ..analysis import cost_model

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


def cmd_roster_pdf(args: argparse.Namespace) -> int:
    try:
        from ..tournament_kit import pdf_builder
    except ImportError:
        print("Le kit de tournoi nécessite l'extra [roster] : pip install -e '.[roster]'")
        return 1

    result = pdf_builder.build_roster_pdf(args.list, out_path=args.out, mode=args.mode)
    print(f"PDF généré : {result.output_path}")
    if result.scenario_output_path is not None:
        print(f"PDF avec scénarios : {result.scenario_output_path}")
    if result.absent_references:
        print("  À vérifier (aptitude qui cite une unité absente de la liste) :")
        for ref in result.absent_references:
            print(f"    - {ref.ability} ({ref.owner}) -> {ref.unit}")
    if result.absent_keywords:
        print("  À vérifier (aptitude qui vise un type d'unité amie absent de la liste) :")
        for ref in result.absent_keywords:
            print(f"    - {ref.ability} ({ref.owner}) -> {ref.unit}")
    print(f"  {len(result.units_matched)} profil(s) trouvé(s).")
    print(f"  {len(result.rules_included)} section(s) de règles incluse(s).")
    if result.units_unmatched:
        print(f"  {len(result.units_unmatched)} profil(s) non trouvé(s) dans l'index :")
        for name in result.units_unmatched:
            print(f"    - {name}")
    if result.rules_unmatched:
        print(f"  {len(result.rules_unmatched)} règle(s) non trouvée(s) dans l'index :")
        for name in result.rules_unmatched:
            print(f"    - {name}")
    if result.wahapedia_used:
        print(f"  {len(result.wahapedia_used)} élément(s) complété(s) en anglais via Wahapedia (voir annexe) :")
        for name in result.wahapedia_used:
            print(f"    - {name}")
    return 0


def cmd_cost_residuals(args: argparse.Namespace) -> int:
    con = _connect(args)
    from ..analysis import cost_model

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
        print(f"  {r.name:<28} [{armies.get(r.army_id, '?'):<20}]  pts={r.points:<5} "
              f"prédit={r.predicted:7.1f}  résidu={r.residual:+7.1f} ({r.residual_pct:+.0f}%)")
    con.close()
    return 0


# ----- ability -----------------------------------------------------------------

_VERDICT_FR = {"plan": "PLAN", "correct": "correct", "pari": "PARI", "bonus": "BONUS", "anecdotique": "anecdotique", "a-revoir": "à revoir"}


def cmd_ability_analyze(args: argparse.Namespace) -> int:
    from ..abilities.pipeline import ANALYZER_VERSION, analyze_all, to_rows
    from ..abilities.source import DEFAULT_DATA_DIR

    analyses, orphans = analyze_all(args.data_dir or DEFAULT_DATA_DIR)
    con = _connect(args)
    repository.replace_ability_analyses(con, *to_rows(analyses))
    stats = repository.ability_stats(con)
    con.close()
    print(f"{len(analyses)} aptitudes analysées (analyseur v{ANALYZER_VERSION}).")
    print("  " + ", ".join(f"{_VERDICT_FR.get(v, v)} {n}" for v, n in stats["verdict"]))
    if orphans:
        print(f"⚠ {len(orphans)} correction(s) manuelle(s) orpheline(s) (texte modifié ?) : {', '.join(orphans)}")
    return 0


def _ability_line(r: dict, with_text: bool) -> str:
    axes = f"P{r['power']:.1f} F{r['reliability']:.1f} M{r['ease']:.1f} I{r['interaction']:.1f}"
    head = (f"{_VERDICT_FR.get(r['verdict'], r['verdict']):<11} {axes}  {r['name']}"
            f"  [{r['faction_id']}] {r['owners'] or ''}"[:160])
    out = head + f"\n            {r['tags']}"
    if with_text:
        out += f"\n            {(r['effect_text'] or '')[:300]}"
    return out


def cmd_ability_search(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.search_abilities(
        con, name=args.name, faction=args.faction, owner=args.owner, tags=args.tag,
        verdict=args.verdict, source_kind=args.kind, order_by=args.sort, limit=args.limit)
    con.close()
    if not rows:
        print("Aucune aptitude (lancez `aospy ability analyze` si les tables sont vides).")
        return 1
    print("P=puissance F=fiabilité M=mise en place I=interaction (0-3)")
    for r in rows:
        print(_ability_line(r, args.text))
    return 0


def cmd_ability_show(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = [r for r in repository.search_abilities(con, faction=args.faction, limit=5000, order_by="name")
            if r["uid"] == args.name or args.name.lower() in r["name"].lower()]
    if not rows:
        con.close()
        print(f"Aucune aptitude ne correspond à {args.name!r}.")
        return 1
    for r in rows[:5]:
        print(f"=== {r['name']} — {r['source_kind']} [{r['faction_name']}] uid={r['uid']}")
        print(f"Porteurs : {r['owners']}")
        cost = f" | coût {r['cost_type']} {r['cost_value']}" if r["cost_type"] else ""
        print(f"Timing : {r['condition_text']}{cost}")
        if r["declare_text"]:
            print(f"Annonce : {r['declare_text']}")
        print(f"Effet : {r['effect_text']}")
        print(f"Verdict : {_VERDICT_FR.get(r['verdict'], r['verdict'])}"
              f"{' (corrigé à la main)' if r['overridden'] else ''}")
        print(r["rationale"])
        print(f"Tags : {r['tags']}")
        effects = repository.get_ability_effects(con, r["uid"])
        if effects:
            print("Effets :")
        for e in effects:
            what = f"{e['kind']}{' ' + e['stat'] if e['stat'] else ''}"
            if e["kind"] == "stat_mod":
                what += f" {e['value']:+g}"
            elif e["dice"]:
                what += f" {e['dice']}"
            elif e["value"]:
                what += f" {e['value']:g}"
            scope = e["weapon_scope"] or ""
            if e["weapon_name"]:
                scope += f" « {e['weapon_name']} »"
            if e["includes_companion"]:
                scope += " (Compagnon incluses)"
            bits = [b for b in (f"{e['side']}" if e["side"] else "", f"armes : {scope}" if scope else "",
                                f"cible : {e['target_keywords']}" if e["target_keywords"] else "",
                                e["target_condition"] or "", f"si : {e['requires']}" if e["requires"] else "",
                                f"durée : {e['duration']}" if e["duration"] else "") if b]
            print(f"  - {what} — {', '.join(bits)}")
        print()
    con.close()
    if len(rows) > 5:
        print(f"… {len(rows) - 5} autre(s) ; affinez avec --faction.")
    return 0


def cmd_ability_stats(args: argparse.Namespace) -> int:
    con = _connect(args)
    st = repository.ability_stats(con)
    con.close()
    print("Verdicts : " + ", ".join(f"{_VERDICT_FR.get(v, v)} {n}" for v, n in st["verdict"]))
    print("Origine (total / non comprises) :")
    for kind, n, unknown in st["source_kind"]:
        print(f"  {kind:<16} {n:>5} {unknown:>5}")
    print("Tags : " + ", ".join(f"{t} {n}" for t, n in st["tag"]))
    for version, when, n in st["version"]:
        print(f"Analyseur v{version} — {n} lignes, {when:%Y-%m-%d %H:%M}")
    return 0


def cmd_ability_review(args: argparse.Namespace) -> int:
    from ..abilities.overrides import load_overrides

    reviewed = list(load_overrides())
    con = _connect(args)
    if not args.category:
        print("Familles de cas suspects (hors aptitudes déjà tranchées dans ability_overrides.json) :")
        for key, (label, _sql) in repository.ABILITY_REVIEW_CATEGORIES.items():
            total, _ = repository.ability_review_queue(con, key, reviewed, limit=1)
            print(f"  {key:<11} {total:>4}  {label}")
        con.close()
        return 0
    total, rows = repository.ability_review_queue(con, args.category, reviewed, limit=args.limit)
    con.close()
    label = repository.ABILITY_REVIEW_CATEGORIES[args.category][0]
    print(f"{args.category} — {label} : {total} restant(s), {len(rows)} affiché(s)")
    for i, r in enumerate(rows, 1):
        print(f"\n{i}. {r['name']} [{r['faction_id']}] — {_VERDICT_FR.get(r['verdict'], r['verdict'])} — uid {r['uid']}")
        print(f"   Timing : {r['condition_text']}")
        if r["declare_text"]:
            print(f"   Annonce : {r['declare_text'][:220]}")
        print(f"   Effet : {(r['effect_text'] or '')[:320]}")
    return 0


def cmd_ability_tags(args: argparse.Namespace) -> int:
    from ..abilities.tags import ALL_TAGS

    for tag, desc in ALL_TAGS.items():
        print(f"{tag:<22} {desc}")
    return 0


# ----- chassis -------------------------------------------------------------------

def cmd_chassis_build(args: argparse.Namespace) -> int:
    from ..analysis.chassis import build_chassis_rows

    con = _connect(args)
    rows, notes = build_chassis_rows(con)
    repository.replace_chassis(con, rows)
    con.close()
    print(f"{len(rows)} châssis construits.")
    for n in notes:
        print(f"⚠ {n}")
    return 0


def _pct(v) -> str:
    return "  -  " if v is None else f"{v:+5.0f}%"


def cmd_chassis_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    hero = True if args.heroes else False if args.troops else None
    rows = repository.list_chassis(con, army=args.army, hero=hero, order_by=args.sort,
                                   ascending=args.asc, limit=args.limit)
    con.close()
    if not rows:
        print("Aucun châssis (lancez `aospy chassis build`).")
        return 1
    print("dég/100 = dégâts moyens d'un round vs save 4+ pour 100 pts ; dur/100 = coups à porter pour tuer, "
          "pour 100 pts ; rang = centile dans le segment ; résidu < 0 = moins cher que prédit ; "
          "%D1/%Comp = part des dégâts d'armes à 1 dégât / Compagnon")
    print(f"{'unité':<38}{'armée':<22}{'pts':>5}{'dég/100':>8}{'rang':>6}{'dur/100':>8}{'rang':>6}"
          f"{'résidu':>8}{'duel':>7}{'%D1':>5}{'%Comp':>6}")
    for r in rows:
        print(f"{r['name'][:37]:<38}{r['army_name'][:21]:<22}{r['points']:>5}{r['dmg_per_100']:>8.1f}"
              f"{r['dmg_pct_rank']:>6.2f}{r['ewounds_per_100']:>8.1f}{r['ewounds_pct_rank']:>6.2f}"
              f"{_pct(r['cost_residual_pct']):>8}{_pct(r['duel_roi_pct']):>7}"
              f"{r['share_damage1']:>5.0%}{r['share_companion']:>6.0%}")
    return 0


def cmd_chassis_show(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_chassis(con, name=args.name, order_by="name", ascending=True, limit=5)
    con.close()
    if not rows:
        print(f"Aucun châssis ne correspond à {args.name!r}.")
        return 1
    for r in rows:
        seg = "héros" if r["is_hero"] else "troupes"
        ward = f", protection {r['ward']}+" if r["ward"] else ""
        print(f"=== {r['name']} [{r['army_name']}] — {r['points']} pts, {r['unit_type']}, {seg}")
        print(f"Profil : {r['models']} fig. × {r['health']} PV, sauvegarde {r['save']}+{ward}, "
              f"mouvement {r['move']}\"{' (vol)' if r['is_flying'] else ''}")
        print(f"Attaque : {r['dmg_melee']:.1f} en mêlée + {r['dmg_ranged']:.1f} au tir (vs save 4+), "
              f"{r['attacks_total']:.0f} attaques — {r['dmg_per_100']:.1f} pour 100 pts (centile {r['dmg_pct_rank']:.0%})")
        print(f"Défense : {r['effective_wounds']:.0f} coups à porter — {r['ewounds_per_100']:.1f} pour 100 pts "
              f"(centile {r['ewounds_pct_rank']:.0%})")
        print(f"Compatibilité : {r['share_melee']:.0%} des dégâts en mêlée, {r['share_damage1']:.0%} d'armes à 1 dégât, "
              f"{r['share_companion']:.0%} d'armes Compagnon, critique dominant {r['crit_type']}")
        print(f"Prix : résidu {_pct(r['cost_residual_pct']).strip()} ; duel : {_pct(r['duel_roi_pct']).strip()}\n")
    return 0


# ----- encounter (couche 3) ------------------------------------------------------

def cmd_encounter_build(args: argparse.Namespace) -> int:
    from ..analysis.encounter import build_encounter_rows

    con = _connect(args)
    from ..analysis.realized import build_realized_rows

    rows, stats = build_encounter_rows(con)
    repository.replace_encounters(con, rows)
    realized = build_realized_rows(con)
    repository.replace_realized(con, realized)
    from ..analysis.marriage import build_marriage_rows

    marriage = build_marriage_rows(con)
    repository.replace_ability_marriage(con, marriage)
    con.close()
    print(f"{len(realized)} valeurs réalisées (châssis + aptitudes propres pondérées).")
    print(f"{len(marriage)} mariages aptitude × porteur (déclenchement × survie).")
    print(f"{stats['rencontres']} rencontres aptitude × châssis ({stats['traduits']} effets amis traduits "
          f"sur {stats['effets']} ; {stats['sans_arme']} paires sans arme concernée).")
    return 0


def cmd_encounter_marriage(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_marriage(con, ability=args.ability, unit=args.unit, family=args.family,
                                    worst=args.worst, limit=args.limit)
    con.close()
    if not rows:
        print("Aucun mariage (lancez `aospy encounter build`).")
        return 1
    print("Mariage = D × S. D = P(conditions tenues par le porteur : charge, territoire, objectif…) × rounds "
          "encore possibles ; S = part des rounds où il survit pour tenir l'effet, à l'exposition imposée "
          "(contact ≤3\", courte ≤9\", longue derrière un écran) face à une unité ennemie moyenne.\n"
          "Hypothèses (marriage.py) à challenger. « bon cas » : conditions tenues par d'autres (couche 4/matchups).")
    print(f"{'aptitude':<28}{'porteur':<30}{'pts':>5}{'mv':>4}{'PV':>4}{'sv':>4}{'fam.':>20}{'P':>6}"
          f"{'expo':>9}{'rnd':>4}{'vie':>6}{'S':>6}{'mariage':>8}  bon cas")
    for r in rows:
        sv = f"{r['save']}+" + (f"/{r['ward']}+" if r['ward'] else "")
        print(f"{r['ability_name'][:27]:<28}{r['unit_name'][:29]:<30}{r['points']:>5}{r['move']:>4}{r['hp']:>4}"
              f"{sv:>7}{(r['family'] or '')[:19]:>17}{r['p_trigger']:>6.2f}{r['exposure']:>9}{r['start_round']:>4}"
              f"{r['rounds_alive']:>6.1f}{r['survival']:>6.2f}{r['marriage']:>8.2f}  {r['good_case_conditions'] or ''}")
    return 0


def _effect_label(r: dict) -> str:
    if r["kind"] == "stat_mod":
        lab = f"{r['value']:+g} {r['stat']}"
    elif r["kind"] == "ward":
        lab = f"protection {r['value']:g}+"
    else:
        lab = r["kind"]
    scope = r["weapon_name"] or r["weapon_scope"]
    return f"{lab} ({scope})" if scope else lab


def cmd_encounter_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_encounters(con, unit=args.unit, ability=args.ability,
                                      relation="porteur" if args.own else None, order_by=args.sort,
                                      limit=args.limit)
    con.close()
    if not rows:
        print("Aucune rencontre (lancez `aospy encounter build`).")
        return 1
    print("gain = sur CE châssis, si l'effet s'applique (dégâts d'un round vs save 4+ / coups à porter) ; "
          "/100 = pour 100 pts du receveur ; P = probabilité de déclenchement (couche 1)")
    print(f"{'unité':<30}{'aptitude':<32}{'effet':<26}{'rel.':<8}{'off':>7}{'déf':>7}{'off/100':>8}"
          f"{'P':>5}  {'verdict':<11}conditions / durée")
    for r in rows:
        off = "" if r["off_gain_pct"] is None or not r["off_gain_pct"] else f"{r['off_gain_pct']:+.0f}%"
        dfn = "" if not r["def_gain_pct"] else f"{r['def_gain_pct']:+.0f}%"
        cond = " ; ".join(x for x in (r["conditions"], r["duration"]) if x)
        print(f"{r['unit_name'][:29]:<30}{r['ability_name'][:31]:<32}{_effect_label(r)[:25]:<26}"
              f"{r['relation']:<8}{off:>7}{dfn:>7}{r['off_gain_per_100']:>8.2f}{r['activation_prob']:>5.0%}  "
              f"{(r['verdict'] or '')[:10]:<11}{cond}")
    return 0


def _gain(after: float, before: float) -> str:
    return "   -  " if not before else f"{100 * (after - before) / before:+5.0f}%"


def _num(v) -> str:
    return "—" if v is None else f"{v:.1f}"


def _print_best(rows: list[dict], detail: bool) -> None:
    print(f"{'#':>3} {'unité':<36}{'armée':<20}{'pts':>5}{'comb.':>7}{'rang':>6}{'dég/100':>8}{'+%':>7}"
          f"{'bon cas':>8}{'dur/100':>8}{'+%':>7}{'bon cas':>8}  │{'ch.dég':>7}{'ch.dur':>7}{'ch.comb':>8}")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3} {r['name'][:35]:<36}{r['army_name'][:19]:<20}{r['points']:>5}{r['combined_per_100']:>7.1f}"
              f"{r['combined_pct_rank']:>6.2f}{r['off_realized_per_100']:>8.1f}"
              f"{_gain(r['off_realized'], r['off_chassis']):>7}{r['off_good_per_100']:>8.1f}"
              f"{r['def_realized_per_100']:>8.1f}{_gain(r['def_realized'], r['def_chassis']):>7}"
              f"{r['def_good_per_100']:>8.1f}  │{_num(r.get('off_fit_per_100')):>7}{_num(r.get('def_fit_per_100')):>7}"
              f"{_num(r.get('combined_fit_per_100')):>8}")
        if detail and r["abilities"]:
            print(f"      aptitudes : {r['abilities']}")


def cmd_encounter_best(args: argparse.Namespace) -> int:
    con = _connect(args)
    segments = [True] if args.heroes else [False] if args.troops else [False, True]
    results = {hero: repository.list_realized(con, army=args.army, hero=hero, name=args.name,
                                              order_by=args.sort, limit=args.limit) for hero in segments}
    con.close()
    if not any(results.values()):
        print("Aucune valeur réalisée (lancez `aospy encounter build`).")
        return 1
    print("Châssis + aptitudes propres qui boostent l'unité, pondérées (rounds 2-3 = 1, 1/4/5 = 1/3 ; "
          "1/bataille courte = 1/2 ; × P(déclenchement)).\n"
          "comb. = √(dég/100 × dur/100) ; rang = centile dans le segment ; dég = dégâts d'un round vs save 4+ ; "
          "dur = coups à porter ; +% = gain sur le châssis nu ; bon cas = avec les effets conditionnels ;\n"
          "ch. = selon châssis : conditions du porteur (charge, territoire, objectif…) × P(ce châssis les remplit)")
    for hero in segments:
        if results[hero]:
            print(f"\n== {'Héros' if hero else 'Troupes'} ==")
            _print_best(results[hero], args.detail)
    return 0

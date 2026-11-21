"""Commande `unit` : list/duel/benchmark/benchmark-all/stats."""

from __future__ import annotations

import argparse

from ..domain.models import Unit
from ..engine.combat import CombatModifiers, distribution_floor, unit_damage_distribution, unit_damage_moments
from ..orchestration import benchmark as bench
from ..persistence import repository
from .common import _connect, _duel_rules, _resolve_army_id, _side_options
from .report import format_benchmark, format_duel_detail, format_unit_stats


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



def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `unit` : list/duel/benchmark/benchmark-all/stats."""
    p_unit = sub.add_parser("unit", help="Commandes sur les unités.")
    su = p_unit.add_subparsers(dest="action", required=True)
    p = su.add_parser("list", help="Liste les unités d'une armée.")
    p.add_argument("--army", required=True, help="Nom de l'armée.")
    p.set_defaults(func=cmd_unit_list)

    p = su.add_parser("duel", help="Duel détaillé entre deux unités.")
    p.add_argument("--attacker", required=True, help="Nom de l'unité attaquante.")
    p.add_argument("--attacker-army", help="Armée de l'attaquant (si ambigu).")
    p.add_argument("--defender", required=True, help="Nom de l'unité défenseuse.")
    p.add_argument("--defender-army", help="Armée du défenseur (si ambigu).")
    p.add_argument("--attacker-reinforced", action="store_true")
    p.add_argument("--defender-reinforced", action="store_true")
    p.add_argument("--charge", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aoa", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aod", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--ran-and-charged", choices=["a", "b", "both", "none"], default="none",
                   help="Côté(s) ayant une règle autorisant courir + charger (interdit par défaut).")
    p.add_argument("--rule-double-shoot", action=argparse.BooleanOptionalAction, default=True,
                   help="Règle optionnelle (active par défaut, --no-rule-double-shoot pour désactiver) : "
                        "le camp à la plus petite portée charge (déduit des stats) ; "
                        "tir double si son Move+charge(+course) < portée adverse.")
    p.add_argument("--rule-charge-threshold", action=argparse.BooleanOptionalAction, default=True,
                   help="Règle optionnelle (active par défaut, --no-rule-charge-threshold pour désactiver) : "
                        "la charge (et son bonus Charge(+N)) se déclenche automatiquement si Move attaquant "
                        "> +30%% du défenseur (indépendant de --charge).")
    p.add_argument("--charge-dist", type=float, default=7.0,
                   help="Distance de charge en pouces (défaut : 7 = espérance de 2D6).")
    p.add_argument("--run-dist", type=float, default=3.5,
                   help="Distance de course en pouces (défaut : 3.5 = espérance de 1D6).")
    p.add_argument("--attacker-mode", choices=["mean", "floor66", "floor80", "floor95"], default="mean",
                   help="Lecture du dégât A→B : espérance (défaut) ou plancher 66%%/80%%/95%%.")
    p.add_argument("--defender-mode", choices=["mean", "floor66", "floor80", "floor95"], default="mean",
                   help="Lecture du dégât B→A : espérance (défaut) ou plancher 66%%/80%%/95%%.")
    p.set_defaults(func=cmd_unit_duel)

    p = su.add_parser("benchmark",
                      help="Benchmark d'un attaquant contre les unités d'autres armées.")
    p.add_argument("--attacker", required=True, help="Nom de l'unité attaquante.")
    p.add_argument("--attacker-army", help="Armée de l'attaquant (si ambigu).")
    p.add_argument("--vs-army",
                   help="Limiter aux unités d'une seule armée (défaut: toutes sauf attaquant).")
    p.add_argument("--include-heroes", action="store_true",
                   help="Inclure les héros dans les défenseurs (défaut: exclus).")
    p.add_argument("--attacker-reinforced", action="store_true")
    p.add_argument("--defender-reinforced", action="store_true")
    p.add_argument("--charge", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aoa", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aod", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--ran-and-charged", choices=["a", "b", "both", "none"], default="none",
                   help="Côté(s) ayant une règle autorisant courir + charger (interdit par défaut).")
    p.add_argument("--rule-double-shoot", action=argparse.BooleanOptionalAction, default=True,
                   help="Règle optionnelle (active par défaut, --no-rule-double-shoot pour désactiver) : "
                        "le camp à la plus petite portée charge (déduit des stats) ; "
                        "tir double si son Move+charge(+course) < portée adverse.")
    p.add_argument("--rule-charge-threshold", action=argparse.BooleanOptionalAction, default=True,
                   help="Règle optionnelle (active par défaut, --no-rule-charge-threshold pour désactiver) : "
                        "la charge (et son bonus Charge(+N)) se déclenche automatiquement si Move attaquant "
                        "> +30%% du défenseur (indépendant de --charge).")
    p.add_argument("--charge-dist", type=float, default=7.0,
                   help="Distance de charge en pouces (défaut : 7 = espérance de 2D6).")
    p.add_argument("--run-dist", type=float, default=3.5,
                   help="Distance de course en pouces (défaut : 3.5 = espérance de 1D6).")
    p.add_argument("--sort-by",
                   choices=["pts-net", "roi", "net", "atb", "bta", "points", "army"],
                   default="pts-net")
    p.add_argument("--top", type=int,
                   help="Limiter la section détails au top N (par net).")
    p.add_argument("--detail", action="store_true",
                   help="Affiche aussi le détail de chaque duel.")
    p.add_argument("--attacker-mode", choices=["mean", "floor66", "floor80", "floor95"], default="mean",
                   help="Lecture du dégât A→B : espérance (défaut) ou plancher 66%%/80%%/95%%.")
    p.add_argument("--defender-mode", choices=["mean", "floor66", "floor80", "floor95"], default="mean",
                   help="Lecture du dégât B→A : espérance (défaut) ou plancher 66%%/80%%/95%%.")
    p.set_defaults(func=cmd_unit_benchmark)

    p = su.add_parser("benchmark-all",
                      help="Benchmarke toutes les unités attaquantes et persiste les résultats.")
    p.add_argument("--include-heroes", action="store_true",
                   help="Inclure les héros (attaquants et défenseurs).")
    p.add_argument("--charge", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aoa", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aod", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--ran-and-charged", choices=["a", "b", "both", "none"], default="none",
                   help="Côté(s) ayant une règle autorisant courir + charger (interdit par défaut).")
    p.add_argument("--rule-double-shoot", action=argparse.BooleanOptionalAction, default=True,
                   help="Règle optionnelle (active par défaut, --no-rule-double-shoot pour désactiver) : "
                        "le camp à la plus petite portée charge (déduit des stats) ; "
                        "tir double si son Move+charge(+course) < portée adverse.")
    p.add_argument("--rule-charge-threshold", action=argparse.BooleanOptionalAction, default=True,
                   help="Règle optionnelle (active par défaut, --no-rule-charge-threshold pour désactiver) : "
                        "la charge (et son bonus Charge(+N)) se déclenche automatiquement si Move attaquant "
                        "> +30%% du défenseur (indépendant de --charge).")
    p.add_argument("--charge-dist", type=float, default=7.0,
                   help="Distance de charge en pouces (défaut : 7 = espérance de 2D6).")
    p.add_argument("--run-dist", type=float, default=3.5,
                   help="Distance de course en pouces (défaut : 3.5 = espérance de 1D6).")
    p.add_argument("--reset", action="store_true",
                   help="Vide la table unit_benchmark avant de relancer.")
    p.add_argument("--attacker-mode", choices=["mean", "floor66", "floor80", "floor95"], default="mean",
                   help="Lecture du dégât A→B : espérance (défaut) ou plancher 66%%/80%%/95%%.")
    p.add_argument("--defender-mode", choices=["mean", "floor66", "floor80", "floor95"], default="mean",
                   help="Lecture du dégât B→A : espérance (défaut) ou plancher 66%%/80%%/95%%.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Affiche la progression attaquant par attaquant.")
    p.set_defaults(func=cmd_unit_benchmark_all)

    p = su.add_parser(
        "stats", help="Moyenne / écart-type / plancher de dégâts 95%% contre 3 cibles standard.",
    )
    p.add_argument("--attacker", required=True, help="Nom de l'unité.")
    p.add_argument("--attacker-army", help="Armée de l'unité (si ambigu).")
    p.add_argument("--charge", action="store_true", help="Applique le bonus de charge.")
    p.set_defaults(func=cmd_unit_stats)

"""CLI AoSPy — gestion des armées, unités et compositions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import commands as cmd
from ..persistence.db import DEFAULT_DB_PATH


def _add_init_reset_subparsers(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="Initialise la DB et seed les données JSON.")
    p.add_argument("--no-compositions", action="store_true",
                   help="Ne charge pas data/compositions.json.")
    p.set_defaults(func=cmd.cmd_init)

    p = sub.add_parser("reset", help="Supprime la base existante.")
    p.set_defaults(func=cmd.cmd_reset)


def _add_army_subparser(sub: argparse._SubParsersAction) -> None:
    p_army = sub.add_parser("army", help="Commandes sur les armées.")
    sa = p_army.add_subparsers(dest="action", required=True)
    sa.add_parser("list", help="Liste les armées.").set_defaults(func=cmd.cmd_army_list)


def _add_unit_subparser(sub: argparse._SubParsersAction) -> None:
    p_unit = sub.add_parser("unit", help="Commandes sur les unités.")
    su = p_unit.add_subparsers(dest="action", required=True)
    p = su.add_parser("list", help="Liste les unités d'une armée.")
    p.add_argument("--army", required=True, help="Nom de l'armée.")
    p.set_defaults(func=cmd.cmd_unit_list)

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
    p.set_defaults(func=cmd.cmd_unit_duel)

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
    p.add_argument("--sort-by",
                   choices=["pts-net", "roi", "net", "atb", "bta", "points", "army"],
                   default="pts-net")
    p.add_argument("--top", type=int,
                   help="Limiter la section détails au top N (par net).")
    p.add_argument("--detail", action="store_true",
                   help="Affiche aussi le détail de chaque duel.")
    p.set_defaults(func=cmd.cmd_unit_benchmark)

    p = su.add_parser("benchmark-all",
                      help="Benchmarke toutes les unités attaquantes et persiste les résultats.")
    p.add_argument("--include-heroes", action="store_true",
                   help="Inclure les héros (attaquants et défenseurs).")
    p.add_argument("--charge", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aoa", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--aod", choices=["a", "b", "both", "none"], default="none")
    p.add_argument("--reset", action="store_true",
                   help="Vide la table unit_benchmark avant de relancer.")
    p.add_argument("--floor95", action="store_true",
                   help="Utilise le plancher de dégâts à 95%% de confiance au lieu de l'espérance.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Affiche la progression attaquant par attaquant.")
    p.set_defaults(func=cmd.cmd_unit_benchmark_all)

    p = su.add_parser(
        "stats", help="Moyenne / écart-type / plancher de dégâts 95% contre 3 cibles standard.",
    )
    p.add_argument("--attacker", required=True, help="Nom de l'unité.")
    p.add_argument("--attacker-army", help="Armée de l'unité (si ambigu).")
    p.add_argument("--charge", action="store_true", help="Applique le bonus de charge.")
    p.set_defaults(func=cmd.cmd_unit_stats)


def _add_comp_subparser(sub: argparse._SubParsersAction) -> None:
    p_comp = sub.add_parser("comp", help="Commandes sur les compositions.")
    sc = p_comp.add_subparsers(dest="action", required=True)

    p = sc.add_parser("list", help="Liste les compositions.")
    p.add_argument("--army", help="Filtrer par nom d'armée.")
    p.add_argument("--kind", choices=["tournament", "custom"], help="Filtrer par type.")
    p.set_defaults(func=cmd.cmd_comp_list)

    p = sc.add_parser("show", help="Affiche le détail d'une composition.")
    p.add_argument("comp_id", type=int, help="ID de la composition.")
    p.set_defaults(func=cmd.cmd_comp_show)

    p = sc.add_parser("create", help="Crée une composition custom vide.")
    p.add_argument("--army", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--format-points", type=int, default=2000)
    p.add_argument("--kind", choices=["tournament", "custom"], default="custom")
    p.add_argument("--source")
    p.add_argument("--notes")
    p.set_defaults(func=cmd.cmd_comp_create)

    p = sc.add_parser("add-unit", help="Ajoute une unité à une composition.")
    p.add_argument("--comp", dest="comp_id", type=int, required=True)
    p.add_argument("--unit", required=True, help="Nom de l'unité.")
    p.add_argument("--reinforced", action="store_true")
    p.add_argument("--general", action="store_true",
                   help="Désigne cette entrée comme général.")
    p.add_argument("--trait", help="Nom du trait héroïque (requiert --general).")
    p.add_argument("--artefact", help="Nom de l'artefact (requiert --general).")
    p.set_defaults(func=cmd.cmd_comp_add_unit)

    p = sc.add_parser("remove-entry", help="Retire une entrée d'une composition.")
    p.add_argument("--entry", dest="entry_id", type=int, required=True)
    p.set_defaults(func=cmd.cmd_comp_remove_entry)

    p = sc.add_parser("clone", help="Duplique une composition (en custom).")
    p.add_argument("--from", dest="source_id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd.cmd_comp_clone)

    p = sc.add_parser("delete", help="Supprime une composition.")
    p.add_argument("comp_id", type=int)
    p.set_defaults(func=cmd.cmd_comp_delete)


def _add_battle_subparser(sub: argparse._SubParsersAction) -> None:
    p_battle = sub.add_parser("battle", help="Simulation d'affrontement.")
    sb = p_battle.add_subparsers(dest="action", required=True)
    p = sb.add_parser("simulate", help="Simule un combat entre 2 compositions.")
    p.add_argument("--a", dest="comp_a", type=int, required=True, help="ID composition A.")
    p.add_argument("--b", dest="comp_b", type=int, required=True, help="ID composition B.")
    p.add_argument("--charge", choices=["a", "b", "both", "none"], default="both",
                   help="Côté(s) qui charge (défaut: both).")
    p.add_argument("--aoa", choices=["a", "b", "both", "none"], default="none",
                   help="All-out Attack (+1 hit).")
    p.add_argument("--aod", choices=["a", "b", "both", "none"], default="none",
                   help="All-out Defense (+1 save).")
    p.set_defaults(func=cmd.cmd_battle_simulate)


def _add_import_subparser(sub: argparse._SubParsersAction) -> None:
    p_import = sub.add_parser("import", help="Import de données externes.")
    si = p_import.add_subparsers(dest="action", required=True)
    p = si.add_parser("bsdata", help="Importe une armée depuis BSData (GitHub).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--army", help="Nom de l'armée (ex: 'Stormcast Eternals').")
    g.add_argument("--all", dest="all_armies", action="store_true",
                   help="Importe toutes les armées connues.")
    p.add_argument("--clean-stale", action="store_true",
                   help="Purge après import les unités non retouchées (plus dans la source).")
    p.set_defaults(func=cmd.cmd_import_bsdata)
    si.add_parser("bsdata-list",
                  help="Liste les armées disponibles à l'import.").set_defaults(
        func=cmd.cmd_import_bsdata_list)
    p = si.add_parser("wahapedia", help="Importe une faction depuis les CSV Wahapedia.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--faction", help="Nom de la faction (ex: 'Stormcast Eternals').")
    g.add_argument("--all", dest="all_factions", action="store_true",
                   help="Importe toutes les factions connues.")
    p.add_argument("--clean-stale", action="store_true",
                   help="Purge après import les unités non retouchées (plus dans la source).")
    p.set_defaults(func=cmd.cmd_import_wahapedia)
    si.add_parser("wahapedia-list",
                  help="Liste les factions disponibles à l'import Wahapedia.").set_defaults(
        func=cmd.cmd_import_wahapedia_list)


def _add_cost_subparser(sub: argparse._SubParsersAction) -> None:
    p_cost = sub.add_parser("cost", help="Modèle de coût (points ~ caractéristiques).")
    scst = p_cost.add_subparsers(dest="action", required=True)
    p = scst.add_parser("fit", help="Ajuste le modèle et affiche les coefficients.")
    p.add_argument("--segmented", action="store_true",
                   help="Ajuste un modèle séparé par segment (hero/troupe).")
    p.set_defaults(func=cmd.cmd_cost_fit)
    p = scst.add_parser("residuals", help="Unités les plus sous/sur-cotées (résidu).")
    p.add_argument("--top", type=int, default=20, help="Nombre d'unités à afficher.")
    p.add_argument("--direction", choices=["under", "over"], default="under",
                   help="Sous-cotées (under, défaut) ou sur-cotées (over).")
    p.set_defaults(func=cmd.cmd_cost_residuals)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aospy",
        description="Calcul de la force de combat d'armées Age of Sigmar.",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help=f"Chemin du fichier DuckDB (défaut: {DEFAULT_DB_PATH}).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    _add_init_reset_subparsers(sub)
    _add_army_subparser(sub)
    _add_unit_subparser(sub)
    _add_comp_subparser(sub)
    _add_battle_subparser(sub)
    _add_import_subparser(sub)
    _add_cost_subparser(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (ValueError, FileNotFoundError) as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

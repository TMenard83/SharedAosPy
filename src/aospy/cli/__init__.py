"""CLI AoSPy — gestion des armées, unités et compositions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import commands as cmd
from ..persistence.db import DEFAULT_DB_PATH


def _add_init_reset_subparsers(sub: argparse._SubParsersAction) -> None:
    """Sous-commandes `init` et `reset` (gestion du fichier DuckDB)."""
    p = sub.add_parser("init", help="Initialise la DB et seed les données JSON.")
    p.add_argument("--no-compositions", action="store_true",
                   help="Ne charge pas data/json/compositions.json.")
    p.set_defaults(func=cmd.cmd_init)

    p = sub.add_parser("reset", help="Supprime la base existante.")
    p.set_defaults(func=cmd.cmd_reset)


def _add_army_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `army` (liste des armées)."""
    p_army = sub.add_parser("army", help="Commandes sur les armées.")
    sa = p_army.add_subparsers(dest="action", required=True)
    sa.add_parser("list", help="Liste les armées.").set_defaults(func=cmd.cmd_army_list)


def _add_unit_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `unit` : list/duel/benchmark/benchmark-all/stats."""
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
    p.set_defaults(func=cmd.cmd_unit_benchmark)

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
    p.set_defaults(func=cmd.cmd_unit_benchmark_all)

    p = su.add_parser(
        "stats", help="Moyenne / écart-type / plancher de dégâts 95%% contre 3 cibles standard.",
    )
    p.add_argument("--attacker", required=True, help="Nom de l'unité.")
    p.add_argument("--attacker-army", help="Armée de l'unité (si ambigu).")
    p.add_argument("--charge", action="store_true", help="Applique le bonus de charge.")
    p.set_defaults(func=cmd.cmd_unit_stats)


def _add_comp_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `comp` : list/show/create/add-unit/remove-entry/clone/delete."""
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
    """Sous-commande `battle` (simulation composition contre composition)."""
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
    """Sous-commande `import` : bsdata/bsdata-list/wahapedia/wahapedia-list."""
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
    p = si.add_parser("verify", help="Compare Wahapedia (en base) et BSData (.cat local) pour une faction : "
                                     "écarts à trancher sur le scan, puis à consigner dans "
                                     "data/json/source_corrections.json.")
    p.add_argument("--faction", required=True)
    p.add_argument("--bsdata-dir", default="data/bsdata", help="Dossier des .cat BSData (défaut data/bsdata).")
    p.set_defaults(func=cmd.cmd_import_verify)


def _add_roster_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `roster` : compile une liste + ses profils d'unité en PDF
    (nécessite l'extra `[roster]`)."""
    p_roster = sub.add_parser("roster", help="Kit de tournoi (liste + profils d'unité) en PDF.")
    sr = p_roster.add_subparsers(dest="action", required=True)
    p = sr.add_parser("analyze", help="Fiche couche 4 chiffrée d'une liste (unités, optimisations, règles "
                                      "mortes, mariages, limites d'armée, magie) en Markdown.")
    p.add_argument("--list", dest="list", required=True, help="Fichier de liste (export texte de l'App).")
    p.add_argument("--out", help="Fichier Markdown de sortie (défaut : affichage).")
    p.set_defaults(func=cmd.cmd_roster_analyze)
    p = sr.add_parser("pdf", help="Compile une liste (export brut de l'App) en PDF.")
    p.add_argument("--list", dest="list", required=True,
                   help="Chemin du fichier de liste (export texte de Warhammer Age of Sigmar: The App).")
    p.add_argument("--out", help="Chemin du PDF de sortie (défaut : scratch/output/roster/<équipe>/<liste>/<liste> (<mode>).pdf, "
                                  "<équipe> = sous-dossier de data/Proposition de listes/, "
                                  "<mode> = 'defaut' pour --mode hybrid).")
    p.add_argument("--mode", choices=["hybrid", "en", "fr", "fr-extended", "fr-split", "fr-split-simple", "en-split-simple"],
                   default="hybrid",
                   help="hybrid (défaut, FR/EN historique) / en (Wahapedia uniquement) / "
                        "fr (vérbatim français intégral, repli Wahapedia) / "
                        "fr-extended (fr + aptitudes génériques MdG) / "
                        "fr-split (fr-extended, aptitudes de toute l'armée en 2 cartes Mon tour / "
                        "Tour adverse par phase, warscrolls réduits aux profils) / "
                        "fr-split-simple (fr-split + simplifications propres à la liste) / "
                        "en-split-simple (même mise en page, en anglais : Wahapedia, Core Rules GW, "
                        "simplifications de la section « en »).")
    p.set_defaults(func=cmd.cmd_roster_pdf)


def _add_cost_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `cost` : fit/residuals (nécessite l'extra `[analysis]`)."""
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


def _add_ability_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `ability` : analyse hors contexte de toutes les aptitudes (src/aospy/abilities/)."""
    p_ab = sub.add_parser("ability", help="Analyse des aptitudes (plan / pari / anecdotique, tags).")
    sab = p_ab.add_subparsers(dest="action", required=True)
    p = sab.add_parser("analyze", help="(Re)construit les tables ability* depuis les CSV Wahapedia.")
    p.add_argument("--data-dir", type=Path, default=None, help="Dossier des CSV (défaut: data/wahapedia).")
    p.set_defaults(func=cmd.cmd_ability_analyze)
    p = sab.add_parser("search", help="Cherche des aptitudes par tag/faction/porteur/verdict.")
    p.add_argument("--name", help="Sous-chaîne du nom de l'aptitude.")
    p.add_argument("--faction", help="Sous-chaîne du nom de faction, ou son code (SE, StD…).")
    p.add_argument("--owner", help="Sous-chaîne du porteur (warscroll ou groupe de règle).")
    p.add_argument("--tag", action="append", default=[], help="Tag exigé (répétable : tous requis).")
    p.add_argument("--verdict", choices=["plan", "correct", "pari", "bonus", "anecdotique", "a-revoir"])
    p.add_argument("--kind", help="Origine : warscroll, battle_trait, spell, prayer…")
    p.add_argument("--sort", default="power", choices=["power", "ease", "reliability", "interaction", "name"])
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--text", action="store_true", help="Affiche aussi le texte de l'effet.")
    p.set_defaults(func=cmd.cmd_ability_search)
    p = sab.add_parser("show", help="Fiche complète (texte, axes, justification) d'une aptitude.")
    p.add_argument("name", help="Nom (sous-chaîne) ou uid.")
    p.add_argument("--faction", help="Restreint à une faction.")
    p.set_defaults(func=cmd.cmd_ability_show)
    p = sab.add_parser("stats", help="Décomptes (verdicts, origines non comprises, tags).")
    p.set_defaults(func=cmd.cmd_ability_stats)
    p = sab.add_parser("review", help="File des cas suspects à revoir (hors aptitudes déjà corrigées).")
    p.add_argument("category", nargs="?", help="Famille (sans argument : liste des familles et décomptes).")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd.cmd_ability_review)
    p = sab.add_parser("tags", help="Vocabulaire des tags.")
    p.set_defaults(func=cmd.cmd_ability_tags)


def _add_chassis_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `chassis` : couche 2, la charte nue (analysis/chassis.py)."""
    p_ch = sub.add_parser("chassis", help="Châssis des unités : la charte nue, sans aptitudes.")
    sch = p_ch.add_subparsers(dest="action", required=True)
    p = sch.add_parser("build", help="(Re)construit la table unit_chassis.")
    p.set_defaults(func=cmd.cmd_chassis_build)
    p = sch.add_parser("list", help="Liste les châssis filtrés et triés.")
    p.add_argument("--army", help="Sous-chaîne du nom d'armée.")
    seg = p.add_mutually_exclusive_group()
    seg.add_argument("--heroes", action="store_true", help="Héros seulement.")
    seg.add_argument("--troops", action="store_true", help="Troupes seulement.")
    p.add_argument("--sort", default="dmg_per_100",
                   choices=["dmg_per_100", "ewounds_per_100", "cost_residual_pct", "duel_roi_pct",
                            "share_damage1", "share_companion", "points", "name"])
    p.add_argument("--asc", action="store_true", help="Tri croissant (ex. résidu le plus négatif).")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd.cmd_chassis_list)
    p = sch.add_parser("show", help="Fiche de châssis d'une unité.")
    p.add_argument("name", help="Nom (sous-chaîne).")
    p.set_defaults(func=cmd.cmd_chassis_show)


def _add_encounter_subparser(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `encounter` : couche 3, rencontre aptitude × châssis (analysis/encounter.py)."""
    p_en = sub.add_parser("encounter", help="Rencontre aptitude × châssis : gain réel d'un effet sur une charte.")
    sen = p_en.add_subparsers(dest="action", required=True)
    p = sen.add_parser("build", help="(Re)construit la table ability_encounter (après `ability analyze`).")
    p.set_defaults(func=cmd.cmd_encounter_build)
    p = sen.add_parser("list", help="Rencontres filtrées, triées par gain.")
    p.add_argument("--unit", help="Receveur (sous-chaîne).")
    p.add_argument("--ability", help="Aptitude (sous-chaîne).")
    p.add_argument("--own", action="store_true", help="Seulement les aptitudes de la charte elle-même.")
    p.add_argument("--sort", default="gain", choices=["gain", "off_per_100", "def_per_100"])
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd.cmd_encounter_list)
    p = sen.add_parser("best", help="Meilleures unités (troupes et héros séparés) : châssis + aptitudes propres, "
                                    "indicateur combiné dégâts × durabilité pour 100 pts.")
    p.add_argument("--army", help="Sous-chaîne du nom d'armée.")
    p.add_argument("--name", help="Sous-chaîne du nom d'unité.")
    seg = p.add_mutually_exclusive_group()
    seg.add_argument("--heroes", action="store_true", help="Héros seulement.")
    seg.add_argument("--troops", action="store_true", help="Troupes seulement.")
    p.add_argument("--sort", default="combined_per_100",
                   choices=["combined_per_100", "combined_fit_per_100", "off_fit_per_100", "def_fit_per_100", "off_realized_per_100", "def_realized_per_100", "off_good_per_100",
                            "def_good_per_100", "off_gain", "def_gain"])
    p.add_argument("--detail", action="store_true", help="Liste les aptitudes prises en compte.")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd.cmd_encounter_best)
    p = sen.add_parser("marriage", help="Mariage châssis × aptitude : le porteur déclenche-t-il l'effet et "
                                        "survit-il pour le tenir ? (bons porteurs d'une aptitude, aptitudes "
                                        "mal mariées d'une unité)")
    p.add_argument("--ability", help="Sous-chaîne du nom d'aptitude.")
    p.add_argument("--unit", help="Sous-chaîne du nom du porteur.")
    p.add_argument("--family", help="Famille (buff-donne, debuff, buff-perso-offensif…).")
    p.add_argument("--worst", action="store_true", help="Pires mariages d'abord.")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd.cmd_encounter_marriage)
    p = sen.add_parser("bearers", help="Bons porteurs des optimisations (traits héroïques, artefacts, "
                                       "améliorations) : chaque unité éligible classée.")
    p.add_argument("--ability", help="Sous-chaîne du nom de l'optimisation.")
    p.add_argument("--unit", help="Sous-chaîne du nom du porteur.")
    p.add_argument("--army", help="Sous-chaîne du nom de faction.")
    p.add_argument("--kind", choices=["heroic_trait", "artefact", "enhancement", "monstrous_trait"])
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd.cmd_encounter_bearers)


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
    _add_roster_subparser(sub)
    _add_ability_subparser(sub)
    _add_chassis_subparser(sub)
    _add_encounter_subparser(sub)

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

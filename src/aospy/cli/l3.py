"""Commande `l3` : outils de la L3 Centre 2026-27 (aller), code dans `aospy/l3/`.

Chaque sous-commande transmet tels quels ses arguments au `main(argv)` du module (ses options
restent celles de l'ancien script `scripts/l3_*.py`) : `aospy l3 diag --help` affiche l'aide du module.
Modules importés à l'appel seulement (`matchups` dépend de pypdf, extra `[roster]`).
"""

from __future__ import annotations

import argparse
import importlib

#: sous-commande -> (module de `aospy.l3`, aide courte)
_COMMANDS = {
    "matchups": ("matchups", "Grilles de matchups des deux équipes (--check : parsing des listes seulement)."),
    "listes": ("listes", "Analyse de toutes les listes de la ligue, un fichier par équipe."),
    "diag": ("diag", "Diagnostic compact (corrélations, --rank, --player, --match, --team)."),
    "compare": ("compare", "Instantanés et comparatifs des grilles (snapshot, list, diff)."),
    "scenarios": ("scenarios", "Analyses scénario par équipe (Scénarios/<équipe>.md)."),
    "scenario-model": ("scenario_model", "Modèle de scénario par carte et par tactique (notes ++ … −−)."),
    "tactiques": ("tactics", "pts de tactique attendus par liste et correction de paire (--ronde, --player)."),
    "scenario-match": ("scenario_matchup", "Composante scénario d'une paire, carte par carte (aisance des 2 listes)."),
    "pairing": ("pairing", "Solveur d'appariement AOSFF (minimax sur la séquence, le défenseur choisit)."),
    "robustesse": ("pairing_robust", "Cases pivot de l'appariement : chaque paire bougée de ±δ, défenseur et valeur."),
    "plan-note": ("plan_note", "note_plan calculée : régression sur les indices couche 4, validation croisée."),
    "qui-tue-qui": ("kills", "Matrice « qui tue qui » d'un match ou des paires de chaque ronde (buffs de liste)."),
    "export-lists": ("export_lists", "Exporte les 54 listes au format texte de l'App (--pdf : + aides de jeu)."),
}


def cmd_l3(args: argparse.Namespace) -> int:
    module = importlib.import_module(f"aospy.l3.{_COMMANDS[args.action][0]}")
    return int(module.main(args.forwarded) or 0)


def register(sub: argparse._SubParsersAction) -> None:
    p_l3 = sub.add_parser("l3", help="Outils L3 Centre 2026-27 (matchups, listes, scénarios).")
    sl3 = p_l3.add_subparsers(dest="action", required=True)
    for name, (_module, help_text) in _COMMANDS.items():
        p = sl3.add_parser(name, help=help_text, add_help=False)
        # Les arguments non reconnus sont transmis au module (voir `cli.main`).
        p.set_defaults(func=cmd_l3, forward_unknown=True)

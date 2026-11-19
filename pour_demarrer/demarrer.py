#!/usr/bin/env python3
"""Point d'entrée interactif pour les utilisateurs qui ne veulent pas lire le code aospy.

Pose quelques questions au clavier puis appelle les commandes `aospy` existantes
(mêmes fonctions, mêmes valeurs par défaut que la CLI). Ne couvre que les cas les
plus courants — voir README.md dans ce dossier pour les paramètres avancés.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "aospy.duckdb"
LISTES_DIR = REPO_ROOT / "data" / "Proposition de listes"

sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from aospy.cli import commands as cmd
    from aospy.persistence import repository
    from aospy.persistence.db import connect
except ImportError:
    print("Le package aospy n'est pas installé.")
    print('Lance d\'abord, depuis la racine du projet : pip install -e ".[dev,analysis,roster]"')
    sys.exit(1)


def ask(question: str) -> str:
    return input(question).strip()


def ask_yes_no(question: str, default: bool = False) -> bool:
    suffixe = " [O/n] " if default else " [o/N] "
    reponse = ask(question + suffixe).lower()
    if not reponse:
        return default
    return reponse in ("o", "oui", "y", "yes")


def choisir_dans_liste(items: list[str], titre: str) -> int:
    print(f"\n{titre}")
    for i, item in enumerate(items, start=1):
        print(f"  {i}. {item}")
    while True:
        choix = ask("> ")
        if choix.isdigit() and 1 <= int(choix) <= len(items):
            return int(choix) - 1
        print("Choix invalide, réessaie.")


def choisir_unite(con, role: str):
    armies = repository.list_armies(con)
    idx = choisir_dans_liste([a.name for a in armies], f"Armée {role} :")
    army = armies[idx]
    units = repository.list_units_for_army(con, army.id)
    if not units:
        raise ValueError(f"aucune unité importée pour {army.name} — choisis une autre armée")
    idx2 = choisir_dans_liste([u.name for u in units], f"Unité {role} dans {army.name} :")
    return units[idx2], army.name


def _args_communs(**overrides) -> dict:
    base = dict(
        db=DB_PATH,
        charge="none", aoa="none", aod="none", ran_and_charged="none",
        rule_double_shoot=True, rule_charge_threshold=True,
        charge_dist=7.0, run_dist=3.5,
        attacker_mode="mean", defender_mode="mean",
    )
    base.update(overrides)
    return base


def _args_duel(**overrides) -> argparse.Namespace:
    base = _args_communs(
        attacker_army=None, defender_army=None,
        attacker_reinforced=False, defender_reinforced=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _args_benchmark(**overrides) -> argparse.Namespace:
    base = _args_communs(
        attacker_army=None, vs_army=None, include_heroes=False,
        attacker_reinforced=False, defender_reinforced=False,
        sort_by="pts-net", top=None, detail=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def action_roster_pdf() -> None:
    listes = sorted(LISTES_DIR.rglob("*.txt"))
    if not listes:
        print(f"Aucune liste trouvée dans {LISTES_DIR}")
        return
    idx = choisir_dans_liste([str(p.relative_to(LISTES_DIR)) for p in listes], "Quelle liste de tournoi ?")
    liste = listes[idx]

    modes = ["hybrid", "en", "fr", "fr-extended"]
    print("\nMode de traduction :")
    print("  hybrid       : FR/EN historique (défaut)")
    print("  en           : Wahapedia uniquement (anglais)")
    print("  fr           : vérbatim français intégral, repli Wahapedia")
    print("  fr-extended  : fr + aptitudes génériques du Manuel du général")
    idx_mode = choisir_dans_liste(modes, "Choix du mode :")

    args = argparse.Namespace(db=DB_PATH, list=str(liste), out=None, mode=modes[idx_mode])
    cmd.cmd_roster_pdf(args)


def action_duel() -> None:
    con = connect(DB_PATH)
    try:
        attaquant, armee_attaquant = choisir_unite(con, "attaquante")
        defenseur, armee_defenseur = choisir_unite(con, "défenseuse")
    finally:
        con.close()

    attaquant_renforce = ask_yes_no("L'attaquant est-il renforcé (doublé) ?")
    defenseur_renforce = ask_yes_no("Le défenseur est-il renforcé (doublé) ?")
    attaquant_charge = ask_yes_no("L'attaquant charge-t-il ?")

    args = _args_duel(
        attacker=attaquant.name, attacker_army=armee_attaquant,
        defender=defenseur.name, defender_army=armee_defenseur,
        attacker_reinforced=attaquant_renforce, defender_reinforced=defenseur_renforce,
        charge="a" if attaquant_charge else "none",
    )
    cmd.cmd_unit_duel(args)


def action_benchmark() -> None:
    con = connect(DB_PATH)
    try:
        attaquant, armee_attaquant = choisir_unite(con, "attaquante")
    finally:
        con.close()

    attaquant_renforce = ask_yes_no("L'attaquant est-il renforcé (doublé) ?")
    attaquant_charge = ask_yes_no("L'attaquant charge-t-il ?")
    inclure_heros = ask_yes_no("Inclure les héros parmi les défenseurs ?")
    detail = ask_yes_no("Afficher le détail de chaque duel ?")

    args = _args_benchmark(
        attacker=attaquant.name, attacker_army=armee_attaquant,
        attacker_reinforced=attaquant_renforce,
        charge="a" if attaquant_charge else "none",
        include_heroes=inclure_heros, detail=detail,
    )
    cmd.cmd_unit_benchmark(args)


ACTIONS = {
    "1": ("Générer le PDF d'une liste de tournoi", action_roster_pdf),
    "2": ("Comparer deux unités en duel", action_duel),
    "3": ("Comparer une unité contre toutes les autres (benchmark)", action_benchmark),
}


def main() -> None:
    if not DB_PATH.exists():
        print(f"Base de données introuvable : {DB_PATH}")
        print("Lance d'abord : aospy init   (puis aospy import bsdata --all, par exemple)")
        sys.exit(1)

    while True:
        print("\n=== AoSPy — que veux-tu faire ? ===")
        for key, (label, _) in ACTIONS.items():
            print(f"  {key}. {label}")
        print("  0. Quitter")
        choix = ask("> ")
        if choix == "0":
            break
        action = ACTIONS.get(choix)
        if action is None:
            print("Choix invalide.")
            continue
        try:
            action[1]()
        except Exception as exc:
            print(f"Erreur : {exc}")


if __name__ == "__main__":
    main()

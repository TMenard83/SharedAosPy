"""Fusionne des lots de notes liste × scénario dans `Données/notes_scenarios.json` et réécrit la section
« 10. Scénarios » de chaque `analyse.md` concerné.

    aospy l3 notes-fusion <assignations.json> <lot_1.json> [<lot_2.json> ...] [--data DIR]

`assignations.json` : {équipe: {joueur: {"analyse": chemin, "scenarios": [...]}}}.
Lot : {équipe: {joueur: {"profil": str, "notes": {clé: [note, commentaire]}, "ecarts": [...]}}}.
Ne touche qu'à `profil` et `notes` des joueurs présents dans les lots (les autres champs restent).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis_files import DATA, append_section10, scenario_order

NOTES = ("++", "+", "=", "−", "−−")


def fusion(assign_path: Path, lots: list[Path], data: Path = DATA) -> list[str]:
    """Fusionne les lots ; renvoie les erreurs (un joueur en erreur est ignoré, les autres sont écrits)."""
    assign = json.loads(Path(assign_path).read_text(encoding="utf-8"))
    notes_path = data / "Données" / "notes_scenarios.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    order = scenario_order(data)
    errs: list[str] = []
    for lp in lots:
        lot = json.loads(Path(lp).read_text(encoding="utf-8"))
        for eq, joueurs in lot.items():
            for j, e in joueurs.items():
                want = assign[eq][j]["scenarios"]
                miss = set(want) - set(e["notes"])
                bad = [k for k, (n, _) in e["notes"].items() if n not in NOTES or k not in order]
                if miss or bad:
                    errs.append(f"{eq}/{j} : manquants {sorted(miss)}, invalides {bad}")
                    continue
                dst = notes["equipes"][eq]["joueurs"][j]
                dst["profil"] = e["profil"]
                dst["notes"] = {k: e["notes"][k] for k in order if k in e["notes"]}
                p = Path(assign[eq][j]["analyse"])
                p.write_text(append_section10(p.read_text(encoding="utf-8"), order, e), encoding="utf-8")
    notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 notes-fusion", description=__doc__.splitlines()[0])
    ap.add_argument("assignations", type=Path)
    ap.add_argument("lots", nargs="+", type=Path)
    ap.add_argument("--data", type=Path, default=DATA, help="dossier « 2026-27 L3 Aller »")
    a = ap.parse_args(argv)
    print("\n".join(fusion(a.assignations, a.lots, a.data)) or "OK")
    return 0

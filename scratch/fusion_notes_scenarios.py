"""Fusionne des lots de notes liste × scénario dans `Données/notes_scenarios.json` et réécrit la section
« 10. Scénarios » de chaque `analyse.md` (scratch/output/liste_analyse/...).

Usage : python scratch/fusion_notes_scenarios.py <assignations.json> <lot_1.json> [<lot_2.json> ...]
`assignations.json` : {équipe: {joueur: {"analyse": chemin, "scenarios": [...]}}}.
Lot : {équipe: {joueur: {"profil": str, "notes": {clé: [note, commentaire]}, "ecarts": [...]}}}.
Ne touche qu'à `profil` et `notes` des joueurs présents dans les lots (les autres champs restent).
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "data" / "2026-27 L3 Aller" / "Données"
NOTES = ("++", "+", "=", "−", "−−")


def section(scen_order, entry):
    lines = ["## 10. Scénarios", "", entry["profil"], "", "| Scénario | Note | Lecture |", "|---|---|---|"]
    for k in scen_order:
        if k in entry["notes"]:
            n, c = entry["notes"][k]
            lines.append(f"| {k} | {n} | {c.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main(assign_path, *lots):
    A = json.loads(Path(assign_path).read_text(encoding="utf-8"))
    N = json.loads((BASE / "notes_scenarios.json").read_text(encoding="utf-8"))
    order = [s["cle"] for s in json.loads((BASE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]]
    errs = []
    for lp in lots:
        L = json.loads(Path(lp).read_text(encoding="utf-8"))
        for eq, js in L.items():
            for j, e in js.items():
                want = A[eq][j]["scenarios"]
                miss = set(want) - set(e["notes"])
                bad = [k for k, (n, _) in e["notes"].items() if n not in NOTES or k not in order]
                if miss or bad:
                    errs.append(f"{eq}/{j} : manquants {sorted(miss)}, invalides {bad}")
                    continue
                dst = N["equipes"][eq]["joueurs"][j]
                dst["profil"] = e["profil"]
                dst["notes"] = {k: e["notes"][k] for k in order if k in e["notes"]}
                p = Path(A[eq][j]["analyse"])
                txt = p.read_text(encoding="utf-8")
                txt = re.sub(r"\n## 10\. Scénarios\n.*?(?=\n## |\Z)", "", txt, flags=re.S).rstrip() + "\n\n"
                p.write_text(txt + section(order, e), encoding="utf-8")
    (BASE / "notes_scenarios.json").write_text(json.dumps(N, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(errs) or "OK")


if __name__ == "__main__":
    main(*sys.argv[1:])

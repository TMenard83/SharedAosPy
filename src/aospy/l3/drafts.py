"""Brouillons rédigés par agent (`Données/auto/<équipe>/<joueur>.json`, consigne
`.claude/skills/l3-matchups/strategie_agent.md`) → une fiche Markdown de lecture rapide par équipe
(`Listes/Brouillons <équipe>.md`) : confiance, contrôles, analyse, budget PC, contre-jeu, tactiques, questions.

Rien n'est validé : les brouillons ne sont pas fusionnés dans `combos/*.json` (clé `strategie`, `note_plan`) tant
que l'utilisateur ne les a pas relus.

usage : python -m aospy.l3.drafts [--team <fichier d'équipe, ex. Limoges_Wargame>] [--status]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "data" / "2026-27 L3 Aller"
AUTO = FOLDER / "Données" / "auto"
OUT = FOLDER / "Listes"


def _bullets(items) -> list[str]:
    if isinstance(items, str):
        return [items, ""]
    return [f"- {x}" for x in items or []] + [""]


def render_player(d: dict) -> list[str]:
    s, t = d.get("strategie", {}), d.get("tactiques", {})
    out = [f"## {d.get('joueur')} — {d.get('faction', '')}", "",
           f"*{d.get('auteur', 'brouillon')}, {d.get('date', '')} — confiance : {d.get('confiance', '?')}*", ""]
    if d.get("controles"):
        out += ["**Contrôles**", ""] + _bullets(d["controles"])
    out += ["### Analyse", "", s.get("analyse", ""), ""]
    out += ["### Points de commandement", ""] + _bullets(s.get("pc"))
    out += ["### Comment la battre", ""] + _bullets(s.get("contre_jeu"))
    if t:
        out += ["### Tactiques de bataille", "", f"**Cartes** : {', '.join(t.get('cartes', []))} — réalistes "
                f"{t.get('realistes', '?')}.", ""]
        if t.get("bilan"):
            out += [t["bilan"], ""]
        for key, label in (("faciles", "Faciles"), ("difficiles", "Difficiles"), ("scenarios", "Scénarios notables")):
            if t.get(key):
                out += [f"*{label}*", ""] + _bullets(t[key])
        if t.get("plan"):
            out += [f"*Plan* : {t['plan']}", ""]
        if t.get("niveaux"):
            out += ["*Niveaux* : " + " ; ".join(f"{k} = {v}" for k, v in t["niveaux"].items()), ""]
    out += [f"**Note de plan proposée** : {d.get('note_plan_proposee', '?')} — {d.get('justification_note', '')}", ""]
    if s.get("challenge"):
        out += ["### Hypothèses fragiles", ""] + _bullets(s["challenge"])
    if d.get("desaccords_combos"):
        out += ["### Désaccords avec la fiche combos", ""] + _bullets(d["desaccords_combos"])
    if s.get("questions"):
        out += ["### Questions pour toi", ""] + [f"{i}. {q}" for i, q in enumerate(s["questions"], 1)] + [""]
    return out


def render_team(team_dir: Path) -> Path | None:
    files = sorted(team_dir.glob("*.json"))
    if not files:
        return None
    data = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    name = data[0].get("equipe", team_dir.name)
    lines = [f"# Brouillons — {name}", "",
             "Rédigés par agent (consigne `strategie_agent.md`), **non validés**. Lire d'abord la confiance et "
             "les questions.", ""]
    for d in data:
        lines += render_player(d) + ["---", ""]
    path = OUT / f"Brouillons {name}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def status() -> None:
    for f in sorted((FOLDER / "Données" / "combos").glob("*.json")):
        players = [k for k in json.loads(f.read_text(encoding="utf-8")) if not k.startswith("_")]
        done = {p.stem for p in (AUTO / f.stem).glob("*.json")}
        print(f"{f.stem:32} {len(done)}/{len(players)}  manquants : {', '.join(p for p in players if p not in done)}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fiches Markdown des brouillons stratégiques (Données/auto/).")
    ap.add_argument("--team", help="fichier d'équipe (ex. Limoges_Wargame) ; défaut : toutes")
    ap.add_argument("--status", action="store_true", help="avancement par équipe, sans rien écrire")
    args = ap.parse_args(argv)
    if args.status:
        status()
        return
    dirs = [AUTO / args.team] if args.team else sorted(p for p in AUTO.iterdir() if p.is_dir())
    for d in dirs:
        path = render_team(d)
        if path:
            print(path)


if __name__ == "__main__":
    main()

"""PDF de la L3 par équipe : plan d'appariement, fiche d'équipe, matchups (`aospy l3 pdf`).

Produit, dans `data/2026-27 L3 Aller/PDF/` par défaut :
  * `Plan d'appariement <équipe>.pdf` (+ `.md`) : tableau récapitulatif des rondes puis, pour chaque
    ronde, la sortie du solveur d'appariement (étape 1), appelé en process ;
  * `Plan détaillé <court>.pdf` si `aospy l3 plan-appariement` a écrit ses `.md` (`PLAN_DIR`) ;
  * `Fiche <court>.pdf` depuis `Fiches/Fiche <court>.md` ;
  * `Matchups <court>.pdf` (paysage) : `Matchups/Matchups <court>.md` puis la grille de chaque ronde.

Nécessite l'extra `[roster]` (reportlab). `--l3-dir` ne change que les fichiers lus ici (calendrier,
fiches, matchups) ; le solveur lit les données du dépôt.

Usage : aospy l3 pdf [--team Melusior|"Vae Victis Vernou"] [--out DIR] [--l3-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .scenarios import FILE_NAME

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = ROOT / "data" / "2026-27 L3 Aller"
TEAMS = list(FILE_NAME)
PLAN_DIR = ROOT / "scratch" / "output" / "appariement" / "L3 aller"  # sorties de `aospy l3 plan-appariement`

_ROW = re.compile(r"^\| (?P<label>[^|]+) \| [^|]* \| [^|]* \| (?P<p>\d+)% \|$")
_VALUE = re.compile(r"^Valeur : (?P<v>\S+) · leur jeu attendu : (?P<theirs>.*)$")
_ROUND_VALUE = re.compile(r"\*\*Valeur de la ronde\*\* \(somme des 6 parties\) : (?P<v>\S+)")


def summarize_round(md: str) -> dict:
    """Extrait du Markdown du solveur : valeur de ronde, défenseurs conseillés (proba > 0), leur jeu."""
    out = {"valeur": "", "defenseurs": [], "leurs": ""}
    for line in md.splitlines():
        m = _ROUND_VALUE.search(line)
        if m:
            out["valeur"] = m.group("v")
        m = _VALUE.match(line)
        if m and not out["leurs"]:
            out["leurs"] = m.group("theirs")
        m = _ROW.match(line)
        if m and int(m.group("p")) > 0 and not out["leurs"]:
            out["defenseurs"].append(f"{m.group('label').strip()} {m.group('p')} %")
    return out


def summary_table(rows: list[dict]) -> str:
    """Tableau Markdown récapitulatif ; une ligne `{"ronde", "adversaire": None}` = BYE."""
    out = ["| Ronde | Adversaire | Valeur | Défenseur conseillé | Leur défenseur probable |", "|---|---|---|---|---|"]
    for r in rows:
        if r.get("adversaire") is None:
            out.append(f"| {r['ronde']} | BYE | | | |")
            continue
        out.append(
            f"| {r['ronde']} | {r['adversaire']} | {r['valeur']} | {', '.join(r['defenseurs'])} | {r['leurs']} |"
        )
    return "\n".join(out)


def plan_markdown(team: str, l3_dir: Path, mode: str = "mixte") -> str:
    """Plan d'appariement complet d'une équipe (tableau + solveur étape 1 pour chaque ronde)."""
    from . import pairing

    cal = json.loads((l3_dir / "Données" / "scenarios.json").read_text(encoding="utf-8"))["calendrier"][team]
    rows: list[dict] = []
    sections: list[str] = []
    for n in range(1, 6):
        opp = cal.get(str(n))
        if opp is None:
            rows.append({"ronde": n, "adversaire": None})
            sections.append(f"# Ronde {n} — BYE\n\n{team} ne joue pas cette ronde.")
            continue
        args = pairing._parser().parse_args(["--team", team, "--ronde", str(n), "--mode", mode])
        md = pairing.render(args)
        rows.append({"ronde": n, "adversaire": opp, **summarize_round(md)})
        sections.append(md)
    head = f"# Plan d'appariement {team}\n\nÉtape 1 de chaque ronde (mode {mode}).\n\n{summary_table(rows)}\n"
    return head + "\n---\n\n" + "\n\n---\n\n".join(sections) + "\n"


def _round_number(path: Path) -> int:
    m = re.search(r"Ronde (\d+)", path.name)
    return int(m.group(1)) if m else 99


def build_team(team: str, l3_dir: Path, out_dir: Path, mode: str = "mixte") -> list[Path]:
    from ..reports.markdown_pdf import build

    short = FILE_NAME[team]
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    plan_md = out_dir / f"Plan d'appariement {team}.md"
    plan_md.write_text(plan_markdown(team, l3_dir, mode), encoding="utf-8")
    made.append(build(plan_md.with_suffix(".pdf"), [plan_md], titre=f"Plan d'appariement {team}"))

    # plan détaillé (`aospy l3 plan-appariement`) : 00 Index.md puis une page par ronde, s'il a été généré
    for d in (PLAN_DIR / team, PLAN_DIR / short):
        index = d / "00 Index.md"
        if index.exists():
            rounds = sorted((p for p in d.glob("Ronde *.md")), key=_round_number)
            made.append(build(out_dir / f"Plan détaillé {short}.pdf", [index, *rounds],
                              titre=f"Plan d'appariement détaillé {short}"))
            break

    fiche = l3_dir / "Fiches" / f"Fiche {short}.md"
    if fiche.exists():
        made.append(build(out_dir / f"Fiche {short}.pdf", [fiche], titre=f"Fiche {short}"))
    else:
        print(f"Fiche absente : {fiche}")

    mdir = l3_dir / "Matchups"
    inputs = [mdir / f"Matchups {short}.md"]
    rondes = sorted(mdir.glob(f"Matchups {short}/Ronde *"), key=_round_number)
    inputs += [r / "00 Grille et profils.md" for r in rondes]
    inputs = [p for p in inputs if p.exists()]
    if inputs:
        made.append(build(out_dir / f"Matchups {short}.pdf", inputs, paysage=True, titre=f"Matchups {short}"))
    else:
        print(f"Matchups absents : {mdir}")
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 pdf", description=__doc__.split("\n")[0])
    ap.add_argument("--team", choices=TEAMS, help="une seule équipe (défaut : les deux)")
    ap.add_argument("--out", type=Path, help="dossier de sortie (défaut : <l3-dir>/PDF)")
    ap.add_argument("--l3-dir", type=Path, default=DEFAULT_DIR, help="dossier des données L3 (lu seulement)")
    ap.add_argument("--mode", choices=["mixte", "prudent"], default="mixte", help="mode du solveur d'appariement")
    a = ap.parse_args(argv)
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("Les PDF nécessitent l'extra [roster] : pip install -e '.[roster]'")
        return 1
    out = a.out or a.l3_dir / "PDF"
    for team in [a.team] if a.team else TEAMS:
        for p in build_team(team, a.l3_dir, out, a.mode):
            print(f"PDF généré : {p}")
    return 0

"""Réécriture des sections des `analyse.md` de la L3 : « 0. La liste » (depuis l'export texte) et
« 10. Scénarios » (depuis `Données/notes_scenarios.json`).

    aospy l3 analyses --section0|--section10 [--root DIR] [--data DIR] [--dry-run]

Les `analyse.md` sont sous `<root>/<équipe>/<joueur>-<faction>/<liste>/` (défaut `scratch/output/liste_analyse`).
Les deux réécritures sont idempotentes ; `--dry-run` liste seulement les fichiers qui changeraient.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "2026-27 L3 Aller"
DEFAULT_ANALYSES = ROOT / "scratch" / "output" / "liste_analyse"

START, END = "<!-- liste:debut -->", "<!-- liste:fin -->"
HEAD_KEYS = ("Spell Lore", "Prayer Lore", "Manifestation Lore", "Battle Tactic Cards", "Drops", "General's Handbook")
#: joueur (clé de notes_scenarios.json) -> préfixe du nom de dossier d'analyse
ALIAS = {"Sharowkyn": "Sharowkin", "Cartoone": "Cartoon", "Laytorne": "Laytorn", "MuaD_Dib": "Muad_Dib"}
_SEC10 = r"\n## 10\. Scénarios\n.*?(?=\n## |\Z)"


def section10(scen_order: list[str], entry: dict) -> str:
    """Texte markdown de la section « 10. Scénarios » d'un joueur."""
    lines = ["## 10. Scénarios", "", entry["profil"], "", "| Scénario | Note | Lecture |", "|---|---|---|"]
    for k in scen_order:
        if k in entry["notes"]:
            n, c = entry["notes"][k]
            lines.append(f"| {k} | {n} | {c.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def replace_section10(txt: str, scen_order: list[str], entry: dict) -> str | None:
    """Remplace la section 10 existante ; `None` si le document n'en a pas."""
    if "\n## 10. Scénarios\n" not in txt:
        return None
    new = re.sub(_SEC10, lambda _m: "\n" + section10(scen_order, entry).rstrip("\n"), txt, flags=re.S)
    return new if new.endswith("\n") else new + "\n"


def append_section10(txt: str, scen_order: list[str], entry: dict) -> str:
    """Retire l'ancienne section 10 puis ajoute la nouvelle en fin de document."""
    txt = re.sub(_SEC10, "", txt, flags=re.S).rstrip() + "\n\n"
    return txt + section10(scen_order, entry)


def scenario_order(data: Path) -> list[str]:
    raw = json.loads((data / "Données" / "scenarios.json").read_text(encoding="utf-8"))
    return [s["cle"] for s in raw["scenarios"]]


def refresh_section10(root: Path, data: Path, dry_run: bool = False) -> tuple[list[Path], list[str]]:
    """Réécrit la section 10 des analyses ; renvoie (fichiers changés, manques)."""
    notes = json.loads((data / "Données" / "notes_scenarios.json").read_text(encoding="utf-8"))
    order = scenario_order(data)
    changed: list[Path] = []
    miss: list[str] = []
    for eq, team in notes["equipes"].items():
        for j, entry in team["joueurs"].items():
            prefix = ALIAS.get(j, j) + "-"
            paths = [p for p in (root / eq).glob("*/*/analyse.md") if p.parts[-3].startswith(prefix)]
            if len(paths) != 1:
                miss.append(f"{eq}/{j} : {len(paths)} fichier(s)")
                continue
            p = paths[0]
            txt = p.read_text(encoding="utf-8")
            new = replace_section10(txt, order, entry)
            if new is None:
                miss.append(f"{eq}/{j} : pas de section 10")
            elif new != txt:
                changed.append(p)
                if not dry_run:
                    p.write_text(new, encoding="utf-8")
    return changed, miss


def _export_for(analyse: Path, root: Path, exports: Path) -> Path | None:
    team = analyse.relative_to(root).parts[0]
    folder = analyse.parent.parent.name.lower()  # « <joueur>-<faction> », le joueur peut contenir un tiret
    for f in (exports / team).glob("*.txt"):
        if folder.startswith(f.stem.lower()[:6]):
            return f
    local = analyse.parent / "liste.txt"
    return local if local.exists() else None


def render_header(text: str) -> str:
    """Chapitre « 0. La liste » (markdown) depuis un export texte de l'App."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out = ["## 0. La liste", ""]
    body = [ln for ln in lines if ln.strip()]
    title, rest = body[0], body[1:]
    out.append(f"**{title}**")
    out.append("")
    head, i = [], 0
    while i < len(rest) and not re.match(r"^(General's Regiment|Regiment \d+)$", rest[i]):
        head.append(rest[i])
        i += 1
    for h in head:
        key = next((k for k in HEAD_KEYS if h.startswith(k)), None)
        if key and ":" in h and key in ("Battle Tactic Cards", "Drops"):
            k, v = h.split(":", 1)
            out.append(f"- {k.strip()} : {v.strip()}")
        elif key and " - " in h:
            k, v = h.split(" - ", 1)
            out.append(f"- {k.strip()} : {v.strip()}")
        else:
            out.append(f"- {h}")
    for ln in rest[i:]:
        if ln.startswith(("Created with", "App:")):
            continue
        if re.match(r"^(General's Regiment|Regiment \d+|Regiments of Renown|Faction Terrain)$", ln):
            out += ["", f"**{ln}**", ""]
            continue
        if ln.lstrip().startswith("•"):
            out.append(f"  - {ln.strip().lstrip('• ').strip()}")
        else:
            out.append(f"- {ln.strip()}")
    return "\n".join(out) + "\n"


def apply_header(doc: str, export_text: str) -> str:
    """Insère (après le titre `# `) ou remplace le chapitre 0 encadré de marqueurs."""
    block = f"{START}\n{render_header(export_text)}{END}\n"
    if START in doc:
        return re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n", lambda _m: block, doc, flags=re.S)
    first, _, rest = doc.partition("\n")
    if first.startswith("# "):
        return f"{first}\n\n{block}{rest}"
    return block + "\n" + doc


def refresh_header(root: Path, exports: Path, dry_run: bool = False) -> tuple[list[Path], list[Path]]:
    """Met à jour le chapitre 0 ; renvoie (fichiers changés, analyses sans export)."""
    changed: list[Path] = []
    no_export: list[Path] = []
    for analyse in sorted(root.glob("*/*/*/analyse.md")):
        src = _export_for(analyse, root, exports)
        if src is None:
            no_export.append(analyse)
            continue
        doc = analyse.read_text(encoding="utf-8")
        new = apply_header(doc, src.read_text(encoding="utf-8"))
        if new != doc:
            changed.append(analyse)
            if not dry_run:
                analyse.write_text(new, encoding="utf-8")
    return changed, no_export


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 analyses", description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--section0", action="store_true", help="chapitre « 0. La liste » depuis l'export texte")
    g.add_argument("--section10", action="store_true", help="section « 10. Scénarios » depuis notes_scenarios.json")
    ap.add_argument("--root", type=Path, default=DEFAULT_ANALYSES, help="dossier des analyses")
    ap.add_argument("--data", type=Path, default=DATA, help="dossier « 2026-27 L3 Aller »")
    ap.add_argument("--dry-run", action="store_true", help="liste les fichiers qui changeraient, sans écrire")
    a = ap.parse_args(argv)
    verbe = "à réécrire" if a.dry_run else "réécrite(s)"
    miss: list[str] = []
    if a.section0:
        changed, no_export = refresh_header(a.root, a.data / "Listes texte", a.dry_run)
        for p in no_export:
            print("SANS EXPORT", p)
    else:
        changed, miss = refresh_section10(a.root, a.data, a.dry_run)
    for p in changed:
        print(f"  {p.relative_to(a.root)}")
    print(f"{len(changed)} analyse(s) {verbe}")
    if a.section10:
        print("\n".join(miss) or "aucun manque")
    return 0

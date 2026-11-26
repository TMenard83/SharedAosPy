"""Ajoute (ou remplace) en tête de chaque analyse.md L3 un chapitre « 0. La liste » réécrit depuis l'export.

Source : `data/2026-27 L3 Aller/Listes texte/<équipe>/<joueur>.txt` (export à jour), sinon `liste.txt` du dossier.
Idempotent : le chapitre est encadré de marqueurs HTML et remplacé à chaque passage.

    .venv/bin/python scratch/analyse_header_liste.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSES = ROOT / "scratch" / "output" / "liste_analyse"
EXPORTS = ROOT / "data" / "2026-27 L3 Aller" / "Listes texte"
START, END = "<!-- liste:debut -->", "<!-- liste:fin -->"
HEAD_KEYS = ("Spell Lore", "Prayer Lore", "Manifestation Lore", "Battle Tactic Cards", "Drops", "General's Handbook")


def _export_for(analyse: Path) -> Path | None:
    team = analyse.relative_to(ANALYSES).parts[0]
    folder = analyse.parent.parent.name.lower()  # « <joueur>-<faction> », le joueur peut contenir un tiret
    for f in (EXPORTS / team).glob("*.txt"):
        if folder.startswith(f.stem.lower()[:6]):
            return f
    local = analyse.parent / "liste.txt"
    return local if local.exists() else None


def render(text: str) -> str:
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
    section = None
    for ln in rest[i:]:
        if ln.startswith(("Created with", "App:")):
            continue
        if re.match(r"^(General's Regiment|Regiment \d+|Regiments of Renown|Faction Terrain)$", ln):
            section = ln
            out += ["", f"**{section}**", ""]
            continue
        if ln.lstrip().startswith("•"):
            out.append(f"  - {ln.strip().lstrip('• ').strip()}")
        else:
            out.append(f"- {ln.strip()}")
    return "\n".join(out) + "\n"


def main() -> None:
    n = 0
    for analyse in sorted(ANALYSES.glob("*/*/*/analyse.md")):
        src = _export_for(analyse)
        if src is None:
            print("SANS EXPORT", analyse)
            continue
        block = f"{START}\n{render(src.read_text(encoding='utf-8'))}{END}\n"
        doc = analyse.read_text(encoding="utf-8")
        if START in doc:
            doc = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n", block.replace("\\", "\\\\"), doc, flags=re.S)
        else:
            first, _, rest = doc.partition("\n")
            if first.startswith("# "):
                doc = f"{first}\n\n{block}{rest}"
            else:
                doc = block + "\n" + doc
        analyse.write_text(doc, encoding="utf-8")
        n += 1
        print(f"{analyse.relative_to(ANALYSES)}  <-  {src.relative_to(ROOT)}")
    print(f"{n} analyses mises à jour")


if __name__ == "__main__":
    main()

"""Dossier d'analyse d'une liste : rapport couche 4 + profils et textes complets de ses aptitudes.

Enveloppe de `aospy roster dossier` (gardée pour `l3/draft_pack.py` et les consignes d'agent).
usage : .venv/bin/python scratch/list_dossier.py <fichier de liste> <dossier de sortie>
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from aospy.cli.roster import write_dossier  # noqa: E402

con = duckdb.connect("data/aospy.duckdb", read_only=True)
stem, missing = write_dossier(con, sys.argv[1], sys.argv[2])
for m in missing:
    print(f"NON RECONNUE EN BASE : {m}")
print(stem, "ok")

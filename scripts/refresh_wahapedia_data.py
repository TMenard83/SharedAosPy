"""Re-télécharge les CSV Wahapedia (data/wahapedia/*.csv) et raffraîchit la DB.

Script autonome, sans dépendance ni appel LLM : lit `Export Data Specs.xlsx`
en dur (les URLs ci-dessous sont recopiées des hyperliens de ce fichier,
fournis par Wahapedia elle-même sur https://wahapedia.ru/aos4/the-rules/data-export/),
compare d'abord la date de `Last_update.csv` distante à la copie locale (seul
indicateur de version fourni par Wahapedia, qui n'expose aucun historique) et
s'arrête là si rien n'a changé. Sinon télécharge les 13 CSV, archive les anciens
dans data/wahapedia/<date de leur Last_update>/, écrit les nouveaux, puis lance
`aospy import wahapedia --all --clean-stale`.

Usage :
    python scripts/refresh_wahapedia_data.py              # télécharge + réimporte si MAJ
    python scripts/refresh_wahapedia_data.py --check       # affiche les dates seulement
    python scripts/refresh_wahapedia_data.py --force       # télécharge même sans MAJ
    python scripts/refresh_wahapedia_data.py --no-import   # télécharge seulement
    python scripts/refresh_wahapedia_data.py --db chemin.duckdb
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WAHAPEDIA_DIR = REPO_ROOT / "data" / "wahapedia"
BASE_URL = "https://wahapedia.ru/aos4/"
LAST_UPDATE = "Last_update.csv"
FILES = [
    "Factions.csv",
    "Source.csv",
    "Warscrolls.csv",
    "Warscrolls_abilities.csv",
    "Warscrolls_weapons.csv",
    "Warscrolls_keywords.csv",
    "Warscrolls_bases.csv",
    "Warscrolls_organisation.csv",
    "Warscrolls_RoRfactions.csv",
    "Faction_ability_types.csv",
    "Faction_ability_subtypes.csv",
    "Faction_abilities.csv",
    "Last_update.csv",
]

_UA = "Mozilla/5.0 (aospy wahapedia refresh script)"


def _fetch(name: str) -> bytes:
    req = urllib.request.Request(BASE_URL + name, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _download(name: str, dest: Path) -> None:
    dest.write_bytes(_fetch(name))


def _parse_last_update(raw: str) -> str | None:
    """`last_update|` puis `2026-08-25 14:30:00|` → `"2026-08-25 14:30:00"`."""
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    return lines[1].split("|", 1)[0].strip() or None


def local_last_update() -> str | None:
    path = WAHAPEDIA_DIR / LAST_UPDATE
    if not path.exists():
        return None
    return _parse_last_update(path.read_text(encoding="utf-8-sig", errors="replace"))


def remote_last_update() -> str | None:
    return _parse_last_update(_fetch(LAST_UPDATE).decode("utf-8-sig", errors="replace"))


def _archive_dir(last_update: str | None) -> Path:
    # "2026-08-25 14:30:00" → data/wahapedia/2026-08-25_1430/
    if last_update is None:
        return WAHAPEDIA_DIR / "old"
    day, _, time = last_update.partition(" ")
    return WAHAPEDIA_DIR / (f"{day}_{time.replace(':', '')[:4]}" if time else day)


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return sum(1 for _ in f)


def download_all(staging_dir: Path) -> None:
    staging_dir.mkdir(parents=True, exist_ok=True)
    print(f"Téléchargement de {len(FILES)} fichiers depuis {BASE_URL}…")
    for name in FILES:
        dest = staging_dir / name
        _download(name, dest)
        print(f"  {name:<32} {dest.stat().st_size:>10} octets")


def install(staging_dir: Path, previous: str | None) -> None:
    backup_dir = _archive_dir(previous)
    backup_dir.mkdir(parents=True, exist_ok=True)
    print("\nComparaison avant/après (nb de lignes) :")
    for name in FILES:
        old_path = WAHAPEDIA_DIR / name
        new_path = staging_dir / name
        old_n, new_n = _row_count(old_path), _row_count(new_path)
        marker = "→" if old_n != new_n else "="
        print(f"  {name:<32} {old_n:>6} {marker} {new_n:>6}")
        if old_path.exists():
            shutil.copy2(old_path, backup_dir / name)
        shutil.copy2(new_path, old_path)
    print(f"\nAnciens fichiers sauvegardés dans {backup_dir.relative_to(REPO_ROOT)}/")


def run_import(db: str | None) -> int:
    cmd = [sys.executable, "-m", "aospy"]
    if db:
        cmd += ["--db", db]
    cmd += ["import", "wahapedia", "--all", "--clean-stale"]
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Comparer les dates locale/distante sans rien télécharger."
    )
    parser.add_argument("--force", action="store_true", help="Télécharger même si Last_update.csv n'a pas changé.")
    parser.add_argument("--no-import", action="store_true", help="Télécharger seulement, ne pas réimporter en DB.")
    parser.add_argument("--db", default=None, help="Chemin du fichier DuckDB (défaut : data/aospy.duckdb).")
    args = parser.parse_args()

    local, remote = local_last_update(), remote_last_update()
    print(f"Last_update local    : {local or '(absent)'}")
    print(f"Last_update distant  : {remote or '(illisible)'}")
    up_to_date = local is not None and local == remote
    if args.check:
        print("→ À jour." if up_to_date else "→ Mise à jour disponible.")
        return 0
    if up_to_date and not args.force:
        print("→ Pas de mise à jour, rien à faire (--force pour retélécharger quand même).")
        return 0

    staging = Path("/tmp") / "wahapedia_refresh_staging"
    if staging.exists():
        shutil.rmtree(staging)

    download_all(staging)
    install(staging, local)
    shutil.rmtree(staging)

    if args.no_import:
        print("\n--no-import : DB non modifiée. Lancer plus tard :")
        print("  aospy import wahapedia --all --clean-stale")
        return 0

    return run_import(args.db)


if __name__ == "__main__":
    raise SystemExit(main())

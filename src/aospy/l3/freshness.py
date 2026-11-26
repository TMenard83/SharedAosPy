"""Fraîcheur des fichiers générés de la L3 : un fichier dérivé plus vieux que ses sources est périmé.

Deux fichiers générés sont relus par d'autres outils au lieu d'être recalculés :

* `Données/indicateurs_listes.json` (indicateurs des 54 listes, `tactics.load_pool`) ← base DuckDB + listes texte ;
* la grille `Matchups/…/Ronde N — …/00 Grille et profils.md` (`scenarios.grid`, lue par le solveur
  d'appariement) ← base + listes texte + `combos/*.json` (note de plan) + `ajustements_matchups.json`.

Un agent ou une session qui lit un dérivé périmé travaille sur d'anciennes listes sans le savoir (surprises déjà
vues, 2026-11-26) : on compare les dates de modification et on signale (ou on régénère) plutôt que de se taire.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "2026-27 L3 Aller"
DB = ROOT / "data" / "aospy.duckdb"


def list_sources() -> list[Path]:
    """Sources des indicateurs de liste : la base et les exports texte des 54 listes."""
    return [DB, *sorted((BASE / "Listes texte").glob("*/*.txt"))]


def grid_sources() -> list[Path]:
    """Sources de la grille de matchups : celles des listes + notes de plan + ajustements par paire."""
    data = BASE / "Données"
    return [*list_sources(), *sorted((data / "combos").glob("*.json")), data / "ajustements_matchups.json"]


def newer_sources(derived: Path, sources: Iterable[Path]) -> list[Path]:
    """Sources modifiées après `derived` (toutes si `derived` n'existe pas), les plus récentes d'abord."""
    if not derived.exists():
        return [s for s in sources if s.exists()]
    t = derived.stat().st_mtime
    return sorted((s for s in sources if s.exists() and s.stat().st_mtime > t), key=lambda s: -s.stat().st_mtime)


def describe(paths: list[Path], n: int = 3) -> str:
    names = [str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p) for p in paths[:n]]
    more = f" (+{len(paths) - n})" if len(paths) > n else ""
    return ", ".join(names) + more

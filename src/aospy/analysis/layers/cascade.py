"""Cascade des couches d'analyse : couche 1 → 2 → 3 → 4, jamais une couche sur une couche périmée.

Chaque build de couche 1-3 enregistre l'empreinte de ses entrées (table `layer_build`) :

1. **aptitudes** (`abilities.pipeline`, tables `ability*`) : version de l'analyseur + date des fichiers lus
   (CSV Wahapedia, `source_corrections.json`, `ability_overrides.json`) ;
2. **châssis** (`chassis.py`, `unit_chassis`) : build de la couche 1 + imports d'unités et duels ;
3. **rencontre** (`encounter`, `realized`, `marriage`, `bearers`) : build de la couche 2.

Une couche est périmée si elle n'a jamais été construite ou si l'empreinte courante de ses entrées diffère
de celle enregistrée ; tout ce qui est au-dessus l'est alors aussi. La couche 4 (`listing.analyse_list`)
n'est pas stockée : elle exige les couches 1-3 à jour (`require_fresh(con, 4)`).

`run_cascade` reconstruit à partir de la première couche périmée (ou de `start`), dans l'ordre.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ...persistence import repository

LAYER_NAMES = {1: "aptitudes", 2: "châssis", 3: "rencontre aptitude × châssis", 4: "liste"}
_REPO_ROOT = Path(__file__).resolve().parents[4]
CASCADE_HINT = "lancez `aospy cascade` (reconstruit les couches périmées dans l'ordre 1 → 2 → 3)"


@dataclass
class LayerStatus:
    layer: int
    built_at: Optional[str]
    fresh: bool
    reason: str = ""


def _layer1_fingerprint(data_dir: str | Path | None = None) -> str:
    from ...abilities.overrides import DEFAULT_OVERRIDES_PATH
    from ...abilities.pipeline import ANALYZER_VERSION
    from ...importers.corrections import DEFAULT_CORRECTIONS_PATH
    from ...sources.wahapedia_csv import DEFAULT_DATA_DIR

    # Chemins relatifs résolus depuis la racine du dépôt : l'empreinte ne doit pas dépendre du dossier
    # courant (sinon, lancée hors de la racine, aucun fichier n'est trouvé et la couche 1 paraît périmée).
    def _abs(p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else _REPO_ROOT / p

    files = [*_abs(data_dir or DEFAULT_DATA_DIR).glob("*.csv"), _abs(DEFAULT_CORRECTIONS_PATH),
             _abs(DEFAULT_OVERRIDES_PATH)]
    mtime = max((f.stat().st_mtime for f in files if f.exists()), default=0.0)
    return f"v{ANALYZER_VERSION}|{mtime:.0f}"


def _fingerprint(con, layer: int, builds: dict[int, tuple[str, str]], data_dir=None) -> str:
    if layer == 1:
        return _layer1_fingerprint(data_dir)
    below = builds.get(layer - 1, ("?", ""))[0]
    if layer == 2:
        return f"L1@{below}|{repository.unit_data_stamp(con)}"
    return f"L2@{below}"


def status(con, data_dir: str | Path | None = None) -> list[LayerStatus]:
    """État des couches 1-3 ; une couche au-dessus d'une couche périmée est périmée."""
    builds = repository.layer_builds(con)
    out: list[LayerStatus] = []
    for layer in (1, 2, 3):
        built = builds.get(layer)
        if out and not out[-1].fresh:
            out.append(LayerStatus(layer, built and built[0], False, f"couche {layer - 1} périmée"))
        elif built is None:
            out.append(LayerStatus(layer, None, False, "jamais construite (ou base antérieure à la cascade)"))
        elif built[1] != _fingerprint(con, layer, builds, data_dir):
            reason = "entrées modifiées depuis le build"
            current = _layer1_fingerprint(data_dir).split("|")[0]
            if layer == 1 and built[1].split("|")[0] != current:
                reason = f"analyseur {built[1].split('|')[0]} en base, {current} dans le code"
            out.append(LayerStatus(layer, built[0], False, reason))
        else:
            out.append(LayerStatus(layer, built[0], True))
    return out


def require_fresh(con, layer: int, data_dir: str | Path | None = None) -> None:
    """Lève ValueError si une couche sous `layer` est périmée (garde-fou de chaque couche)."""
    stale = [s for s in status(con, data_dir) if s.layer < layer and not s.fresh]
    if stale:
        s = stale[0]
        raise ValueError(
            f"couche {layer} ({LAYER_NAMES[layer]}) refusée : couche {s.layer} ({LAYER_NAMES[s.layer]}) "
            f"périmée — {s.reason} ; {CASCADE_HINT}."
        )


# ----- builds ------------------------------------------------------------------------------------


def build_layer1(
    con, data_dir: str | Path | None = None, verdict_label: Callable[[str], str] = str
) -> list[str]:
    from ...abilities.pipeline import ANALYZER_VERSION, analyze_all, to_rows
    from ...abilities.source import DEFAULT_DATA_DIR

    analyses, orphans = analyze_all(data_dir or DEFAULT_DATA_DIR)
    repository.replace_ability_analyses(con, *to_rows(analyses))
    repository.mark_layer_built(con, 1, _layer1_fingerprint(data_dir))
    stats = repository.ability_stats(con)
    lines = [f"{len(analyses)} aptitudes analysées (analyseur v{ANALYZER_VERSION}).",
             "  " + ", ".join(f"{verdict_label(v)} {n}" for v, n in stats["verdict"])]
    if orphans:
        lines.append(
            f"⚠ {len(orphans)} correction(s) manuelle(s) orpheline(s) (texte modifié ?) : {', '.join(orphans)}"
        )
    return lines


def build_layer2(con, data_dir: str | Path | None = None) -> list[str]:
    from .chassis import build_chassis_rows

    require_fresh(con, 2, data_dir)
    rows, notes = build_chassis_rows(con)
    repository.replace_chassis(con, rows)
    repository.mark_layer_built(con, 2, _fingerprint(con, 2, repository.layer_builds(con)))
    return [f"{len(rows)} châssis construits.", *(f"⚠ {n}" for n in notes)]


def build_layer3(con, data_dir: str | Path | None = None) -> list[str]:
    from .bearers import build_bearer_rows
    from .encounter import build_encounter_rows
    from .marriage import build_marriage_rows
    from .realized import build_realized_rows

    require_fresh(con, 3, data_dir)
    rows, stats = build_encounter_rows(con)
    repository.replace_encounters(con, rows)
    realized = build_realized_rows(con)
    repository.replace_realized(con, realized)
    marriage = build_marriage_rows(con)
    repository.replace_ability_marriage(con, marriage)
    bearers = build_bearer_rows(con)
    repository.replace_enhancement_bearers(con, bearers)
    repository.mark_layer_built(con, 3, _fingerprint(con, 3, repository.layer_builds(con)))
    return [
        f"{len(bearers)} couples optimisation × porteur éligible.",
        f"{len(realized)} valeurs réalisées (châssis + aptitudes propres pondérées).",
        f"{len(marriage)} mariages aptitude × porteur (déclenchement × survie × tempo × amplification × rôle).",
        f"{stats['rencontres']} rencontres aptitude × châssis ({stats['traduits']} effets amis traduits "
        f"sur {stats['effets']} ; {stats['sans_arme']} paires sans arme concernée).",
    ]


def run_cascade(
    con,
    start: Optional[int] = None,
    data_dir: str | Path | None = None,
    log: Callable[[str], None] = print,
) -> list[int]:
    """Reconstruit les couches à partir de `start` (défaut : première couche périmée). Renvoie les couches faites."""
    if start is None:
        stale = [s.layer for s in status(con, data_dir) if not s.fresh]
        if not stale:
            return []
        start = stale[0]
    done = []
    for layer in range(start, 4):
        log(f"— couche {layer} ({LAYER_NAMES[layer]})")
        build = {1: build_layer1, 2: build_layer2, 3: build_layer3}[layer]
        lines = build(con, data_dir)
        for line in lines:
            log("  " + line)
        done.append(layer)
    return done

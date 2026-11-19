"""Corrections manuelles de l'analyse (`data/json/ability_overrides.json`).

Format : `{"overrides": {"<uid>": {"name": "...", <champs>}}}` où `name` n'est
qu'un rappel lisible (non utilisé pour la jointure, l'uid fait foi). Champs
acceptés : `ease`/`power`/`reliability`/`interaction` (0-3), `verdict`,
`add_tags`/`remove_tags` (listes), `note` (ajoutée à la justification).
Un override dont l'uid n'existe plus est signalé par `aospy ability stats`
(texte Wahapedia modifié → l'uid change, la correction est à revalider).
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import AbilityAnalysis
from .tags import ALL_TAGS

DEFAULT_OVERRIDES_PATH = Path("data") / "json" / "ability_overrides.json"
_AXES = ("ease", "power", "reliability", "interaction")


def load_overrides(path: str | Path = DEFAULT_OVERRIDES_PATH) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("overrides", {})


def apply_override(a: AbilityAnalysis, ov: dict) -> AbilityAnalysis:
    for axis in _AXES:
        if axis in ov:
            setattr(a.score, axis, float(ov[axis]))
    if "verdict" in ov:
        old = a.score.verdict
        a.score.verdict = ov["verdict"]
        a.tags = [t for t in a.tags if t != old] + [ov["verdict"]]
    for tag in ov.get("add_tags", []):
        if tag not in ALL_TAGS:
            raise ValueError(f"tag inconnu dans l'override {a.raw.uid}: {tag}")
        if tag not in a.tags:
            a.tags.append(tag)
    a.tags = sorted(t for t in a.tags if t not in set(ov.get("remove_tags", [])))
    if ov.get("note"):
        a.score.rationale.append(f"Correction manuelle — {ov['note']}")
    a.overridden = True
    return a

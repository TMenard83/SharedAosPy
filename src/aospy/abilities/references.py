"""Seconde passe (analyseur v34, chantier B) : valeur des effets qui renvoient à d'autres aptitudes.

`extract.references` repère les effets `ability_ref` / `status_grant` / `free_enhancement` / `terrain_setup`
(valeur 0) ; ici on leur donne la puissance tirée des aptitudes citées, notées en première passe. Les
aptitudes de référence sont cherchées dans la même faction (repli : toutes factions pour un nom exact).
Seules comptent les aptitudes de puissance > 0 qui ne sont pas elles-mêmes des renvois. Une référence
introuvable reste à 0 (l'aptitude sort des « a-revoir » mais reste anecdotique) : jamais devinée.
"""

from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from statistics import mean

from .extract.references import REF_FRACTIONS, STATUSES, TERRAIN_FRACTION
from .models import AbilityAnalysis, Effect
from .scoring import RESOLVED_KINDS

_STATUS_READERS = {label: reader for label, _give, reader in STATUSES}
_KIND_OF = {"artefact": "artefact", "heroic_trait": "heroic_trait", "enhancement": "enhancement"}


def _faction(a: AbilityAnalysis) -> str:
    return a.raw.owners[0].faction_id if a.raw.owners else ""


def _text(a: AbilityAnalysis) -> str:
    return f"{a.raw.declare}\n{a.raw.effect}"


class _Index:
    def __init__(self, analyses: list[AbilityAnalysis]):
        # un renvoi pas encore résolu vaut 0 : il est exclu de fait ; résolu à la passe 1, il compte à la passe 2
        self.pool = [a for a in analyses if a.score.power > 0]
        self.by_faction: dict[str, list[AbilityAnalysis]] = defaultdict(list)
        self.by_name: dict[str, list[AbilityAnalysis]] = defaultdict(list)
        for a in self.pool:
            self.by_faction[_faction(a)].append(a)
            self.by_name[a.raw.name.lower()].append(a)

    def _mean(self, found: list[AbilityAnalysis], me: AbilityAnalysis, unrotated: bool = False) -> tuple[float, int]:
        # « as if it were active » / « You believe the X DELUSION » : l'effet s'applique hors rotation
        vals = [
            a.score.power / (a.extraction.power_factor if unrotated else 1.0) for a in found if a.raw.uid != me.raw.uid
        ]
        return (round(min(3.0, mean(vals)), 2), len(vals)) if vals else (0.0, 0)

    def ref(self, target: str, me: AbilityAnalysis, unrotated: bool = False) -> tuple[float, int]:
        fid = _faction(me)
        kind, _, what = target.partition(":")
        if kind == "nom":
            found = [a for a in self.by_name.get(what.lower(), []) if _faction(a) == fid] or self.by_name.get(
                what.lower(), []
            )
        elif kind == "mc":
            found = [
                a
                for a in self.by_faction[fid]
                if what.lower() in {k.strip().lower() for k in a.raw.keywords.split(",")}
                or a.raw.name.lower() == what.lower()
            ]
        else:  # « jet:shield bash » → aptitudes qui font ce jet
            rx = re.compile(rf"\b{re.escape(what)} roll", re.I)
            found = [a for a in self.by_faction[fid] if rx.search(_text(a)) or what.lower() in a.raw.name.lower()]
        return self._mean(found, me, unrotated)

    def status(self, label: str, me: AbilityAnalysis) -> tuple[float, int]:
        rx = re.compile(_STATUS_READERS[label])
        return self._mean([a for a in self.by_faction[_faction(me)] if rx.search(_text(a))], me)

    def terrain(self, name: str, me: AbilityAnalysis) -> tuple[float, int]:
        def on(stem: str) -> list[AbilityAnalysis]:
            return [
                a
                for a in self.by_faction[_faction(me)]
                if any(o.owner_kind == "warscroll" and stem in o.owner_name.lower() for o in a.raw.owners)
            ]

        stem = name.lower().rstrip("s")
        # « Nullifier Auto-Endrin » → charte « Auto-Endrins » : repli sur le dernier mot
        return self._mean(on(stem) or on(stem.split()[-1]), me)

    def enhancement(self, kind: str, tables: list[str], me: AbilityAnalysis) -> tuple[float, int]:
        same = [a for a in self.by_faction[_faction(me)] if a.raw.source_kind == _KIND_OF.get(kind, kind)]
        named = [
            a
            for a in same
            if any(t.lower() in o.owner_name.lower() for t in tables for o in a.raw.owners)
        ]
        return self._mean(named or same, me)


def _resolve(e: Effect, a: AbilityAnalysis, idx: _Index) -> Effect | None:
    """Effet valorisé, ou None si l'aptitude citée est introuvable (règle de saison, ordre de base…)."""
    if e.kind == "ability_ref":
        found = [idx.ref(t, a, unrotated=e.stat == "full") for t in e.detail.split("|")]
        found = [f for f in found if f[1]]
        if not found:
            return None
        value = REF_FRACTIONS[e.stat] * mean(v for v, _ in found)  # plusieurs citées : hors contexte, la moyenne
    elif e.kind == "status_grant":
        base, n = idx.status(e.detail, a)
        value = base
    elif e.kind == "terrain_setup":
        base, n = idx.terrain(e.detail, a)
        value = TERRAIN_FRACTION * base
    else:  # free_enhancement
        base, n = idx.enhancement(e.stat, [t for t in e.detail.split("|") if t], a)
        value = min(3.0, base * int(e.dice or 1))
    if e.kind != "ability_ref" and not n:
        return None
    return dataclasses.replace(e, value=round(value, 2))


#: Passes de résolution : la 2e résout les renvois vers une aptitude elle-même résolue à la 1re
#: (HEAD GARDENER → 'Cultivating the Garden of Nurgle', qui pose un Gnarlmaw).
RESOLUTION_PASSES = 2


def resolve_references(analyses: list[AbilityAnalysis], pending: dict[int, list[Effect]]) -> dict[int, list[Effect]]:
    """Une passe : `pending` = indice → effets d'origine (non résolus). Met à jour les effets en place
    (renvoi introuvable retiré : l'aptitude reste « a-revoir ») et renvoie ce qui reste introuvable."""
    idx = _Index(analyses)
    left = {}
    for i, original in pending.items():
        a = analyses[i]
        resolved = [_resolve(e, a, idx) if e.kind in RESOLVED_KINDS else e for e in original]
        if any(r is None for r in resolved):
            left[i] = original
        a.extraction.effects = [r for r in resolved if r is not None]
    return left


def pending_references(analyses: list[AbilityAnalysis]) -> dict[int, list[Effect]]:
    """Aptitudes dont au moins un effet est à résoudre (indice → effets d'origine)."""
    return {
        i: list(a.extraction.effects)
        for i, a in enumerate(analyses)
        if any(e.kind in RESOLVED_KINDS for e in a.extraction.effects)
    }

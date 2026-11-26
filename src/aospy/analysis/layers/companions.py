"""Compagnons gratuits : unités à 0 pt livrées avec un héros payant (« This unit can only be taken in X's regiment »).

L'importeur Wahapedia les garde en unités séparées à 0 pt (l'importeur BSData les fond dans le parent,
cf. importers/README.md). Sans prix, la couche 3 les écartait (aucune valeur réalisée : 0 dégât pour
100 pts dans la fiche couche 4) et la couche 4 ne les ajoutait pas quand l'export les omet (Morathi-Khaine
sans The Shadow Queen, 2026-11-25). Le coût du parent est réparti sur le groupe au prorata des PV, comme
dans les grilles L3 (`l3.matchups._add_companions`), d'où ce module partagé.
"""

from __future__ import annotations

from typing import Iterable

from ...domain.models import Unit

#: parent payant -> compagnons gratuits (noms en base)
COMPANIONS: dict[str, list[str]] = {
    "Morathi-Khaine": ["The Shadow Queen"],
    "Neave Blacktalon": ["Lorai, Child of the Abyss", "Neave’s Companions"],
    "Gunnar Brand": ["Singri Brand", "The Oathsworn Kin"],
    "Callis and Toll": ["Toll’s Companions"],
    "Ma Maegran, Chooser Of The Mighty": ["Ancient Ghyrochs"],
}


def _hp(u: Unit) -> int:
    return u.health * max(u.models, 1)


def effective_points(units: Iterable[Unit]) -> dict[int, float]:
    """unit.id du compagnon -> sa part du coût du parent (prorata des PV du groupe), pour les seuls compagnons à 0 pt
    dont le parent est dans `units` (même armée ou non : les noms sont uniques en pratique)."""
    by_name = {u.name: u for u in units}
    out: dict[int, float] = {}
    for parent, names in COMPANIONS.items():
        p = by_name.get(parent)
        group = [by_name[n] for n in names if n in by_name and by_name[n].points <= 0]
        if p is None or not group or p.points <= 0:
            continue
        total = _hp(p) + sum(_hp(c) for c in group)
        for c in group:
            if c.id is not None:
                out[c.id] = p.points * _hp(c) / total
    return out

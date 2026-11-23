"""Couche 4 — enchaînements : des mécaniques de la liste qui s'enchaînent sur une même unité.

Deuxième type de combo (méthode utilisateur, mémoire `list-building-concept`) :

* **sortir du combat → se Rallier** (chiffré, réponse utilisateur 2026-11-23 « survie gagnée, 1 fois par round ») :
  le Ralliement (commande de base, 1 PC, seulement hors combat) lance 6 dés, un point par 4+, soit 3 points par
  défaut, plus les dés de ralliement que la liste ajoute (« make 3 additional rally rolls ») ; les points soignent
  1 PV chacun ou rendent une figurine pour autant de points que ses PV. Une unité qui peut se dégager (sa propre
  aptitude ou une aptitude reçue : retraite sans blessures mortelles, mouvement hors du combat…) en profite : gain
  = rounds de survie gagnés par un Ralliement par round (`marriage.heal_survival_gain`, même pression que S) ×
  P(dégagement). Les PC ne sont pas arbitrés entre unités ;
* **tir mobile** (listé) : un mouvement après le tir (« If this unit used a SHOOT ability this phase, this unit can
  move D6" », Spirit of the Wind ; « After that SHOOT ability has been resolved, this unit can move », Zephyrspites) ;
* **relais de portée** (listé) : un sort ou une bulle mesuré depuis autre chose que le lanceur (« measure range and
  visibility from either part of this MANIFESTATION », Arcane Passage), ou un gardien posé sur un décor mobile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ...domain.models import Unit

#: Ralliement de base : 6 dés, un point par 4+.
RALLY_DICE = 6
RALLY_P = 0.5
_MORE_RALLY = re.compile(r"make (\d+|an) additional rally rolls?", re.I)
_POST_SHOOT = re.compile(
    r"(?:used a SHOOT ability this (?:phase|turn)|After that SHOOT ability has been resolved)[^.]*?\bcan (?:move|make)",
    re.I,
)
_RANGE_RELAY = re.compile(r"measure (?:the )?range (?:and visibility )?from (?!this unit\b)", re.I)


@dataclass(frozen=True)
class RallyChain:
    unit: str
    disengage: tuple[str, ...]  # aptitudes qui le sortent du combat
    p_disengage: float
    rally_points: float
    survival_gain: Optional[float]  # gain relatif de rounds de survie (× P(dégagement))
    cp_per_round: int = 1


@dataclass(frozen=True)
class ChainNote:
    kind: str  # « tir mobile » / « relais de portée »
    ability: str
    source: str
    units: tuple[str, ...]


def rally_dice(unit: Unit, abilities, vocab: frozenset[str]) -> int:
    """Dés de Ralliement de l'unité : 6, + musicien, + les dés que lui ajoutent les aptitudes de la liste."""
    from .listing import list_receivers

    n = RALLY_DICE + (1 if any(k.startswith("MUSICIAN") for k in unit.keywords) else 0)
    for ab in abilities:
        if not any(e.kind == "rally" for e in ab.effects):
            continue
        m = _MORE_RALLY.search(ab.text or "")
        if m and list_receivers(ab, [unit], vocab):
            n += 1 if m.group(1).lower() == "an" else int(m.group(1))
    return n


def rally_chains(
    abilities,
    units: list[Unit],
    vocab: frozenset[str],
    families: dict[str, str],
    incoming: dict[int, tuple[float, float]],
    share_melee: dict[str, float],
    cast_prob: Optional[dict] = None,
) -> list[RallyChain]:
    from .listing import _activation, effect_ability, list_receivers
    from .marriage import heal_survival_gain, mobility_kind

    out = []
    for unit in {u.name: u for u in units}.values():
        srcs, p_best = [], 0.0
        for ab in abilities:
            if families.get(ab.uid) != "mobilite":
                continue
            e_list = [
                (e.kind, e.requires, e.target_condition, e.target_keywords, e.duration, e.weapon_scope, e.stat,
                 "mobilite", e.value, e.detail)
                for e in ab.effects
            ]
            if mobility_kind(e_list, ab.text) != "dégagement":
                continue
            if not any(list_receivers(effect_ability(ab, e.friendly_target), [unit], vocab) for e in ab.effects):
                continue
            srcs.append(ab.name)
            p_best = max(p_best, _activation(ab, cast_prob or {}))
        if not srcs:
            continue
        pts = rally_dice(unit, abilities, vocab) * RALLY_P
        # points : 1 PV soigné chacun, ou une figurine rendue pour autant de points que ses PV
        e_list = [("heal", "", "", "", "immédiat", "", "", "soin", pts, "")]
        if unit.models > 1 and unit.health <= pts:
            e_list.append(("return_models", "", "", "", "immédiat", "", "", "soin", pts // unit.health, ""))
        sm = share_melee.get(unit.name, 1.0)
        g = heal_survival_gain(
            unit, e_list, "unlimited", "yours", incoming.get(unit.id, (0.0, 0.0)), "contact" if sm >= 0.5 else "longue"
        )
        out.append(
            RallyChain(unit.name, tuple(srcs), round(p_best, 2), pts, None if g is None else round(g * p_best, 3))
        )
    return sorted(out, key=lambda r: -(r.survival_gain or 0))


def chain_notes(abilities, units: list[Unit], vocab: frozenset[str], guardians: dict[str, str]) -> list[ChainNote]:
    from .listing import list_receivers

    out = []
    for ab in abilities:
        if _POST_SHOOT.search(ab.text or ""):
            recv = tuple(u.name for u, _r in list_receivers(ab, units, vocab)) or ab.carriers
            out.append(ChainNote("tir mobile", ab.name, ab.source, recv))
        if _RANGE_RELAY.search(ab.text or ""):
            out.append(ChainNote("relais de portée", ab.name, ab.source, ab.carriers))
    for unit, terrain in guardians.items():
        out.append(
            ChainNote("relais de portée", f"gardien de {terrain}", "décor de faction", (unit,))
        )
    return out

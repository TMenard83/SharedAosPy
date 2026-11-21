"""Couche 3 — l'approche : à chaque round, l'unité tire-t-elle, combat-elle, ou ne fait-elle rien ?

Demande utilisateur (2026-11-21, « modélise [l'approche]. Je pense que la portée est un facteur important ») :
le classement supposait qu'une unité de mêlée combat dès le round 1 et qu'un tireur tire à chaque round. On
simule plutôt les 5 rounds sur la géométrie de la saison (`marriage.ENGAGE_GAP_ROUND1` = 18" au départ) :

* **plan mêlée** — l'unité avance de son mouvement (vol compris, `marriage.reach`), tire avec les armes à
  portée de l'ennemi après ce mouvement, puis charge (2D6 ≥ distance restante). Trop loin pour charger et rien
  à portée : elle court (pas de tir, pas de charge). Une fois au contact elle y reste, ne tirant plus qu'avec
  ses armes « Shoot in Combat » ;
* **plan tir à L"** — l'unité se tient à L" de l'ennemi (L = portée de l'une de ses armes ; au round 1 elle ne
  peut pas s'approcher à plus de son mouvement de la distance de départ) et tire avec les armes qui portent ;
  chaque tour adverse, l'ennemi la charge avec P = `ENEMY_CHARGE_SHARE` × P(2D6 ≥ L − `ENEMY_MOVE`) : une
  arme à 24" tient l'ennemi à distance, une arme à 10" se fait charger presque à chaque tour. Chargée, elle
  reste au combat (s'y désengager coûte aussi son tir) ;
* l'**ennemi avance** de `ENEMY_MOVE` à chaque tour adverse et charge l'unité de mêlée qui ne l'a pas encore
  atteint avec la même probabilité.

Le résultat est un `Plan` : des **types de round** (part de la partie pondérée par `timeline.DEFAULT_RHYTHM`,
ensemble des armes qui frappent ce round). `encounter.plan_offense` lit chaque type au plancher de sa distribution
exacte puis somme. L'unité prend le plan qui lui rapporte le plus ; les effets sont mesurés sur le plan de la
charte nue.

**Hypothèses à challenger** (constantes ci-dessous) : `ENEMY_MOVE` (médiane des mouvements des unités payantes,
6"), `ENEMY_CHARGE_SHARE` (une menace de mêlée vise cette unité un tour adverse sur deux), l'unité joue en
premier au round 1, l'ennemi n'esquive pas l'unité de mêlée, aucun décor ni écran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...domain.models import Unit, Weapon
from .marriage import ENGAGE_GAP_ROUND1, RUN_MEAN, p_2d6_at_least, reach
from .timeline import DEFAULT_RHYTHM

#: Distance entre les armées au début du round 1 (2 × 9" de la règle « Deploy Unit », saison 2026-27).
START_GAP = ENGAGE_GAP_ROUND1
#: Mouvement de l'ennemi de référence (médiane des unités payantes, 6").
ENEMY_MOVE = 6.0
#: Part des tours adverses où une menace de mêlée vise cette unité (s'il peut la charger).
ENEMY_CHARGE_SHARE = 0.5


@dataclass(frozen=True)
class Plan:
    name: str
    #: (part de la partie, indices des armes qui frappent ce round) ; Σ parts = 1.
    rounds: tuple[tuple[float, frozenset[int]], ...]

    def weapon_share(self, i: int) -> float:
        """Part de la partie où l'arme `i` frappe."""
        return sum(s for s, ws in self.rounds if i in ws)


def shoots_in_combat(w: Weapon) -> bool:
    return w.kind == "ranged" and "shoot in combat" in (w.abilities or "").lower()


def p_charge_at(distance: float) -> float:
    """P(réussir une charge à `distance`" restants) ; au contact ou presque, sûre."""
    return 1.0 if distance <= 0 else p_2d6_at_least(distance)


def _families(unit: Unit) -> tuple[frozenset[int], frozenset[int], dict[int, float]]:
    """(mêlée, tir « Shoot in Combat », portée de chaque arme de tir)."""
    melee = frozenset(i for i, w in enumerate(unit.weapons) if w.kind != "ranged")
    sic = frozenset(i for i, w in enumerate(unit.weapons) if shoots_in_combat(w))
    ranges = {i: float(w.range_in or 0) for i, w in enumerate(unit.weapons) if w.kind == "ranged"}
    return melee, sic, ranges


class _Acc:
    def __init__(self) -> None:
        self.parts: dict[frozenset[int], float] = {}

    def add(self, share: float, weapons: frozenset[int]) -> None:
        if share > 1e-12:
            self.parts[weapons] = self.parts.get(weapons, 0.0) + share

    def plan(self, name: str) -> Plan:
        items = sorted(self.parts.items(), key=lambda kv: (-kv[1], sorted(kv[0])))
        return Plan(name, tuple((share, weapons) for weapons, share in items))


def _weights(rhythm: Sequence[float]) -> list[float]:
    total = sum(rhythm)
    return [r / total for r in rhythm]


def melee_plan(unit: Unit, rhythm: Sequence[float] = DEFAULT_RHYTHM) -> Plan:
    melee, sic, ranges = _families(unit)
    rch = reach(unit)
    acc, free, d = _Acc(), 1.0, START_GAP
    for w in _weights(rhythm):
        acc.add(w * (1 - free), melee | sic)
        gap = max(d - rch, 0.0)
        pch = p_charge_at(gap)
        fire = frozenset(i for i, rg in ranges.items() if rg >= gap)
        if pch == 0 and not fire:                       # trop loin : il court
            gap = max(d - rch - RUN_MEAN, 0.0)
            acc.add(w * free, frozenset())
        else:
            acc.add(w * free * pch, fire | melee)
            acc.add(w * free * (1 - pch), fire)
        pe = ENEMY_CHARGE_SHARE * p_charge_at(gap - ENEMY_MOVE)
        free *= (1 - pch) * (1 - pe)
        d = max(gap - ENEMY_MOVE, 0.0)
    return acc.plan("mêlée")


def shooting_plan(unit: Unit, stand_off: float, rhythm: Sequence[float] = DEFAULT_RHYTHM) -> Plan:
    melee, sic, ranges = _families(unit)
    acc, free = _Acc(), 1.0
    for r, w in enumerate(_weights(rhythm)):
        dist = max(stand_off, START_GAP - reach(unit)) if r == 0 else stand_off
        acc.add(w * (1 - free), melee | sic)
        acc.add(w * free, frozenset(i for i, rg in ranges.items() if rg >= dist))
        free *= 1 - ENEMY_CHARGE_SHARE * p_charge_at(dist - ENEMY_MOVE)
    return acc.plan(f'tir à {stand_off:g}"')


def candidate_plans(unit: Unit, rhythm: Sequence[float] = DEFAULT_RHYTHM) -> list[Plan]:
    """Plan mêlée + un plan de tir par portée d'arme distincte."""
    _melee, _sic, ranges = _families(unit)
    plans = [melee_plan(unit, rhythm)]
    plans += [shooting_plan(unit, rg, rhythm) for rg in sorted({rg for rg in ranges.values() if rg > 0})]
    return plans

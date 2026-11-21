"""Couche 3 — axe **mobilité** du classement des meilleures unités (`unit_realized`).

Constat (2026-11-21) : GW ne fait presque pas payer le mouvement (retiré du modèle de coût, p = 0,44), si bien
qu'un classement « dégâts × durabilité pour 100 pts » favorise mécaniquement les unités lentes, qui mettent leurs
points en PV et en sauvegarde. Le modèle d'approche (`approach.py`) ne corrige que le côté dégâts (rounds perdus
avant le contact) ; or l'écart vient surtout de la durabilité. Pour l'utilisateur, la mobilité est un avantage
tactique à part entière : on choisit le rythme du jeu, on score mieux, on choisit ses combats.

Mesure : **portée par tour** = mouvement + course moyenne + vol + aptitudes de mouvement de la charte (frappe en
profondeur, redéploiement, mouvement supplémentaire, course puis charge, repli libre, bonus de mouvement),
pondérées par leur probabilité et ×½ si une fois par bataille. Le score devient
√(dég/100 × dur/100) × (portée / portée médiane)^`MOBILITY_WEIGHT` — 0,35 choisi par l'utilisateur
(0,25 neutralisait à peu près le biais, 0,5 l'inversait). Toutes les valeurs en pouces sont des hypothèses de
travail, à challenger.
"""

from __future__ import annotations

import statistics
from typing import Iterable

from ...domain.models import Unit

#: Poids de l'axe mobilité (exposant du facteur de portée), utilisateur 2026-11-21.
MOBILITY_WEIGHT = 0.35
#: Course moyenne (1D6).
RUN_IN = 3.5
#: Le vol ignore écrans et décors : équivalent en pouces.
FLY_IN = 2.0
#: Équivalent en pouces d'une aptitude de mouvement de la charte (avant probabilité et fréquence).
MOVE_ABILITY_IN = {
    "deep_strike": 3.0,       # arriver où l'on veut
    "redeploy": 3.0,
    "extra_move": 3.0,
    "run_and_charge": 1.5,    # courir sans renoncer à la charge
    "free_retreat": 1.0,      # se désengager sans perte
}
#: Plafond d'un bonus de caractéristique de mouvement (« +N" »).
MAX_MOVE_BONUS_IN = 6.0
ONCE_PER_BATTLE = 0.5
#: Effets de mouvement lus dans `ability_effect`.
MOBILITY_KINDS = frozenset(MOVE_ABILITY_IN) | {"fly", "stat_mod"}


def ability_bonus(kind: str, stat: str, value: float, activation_prob: float, frequency: str) -> float:
    """Pouces équivalents d'un effet de mouvement (0 s'il n'en est pas un)."""
    if kind == "stat_mod":
        if stat != "move" or value <= 0:
            return 0.0
        base = min(value, MAX_MOVE_BONUS_IN)
    else:
        base = MOVE_ABILITY_IN.get(kind, 0.0)
    return base * activation_prob * (ONCE_PER_BATTLE if frequency == "once_per_battle" else 1.0)


def reach(unit: Unit, effects: Iterable[tuple[str, str, float, float, str]] = ()) -> float:
    """Portée par tour (pouces). `effects` : (kind, stat, value, activation_prob, frequency) des aptitudes de
    mouvement qui tombent sur l'unité ; par type d'effet, seul le plus fort compte."""
    best: dict[str, float] = {}
    fly = "FLY" in unit.keywords
    for kind, stat, value, prob, freq in effects:
        if kind == "fly":
            fly = fly or prob >= 0.5
            continue
        b = ability_bonus(kind, stat, value, prob, freq)
        if b > best.get(kind, 0.0):
            best[kind] = b
    return unit.move + RUN_IN + (FLY_IN if fly else 0.0) + sum(best.values())


def median_reach(reaches: Iterable[float]) -> float:
    return statistics.median(list(reaches))


def mobility_factor(unit_reach: float, median: float, weight: float = MOBILITY_WEIGHT) -> float:
    """Multiplicateur du score : (portée / médiane)^poids (1 pour une unité de portée médiane)."""
    if median <= 0 or unit_reach <= 0:
        return 1.0
    return (unit_reach / median) ** weight

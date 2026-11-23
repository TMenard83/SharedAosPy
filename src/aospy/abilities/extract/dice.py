"""Probabilités de dés (2D6, D6, moyenne d'une expression de dés)."""

from __future__ import annotations

from typing import Optional

_P_2D6_AT_LEAST = {n: sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= n) / 36 for n in range(2, 13)}


def p_2d6(n: int) -> float:
    return 1.0 if n <= 2 else 0.0 if n > 12 else _P_2D6_AT_LEAST[n]


def p_d6(n: int) -> float:
    return max(0.0, min(1.0, (7 - n) / 6))


_DICE_MEAN = {
    "D3": 2.0,
    "D6": 3.5,
    "2D3": 4.0,
    "2D6": 7.0,
    "3D6": 10.5,
    "3D3": 6.0,
    "4D3": 8.0,
    "4D6": 14.0,
    "D6+2": 5.5,
    "D3+1": 3.0,
    "D3+3": 5.0,
    "D6+1": 4.5,
    "D6+3": 6.5,
    "D3+2": 4.0,
}


def dice_mean(expr: str) -> Optional[float]:
    """« 3 » → 3, « D3 » → 2, « 2D6 » → 7 ; None si non numérique (X, any…)."""
    e = expr.strip().upper().replace(" ", "")
    if e.isdigit():
        return float(e)
    return _DICE_MEAN.get(e)

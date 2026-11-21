"""Timing d'une aptitude : fréquence d'usage et côté du tour."""

from __future__ import annotations

import re

from ..models import Frequency, TurnSide

_FREQ_PATTERNS: list[tuple[str, Frequency]] = [
    (r"once per battle round \(army\)", "once_per_round_army"),
    (r"once per battle round", "once_per_round"),
    (r"once per battle \(army\)", "once_per_battle_army"),
    (r"once per battle", "once_per_battle"),
    (r"once per turn \(army\)", "once_per_turn_army"),
    (r"once per turn", "once_per_turn"),
    (r"once per phase \(army\)", "once_per_phase_army"),
]


def frequency_of(condition: str) -> Frequency:
    c = condition.lower()
    if c.startswith("passive"):
        return "passive"
    if re.search(r"first battle round", c):
        return "once_per_battle"  # un seul déclenchement : début du premier round
    if "deployment" in c:
        # La phase de déploiement n'a lieu qu'une fois : « Once Per Battle » y est un garde-fou
        # redondant de GW (avis utilisateur), pas une limite qui coûte de la puissance.
        return "unlimited"
    for pat, freq in _FREQ_PATTERNS:
        if re.search(pat, c):
            return freq
    return "unlimited"


def turn_of(condition: str, phase: str) -> TurnSide:
    c = condition.lower()
    if "deployment" in c:
        return "deployment"
    if re.search(r"start of (?:the )?(?:first )?battle round", c):
        return "round_start"
    if re.search(r"\byour\b", c) and not re.search(r"\bany\b|opponent|enemy", c):
        return "yours"
    if re.search(r"\benemy\b.*phase|opponent", c):
        return "enemy"
    return "any"

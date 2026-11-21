"""Probabilité de déclenchement (sort, prière, jet de dé, test opposé)."""

from __future__ import annotations

import re

from ..models import RawAbility
from .dice import p_2d6, p_d6

_GATE_D6 = re.compile(r"\b[Rr]oll a dice\b(?! for each)[^.]*\.(?:[^.]*?)\b[Oo]n an? (\d)\+")
_GATE_2D6 = re.compile(r"\b[Rr]oll 2D6\b[^.]*\.(?:[^.]*?)\b[Oo]n an? (\d{1,2})\+")
_GATE_VS_STAT = re.compile(
    r"Roll (?:2D6|a dice|D3|3D6)\. If (?:the )?(?:roll|result) (?:exceeds|is (?:equal to or )?greater than|"
    r"equals or exceeds|is (?:equal to or )?less than)",
    re.I,
)
#: Probabilité forfaitaire d'un test contre une caractéristique de la cible inconnue.
OPPOSED_TEST_PROB = 0.5
#: Par caractéristique visée : « D6 > Contrôle » (Contrôle 1-2 en général : 83 %/67 %),
#: « 2D6 > PV » d'un héros (~6 PV : 42 %).
OPPOSED_TEST_PROBS = {"control": 0.75, "health": 0.42}
_BINOMIAL = re.compile(
    r"roll a (?:number of )?dice (?:for each|equal to)|roll a number of dice|"
    r"for each (?:\d\+|roll of)|for each (?:model|enemy model|point)",
    re.I,
)
_DICE_IN_EFFECT = re.compile(r"\b\d?D[36](?:\+\d)?\b")


def p_prayer_banked(n: int) -> float:
    """P(prière à `n` exaucée au round clé), points rituels stockés au tour précédent (Core Rules 19.0).

    Un 1 naturel échoue (et retire D3 points : la réserve d'une seule tentative est alors vide) ; un jet
    de 2+ peut être stocké en points rituels, puis ajouté au jet suivant. Deux tentatives : on stocke au
    round 1 et on prie au round clé — ou on prie directement si c'est plus sûr (petite valeur).
    Une prière ne se dissipe pas, contrairement à un sort.
    """
    banked = 0.0
    for d1 in range(1, 7):
        rp = d1 if d1 >= 2 else 0
        banked += sum(1 for d2 in range(2, 7) if d2 + rp >= n) / 36.0
    return max(p_d6(n), banked)


def activation_of(raw: RawAbility, effect: str) -> tuple[float, list[str], str]:
    """(probabilité de déclenchement, notes FR, variance de l'effet)."""
    p, notes = 1.0, []
    cost = raw.cost_type.lower()
    val = re.match(r"\d+", raw.cost_value or "")
    if cost == "spell" and val:
        n = int(val.group())
        p *= p_2d6(n)
        notes.append(f"sort à {n} : {p_2d6(n):.0%} au lancer (dissipation ignorée)")
    elif cost == "prayer" and val:
        n = int(val.group())
        p *= p_prayer_banked(n)
        notes.append(
            f"prière à {n} : {p_prayer_banked(n):.0%} au round clé (points rituels stockés au round 1 ; "
            f"{p_d6(n):.0%} d'un seul jet ; pas de dissipation)"
        )
    elif cost == "command":
        notes.append(f"ordre : {raw.cost_value or 1} PC")
    elif cost:
        notes.append(f"coût {raw.cost_type} {raw.cost_value}")

    m = _GATE_D6.search(effect)
    if m and not _BINOMIAL.search(effect[: m.start() + 40]):
        n = int(m.group(1))
        p *= p_d6(n)
        note = f"jet de déclenchement {n}+ : {p_d6(n):.0%}"
        if re.search(r"[Aa]dd 1 to the roll", effect):
            note += " (bonus possible)"
        notes.append(note)
    else:
        m = _GATE_2D6.search(effect)
        if m:
            n = int(m.group(1))
            p *= p_2d6(n)
            notes.append(f"test 2D6 à {n}+ : {p_2d6(n):.0%}")
        elif _GATE_VS_STAT.search(effect):
            m = _GATE_VS_STAT.search(effect)
            stat = re.search(r"(Control|Health|Save|Move)\b", effect[m.end() : m.end() + 60])
            key = stat.group(1).lower() if stat else ""
            prob = OPPOSED_TEST_PROBS.get(key, OPPOSED_TEST_PROB)
            p *= prob
            label = {"control": "le Contrôle", "health": "les PV", "save": "la Sauvegarde", "move": "le Mouvement"}
            notes.append(f"test contre {label.get(key, 'une caractéristique')} de la cible : ~{prob:.0%} hors contexte")

    if _BINOMIAL.search(effect):
        variance = "binomial"
    elif _DICE_IN_EFFECT.search(effect):
        variance = "des"
    else:
        variance = "fixe"
    return p, notes, variance

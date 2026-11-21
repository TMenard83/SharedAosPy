"""Effets sur les jets : relances, mouvements accordés, nombre de dés lancés."""

from __future__ import annotations

import re

from ..models import Effect
from ..perimeter import sentence_at

#: Relances (analyseur v25) : verbe « re-roll » seul — « cannot be re-rolled », « after any re-rolls »,
#: « each hit roll that is re-rolled » ne sont pas des relances accordées. « re roll » (sans tiret) existe.
_REROLL_RE = re.compile(r"\b[Rr]e[- ]?roll\b(?![- ]?(?:ed|s)\b)([^.:\n]*)")
_REROLL_STATS = (
    ("charge", r"charge rolls?"),
    ("run", r"run rolls?"),
    ("hit", r"hit rolls?"),
    ("wound", r"wound rolls?"),
    ("save", r"save rolls?"),
    ("cast", r"casting rolls?"),
    ("chant", r"chanting rolls?"),
    ("unbind", r"unbinding rolls?"),
    ("ward", r"ward rolls?"),
)
#: Relance partielle (validé utilisateur : moitié d'une relance complète) : 1 seul jet, 1 seul dé, les 1.
_REROLL_PARTIAL = re.compile(r"^\s*(?:\d+|a|one) (?:of the )?(?:dice|[a-z']+ rolls?)\b|\brolls? of 1\b")


def rerolls_of(full: str) -> list[tuple[Effect, int]]:
    """Une relance par jet relancé (« re-roll run rolls and charge rolls » = 2 effets), stat '' si le
    jet n'est pas nommé (« re-roll the dice »). `value` = 1 (complète) ou 0,5 (partielle)."""
    found: dict[str, tuple[Effect, int]] = {}
    for m in _REROLL_RE.finditer(full):
        if re.search(r"(?:casting|chanting) roll was \d+\+[^.]*$", full[max(0, m.start() - 160) : m.start()]):
            continue  # bonus sur un jet élevé : pas acquis (v21)
        clause = m.group(1)
        # « re-roll 1 hit roll, or 1 wound roll » : chaque jet de l'énumération est partiel
        partial = bool(_REROLL_PARTIAL.search(clause))
        stats = [st for st, pat in _REROLL_STATS if re.search(r"\b" + pat + r"\b", clause)] or [""]
        for st in stats:
            e = Effect(
                "reroll", st, 0.5 if partial else 1.0, "", "friendly", "relance partielle" if partial else "relance"
            )
            if st not in found or e.value > found[st][0].value:
                found[st] = (e, m.start())
    return list(found.values())


_MAKE_MOVE_RE = re.compile(r"\bcan (?:immediately )?make an? (\d+|\d?D[36])\" move")

#: Nombre de dés d'un jet changé (analyseur v28) : « add 1 to the number of dice rolled when making charge
#: rolls, to a maximum of 3 » (3D6), « … then remove 1 dice of your choice » (3 dés, on garde les 2 meilleurs),
#: « roll 3D6 instead of 2D6 », « subtract 1 from the number of dice rolled … to a minimum of 1 » (1D6).
_DICE_COUNT_RE = re.compile(
    r"\b(?:([Aa]dd|[Ss]ubtract) 1 (?:to|from) the number of dice rolled|(?:roll|rolls?) (?:1|an|one) additional dice|"
    r"(?:roll|roll is|rolls? (?:is|are)) 3D6 instead of 2D6|roll 2 dice instead of 1|roll an additional D6|"
    r"(change the lowest D6[^.]*? to match the highest D6)|(change the highest D6 to match the lowest D6|"
    r"change one of the dice in that [a-z]+ roll to a 1|remove that dice from the [a-z]+ roll))"
)
_DICE_ROLLS = (
    ("charge", r"charge roll"),
    ("cast", r"casting roll"),
    ("unbind", r"unbinding roll"),
    ("banish", r"banishment roll"),
    ("chant", r"chanting roll"),
    ("run", r"run roll"),
    ("redeploy", r"'Redeploy' command"),
)
_DICE_KEEP = re.compile(r"(?:remove|discard) 1 dice|pick either result|pick (?:the )?(?:highest|one)")


def dice_count_of(full: str) -> list[tuple[Effect, int]]:
    """Un effet `dice_count` par jet dont le nombre de dés change. value = +1 / −1 dé ;
    detail = « garder » (on retire un dé : ≈ une relance) ou « somme » (tous les dés comptent)."""
    out: list[tuple[Effect, int]] = []
    seen: set[tuple[str, int]] = set()
    for m in _DICE_COUNT_RE.finditer(full):
        if re.search(r"(?:casting|chanting) roll was \d+\+[^.]*$", full[max(0, m.start() - 160) : m.start()]):
            continue  # bonus sur un jet élevé : pas acquis (v21)
        sent = sentence_at(full, m.start())
        after = sent[sent.find(m.group(0)[:20]) :] if m.group(0)[:20] in sent else sent
        hits = [(re.search(p, after).start() if re.search(p, after) else 10**6, st) for st, p in _DICE_ROLLS]
        if min(hits)[0] == 10**6:
            hits = [(re.search(p, sent).start() if re.search(p, sent) else 10**6, st) for st, p in _DICE_ROLLS]
        stat = min(hits)[1] if min(hits)[0] < 10**6 else ""
        sign = -1 if (m.group(1) or "").lower() == "subtract" or m.group(3) else 1
        if (stat, sign) in seen:
            continue
        seen.add((stat, sign))
        keep = "max" if m.group(2) else "min" if m.group(3) else "garder" if _DICE_KEEP.search(sent) else "somme"
        if sign < 0:
            own = bool(re.search(r"\bbut subtract\b", sent))  # contrepartie sur sa propre unité
            e = Effect("dice_count", stat, -1.0, "", "friendly" if own else "enemy", keep)
        else:
            e = Effect("dice_count", stat, 1.0, "", "friendly", keep)
        out.append((e, m.start()))
    return out

"""Couche 3 — **dégâts directs** : blessures mortelles infligées par une aptitude (sort, prière, rampage…).

Portée d'action, variante B, étape 2 (utilisateur, 2026-11-21). Le montant écrit en couche 1
(`ability_effect.value`) n'est pas fiable pour ces textes (« Roll 8 dice, for each 4+… » stocké à 1, « Roll a D3.
On a 2+, … equal to the roll » à 0), et plusieurs dépendent de la cible (« a dice for each model in the target
unit », « equal to the target's Health ») : l'espérance se lit ici, contre une **cible type** (`TARGET_*`).

Formes reconnues (texte de l'aptitude, une option à la fois quand il faut en choisir une) :

* « Roll a D3. On a 2+, inflict … equal to the roll » → moyenne des faces ≥ seuil ;
* « Roll N dice / a number of dice equal to … [, to a maximum of M]. For each X+, inflict Y » → N × P(X+) × Y ;
* « Roll a dice. On a X+, inflict Y » (et paliers « On a 3-5 … On a 6 … ») → Σ P(palier) × Y ;
* « Inflict Y mortal damage » sans jet → Y.

Non comptés : déclencheurs par attaque ou par sauvegarde (« Each time … ») — ils relèvent du profil d'arme ou
sont anecdotiques — et les textes non reconnus (renvoient None). Hypothèses à challenger : la cible type, le
jet de lancement réussi moyen, le nombre d'ennemis touchés par une aptitude de zone.
"""

from __future__ import annotations

import re
from typing import Optional

#: Cible type : 5 figurines à 2 PV, mouvement 5", 3 dégâts déjà subis.
TARGET_MODELS = 5
TARGET_HEALTH = 2
TARGET_DAMAGE_POINTS = 3
#: Jet de lancement (2D6) d'un sort réussi : en moyenne au-dessus de la valeur de lancement.
CASTING_ROLL = 8
#: Ennemis touchés par une aptitude de zone (« each target », « each enemy unit within … »).
ENEMY_AURA_TARGETS = 1.5

_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}


PMF = list[float]  # PMF[d] = P(d blessures mortelles)


def _conv(a: PMF, b: PMF) -> PMF:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                out[i + j] += x * y
    return out


def _mix(parts: list[tuple[float, PMF]]) -> PMF:
    """Mélange Σ p·PMF (le reste de probabilité va à 0 dégât)."""
    n = max((len(q) for _p, q in parts), default=1)
    out = [0.0] * n
    for p, q in parts:
        for d, x in enumerate(q):
            out[d] += p * x
    out[0] += max(0.0, 1.0 - sum(p for p, _q in parts))
    return out


def _const(n: int) -> PMF:
    return [0.0] * n + [1.0]


def dice_pmf(expr: str) -> Optional[PMF]:
    """Distribution d'une quantité « D3 », « 2D6 », « D3+1 », « 3 »."""
    m = re.fullmatch(r"\s*(\d*)\s*d\s*(\d+)\s*(?:\+\s*(\d+))?\s*", expr, re.I)
    if m:
        faces = int(m.group(2))
        die = [0.0] + [1.0 / faces] * faces
        out = _const(int(m.group(3) or 0))
        for _ in range(int(m.group(1) or 1)):
            out = _conv(out, die)
        return out
    m = re.fullmatch(r"\s*(\d+)\s*", expr)
    return _const(int(m.group(1))) if m else None


def mean(pmf: PMF) -> float:
    return sum(d * x for d, x in enumerate(pmf))


def dice_mean(expr: str) -> Optional[float]:
    """Espérance d'une quantité « D3 », « 2D6 », « D3+1 », « 3 »."""
    q = dice_pmf(expr)
    return None if q is None else mean(q)


def _p(threshold: int, faces: int = 6) -> float:
    return max(0, faces - threshold + 1) / faces


_AMOUNT = r"(\d*\s*D\s*\d+(?:\s*\+\s*\d+)?|\d+)"


def _dice_count(phrase: str, own_models: int) -> Optional[int]:
    """Nombre de dés d'un « Roll … » : nombre écrit, ou quantité liée à la cible / au lanceur."""
    p = phrase.lower()
    cap = re.search(r"to a maximum of (\d+)", p)
    if "model" in p and ("target" in p or "that unit" in p or "enemy" in p):
        n = TARGET_MODELS
    elif "model" in p and "this unit" in p:
        n = own_models
    elif "health" in p:
        n = TARGET_HEALTH
    elif "damage point" in p:
        n = TARGET_DAMAGE_POINTS
    elif "casting roll" in p or "chanting roll" in p:
        n = CASTING_ROLL
    else:
        m = re.match(r"\s*(\d+|a|an|one|two|three)\b", p)
        if not m:
            return None
        n = int(_NUM.get(m.group(1), m.group(1)))
    return int(min(n, int(cap.group(1))) if cap else n)


#: « If this unit charged this turn/phase, … » : dégâts conditionnels (charge), comptés à part.
CHARGED_RE = re.compile(r"^if this unit (?:charged|made a charge move)", re.I)


def _segment(text: str, own_models: int) -> Optional[PMF]:
    t = " ".join(text.split())
    low = t.lower()
    # jet préalable : « Roll a dice. On a 3+, roll a dice for each model … » → P(seuil) × la suite
    m = re.match(r"(?:if [^,]*, )?roll a dice\.\s*on a (\d)\+[,:]\s*(.*)$", t, re.I)
    if m and "equal to the roll" not in m.group(2).lower() and re.match(r"\s*-?\s*roll", m.group(2), re.I):
        rest = _segment(m.group(2), own_models)
        return None if rest is None else _mix([(_p(int(m.group(1))), rest)])
    # « Roll a D3 / a dice. [modificateurs.] On a 2+, inflict an amount of mortal damage … equal to the roll »
    m = re.search(r"roll (?:a |1 )?(d3|d6|dice)\b.*?on (?:a )?(\d)\+[^.]*?equal to the roll", low)
    if m:
        faces = 3 if m.group(1) == "d3" else 6
        return _mix([(1 / faces, _const(r)) for r in range(int(m.group(2)), faces + 1)])
    # « Roll N dice … For each X+, inflict Y mortal damage » : binomiale × montant
    m = re.search(
        r"roll (?:either )?((?:a number of dice equal to|a dice for each|\d+|a|one|two|three)[^.]*?)\.\s*"
        r"(?:[^.]*\.\s*)?for each (\d)\+?,?\s*(?:[^.]*?)inflict " + _AMOUNT + r" mortal damage",
        t,
        re.I,
    )
    if m:
        n = _dice_count(m.group(1).replace("a dice for each", "a number of dice equal to the"), own_models)
        amount = dice_pmf(m.group(3))
        if n is not None and amount is not None:
            p = _p(int(m.group(2)))
            one = _mix([(p, amount)])
            out = [1.0]
            for _ in range(n):
                out = _conv(out, one)
            cap = re.search(r"to a maximum of (\d+) mortal damage", low)
            if cap and len(out) > int(cap.group(1)) + 1:
                k = int(cap.group(1))
                out = out[:k] + [sum(out[k:])]
            return out
    # « Roll a dice [for each target]. On a X+ / On a 3-5 / On a 1, inflict Y mortal damage … »
    if re.search(r"roll a dice\b", low):
        parts = []
        for lo, plus, hi, amount in re.findall(
            r"on a (\d)(\+|-(\d))?[^.]*?inflict " + _AMOUNT + r" mortal damage", t, re.I
        ):
            y = dice_pmf(amount)
            if y is None:
                continue
            lo_i = int(lo)
            hi_i = 6 if plus == "+" else int(hi) if hi else lo_i  # « On a 1 » : cette face seulement
            parts.append((max(0, hi_i - lo_i + 1) / 6, y))
        if parts:
            return _mix(parts)
    # « Inflict Y mortal damage » avant tout jet (« … and then roll 2D6 » pour un mouvement)
    m = re.search(r"inflict " + _AMOUNT + r" mortal damage", t, re.I)
    roll = re.search(r"\broll\b", low)
    if m and (roll is None or roll.start() > m.start()):
        return dice_pmf(m.group(1))
    return None


def mortal_pmf(text: str, own_models: int = 1) -> Optional[PMF]:
    """Distribution des blessures mortelles d'une utilisation contre la cible type (une seule cible), ou None
    si le texte n'est pas reconnu, relève d'un déclencheur par attaque ou d'un choix de l'adversaire. Condition
    de charge en tête (« If this unit charged… ») : voir `CHARGED_RE`, lue par l'appelant."""
    t = " ".join((text or "").split())
    t = CHARGED_RE.sub("", t).lstrip(" ,")
    t = re.sub(r"^this turn, |^this phase, ", "", t, flags=re.I)
    low = t.lower()
    if not t or 0 <= low.find("each time") < low.find("inflict"):
        return None  # déclencheur par attaque / par sauvegarde / par mort
    if re.match(r"(while|if this unit is destroyed)", t, re.I) or re.search(r"your opponent must", t, re.I):
        return None  # passif d'aura, mort du porteur, choix laissé à l'adversaire
    if re.search(r"pick (?:1|one) of the following", t, re.I):
        opts = [q for seg in re.split(r"\s-\s", t)[1:] if (q := _segment(seg, own_models)) is not None]
        return max(opts, key=mean) if opts else None
    return _segment(t, own_models)


def expected_mortals(text: str, own_models: int = 1) -> Optional[float]:
    """Espérance de `mortal_pmf`."""
    q = mortal_pmf(text, own_models)
    return None if q is None else mean(q)


def enemy_targets(scope: str) -> float:
    return ENEMY_AURA_TARGETS if scope == "enemy_aura" else 1.0

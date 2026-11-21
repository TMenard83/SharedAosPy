"""Axe du temps — la frise de la partie en 10 demi-tours (R1 mon tour, R1 tour adverse, … R5 tour adverse).

Proposition validée par l'utilisateur (2026-11-20, « ok pour ta proposition sur les durées ») : la durée n'est
pas une 5e couche mais l'axe temporel qui traverse les couches. Chaque couche y projette un profil :

* couche 1 — **quand l'effet est actif** : fréquence (passif, chaque tour, 1/round, 1/bataille), tour où on
  peut le jouer (`ability.turn_side` : mon tour / adverse / les deux), durée écrite (immédiat, tour, jusqu'au
  prochain tour, round, reste de la bataille…) ;
* couche 3 — **quand le porteur le déclenche et le tient** : round au plus tôt, survie case par case
  (`marriage.alive_profile`) ;
* **pertinence d'une case** selon ce que fait l'effet : un buff offensif sert à mon tour (tir + combat) et au
  tour adverse pour la seule riposte au corps à corps ; un buff défensif surtout au tour adverse ;
* couche 4 — **le poids de chaque round** selon le rythme de la liste (`DEFAULT_RHYTHM` = rounds 2-3 majeurs,
  règle utilisateur ; une liste cumulative pèsera plus sur les rounds 4-5).

valeur = Σ cases gain × activité × pertinence × survie × poids du round. `coverage` renvoie la part de la
partie couverte (0-1), normalisée par ce qu'aurait un effet permanent.

Règles conservées de la pondération utilisateur (mémoire `ability-weighting-rules`) :
* une fois par bataille, effet court : joué au kairos et valant **1/2** d'un effet permanent (choix
  utilisateur) — la frise ne fait que répartir ce 1/2 selon la part du round qu'il couvre (une protection
  « pour le reste du tour » jouée au tour adverse couvre l'essentiel des coups reçus, au mien presque rien) ;
* une fois par bataille, effet durable : activé au round 2, couvre la suite.

Hypothèses à challenger : `DEF_SHARE_ENEMY_TURN` (part des dégâts subis pendant le tour adverse), la riposte au
corps à corps = moitié des combats d'une unité de mêlée (cohérent avec `marriage.CHARGE_FIGHT_SHARE`).
"""

from __future__ import annotations

from typing import Optional, Sequence

#: Poids des rounds 1 à 5 — rythme par défaut (rounds 2-3 majeurs, 1/4/5 = ouverture, fin des combats, scoring).
DEFAULT_RHYTHM = (1 / 3, 1.0, 1.0, 1 / 3, 1 / 3)
MINE, ENEMY = 0, 1
N_SLOTS = 10

#: Part des dégâts SUBIS pendant le tour adverse (il tire et charge) ; le reste = sa riposte à mon tour.
DEF_SHARE_ENEMY_TURN = 0.7
#: Une fois par bataille, effet court : 1/2 d'un effet permanent (choix utilisateur, joué au kairos).
KAIROS_SHORT = 0.5
#: Une fois par bataille, effet durable : activé au round 2.
LASTING_START_ROUND = 2

_LASTING = {"bataille", "permanent", "conditionnelle"}
_REPEATABLE = {"unlimited", "once_per_turn", "once_per_turn_army", "once_per_phase_army", ""}
_PER_ROUND = {"once_per_round", "once_per_round_army"}


def slot(round_: int, side: int) -> int:
    return (round_ - 1) * 2 + side


def relevance(polarity: str, share_melee: float = 1.0) -> tuple[float, float]:
    """(mon tour, tour adverse) pour une polarité : 'off' (dégâts infligés), 'def' (dégâts subis), autre.

    Offensif : le tir ne sert qu'à mon tour ; la mêlée combat dans les deux tours (riposte) → moitié chacun."""
    if polarity == "off":
        sm = min(max(share_melee, 0.0), 1.0)
        return (1 - sm) + sm * 0.5, sm * 0.5
    if polarity == "def":
        return 1 - DEF_SHARE_ENEMY_TURN, DEF_SHARE_ENEMY_TURN
    return 0.5, 0.5


def _sides(turn_side: str) -> tuple[int, ...]:
    if turn_side == "yours":
        return (MINE,)
    if turn_side == "enemy":
        return (ENEMY,)
    if turn_side in ("deployment", "round_start"):
        return (MINE,)   # avant les deux tours du round : l'empan « round » couvre aussi le tour adverse
    return (MINE, ENEMY)


def span(start: int, duration: str) -> list[int]:
    """Cases couvertes par un effet joué dans la case `start`, selon sa durée écrite."""
    if duration in _LASTING:
        return list(range(start, N_SLOTS))
    if duration == "jusqu'au prochain tour":
        return [s for s in (start, start + 1) if s < N_SLOTS]
    if duration == "round":
        return list(range(start, (start // 2) * 2 + 2))
    return [start]


def activity(frequency: str, duration: str, turn_side: str) -> list[float]:
    """Profil d'activité (0-1 par case) d'un effet RÉUTILISABLE ou passif ; une fois par bataille → `coverage`."""
    act = [0.0] * N_SLOTS
    if frequency == "passive":
        return [1.0] * N_SLOTS
    if turn_side == "deployment":            # joué une fois, avant le round 1
        for s in span(0, duration):
            act[s] = 1.0
        return act
    sides = _sides(turn_side)
    for r in range(1, 6):
        for side in sides:
            for s in span(slot(r, side), duration):
                act[s] = 1.0
    return act


def coverage(frequency: str, duration: str, turn_side: str, polarity: str, share_melee: float = 1.0,
             rhythm: Sequence[float] = DEFAULT_RHYTHM, alive: Optional[Sequence[float]] = None,
             start_round: int = 1) -> float:
    """Part de la partie couverte (0-1) par rapport à un effet permanent, pondérée par la pertinence et le rythme.

    `alive` (par round, `marriage.alive_profile`) : le porteur doit être en vie dans la case pour que l'effet
    compte ; `start_round` : premier round où il peut le déclencher."""
    rel = relevance(polarity, share_melee)
    w = [rhythm[s // 2] * rel[s % 2] for s in range(N_SLOTS)]
    total = sum(w)
    if total <= 0:
        return 0.0
    live = [1.0 if alive is None else alive[s // 2] for s in range(N_SLOTS)]
    first = (start_round - 1) * 2

    def value(slots: list[int]) -> float:
        return sum(w[s] * live[s] for s in slots if s >= first)

    freq = frequency or ""
    if freq.startswith("once_per_battle"):
        allowed = [slot(r, side) for r in range(1, 6) for side in _sides(turn_side)]
        if duration in _LASTING:
            starts = [s for s in allowed if s >= max(first, (LASTING_START_ROUND - 1) * 2)]
            return max((value(span(s, duration)) for s in starts), default=0.0) / total
        # kairos : 1/2 d'un effet permanent, réparti selon la part du round (pondérée) que couvre la fenêtre
        best = 0.0
        for s in allowed:
            if s < first:
                continue
            r = s // 2
            round_val = (rel[0] + rel[1])
            covered = sum(rel[x % 2] * live[x] for x in span(s, duration) if x // 2 == r)
            best = max(best, covered / round_val if round_val else 0.0)
        return KAIROS_SHORT * best
    if freq in _PER_ROUND:
        # une fois par round : dans chaque round, la meilleure case autorisée
        tot = 0.0
        for r in range(1, 6):
            tot += max((value(span(slot(r, side), duration)) for side in _sides(turn_side)), default=0.0)
        return min(tot / total, 1.0)
    act = activity(freq, duration, turn_side)
    return sum(w[s] * live[s] * act[s] for s in range(N_SLOTS) if s >= first) / total


def start_share(frequency: str, duration: str, turn_side: str, start_round: int, polarity: str = "autre") -> float:
    """Part de la couverture conservée si l'effet n'est possible qu'à partir du round `start_round`."""
    if start_round <= 1:
        return 1.0
    full = coverage(frequency, duration, turn_side, polarity)
    return coverage(frequency, duration, turn_side, polarity, start_round=start_round) / full if full else 0.0

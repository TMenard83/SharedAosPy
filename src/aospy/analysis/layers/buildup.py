"""Couche 4 — montée en puissance : la valeur d'une liste round par round.

Troisième type de combo (méthode utilisateur : « laisser traîner la partie pour accumuler les runes », Totosai).
Réponses utilisateur du 2026-11-23 : plan de runes **automatique** (glouton) et **courbe affichée** sans changer
les poids des rounds (le rythme se décide à la lecture, avec l'adversaire).

Pour chaque round 1..5, l'empilement de la liste (`stacking`, sans les commandes) est rejoué avec ce qui est
disponible à ce round :

* **ressource qui s'accumule** : une aptitude disponible à partir d'un round (`ability.available_round` : Dîme de
  Sang) n'entre qu'à partir de ce round ;
* **tableau de runes** (« Pick 1 of the following runes to depict on your battle scripture … Each rune remains on
  your battle scripture for the rest of the battle », DEPICT RUNE) : une rune par round ; son effet ne vaut que pour
  le round où elle est posée, mais elle reste au tableau et compte pour les aptitudes « for each instance of <rune>
  depicted » (With the Force of a Landslide : +1 Attaque par Alaithi), dont l'effet est multiplié par le nombre
  d'exemplaires. Chaque round, la rune posée est celle qui rapporte le plus à la liste (dégâts + durabilité,
  relatifs) au vu du tableau déjà constitué ; une rune prise par une amélioration (« cannot be depicted ») est
  exclue. Les effets renforcés (« While <rune> is depicted … ») ne sont pas lus (limite).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Optional

from ...domain.models import Unit

_BOARD = re.compile(r"remains? on your battle scripture", re.I)
_PER_INSTANCE = re.compile(r"for each instance of ([A-Z][\w' ,-]+?) depicted", re.I)
ROUNDS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class RoundValue:
    round: int
    damage: float  # Σ des dégâts d'un round « tout en place » des unités de la liste
    durability: float  # Σ des PV effectifs « tout en place »
    rune: str = ""  # rune posée ce round (plan glouton)
    unlocked: tuple[str, ...] = ()  # aptitudes disponibles à partir de ce round


@dataclass
class Curve:
    rounds: list[RoundValue] = field(default_factory=list)
    board_ability: str = ""

    @property
    def peak(self) -> Optional[int]:
        if not self.rounds:
            return None
        base_d, base_w = self.rounds[0].damage or 1.0, self.rounds[0].durability or 1.0
        return max(self.rounds, key=lambda r: r.damage / base_d + r.durability / base_w).round

    @property
    def grows(self) -> bool:
        """La liste monte en puissance : la fin de partie vaut nettement plus que le round 1 (≥ +15 %)."""
        if len(self.rounds) < 2:
            return False
        a, b = self.rounds[0], self.rounds[-1]
        gain = (b.damage / a.damage if a.damage else 1.0) + (b.durability / a.durability if a.durability else 1.0)
        return gain >= 2.3


def _runes(board) -> list[str]:
    return list(dict.fromkeys(e.option_group for e in board.effects if e.option_group and "," in e.option_group
                              and not e.option_group.lower().startswith(("while", "if "))))


def _abilities_at(abilities, board, plan: list[str], r: int):
    """Aptitudes de la liste telles qu'au round `r` : disponibilité, rune posée ce round, exemplaires au tableau."""
    from dataclasses import replace

    counts = {rn: plan[:r].count(rn) for rn in set(plan[:r])}
    out = []
    for ab in abilities:
        if ab.available_round and ab.available_round > r:
            continue
        if board is not None and ab.uid == board.uid:
            chosen = plan[r - 1] if len(plan) >= r else ""
            effs = tuple(e for e in ab.effects if not e.option_group or e.option_group == chosen)
            effs = tuple(e for e in effs if not e.option_group or e.option_group == chosen)
            out.append(replace(ab, effects=tuple(dataclasses.replace(e, option_group="") for e in effs)))
            continue
        m = _PER_INSTANCE.search(ab.text or "")
        if m:
            rune = next((rn for rn in counts if rn.lower().startswith(m.group(1).split(",")[0].strip().lower())), None)
            n = counts.get(rune, 0) if rune else 0
            if n == 0:
                continue
            out.append(replace(ab, effects=tuple(dataclasses.replace(e, value=e.value * n) for e in ab.effects)))
            continue
        out.append(ab)
    return out


def _totals(abilities, units: list[Unit], vocab: frozenset[str], dead: frozenset[str]) -> tuple[float, float]:
    from .encounter import unit_durability
    from .stacking import stacks

    sts = {s.receiver: s for s in stacks(abilities, units, vocab, dead, core_costs={})}
    dmg = dur = 0.0
    for u in {x.name: x for x in units}.values():
        st = sts.get(u.name)
        base_ew = unit_durability(u)
        if st is None:
            from .encounter import CombatModifiers, EffectSpec, plan_offense, play_plan, probe_for_effect

            probe = probe_for_effect(EffectSpec("stat_mod", "hit", 1.0))
            mods = CombatModifiers(attacker_charged=True)  # même hypothèse que l'empilement
            dmg += plan_offense(u, probe, mods, play_plan(u, probe, mods))
            dur += base_ew
        else:
            dmg += st.off_after
            dur += base_ew * (1 + st.def_joint_pct / 100.0)
    return dmg, dur


def power_curve(abilities, units: list[Unit], vocab: frozenset[str], dead: frozenset[str] = frozenset()) -> Curve:
    board = next((ab for ab in abilities if _BOARD.search(ab.text or "") and _runes(ab)), None)
    from .givers import claimed_options

    forbidden = claimed_options(abilities)
    candidates = [rn for rn in _runes(board) if rn not in forbidden] if board is not None else []
    curve = Curve(board_ability=board.name if board is not None else "")
    plan: list[str] = []
    ref: Optional[tuple[float, float]] = None
    for r in ROUNDS:
        if candidates:
            best = None
            for rn in candidates:
                d, w = _totals(_abilities_at(abilities, board, plan + [rn], r), units, vocab, dead)
                if ref is None:
                    ref = (d or 1.0, w or 1.0)
                score = d / ref[0] + w / ref[1]
                if best is None or score > best[0]:
                    best = (score, rn, d, w)
            plan.append(best[1])
            d, w, rune = best[2], best[3], best[1]
        else:
            d, w = _totals(_abilities_at(abilities, None, plan, r), units, vocab, dead)
            rune = ""
        unlocked = tuple(ab.name for ab in abilities if ab.available_round == r and r > 1)
        curve.rounds.append(RoundValue(r, round(d, 2), round(w, 1), rune, unlocked))
    return curve

"""Indices couche 4 d'une liste L3 (`analysis.layers.listing.analyse_list`), à la place du compteur regex.

Pour chaque liste (export App de `Listes texte/<équipe>/<joueur>.txt`) :

* **empilement** (`stacking`, sans les commandes de base, communes à toutes les listes) : dégâts d'un round et
  PV effectifs de la liste « tout en place » rapportés à la liste nue. Une aptitude à cible unique
  (`stacking.target_choices`) ne compte que sur sa meilleure cible : second passage de l'empilement sans elle sur
  les autres receveurs (`stacking.single_target_stacks` ; sinon un +1 Attaque à une seule unité compterait sur
  toutes). Copies d'une même unité comprises ;
* **montée en puissance** (`buildup.power_curve`) : la courbe round par round, pondérée par le rythme de partie
  (`timeline.DEFAULT_RHYTHM` : 1/3, 1, 1, 1/3, 1/3), rapportée au round 1 — multiplie l'empilement ;
* **assaut** (`assault.Threat`) : allonge de charge apportée par la liste à chaque chargeur, en pouces
  (plus longue charge réussie à 50 % avec ses bonus, moins à sec) ; la relance de l'ordre est commune à tous,
  elle n'entre pas. Les charges groupées après téléportation (P(≥ 2)) sont gardées pour le diagnostic.

* **soins** (`listgrid`, famille soin) : survie gagnée par chaque receveur (`marriage.heal_survival_gain`),
  pondérée par sa durabilité, ses copies et P(l'aptitude sert) (déclenchement × invocation × suivi) ; une aptitude
  à cible unique ne compte que sur sa meilleure cible — multiplie la durabilité ;
* **contrôle** (`listgrid`, famille contrôle) : bonus de score de contrôle des receveurs, mêmes poids (une fois
  par bataille = 1/2) — s'ajoute au contrôle de la liste dans le pilier scénario (`ArmyList.control_eff`).

Ce qui n'est pas couvert (débuffs, objectifs hors score de contrôle, magie) reste lu par le compteur
(`l3/aptitudes.py`), en complément : voir `matchups.rate_lists`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..analysis.layers.encounter import (
    CombatModifiers,
    EffectSpec,
    plan_offense,
    play_plan,
    probe_for_effect,
    unit_durability,
)
from ..analysis.layers.listing import analyse_list
from ..analysis.layers.stacking import single_target_stacks
from ..analysis.layers.timeline import DEFAULT_RHYTHM
from ..tournament_kit.list_parser import parse_list_file

#: Allonge de charge maximale retenue (3 dés additionnés ≈ +3,5") : au-delà, la portée ne se lit plus en charge.
CHARGE_CAP = 3.5


@dataclass
class L4Indices:
    off_stack: float = 1.0  # dégâts « tout en place » / nus
    def_stack: float = 1.0  # PV effectifs « tout en place » / nus
    off_time: float = 1.0  # montée en puissance (courbe pondérée / round 1), dégâts
    def_time: float = 1.0  # idem, durabilité
    charge: dict[str, float] = field(default_factory=dict)  # unité -> pouces de charge apportés par la liste
    assault_p2: float = 0.0  # meilleure P(≥ 2 charges) des scénarios d'assaut groupé (téléportation)
    missing: list[str] = field(default_factory=list)  # unités de la liste absentes de la base
    top: list[tuple[str, float]] = field(default_factory=list)  # (unité, dégâts tout en place / nus), 3 meilleures
    heal: float = 0.0  # survie gagnée par les soins, part de la durabilité de la liste
    control: float = 0.0  # score de contrôle ajouté par les aptitudes (espérance)
    heal_top: list[tuple[str, float]] = field(default_factory=list)  # (aptitude, apport à `heal`), 3 meilleures
    control_top: list[tuple[str, float]] = field(default_factory=list)  # (aptitude, apport à `control`)
    unit_off: dict[str, float] = field(default_factory=dict)  # unité -> dégâts tout en place / nus (toutes)
    unit_def: dict[str, float] = field(default_factory=dict)  # unité -> PV effectifs tout en place / nus

    @property
    def off(self) -> float:
        return self.off_stack * self.off_time

    @property
    def deff(self) -> float:
        return self.def_stack * self.def_time * (1.0 + self.heal)

    @property
    def value(self) -> float:
        """Indice brut : ln(multiplicateur offensif) + ln(multiplicateur défensif)."""
        return math.log(max(self.off, 1e-6)) + math.log(max(self.deff, 1e-6))


def _bare_offense(u) -> float:
    probe = probe_for_effect(EffectSpec("stat_mod", "hit", 1.0))
    mods = CombatModifiers(attacker_charged=True)  # même hypothèse que l'empilement
    return plan_offense(u, probe, mods, play_plan(u, probe, mods))


def _time_factor(values: list[float]) -> float:
    if not values or not values[0]:
        return 1.0
    w = DEFAULT_RHYTHM[: len(values)]
    return sum(wi * v / values[0] for wi, v in zip(w, values)) / sum(w)


#: Un bonus de contrôle ne sert que sur les objectifs disputés : une aura ou une règle d'armée compte sur ses
#: CONTROL_RECEIVERS meilleures unités (une ou deux unités par objectif), pas sur toute la liste.
CONTROL_RECEIVERS = 2


def _grid_part(row, counts: dict[str, int], scale: dict[str, float], best: Optional[int] = None) -> float:
    """Apport d'une ligne de `rep.grid` : poids × Σ copies × échelle × gain ; une aptitude à cible unique
    (`one_friendly`) ne sert qu'une unité : sa meilleure cible seule ; `best` = au plus autant d'unités."""
    vals = sorted(
        (scale.get(n, 1.0) * g for n, g in row.gains if g > 0 for _ in range(counts.get(n, 1))), reverse=True
    )
    if not vals:
        return 0.0
    if row.scope == "one_friendly":
        vals = vals[:1]
    elif best is not None:
        vals = vals[:best]
    return row.weight * sum(vals)


def heal_and_control(rep, units) -> tuple[float, float, list, list]:
    """(soins en part de durabilité, score de contrôle ajouté, détails) des lectures `rep.grid`."""
    counts: dict[str, int] = {}
    for u in units:
        counts[u.name] = counts.get(u.name, 0) + 1
    ew = {u.name: unit_durability(u) for u in units}
    total = sum(counts[n] * ew[n] for n in counts) or 1.0
    heal_parts, ctl_parts = [], []
    for row in getattr(rep, "grid", []) or []:
        if row.family == "soin" and row.gains:
            v = _grid_part(row, counts, ew) / total
            if v:
                heal_parts.append((row.ability, v))
        elif row.family == "controle" and row.gains:
            v = _grid_part(row, counts, {}, CONTROL_RECEIVERS)
            if v:
                ctl_parts.append((row.ability, v))
    heal = sum(v for _n, v in heal_parts)
    ctl = sum(v for _n, v in ctl_parts)
    top = lambda parts: sorted(parts, key=lambda t: -t[1])[:3]  # noqa: E731
    return heal, ctl, top(heal_parts), top(ctl_parts)


def indices_from_report(rep) -> L4Indices:
    units = [u for _n, _p, u in rep.units if u is not None]
    counts: dict[str, int] = {}
    for u in units:
        counts[u.name] = counts.get(u.name, 0) + 1
    distinct = {u.name: u for u in units}
    dead = frozenset(a.uid for a, _r in rep.dead)
    # aptitude à cible unique : seulement sur la meilleure cible (second passage de l'empilement, 2026-11-25 :
    # retirer l'apport marginal laissait deux protections substituables sur toute l'armée)
    sts = {s.receiver: s for s in single_target_stacks(rep.abilities, units, rep.vocab, dead, core_costs={})[0]}
    d0 = d1 = w0 = w1 = 0.0
    top = []
    unit_off: dict[str, float] = {}
    unit_def: dict[str, float] = {}
    for name, u in distinct.items():
        n = counts[name]
        ew = unit_durability(u)
        st = sts.get(name)
        if st is None:
            b = _bare_offense(u)
            d0, d1, w0, w1 = d0 + n * b, d1 + n * b, w0 + n * ew, w1 + n * ew
            continue
        after = max(st.off_before, st.off_after)
        d0 += n * st.off_before
        d1 += n * after
        w0 += n * ew
        def_mult = 1 + max(0.0, st.def_joint_pct) / 100.0
        w1 += n * ew * def_mult
        unit_def[name] = def_mult
        if st.off_before:
            top.append((name, after / st.off_before))
            unit_off[name] = after / st.off_before
    ind = L4Indices(
        off_stack=d1 / d0 if d0 else 1.0,
        def_stack=w1 / w0 if w0 else 1.0,
        missing=[n for n, _p, u in rep.units if u is None],
        top=sorted(top, key=lambda t: -t[1])[:3],
        unit_off=unit_off,
        unit_def=unit_def,
    )
    ind.heal, ind.control, ind.heal_top, ind.control_top = heal_and_control(rep, units)
    if rep.curve is not None and rep.curve.rounds:
        ind.off_time = _time_factor([r.damage for r in rep.curve.rounds])
        ind.def_time = _time_factor([r.durability for r in rep.curve.rounds])
    if rep.assault is not None:
        for t in rep.assault.threats:  # clé = nom en base (« X (renforcé) » de la couche 4 → « X »)
            name = t.unit.removesuffix(" (renforcé)")
            ind.charge[name] = max(ind.charge.get(name, 0.0), min(CHARGE_CAP, max(0.0, t.bonus - t.dry)))
        ind.assault_p2 = max(
            (c.at_least[1] for sc in rep.assault.scenarios for c in sc.cases if len(c.at_least) > 1), default=0.0
        )
    return ind


def list_file(folder: Path, team: str, player: str) -> Optional[Path]:
    path = folder / team / f"{player}.txt"
    return path if path.exists() else None


def indices(con, path: Path) -> L4Indices:
    from ..analysis.layers.cascade import require_fresh

    require_fresh(con, 4)
    return indices_from_report(analyse_list(con, parse_list_file(path)))

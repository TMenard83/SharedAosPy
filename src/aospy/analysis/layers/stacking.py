"""Couche 4 — empilement : ce que chaque unité d'une liste reçoit EN MÊME TEMPS.

Premier type de combo (choix utilisateur, 2026-11-23) : pour chaque unité de la liste, tous les effets traduisibles
qu'elle peut recevoir (chartes, traits de bataille, formation, domaines, améliorations, manifestations) et les
commandes de base All-out Attack / All-out Defence (`data/json/generic_core_abilities.json`, coût en PC lu dans le
verbatim du MdG 26-27) sont appliqués ENSEMBLE par le moteur, puis comparés à la somme de leurs gains pris un par
un (leur produit : des effets indépendants se multiplient) :

* le **plafond ±1** des jets pour toucher, pour blesser et de sauvegarde porte sur le TOTAL des modificateurs
  (règles de base), pas sur chaque effet : deux « +1 pour toucher » font +1 ; un effet entièrement absorbé par le
  plafond est un **doublon plafonné** — à garder seulement s'il couvre autre chose (autres cibles, tir, unités
  hors bulle : un doublon partiel n'est pas une règle morte, mémoire `list-building-concept`) ;
* l'effet **ensemble** (« tout en place ») fait ressortir le Death-Star de la liste : l'unité qui gagne le plus quand
  tout tombe sur elle ;
* une seule option par aptitude à choix exclusif (la meilleure sur cette unité) ;
* les protections ne se cumulent pas (le moteur garde la meilleure).

Pas de pondération par la fiabilité ici : c'est le cas « tout en place » ; les conditions restent affichées (la
fiabilité de leurs fournisseurs est l'étape suivante des combos).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...domain.models import Unit
from .encounter import (
    CombatModifiers,
    EffectSpec,
    apply_effect,
    plan_offense,
    play_plan,
    probe_for_effect,
    unit_durability,
)

#: Jets dont le TOTAL des modificateurs est plafonné à ±1 (règles de base).
CAPPED = ("hit", "wound")
_CORE_JSON = Path(__file__).resolve().parents[4] / "data" / "json" / "generic_core_abilities.json"
#: Commandes de base traduisibles par le moteur : (nom français du MdG, nom anglais, effets).
CORE_COMMANDS = (
    (
        "Attaque en Règle",
        "All-out Attack",
        # « For the rest of the turn, subtract 1 from save rolls for the unit using this ability » : non compté —
        # la durabilité « tout en place » suppose All-out Defence au tour adverse, où ce malus ne joue plus
        (EffectSpec("stat_mod", "hit", 1.0, weapon_scope="all", includes_companion=True),),
    ),
    ("Défense en Règle", "All-out Defence", (EffectSpec("stat_mod", "save", 1.0),)),
)


@dataclass(frozen=True)
class StackItem:
    ability: str
    source: str
    off_alone_pct: float
    def_alone_pct: float
    capped: bool  # n'ajoute rien une fois les autres en place (plafond ±1, protection déjà meilleure)
    conditions: str = ""
    cp: int = 0


@dataclass(frozen=True)
class Stack:
    receiver: str
    items: tuple[StackItem, ...]
    off_joint_pct: float
    def_joint_pct: float
    #: produit des gains pris un par un, Π(1 + g) − 1 : la référence sans interaction (des effets indépendants
    #: se MULTIPLIENT — +1 Attaque et +1 pour toucher : 1,17 × 1,33 ≈ +56 % en moyenne) ; ensemble < produit =
    #: plafonds ±1 / protections non cumulées, ensemble > produit = effet de seuil du plancher de dégâts
    off_prod_pct: float
    def_prod_pct: float
    off_before: float = 0.0  # dégâts d'un round (plan de jeu, vs sauvegarde 4+), nus puis tout en place
    off_after: float = 0.0

    @property
    def cp(self) -> int:
        return sum(i.cp for i in self.items)


def core_command_costs(path: Path = _CORE_JSON) -> dict[str, int]:
    """Coût en PC des commandes de base, par nom anglais, d'après le verbatim français du MdG."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    by_fr = {r.get("name"): r for r in rows}
    out = {}
    for fr, en, _effs in CORE_COMMANDS:
        r = by_fr.get(fr) or {}
        if (r.get("points_type") or "").lower() == "command" and r.get("points"):
            out[en] = int(r["points"])
    return out


def _cap(base: Unit, after: Unit) -> Unit:
    """Plafond ±1 sur le TOTAL des modificateurs de toucher/blessure (par arme) et de sauvegarde."""
    ws = []
    for b, a in zip(base.weapons, after.weapons):
        ws.append(dataclasses.replace(a, hit=min(max(a.hit, b.hit - 1), b.hit + 1),
                                      wound=min(max(a.wound, b.wound - 1), b.wound + 1)))
    save = min(max(after.save, base.save - 1), base.save + 1)
    return dataclasses.replace(after, weapons=ws, save=save)


def _apply_all(unit: Unit, effs: list[EffectSpec], probe: Unit, mods: CombatModifiers) -> Unit:
    out = unit
    for e in effs:
        nxt = apply_effect(out, e, probe, mods)
        if nxt is not None:
            out = nxt
    return _cap(unit, out)


def _gains(unit: Unit, after: Unit, probe: Unit, mods: CombatModifiers, plan) -> tuple[float, float]:
    off0, def0 = plan_offense(unit, probe, mods, plan), unit_durability(unit)
    off1, def1 = plan_offense(after, probe, mods, plan), unit_durability(after)
    return (
        100.0 * (off1 - off0) / off0 if off0 else 0.0,
        100.0 * (def1 - def0) / def0 if def0 else 0.0,
    )


def stack_for(unit: Unit, offers: list[tuple[str, str, EffectSpec, str, str, int]]) -> Optional[Stack]:
    """`offers` = (aptitude, origine, effet, option exclusive, conditions, PC). None sans effet applicable."""
    probe = probe_for_effect(EffectSpec("stat_mod", "hit", 1.0))
    mods = CombatModifiers()
    plan = play_plan(unit, probe, mods)
    # une option par aptitude à choix exclusif : la meilleure seule sur ce châssis
    by_opt: dict[tuple[str, str, str], list] = {}
    plain = []
    for o in offers:
        (by_opt.setdefault((o[0], o[1], o[3]), []) if o[3] else plain).append(o)
    best_opt: dict[tuple[str, str], tuple[float, list]] = {}
    for (ab, src, _opt), group in by_opt.items():
        sc = sum(_gains(unit, _apply_all(unit, [g[2] for g in group], probe, mods), probe, mods, plan))
        if (ab, src) not in best_opt or sc > best_opt[(ab, src)][0]:
            best_opt[(ab, src)] = (sc, group)
    chosen = plain + [o for _sc, g in best_opt.values() for o in g]
    by_ability: dict[tuple[str, str], list] = {}
    for o in chosen:
        if apply_effect(unit, o[2], probe, mods) is not None:
            by_ability.setdefault((o[0], o[1]), []).append(o)
    if not by_ability:
        return None
    all_effs = [o[2] for group in by_ability.values() for o in group]
    joint = _apply_all(unit, all_effs, probe, mods)
    off_j, def_j = _gains(unit, joint, probe, mods, plan)
    items = []
    for (ab, src), group in by_ability.items():
        mine = [o[2] for o in group]
        off_a, def_a = _gains(unit, _apply_all(unit, mine, probe, mods), probe, mods, plan)
        rest = [e for e in all_effs if not any(e is m for m in mine)]
        off_r, def_r = _gains(unit, _apply_all(unit, rest, probe, mods), probe, mods, plan)
        adds = abs(off_j - off_r) > 0.05 or abs(def_j - def_r) > 0.05
        alone = abs(off_a) > 0.05 or abs(def_a) > 0.05
        conds = " | ".join(dict.fromkeys(c for o in group for c in o[4].split(" | ") if c))
        items.append(StackItem(ab, src, round(off_a, 1), round(def_a, 1), alone and not adds, conds, group[0][5]))
    items.sort(key=lambda i: -(i.off_alone_pct + i.def_alone_pct))
    return Stack(
        unit.name,
        tuple(items),
        round(off_j, 1),
        round(def_j, 1),
        round(_product(i.off_alone_pct for i in items), 1),
        round(_product(i.def_alone_pct for i in items), 1),
        round(plan_offense(unit, probe, mods, plan), 2),
        round(plan_offense(joint, probe, mods, plan), 2),
    )


def _product(pcts) -> float:
    out = 1.0
    for g in pcts:
        out *= 1.0 + g / 100.0
    return 100.0 * (out - 1.0)


def stacks(abilities, units: list[Unit], vocab: frozenset[str], dead: frozenset[str] = frozenset(),
           core_costs: Optional[dict[str, int]] = None) -> list[Stack]:
    """Empilement par unité distincte de la liste, trié par dégâts « tout en place » (absolus : un +200 % sur une
    unité qui ne frappe pas reste petit)."""
    from .listing import effect_ability, list_receivers

    core_costs = core_command_costs() if core_costs is None else core_costs
    out = []
    for unit in {u.name: u for u in units}.values():
        offers = []
        for ab in abilities:
            if ab.uid in dead:
                continue
            for eff in ab.translatable:
                recv = list_receivers(effect_ability(ab, eff.friendly_target), [unit], vocab)
                if not recv:
                    continue
                conds = eff.conditions
                if ab.charge_required and "a chargé" not in conds:
                    conds = " | ".join(c for c in (conds, "a chargé") if c)
                offers.append((ab.name, ab.source, eff, eff.option_group, conds, 0))
        for _fr, en, effs in CORE_COMMANDS:
            if en in core_costs:
                offers += [(en, "commande de base", e, "", "", core_costs[en]) for e in effs]
        st = stack_for(unit, offers)
        if st is not None:
            out.append(st)
    return sorted(out, key=lambda s: -s.off_after)

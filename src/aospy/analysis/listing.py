"""Couche 4 — aptitudes × armée : ce qu'une liste fait de ses aptitudes.

Architecture « aptitude ≠ châssis » (cf. CLAUDE.md, « Ability analysis ») : les couches 1-3 jugent
une aptitude hors contexte, une charte nue, puis un effet posé sur une charte. Ici on prend une
**liste réelle** (export de l'App, `tournament_kit.list_parser`) et on relève :

* **les mariages** — chaque effet ami traduisible de la liste (chartes, traits de bataille,
  formation choisie, améliorations prises, domaines choisis) posé sur chaque unité de la liste
  qui peut le recevoir, mesuré par le moteur (`encounter.encounter`) et pondéré comme en couche 3
  (`realized.coverage` × probabilité de déclenchement) ;
* **les conflits** — une aptitude « une fois par tour/round/bataille (armée) » portée par plusieurs
  unités ne sert qu'une fois : c'est ici, et pas en couche 3, que la limite anti-spam compte
  (règle utilisateur, mémoire `ability-weighting-rules`) ;
* **le budget de magie** — sorts disponibles face au nombre de lancers (un par sorcier et par
  tour, `WIZARD (N)` → N) ;
* **les aptitudes à lire** — sans effet traduisible (verdict `a-revoir`, mécaniques propres à la
  faction, tempo, débuffs) : l'analyse de liste les reprend à la main, jamais devinées.

Cœur pur sauf `collect_*` (lecture DuckDB) ; aucune écriture en base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..domain.models import Unit
from .encounter import EffectSpec, encounter, is_translatable, matches_friendly_target, receivers
from .realized import coverage

#: Fréquences dont la limite porte sur l'armée entière (un seul usage, quel que soit le porteur).
ARMY_LIMITED = {"once_per_turn_army", "once_per_round_army", "once_per_battle_army", "once_per_phase_army"}

_OPTION_COST_RE = re.compile(r"\s*-\s*\(\d+\)\s*Points?\s*$", re.I)
_WIZARD_LEVEL_RE = re.compile(r"WIZARD\s*\((\d+)\)")


def _base_name(s: Optional[str]) -> str:
    return (s or "").split("(", 1)[0].strip()


@dataclass(frozen=True)
class ListAbility:
    """Une aptitude présente dans la liste, avec son origine et son porteur éventuel."""

    uid: str
    name: str
    source: str            # « charte : Avalenor… », « formation : Warhost of Duality », « domaine : … »
    source_kind: str
    carriers: tuple[str, ...]  # unités de la liste qui la portent (vide pour une règle d'armée)
    scope: str
    frequency: str
    turn_side: str
    phase: str
    cost_type: str
    cost_value: Optional[float]
    activation_prob: float
    available_round: Optional[int]
    friendly_target: str
    excludes_self: bool
    verdict: str
    power: float
    reliability: float
    ease: float
    interaction: float
    effects: tuple[EffectSpec, ...] = ()

    @property
    def translatable(self) -> tuple[EffectSpec, ...]:
        return tuple(e for e in self.effects if is_translatable(e))


@dataclass(frozen=True)
class Marriage:
    """Un effet de la liste posé sur un receveur de la liste."""

    ability: str
    source: str
    receiver: str
    relation: str
    kind: str
    off_gain_pct: Optional[float]
    def_gain_pct: Optional[float]
    weight: float
    conditions: str

    @property
    def score(self) -> float:
        """Gain pondéré (%) attaque + défense — sert seulement à trier."""
        return self.weight * ((self.off_gain_pct or 0.0) + (self.def_gain_pct or 0.0))


@dataclass(frozen=True)
class Conflict:
    ability: str
    frequency: str
    carriers: tuple[str, ...]


@dataclass(frozen=True)
class MagicBudget:
    casters: tuple[tuple[str, int], ...]   # (sorcier, lancers par tour)
    spells: tuple[tuple[str, str, float, float], ...]  # (sort, origine, valeur de lancement, P(réussite))

    @property
    def casts_per_turn(self) -> int:
        return sum(n for _c, n in self.casters)


@dataclass
class ListReport:
    title: str
    faction: str
    units: list[tuple[str, int, Optional[Unit]]]
    abilities: list[ListAbility]
    marriages: list[Marriage] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    magic: Optional[MagicBudget] = None
    unresolved: list[ListAbility] = field(default_factory=list)


# ----- cœur pur ------------------------------------------------------------------

def wizard_level(unit: Unit) -> int:
    lv = [int(m.group(1)) for k in unit.keywords for m in [_WIZARD_LEVEL_RE.search(k)] if m]
    if lv:
        return max(lv)
    return 1 if "WIZARD" in unit.keywords else 0


def list_receivers(ab: ListAbility, units: list[Unit], vocab: frozenset[str]) -> list[tuple[Unit, str]]:
    """Receveurs d'une aptitude dans la liste : porteur pour `self`, cibles éligibles sinon."""
    if ab.carriers:
        carriers = [u for u in units if u.name in ab.carriers]
        if ab.scope in ("self", "unknown"):
            return [(u, "porteur") for u in carriers]
        if ab.scope in ("one_friendly", "friendly_aura", "army"):
            return [(u, "porteur" if u in carriers else "allié") for u in units
                    if matches_friendly_target(u, ab.friendly_target, vocab)
                    and not (ab.excludes_self and u in carriers)]
        return []
    return receivers(ab.source_kind, ab.scope, "faction_rule", ab.source, units, ab.friendly_target, vocab,
                     ab.excludes_self)


def marriages(abilities: list[ListAbility], units: list[Unit], vocab: frozenset[str]) -> list[Marriage]:
    out: list[Marriage] = []
    seen: set[tuple] = set()
    for ab in abilities:
        effs = ab.translatable
        if not effs:
            continue
        for unit, rel in list_receivers(ab, units, vocab):
            for eff in effs:
                key = (ab.uid, eff, unit.name)
                if key in seen:
                    continue
                seen.add(key)
                enc = encounter(unit, eff)
                if enc is None:
                    continue
                w = coverage(ab.frequency, eff.duration, ab.available_round) * ab.activation_prob
                out.append(Marriage(ab.name, ab.source, unit.name, rel, eff.kind, enc.off_gain_pct,
                                    enc.def_gain_pct, round(w, 3), eff.conditions))
    return sorted(out, key=lambda m: -m.score)


def conflicts(abilities: list[ListAbility], unit_counts: dict[str, int]) -> list[Conflict]:
    """Aptitudes limitées à l'armée portées par plusieurs exemplaires d'unités de la liste."""
    out = []
    for ab in abilities:
        if ab.frequency in ARMY_LIMITED and ab.carriers:
            n = sum(unit_counts.get(c, 1) for c in ab.carriers)
            if n > 1:
                out.append(Conflict(ab.name, ab.frequency, tuple(
                    f"{c} ×{unit_counts.get(c, 1)}" if unit_counts.get(c, 1) > 1 else c for c in ab.carriers)))
    return out


def magic_budget(abilities: list[ListAbility], units: list[Unit]) -> MagicBudget:
    casters = tuple((u.name, wizard_level(u)) for u in units if wizard_level(u) > 0)
    spells = tuple((ab.name, ab.source, ab.cost_value or 0.0, round(ab.activation_prob, 2))
                   for ab in abilities if (ab.cost_type or "").lower() == "spell")
    return MagicBudget(casters, spells)


def analyse(title: str, faction: str, entries: list[tuple[str, int, Optional[Unit]]],
            abilities: list[ListAbility], vocab: frozenset[str]) -> ListReport:
    units = [u for _n, _p, u in entries if u is not None]
    distinct = list({u.name: u for u in units}.values())
    counts: dict[str, int] = {}
    for u in units:
        counts[u.name] = counts.get(u.name, 0) + 1
    rep = ListReport(title, faction, entries, abilities)
    rep.marriages = marriages(abilities, distinct, vocab)
    rep.conflicts = conflicts(abilities, counts)
    rep.magic = magic_budget(abilities, units)
    rep.unresolved = [a for a in abilities if not a.translatable and a.scope != "one_enemy"
                      or a.verdict == "a-revoir"]
    return rep


# ----- lecture en base -------------------------------------------------------------

def _rule_groups(parsed) -> list[tuple[str, str]]:
    """(groupe `ability_owner.owner_name`, libellé d'origine) des règles d'armée choisies."""
    groups = [("Battle Traits › Battle Traits", "trait de bataille")]
    if parsed.allegiance:
        groups.append((f"Battle Formations › {_base_name(parsed.allegiance)}", "formation"))
    for lore, label in ((parsed.spell_lore, "domaine de sorts"), (parsed.prayer_lore, "domaine de prières"),
                        (parsed.manifestation_lore, "domaine de manifestations")):
        if lore:
            kind = {"domaine de sorts": "Spell Lore", "domaine de prières": "Prayer Lore",
                    "domaine de manifestations": "Manifestation Lore"}[label]
            groups.append((f"{kind} › {_base_name(lore)}", label))
    return groups


def _ability_from_row(row, source: str, carriers: tuple[str, ...], effects) -> ListAbility:
    (uid, name, source_kind, scope, freq, turn, phase, ctype, cval, prob, avail, ft, excl, verdict,
     power, rel, ease, inter) = row
    return ListAbility(uid, name, source, source_kind or "", carriers, scope or "", freq or "", turn or "",
                       phase or "", ctype or "", cval, prob if prob is not None else 1.0, avail, ft or "",
                       bool(excl), verdict or "", power or 0.0, rel or 0.0, ease or 0.0, inter or 0.0,
                       tuple(effects.get(uid, ())))


_ABILITY_SELECT = """SELECT DISTINCT a.uid, a.name, a.source_kind, a.scope, a.frequency, a.turn_side, a.phase,
       a.cost_type, a.cost_value, a.activation_prob, a.available_round, a.friendly_target, a.excludes_self,
       a.verdict, a.power, a.reliability, a.ease, a.interaction
FROM ability a JOIN ability_owner o ON o.ability_uid = a.uid"""


def _effects(con, uids: list[str]) -> dict[str, list[EffectSpec]]:
    if not uids:
        return {}
    out: dict[str, list[EffectSpec]] = {}
    for (uid, kind, stat, value, detail, side, wscope, wname, comp, tkw, tcond, req, dur) in con.execute(
            """SELECT ability_uid, kind, stat, value, detail, side, weapon_scope, weapon_name, includes_companion,
                      target_keywords, target_condition, requires, duration
               FROM ability_effect WHERE ability_uid IN ? ORDER BY ability_uid, seq""", [uids]).fetchall():
        out.setdefault(uid, []).append(EffectSpec(
            kind=kind, stat=stat or "", value=value or 0.0, detail=detail or "", side=side or "",
            weapon_scope=wscope or "", weapon_name=wname or "", includes_companion=bool(comp),
            target_keywords=tkw or "", target_condition=tcond or "", requires=req or "", duration=dur or ""))
    return out


def collect(con, parsed) -> tuple[list[tuple[str, int, Optional[Unit]]], list[ListAbility], frozenset[str]]:
    """Unités (nom, points, `Unit` en base ou None) et aptitudes de la liste."""
    from ..persistence import repository

    faction = parsed.base_faction
    units_by_army = repository.load_all_units_with_weapons(con)
    army_names = dict(con.execute("SELECT id, name FROM army").fetchall())
    pool = {u.name.lower(): u for aid, us in units_by_army.items() if army_names.get(aid) == faction for u in us}
    vocab = frozenset(k for us in units_by_army.values() for u in us for k in u.keywords)

    entries: list[tuple[str, int, Optional[Unit]]] = []
    options: list[tuple[str, str]] = []
    for reg in parsed.regiments:
        for ue in reg.units:
            entries.append((ue.name, ue.points, pool.get(ue.name.lower())))
            options.extend((ue.name, _OPTION_COST_RE.sub("", o).strip()) for o in ue.options)

    rows: list[tuple[tuple, str, tuple[str, ...]]] = []
    carriers = sorted({n for n, _p, _u in entries} | set(parsed.faction_terrain))
    for name in carriers:
        for row in con.execute(_ABILITY_SELECT + " WHERE o.owner_kind = 'warscroll' AND o.faction_name = ? "
                               "AND lower(o.owner_name) = lower(?)", [faction, name]).fetchall():
            rows.append((row, f"charte : {name}", (name,)))
    for group, label in _rule_groups(parsed):
        for row in con.execute(_ABILITY_SELECT + " WHERE o.owner_kind = 'faction_rule' AND o.owner_name = ? "
                               "AND (o.faction_name = ? OR o.faction_name = 'Endless Spells')",
                               [group, faction]).fetchall():
            rows.append((row, f"{label} : {group.split(' › ', 1)[1]}", ()))
    for unit_name, opt in options:
        for row in con.execute(_ABILITY_SELECT + " WHERE o.owner_kind = 'faction_rule' AND o.faction_name = ? "
                               "AND upper(a.name) = upper(?)", [faction, opt]).fetchall():
            rows.append((row, f"amélioration : {opt}", (unit_name,)))

    effects = _effects(con, sorted({r[0][0] for r in rows}))
    merged: dict[tuple[str, str], ListAbility] = {}
    for row, source, carr in rows:
        key = (row[0], source if not carr or source.startswith("amélioration") else "charte")
        prev = merged.get(key)
        if prev is None:
            merged[key] = _ability_from_row(row, source, carr, effects)
        else:  # même aptitude sur plusieurs chartes de la liste (ex. Battle Damaged)
            from dataclasses import replace
            merged[key] = replace(prev, carriers=tuple(dict.fromkeys(prev.carriers + carr)),
                                  source=prev.source if carr[0] in prev.source else f"{prev.source}, {carr[0]}")
    return entries, list(merged.values()), vocab


def analyse_list(con, parsed) -> ListReport:
    entries, abilities, vocab = collect(con, parsed)
    return analyse(parsed.title, parsed.base_faction, entries, abilities, vocab)

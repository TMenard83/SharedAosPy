"""Couche 4 — fiabilité d'un donneur recalculée avec ce que la liste lui donne.

La couche 3 juge un porteur NU : un Scinari Enlightener seul lance Clarity of Thought (valeur 7) à 58 % et ne tient
que 42 % des rounds. Dans la liste de Totosai (remarque utilisateur, 2026-11-23), il porte Silver Wand (+1 au
lancement), Scholar of the Sigils pris sur Thalari (+1 au lancement) et lance depuis le Shrine Luminor, qui relance
le jet (Cleansing Rituals) et prend les coups à sa place (Shrine Guardian : « All attacks that would target the
Shrine Guardian target this terrain feature instead ») : 97 % au lancement, et une survie qui n'a plus rien à voir.

* **lancement** (`caster_bonus`, `p_cast`) : tous les bonus de lancement (`stat_mod cast` > 0) et relances
  (`reroll cast`) que le lanceur reçoit dans la liste — sans plafond ±1 (le plafond des règles de base porte sur
  toucher, blesser et sauvegarder) ; une option exclusive qui donne un bonus de lancement est supposée choisie
  (notée) ; P = P(2D6 ≥ valeur − bonus), relance : 1 − (1 − P)² ;
* **survie** (`list_survival`) : la pression de S (couche 3) sur ses PV effectifs avec les protections reçues
  dans la liste (empilement sans les commandes, `stacking`), plus, pour un **gardien de décor**, les PV effectifs du
  décor de faction (profil Wahapedia : PV, sauvegarde, protection) qui encaisse à sa place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ...domain.models import Unit

_WARSCROLLS_CSV = Path(__file__).resolve().parents[4] / "data" / "wahapedia" / "Warscrolls.csv"
#: « All attacks that would target the Shrine Guardian target this terrain feature instead » (Shrine Guardian,
#: Words of Hate, Steward of the Realm, Man Da Tower!, Feed the Maw).
GUARDIAN_RE = re.compile(r"All attacks that would target the ([A-Z][\w' -]+?) target this terrain feature instead")
#: « pick a friendly LUMINETH REALM‐LORDS INFANTRY HERO within 3" of it … The target is now a Shrine Guardian »
_GUARDIAN_PICK = re.compile(r"[Pp]ick a friendly ([^.]*?) within \d+\" of (?:it|this terrain feature)")


def p_2d6(target: float) -> float:
    """P(2D6 ≥ target)."""
    n = sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= target)
    return n / 36


def p_cast(value, bonus: float = 0.0, reroll: bool = False) -> Optional[float]:
    """P(lancement) d'un sort de valeur `value` (nombre ou texte « 7 », `ability.cost_value`)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not v:
        return None
    p = p_2d6(v - bonus)
    return 1 - (1 - p) ** 2 if reroll else p


@dataclass
class CasterBonus:
    bonus: float = 0.0
    reroll: bool = False
    sources: list[str] = field(default_factory=list)


def caster_bonus(caster: Unit, abilities, vocab: frozenset[str]) -> CasterBonus:
    """Bonus de lancement et relances que `caster` reçoit des aptitudes de la liste (porteur compris)."""
    from .listing import effect_ability, list_receivers

    out = CasterBonus()
    # une option fixée par une amélioration (Scholar of the Sigils : « That rune cannot be depicted on your battle
    # scripture for the rest of the battle ») n'est plus disponible pour les autres aptitudes, pour toute l'armée
    claimed = {
        e.option_group
        for ab in abilities
        if ab.source.startswith("amélioration") and re.search(r"cannot be depicted", ab.text or "")
        for e in ab.effects
        if e.option_group and e.stat == "cast"
    }
    for ab in abilities:
        best = 0.0
        rr = False
        mine = ab.source.startswith("amélioration") and caster.name in ab.carriers
        for e in ab.effects:
            if e.side not in ("friendly", "") or e.stat != "cast":
                continue
            if e.option_group in claimed and not mine:
                continue
            if e.kind not in ("stat_mod", "reroll") or (e.kind == "stat_mod" and e.value <= 0):
                continue
            if not list_receivers(effect_ability(ab, e.friendly_target), [caster], vocab):
                continue
            if e.kind == "stat_mod":
                best = max(best, e.value)
            else:
                rr = True
        if best or rr:
            out.bonus += best
            out.reroll = out.reroll or rr
            tag = []
            if best:
                tag.append(f"+{best:g}")
            if rr:
                tag.append("relance")
            opt = next((e.option_group for e in ab.effects if e.stat == "cast" and e.option_group), "")
            out.sources.append(f"{ab.name} ({' '.join(tag)}{', option ' + opt if opt else ''})")
    return out


def terrain_profile(name: str, path: Path = _WARSCROLLS_CSV) -> Optional[tuple[int, int, Optional[int]]]:
    """(PV, sauvegarde, protection) d'un décor de faction d'après Wahapedia, None s'il est introuvable."""
    from ...sources.wahapedia_csv import read_csv

    try:
        rows = read_csv(path)
    except OSError:
        return None
    r = next((x for x in rows if (x.get("name") or "").lower() == name.lower()), None)
    if not r or not (r.get("Health") or "").isdigit():
        return None
    num = lambda s: int(s.rstrip("+")) if s and s.rstrip("+").isdigit() else None  # noqa: E731
    return int(r["Health"]), num(r.get("Save")) or 7, num(r.get("Ward"))


def guardians(abilities, units: list[Unit], vocab: frozenset[str]) -> dict[str, str]:
    """Unité de la liste → décor de faction qui encaisse à sa place (UN gardien par décor), d'après le texte du décor :
    « All attacks that would target the <rôle> target this terrain feature instead » et la désignation de
    l'aptitude qui y place l'unité. Le jeu est supposé en place (l'unité est posée sur le décor)."""
    from .encounter import matches_friendly_target, unit_durability
    from .marriage import caster_level

    terrains = {c for ab in abilities for c in ab.carriers if GUARDIAN_RE.search(ab.text or "")}
    out: dict[str, str] = {}
    for terrain in sorted(terrains):
        picks = [
            m.group(1) for ab in abilities if terrain in ab.carriers for m in _GUARDIAN_PICK.finditer(ab.text or "")
        ]
        eligible = [
            u
            for u in units
            if u.name not in out
            and (
                any(matches_friendly_target(u, ph.replace("‐", "-"), vocab) for ph in picks)
                or (not picks and u.is_hero)
            )
        ]
        if eligible:
            # un seul gardien par décor : le lanceur de plus haut niveau, puis le plus fragile (il y gagne le plus)
            best = max(eligible, key=lambda u: (caster_level(u, "WIZARD") + caster_level(u, "PRIEST"),
                                                -unit_durability(u)))
            out[best.name] = terrain
    return out


def list_survival(
    unit: Unit,
    incoming: tuple[float, float],
    exposure: str,
    start: int,
    lasting: bool,
    durability_gain_pct: float = 0.0,
    shield_wounds: float = 0.0,
) -> float:
    """S (couche 3) avec ce que la liste donne : PV effectifs × (1 + gain de durabilité de l'empilement), plus les
    PV effectifs d'un décor qui encaisse à sa place."""
    from .encounter import unit_durability
    from .marriage import alive_profile, damage_per_round, survival_coverage

    hp = unit.health * unit.models
    ew = unit_durability(unit)
    # la pression `damage_per_round` est déjà nette de la sauvegarde du porteur : on la ramène sur ses PV, puis on
    # agrandit la réserve à proportion des PV effectifs gagnés (protections) et de ceux du décor
    scale = ((ew * (1 + durability_gain_pct / 100.0)) + shield_wounds) / ew if ew else 1.0
    profile = alive_profile(hp * scale, damage_per_round(incoming[0], incoming[1], exposure), start=start)
    return survival_coverage(profile, start, lasting=lasting)


@dataclass(frozen=True)
class GiverRow:
    """Un porteur d'aptitude donnée (ou de sort), nu (couche 3) puis dans la liste."""

    giver: str
    ability: str
    cast_bare: Optional[float]
    cast_list: Optional[float]
    survival_bare: float
    survival_list: float
    bearing_list: float  # D × S dans la liste (sans le lancement, compté à part)
    notes: tuple[str, ...] = ()


def giver_rows(
    abilities,
    units: list[Unit],
    vocab: frozenset[str],
    marriage_rows: dict[tuple[str, str], tuple],
    incoming: dict[int, tuple[float, float]],
    dead: frozenset[str] = frozenset(),
) -> list[GiverRow]:
    """Pour chaque aptitude d'une charte de la liste donnée à d'autres (ou sort) : lancement et survie du porteur
    recalculés avec la liste. `marriage_rows[(porteur, uid)]` = (exposition, déclenchement, round de départ,
    survie, D × S) de `ability_marriage`."""
    from .encounter import compute_effective_wounds
    from .marriage import _lasting
    from .stacking import stacks

    by_name = {u.name: u for u in units}
    guard = guardians(abilities, units, vocab)
    stack_def = {
        st.receiver: st.def_joint_pct for st in stacks(abilities, list(by_name.values()), vocab, dead, core_costs={})
    }
    shields: dict[str, float] = {}
    for unit_name, terrain in guard.items():
        prof = terrain_profile(terrain)
        if prof:
            shields[unit_name] = compute_effective_wounds(prof[0], prof[1], prof[2] or 7)
    rows = []
    for ab in abilities:
        is_spell = (ab.cost_type or "").lower() == "spell"
        given = ab.scope in ("one_friendly", "friendly_aura", "army")
        if ab.uid in dead or not ab.carriers or not (given or is_spell):
            continue
        for c in ab.carriers:
            u = by_name.get(c)
            mr = marriage_rows.get((c, ab.uid))
            if u is None or mr is None:
                continue
            expo, _p_trig, start, surv, bearing = mr
            d3 = bearing / surv if surv else 0.0
            notes = []
            s_list = list_survival(
                u,
                incoming.get(u.id, (0.0, 0.0)),
                expo,
                start or 1,
                _lasting(ab.frequency, {e.duration for e in ab.effects}),
                stack_def.get(c, 0.0),
                shields.get(c, 0.0),
            )
            if c in guard:
                notes.append(f"gardien de « {guard[c]} » : le décor encaisse à sa place")
            if stack_def.get(c):
                notes.append(f"protections reçues : durabilité {stack_def[c]:+.0f} %")
            cb = cl = None
            if is_spell:
                bonus = caster_bonus(u, abilities, vocab)
                cb = p_cast(ab.cost_value)
                cl = p_cast(ab.cost_value, bonus.bonus, bonus.reroll)
                notes += bonus.sources
            rows.append(GiverRow(c, ab.name, cb, cl, round(surv, 3), round(s_list, 3), round(d3 * s_list, 3),
                                 tuple(notes)))
    return rows


def best_list_cast(ab, units: list[Unit], abilities, vocab: frozenset[str]) -> Optional[float]:
    """Sort de domaine (sans porteur attitré) : la meilleure P(lancement) parmi les sorciers de la liste, avec ce
    que chacun reçoit (bonus, relances)."""
    from .marriage import caster_level

    best = None
    for u in units:
        if caster_level(u, "WIZARD") <= 0:
            continue
        b = caster_bonus(u, abilities, vocab)
        p = p_cast(ab.cost_value, b.bonus, b.reroll)
        if p is not None and (best is None or p > best):
            best = p
    return best

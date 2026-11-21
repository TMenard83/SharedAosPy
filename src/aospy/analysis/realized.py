"""Couche 3 — valeur réalisée d'une unité : son châssis + ses propres aptitudes qui la boostent.

Pour refaire les « meilleures unités » (cf. CLAUDE.md, « Ability analysis ») : on ne cherche pas des
buffers, donc seules comptent les aptitudes de la charte qui s'appliquent à l'unité elle-même —
portée `self`, ou bulle/ordre ami dont elle est une cible éligible (restriction de cible amie
satisfaite, pas « another/other friendly »). Traits héroïques, artefacts, règles d'armée et buffs
d'autres unités relèvent de la liste (couche 4).

Pondération (validée par l'utilisateur, 2026-11-19) :

* **rounds** : 2 et 3 pèsent 1 chacun, 1/4/5 pèsent 1/3 chacun (ouverture, fin des combats,
  scoring) — total 3 ;
* **durée × fréquence** : passif, permanent, ou réutilisable à chaque tour/phase/round → 1 (les
  limites « une fois par tour (armée) » empêchent le spam entre plusieurs unités : elles comptent
  en analyse de liste, pas ici) ; une fois par bataille et de courte durée → 1/2, joué au kairos
  (le point de bascule) ; une fois par bataille et pour le reste de la bataille → activé au round 2,
  couvre les rounds 2-5 = 8/9 ;
* **ressource de faction** : Dîme de Sang → seulement les rounds où elle est disponible
  (`ability.available_round`) ; ressource au rythme inconnu (prérequis
  `perimeter.SPENDS_RESOURCE`, « Spend N … points ») → 1/2, un usage
  fort au kairos (hypothèse à challenger) ;
* **paliers/options** d'une même aptitude (« +1 … +2 instead ») : le plus fort seulement ;
* **déclenchement** : × `ability.activation_prob` (prières : points rituels stockés, cf.
  `abilities.extract.p_prayer_banked`) ;
* **conditions** (« a chargé », « vs HERO », « sur objectif »…) : aucun poids — ce sont des
  interactions (carte, alliés, adversaire) qui orientent la liste. Elles sont exclues du chiffre
  **réalisé** et ajoutées dans un second chiffre **dans le bon cas**.

Calcul : les effets de poids 1 sans condition s'appliquent ensemble au profil (les multiplications
se combinent : +1 touche et +1 attaque) ; les autres s'ajoutent ensuite comme gains pondérés,
mesurés sur ce profil déjà boosté.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..abilities.perimeter import RESOURCE_SCALED, SPENDS_RESOURCE
from ..domain.models import Unit
from ..engine.combat import CombatModifiers
from .marriage import trigger
from .timeline import DEFAULT_RHYTHM, KAIROS_SHORT
from .timeline import coverage as timeline_coverage
from .encounter import (FRIENDLY_SCOPES, EffectSpec, _defense, _offense, _probe, apply_effect,
                        is_translatable, matches_friendly_target, play_plan)

#: Poids des rounds 1 à 5 (somme 3) = rythme par défaut de la frise (`timeline.DEFAULT_RHYTHM`).
ROUND_WEIGHTS = DEFAULT_RHYTHM
#: Une fois par bataille, effet court : joué au kairos, le round de bascule (choix utilisateur : 1/2).
ONCE_PER_BATTLE_SHORT = KAIROS_SHORT
_LASTING = {"bataille", "permanent", "conditionnelle"}


#: Ressource de faction au rythme de gain inconnu (points de discipline, d'oath…) : on suppose qu'elle
#: finance un usage fort au moment clé, comme une aptitude une fois par bataille (hypothèse à challenger).
UNKNOWN_RESOURCE = ONCE_PER_BATTLE_SHORT


def coverage(frequency: str, duration: str, available_round: Optional[int] = None,
             uses_resource: bool = False, turn_side: str = "any", polarity: str = "autre",
             share_melee: float = 1.0, start_round: int = 1) -> float:
    """Part de la partie couverte par l'effet (0-1) : frise de 10 demi-tours (`timeline.coverage`) — fréquence,
    tour où on le joue, durée écrite, pertinence offensive/défensive de chaque demi-tour.

    `available_round` (Dîme de Sang…, cf. `abilities.pipeline.RESOURCE_RATES`) : l'effet ne couvre que
    les rounds à partir de celui-là. Ressource sans rythme connu : `UNKNOWN_RESOURCE`."""
    start = max(start_round, available_round or 1)
    base = timeline_coverage(frequency or "", duration or "", turn_side or "any", polarity, share_melee,
                             start_round=min(start, 6))
    if uses_resource and not (available_round and available_round > 1):
        base = min(base, UNKNOWN_RESOURCE)
    return base


@dataclass(frozen=True)
class OwnEffect:
    """Effet d'une aptitude propre de la charte, avec ce qu'il faut pour le pondérer."""

    ability: str
    spec: EffectSpec
    frequency: str
    activation_prob: float
    available_round: Optional[int] = None
    uses_resource: bool = False
    turn_side: str = "any"

    def weight(self, polarity: str = "autre", share_melee: float = 1.0, start_round: int = 1,
               turn_side: Optional[str] = None) -> float:
        """Couverture sur la frise (polarité 'off'/'def') × P(déclenchement). `turn_side` remplace celui de
        l'aptitude (« a chargé » → mon tour seulement)."""
        spends = (self.uses_resource or SPENDS_RESOURCE in self.spec.requires
                  or RESOURCE_SCALED in self.spec.requires)
        return coverage(self.frequency, self.spec.duration, self.available_round, spends,
                        turn_side or self.turn_side, polarity, share_melee, start_round) * self.activation_prob

    def full(self, share_melee: float = 1.0) -> bool:
        """Actif sur toute la partie, en attaque comme en défense : appliqué directement au profil."""
        return self.weight("off", share_melee) >= 0.999 and self.weight("def", share_melee) >= 0.999

    @property
    def conditional(self) -> bool:
        # Un bonus « Charge (+N) » n'existe que si quelqu'un a chargé (nous, ou l'ennemi pour un
        # anti-charge) : conditionnel par nature, même quand le texte ne l'écrit pas comme prérequis.
        conds = [c for c in self.spec.conditions.split(" | ")
                 if c and c not in (SPENDS_RESOURCE, RESOURCE_SCALED)]
        return bool(conds) or self.spec.kind == "charge_bonus"


@dataclass(frozen=True)
class Realized:
    off_chassis: float
    def_chassis: float
    off_realized: float
    def_realized: float
    off_good_case: float
    def_good_case: float
    n_effects: int
    n_conditional: int
    #: « selon châssis » (couche 3, mariage) : réalisé + effets dont les conditions tiennent au porteur,
    #: pondérés par la probabilité que CE châssis les remplisse (`marriage.trigger`).
    off_fit: float = 0.0
    def_fit: float = 0.0


def _measure(unit: Unit, plan: str) -> tuple[float, float]:
    probe = _probe(EffectSpec("none"))
    mods = CombatModifiers()
    return _offense(unit, probe, mods, plan), _defense(unit)


def realize(unit: Unit, effects: list[OwnEffect], share_melee: float = 1.0) -> Realized:
    """Valeur réalisée (et « dans le bon cas ») d'une unité avec ses propres effets.

    Offense lue selon le plan de jeu de la charte nue (`approach.Plan` : à chaque round l'unité tire, combat ou approche, selon distance et portées)."""
    sm = share_melee
    plan = play_plan(unit)
    off0, def0 = _measure(unit, plan)
    base = [e for e in effects if not e.conditional and e.full(sm)]
    boosted = unit
    for e in base:
        boosted = apply_effect(boosted, e.spec) or boosted
    off_b, def_b = _measure(boosted, plan)

    def weighted(pool: list[OwnEffect], factors: Optional[list[float]] = None,
                 starts: Optional[list[int]] = None, sides: Optional[list[Optional[str]]] = None
                 ) -> tuple[float, float]:
        d_off = d_def = 0.0
        for k, e in enumerate(pool):
            f = factors[k] if factors is not None else 1.0
            if f <= 0:
                continue
            st = starts[k] if starts is not None else 1
            ts = sides[k] if sides is not None else None
            mods = CombatModifiers(attacker_charged="a chargé" in e.spec.requires or e.spec.kind == "charge_bonus")
            probe = _probe(e.spec)
            after = apply_effect(boosted, e.spec, probe, mods)
            if after is None:
                continue
            d_off += f * e.weight("off", sm, st, ts) * (_offense(after, probe, mods, plan)
                                                       - _offense(boosted, probe, mods, plan))
            d_def += f * e.weight("def", sm, st, ts) * (_defense(after) - def_b)
        return d_off, d_def

    rest = [e for e in effects if not e.conditional and not e.full(sm)]
    cond = [e for e in effects if e.conditional]
    r_off, r_def = weighted(rest)
    c_off, c_def = weighted(cond)
    fit, starts, sides = [], [], []
    for e in cond:
        t = trigger(unit, e.spec.requires, e.spec.conditions, sm,
                    melee_effect=e.spec.weapon_scope == "melee", kind=e.spec.kind)
        fit.append(t.p if t.bearer_only else 0.0)
        starts.append(t.start)
        sides.append("yours" if t.charged else None)       # « a chargé » : le combat de MON tour
    f_off, f_def = weighted(cond, fit, starts, sides)
    return Realized(
        off_chassis=off0, def_chassis=def0,
        off_realized=off_b + r_off, def_realized=def_b + r_def,
        off_good_case=off_b + r_off + c_off, def_good_case=def_b + r_def + c_def,
        n_effects=len(effects), n_conditional=len(cond),
        off_fit=off_b + r_off + f_off, def_fit=def_b + r_def + f_def,
    )


def own_effects(con) -> dict[tuple[str, str], list[tuple[str, str, bool, str, OwnEffect]]]:
    """Effets amis traduisibles des aptitudes de charte, par (faction, charte en minuscules).

    Chaque entrée : (portée, restriction de cible amie, exclut le porteur, nom, effet)."""
    rows = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.name, a.scope,
                  coalesce(e.friendly_target, a.friendly_target), a.excludes_self,
                  a.frequency, a.activation_prob, a.available_round,
                  FALSE, a.turn_side,
                  e.kind, e.stat, e.value, e.detail, e.side, e.weapon_scope, e.weapon_name, e.includes_companion,
                  e.target_keywords, e.target_condition, e.requires, e.duration
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           JOIN ability_effect e ON e.ability_uid = a.uid
           WHERE o.owner_kind = 'warscroll' AND e.side = 'friendly'
             AND a.source_kind NOT IN ('manifestation')"""
    ).fetchall()
    out: dict[tuple[str, str], list] = {}
    for (fac, owner, name, scope, ftarget, excl, freq, prob, avail, resource, tside, kind, stat, value, detail, side,
         wscope, wname, comp, tkw, tcond, req, dur) in rows:
        spec = EffectSpec(kind=kind, stat=stat or "", value=value or 0.0, detail=detail or "", side=side or "",
                          weapon_scope=wscope or "", weapon_name=wname or "", includes_companion=bool(comp),
                          target_keywords=tkw or "", target_condition=tcond or "", requires=req or "",
                          duration=dur or "")
        if not is_translatable(spec):
            continue
        out.setdefault((fac, owner), []).append(
            (scope, ftarget or "", bool(excl), name,
             OwnEffect(ability=name, spec=spec, frequency=freq or "", activation_prob=prob if prob is not None else 1.0,
                       available_round=avail, uses_resource=bool(resource), turn_side=tside or "any")))
    return out


def applicable(unit: Unit, entries: list, vocab: frozenset[str]) -> list[OwnEffect]:
    """Effets qui tombent sur l'unité elle-même : `self`, ou portée amie dont elle est cible éligible."""
    keep = []
    for scope, ftarget, excl, _name, eff in entries:
        if scope == "self" or (scope in FRIENDLY_SCOPES and not excl
                               and matches_friendly_target(unit, ftarget, vocab)):
            keep.append(eff)
    return strongest_alternatives(keep)


def strongest_alternatives(effects: list[OwnEffect]) -> list[OwnEffect]:
    """Dans une même aptitude, des effets de même nature sont des paliers ou des options
    (« +1 Damage … +2 instead ») : on garde le plus fort, on ne les additionne pas."""
    best: dict[tuple, OwnEffect] = {}
    for e in effects:
        s = e.spec
        key = (e.ability, s.kind, s.stat, s.weapon_scope, s.weapon_name)
        cur = best.get(key)
        stronger = cur is None or (s.value < cur.spec.value if s.kind == "ward" else s.value > cur.spec.value)
        if stronger:
            best[key] = e
    return list(best.values())


REALIZED_COLS = (
    "unit_id", "off_chassis", "def_chassis", "off_realized", "def_realized", "off_good_case", "def_good_case",
    "off_realized_per_100", "def_realized_per_100", "off_good_per_100", "def_good_per_100",
    "off_pct_rank", "def_pct_rank", "n_effects", "n_conditional", "abilities",
    "combined_per_100", "combined_pct_rank",
    "off_fit", "def_fit", "off_fit_per_100", "def_fit_per_100", "combined_fit_per_100", "combined_fit_pct_rank",
    "reach_in", "mobility", "score_per_100", "score_pct_rank", "score_fit_per_100",
)


def mobility_effects(con) -> dict[tuple[str, str], list[tuple]]:
    """Effets de mouvement des aptitudes de charte, par (faction, charte en minuscules) : (portée, cible amie,
    exclut le porteur, (kind, stat, value, activation_prob, frequency)) — même règle de receveur qu'`applicable`."""
    from .mobility import MOBILITY_KINDS

    rows = con.execute(
        f"""SELECT o.faction_name, lower(o.owner_name), a.scope, coalesce(e.friendly_target, a.friendly_target),
                   a.excludes_self, e.kind, e.stat, e.value, a.activation_prob, a.frequency
            FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
            JOIN ability_effect e ON e.ability_uid = a.uid
            WHERE o.owner_kind = 'warscroll' AND coalesce(e.side, 'friendly') = 'friendly'
              AND a.source_kind NOT IN ('manifestation')
              AND e.kind IN ({', '.join('?' * len(MOBILITY_KINDS))})""",
        sorted(MOBILITY_KINDS),
    ).fetchall()
    out: dict[tuple[str, str], list] = {}
    for fac, owner, scope, ftarget, excl, kind, stat, value, prob, freq in rows:
        out.setdefault((fac, owner), []).append(
            (scope, ftarget or "", bool(excl),
             (kind, stat or "", value or 0.0, prob if prob is not None else 1.0, freq or "")))
    return out


def unit_mobility_effects(unit: Unit, entries: list, vocab: frozenset[str]) -> list[tuple]:
    """Effets de mouvement qui tombent sur l'unité elle-même (`self`, ou portée amie dont elle est cible)."""
    return [eff for scope, ftarget, excl, eff in entries
            if scope == "self" or (scope in FRIENDLY_SCOPES and not excl
                                   and matches_friendly_target(unit, ftarget, vocab))]


def combined(off_per_100: float, def_per_100: float) -> float:
    """Indicateur combiné (validé par l'utilisateur, 2026-11-19) : moyenne géométrique des dégâts et de
    la durabilité pour 100 pts — logique de Lanchester, ce qu'une unité inflige sur sa durée de vie
    dépend des deux ; un canon de verre (gros dégâts, aucune durabilité) ne domine plus."""
    return (max(off_per_100, 0.0) * max(def_per_100, 0.0)) ** 0.5


def build_realized_rows(con) -> list[tuple]:
    """Tuples `REALIZED_COLS` pour toutes les unités payantes."""
    from ..persistence import repository
    from .chassis import _pct_rank

    units_by_army = repository.load_all_units_with_weapons(con)
    army_names = dict(con.execute("SELECT id, name FROM army").fetchall())
    units = [(army_names[aid], u) for aid, us in units_by_army.items() for u in us if u.points > 0]
    vocab = frozenset(k for _f, u in units for k in u.keywords)
    effects = own_effects(con)
    share_melee = dict(con.execute("SELECT unit_id, coalesce(share_melee, 1.0) FROM unit_chassis").fetchall())

    from .mobility import median_reach, mobility_factor, reach

    moves = mobility_effects(con)
    results = []
    reaches = []
    for fac, u in units:
        effs = applicable(u, effects.get((fac, u.name.lower()), []), vocab)
        results.append((u, realize(u, effs, share_melee.get(u.id, 1.0)), sorted({e.ability for e in effs})))
        reaches.append(reach(u, unit_mobility_effects(u, moves.get((fac, u.name.lower()), []), vocab)))
    med = median_reach(reaches) if reaches else 0.0
    mob = [mobility_factor(x, med) for x in reaches]

    rows: list[tuple] = []
    ranks: dict[int, tuple[float, float, float, float, float]] = {}
    for hero in (True, False):
        idx = [i for i, (u, _r, _a) in enumerate(results) if u.is_hero == hero]
        offs = [results[i][1].off_realized * 100 / results[i][0].points for i in idx]
        defs = [results[i][1].def_realized * 100 / results[i][0].points for i in idx]
        orank, drank = _pct_rank(offs), _pct_rank(defs)
        crank = _pct_rank([combined(o, d) for o, d in zip(offs, defs)])
        frank = _pct_rank([combined(results[i][1].off_fit * 100 / results[i][0].points,
                                    results[i][1].def_fit * 100 / results[i][0].points) for i in idx])
        srank = _pct_rank([combined(o, d) * mob[i] for i, o, d in zip(idx, offs, defs)])
        for k, i in enumerate(idx):
            ranks[i] = (orank[k], drank[k], crank[k], frank[k], srank[k])
    for i, (u, r, names) in enumerate(results):
        per = 100.0 / u.points
        rows.append((
            u.id, round(r.off_chassis, 3), round(r.def_chassis, 2), round(r.off_realized, 3),
            round(r.def_realized, 2), round(r.off_good_case, 3), round(r.def_good_case, 2),
            round(r.off_realized * per, 3), round(r.def_realized * per, 3), round(r.off_good_case * per, 3),
            round(r.def_good_case * per, 3), ranks[i][0], ranks[i][1], r.n_effects, r.n_conditional,
            " | ".join(names) or None,
            round(combined(r.off_realized * per, r.def_realized * per), 3), ranks[i][2],
            round(r.off_fit, 3), round(r.def_fit, 2), round(r.off_fit * per, 3), round(r.def_fit * per, 3),
            round(combined(r.off_fit * per, r.def_fit * per), 3), ranks[i][3],
            round(reaches[i], 2), round(mob[i], 3),
            round(combined(r.off_realized * per, r.def_realized * per) * mob[i], 3), ranks[i][4],
            round(combined(r.off_fit * per, r.def_fit * per) * mob[i], 3),
        ))
    return rows

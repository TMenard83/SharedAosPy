"""Couche 3 — valeur réalisée d'une unité : son châssis + ses propres aptitudes qui la boostent.

Pour refaire les « meilleures unités » (cf. analysis/README.md, « Architecture en quatre couches ») : on ne cherche pas des
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

from ...abilities.perimeter import RESOURCE_SCALED, SPENDS_RESOURCE
from ...domain.models import Unit
from ...engine.combat import CombatModifiers
from .encounter import (
    FRIENDLY_SCOPES,
    EffectSpec,
    apply_effect,
    is_translatable,
    matches_friendly_target,
    plan_offense,
    play_plan,
    probe_for_effect,
    unit_durability,
)
from .marriage import CHAINED_FIGHT_SHARE, trigger
from .timeline import DEFAULT_RHYTHM, KAIROS_SHORT
from .timeline import coverage as timeline_coverage

#: prérequis « combat enchaîné » (`abilities.perimeter`) : compté à `CHAINED_FIGHT_SHARE`, pas écarté
CHAINED = "combat enchaîné"
#: Prérequis « au combat » (couche 1, `abilities.perimeter`).
IN_COMBAT = "au combat"

#: Poids des rounds 1 à 5 (somme 3) = rythme par défaut de la frise (`timeline.DEFAULT_RHYTHM`).
ROUND_WEIGHTS = DEFAULT_RHYTHM
#: Une fois par bataille, effet court : joué au kairos, le round de bascule (choix utilisateur : 1/2).
ONCE_PER_BATTLE_SHORT = KAIROS_SHORT
_LASTING = {"bataille", "permanent", "conditionnelle"}


#: Ressource de faction au rythme de gain inconnu (points de discipline, d'oath…) : on suppose qu'elle
#: finance un usage fort au moment clé, comme une aptitude une fois par bataille (hypothèse à challenger).
UNKNOWN_RESOURCE = ONCE_PER_BATTLE_SHORT


def coverage(
    frequency: str,
    duration: str,
    available_round: Optional[int] = None,
    uses_resource: bool = False,
    turn_side: str = "any",
    polarity: str = "autre",
    share_melee: float = 1.0,
    start_round: int = 1,
    resource_usage: Optional[float] = None,
) -> float:
    """Part de la partie couverte par l'effet (0-1) : frise de 10 demi-tours (`timeline.coverage`) — fréquence,
    tour où on le joue, durée écrite, pertinence offensive/défensive de chaque demi-tour.

    `available_round` (Dîme de Sang…, cf. `abilities.pipeline.RESOURCE_RATES`) : l'effet ne couvre que
    les rounds à partir de celui-là. Ressource dépensée à chaque usage au rythme connu (`ability.resource_usage`
    = min(1, rythme/coût), analyseur v34, validé par l'utilisateur) : la couverture × ce facteur ; sans rythme
    connu : plafonnée à `UNKNOWN_RESOURCE`."""
    start = max(start_round, available_round or 1)
    base = timeline_coverage(
        frequency or "", duration or "", turn_side or "any", polarity, share_melee, start_round=min(start, 6)
    )
    if uses_resource and not (available_round and available_round > 1):
        base = base * resource_usage if resource_usage is not None else min(base, UNKNOWN_RESOURCE)
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
    #: facteur d'usage de la ressource dépensée (`ability.resource_usage`) ; None = rythme inconnu
    resource_usage: Optional[float] = None
    #: option d'une aptitude à choix exclusif (`ability_effect.option_group`, analyseur v33) ; '' = hors option
    option: str = ""

    def weight(
        self, polarity: str = "autre", share_melee: float = 1.0, start_round: int = 1, turn_side: Optional[str] = None
    ) -> float:
        """Couverture sur la frise (polarité 'off'/'def') × P(déclenchement). `turn_side` remplace celui de
        l'aptitude (« a chargé » → mon tour seulement)."""
        spends = self.uses_resource or SPENDS_RESOURCE in self.spec.requires or RESOURCE_SCALED in self.spec.requires
        return (
            coverage(
                self.frequency,
                self.spec.duration,
                self.available_round,
                spends,
                turn_side or self.turn_side,
                polarity,
                share_melee,
                start_round,
                self.resource_usage,
            )
            * self.activation_prob
        )

    def full(self, share_melee: float = 1.0) -> bool:
        """Actif sur toute la partie, en attaque comme en défense : appliqué directement au profil."""
        return self.weight("off", share_melee) >= 0.999 and self.weight("def", share_melee) >= 0.999

    @property
    def conditional(self) -> bool:
        # Un bonus « Charge (+N) » n'existe que si quelqu'un a chargé (nous, ou l'ennemi pour un
        # anti-charge) : conditionnel par nature, même quand le texte ne l'écrit pas comme prérequis.
        conds = [c for c in self.spec.conditions.split(" | ") if c and c not in (SPENDS_RESOURCE, RESOURCE_SCALED)]
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
    probe = probe_for_effect(EffectSpec("none"))
    mods = CombatModifiers()
    return plan_offense(unit, probe, mods, plan), unit_durability(unit)


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

    def weighted(
        pool: list[OwnEffect],
        factors: Optional[list[float]] = None,
        starts: Optional[list[int]] = None,
        sides: Optional[list[Optional[str]]] = None,
    ) -> tuple[float, float]:
        d_off = d_def = 0.0
        for k, e in enumerate(pool):
            f = factors[k] if factors is not None else 1.0
            if f <= 0:
                continue
            st = starts[k] if starts is not None else 1
            ts = sides[k] if sides is not None else None
            mods = CombatModifiers(attacker_charged="a chargé" in e.spec.requires or e.spec.kind == "charge_bonus")
            probe = probe_for_effect(e.spec)
            after = apply_effect(boosted, e.spec, probe, mods)
            if after is None:
                continue
            d_off += (
                f
                * e.weight("off", sm, st, ts)
                * (plan_offense(after, probe, mods, plan) - plan_offense(boosted, probe, mods, plan))
            )
            d_def += f * e.weight("def", sm, st, ts) * (unit_durability(after) - def_b)
        return d_off, d_def

    rest = [e for e in effects if not e.conditional and not e.full(sm)]
    cond = [e for e in effects if e.conditional]
    r_off, r_def = weighted(rest)
    c_off, c_def = weighted(cond)
    fit, starts, sides = [], [], []
    for e in cond:
        t = trigger(
            unit, e.spec.requires, e.spec.conditions, sm, melee_effect=e.spec.weapon_scope == "melee", kind=e.spec.kind
        )
        fit.append(t.p if t.bearer_only else 0.0)
        starts.append(t.start)
        sides.append("yours" if t.charged else None)  # « a chargé » : le combat de MON tour
    f_off, f_def = weighted(cond, fit, starts, sides)
    return Realized(
        off_chassis=off0,
        def_chassis=def0,
        off_realized=off_b + r_off,
        def_realized=def_b + r_def,
        off_good_case=off_b + r_off + c_off,
        def_good_case=def_b + r_def + c_def,
        n_effects=len(effects),
        n_conditional=len(cond),
        off_fit=off_b + r_off + f_off,
        def_fit=def_b + r_def + f_def,
    )


def own_effects(con) -> dict[tuple[str, str], list[tuple[str, str, bool, str, OwnEffect]]]:
    """Effets amis traduisibles des aptitudes de charte, par (faction, charte en minuscules).

    Chaque entrée : (portée, restriction de cible amie, exclut le porteur, nom, effet)."""
    rows = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.name, a.scope,
                  coalesce(e.friendly_target, a.friendly_target), a.excludes_self,
                  a.frequency, a.activation_prob, a.available_round,
                  FALSE, a.turn_side, a.resource_usage,
                  e.kind, e.stat, e.value, e.detail, e.side, e.weapon_scope, e.weapon_name, e.includes_companion,
                  e.target_keywords, e.target_condition, e.requires, e.duration, coalesce(e.option_group, '')
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           JOIN ability_effect e ON e.ability_uid = a.uid
           WHERE o.owner_kind = 'warscroll' AND e.side = 'friendly'
             AND a.source_kind NOT IN ('manifestation')"""
    ).fetchall()
    out: dict[tuple[str, str], list] = {}
    for (
        fac,
        owner,
        name,
        scope,
        ftarget,
        excl,
        freq,
        prob,
        avail,
        resource,
        tside,
        usage,
        kind,
        stat,
        value,
        detail,
        side,
        wscope,
        wname,
        comp,
        tkw,
        tcond,
        req,
        dur,
        option,
    ) in rows:
        spec = EffectSpec(
            kind=kind,
            stat=stat or "",
            value=value or 0.0,
            detail=detail or "",
            side=side or "",
            weapon_scope=wscope or "",
            weapon_name=wname or "",
            includes_companion=bool(comp),
            target_keywords=tkw or "",
            target_condition=tcond or "",
            requires=req or "",
            duration=dur or "",
        )
        if not is_translatable(spec):
            continue
        out.setdefault((fac, owner), []).append(
            (
                scope,
                ftarget or "",
                bool(excl),
                name,
                OwnEffect(
                    ability=name,
                    spec=spec,
                    frequency=freq or "",
                    activation_prob=prob if prob is not None else 1.0,
                    available_round=avail,
                    uses_resource=bool(resource),
                    turn_side=tside or "any",
                    resource_usage=usage,
                    option=option,
                ),
            )
        )
    return out


def applicable(unit: Unit, entries: list, vocab: frozenset[str]) -> list[OwnEffect]:
    """Effets qui tombent sur l'unité elle-même : `self`, ou portée amie dont elle est cible éligible."""
    keep = []
    for scope, ftarget, excl, _name, eff in entries:
        if scope == "self" or (scope in FRIENDLY_SCOPES and not excl and matches_friendly_target(unit, ftarget, vocab)):
            keep.append(eff)
    return strongest_alternatives(keep)


def strongest_alternatives(effects: list[OwnEffect]) -> list[OwnEffect]:
    """Dans une même aptitude, des effets de même nature sont des paliers ou des options
    (« +1 Damage … +2 instead ») : on garde le plus fort, on ne les additionne pas. Options exclusives
    (`OwnEffect.option`, analyseur v33 : runes de Master of the Runes) : une seule option par aptitude, celle
    qui porte le plus d'effets traduisibles (la première à égalité) — approximation, pas une mesure."""
    by_ability: dict[str, dict[str, int]] = {}
    for e in effects:
        if e.option:
            opts = by_ability.setdefault(e.ability, {})
            opts[e.option] = opts.get(e.option, 0) + 1
    chosen = {a: max(opts, key=lambda o: opts[o]) for a, opts in by_ability.items()}
    effects = [e for e in effects if not e.option or chosen.get(e.ability) == e.option]
    best: dict[tuple, OwnEffect] = {}
    for e in effects:
        s = e.spec
        key = (e.ability, s.kind, s.stat, s.weapon_scope, s.weapon_name)
        cur = best.get(key)
        stronger = cur is None or (s.value < cur.spec.value if s.kind == "ward" else s.value > cur.spec.value)
        if stronger:
            best[key] = e
    return list(best.values())


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
              AND e.kind IN ({", ".join("?" * len(MOBILITY_KINDS))})""",
        sorted(MOBILITY_KINDS),
    ).fetchall()
    out: dict[tuple[str, str], list] = {}
    for fac, owner, scope, ftarget, excl, kind, stat, value, prob, freq in rows:
        out.setdefault((fac, owner), []).append(
            (
                scope,
                ftarget or "",
                bool(excl),
                (kind, stat or "", value or 0.0, prob if prob is not None else 1.0, freq or ""),
            )
        )
    return out


def unit_mobility_effects(unit: Unit, entries: list, vocab: frozenset[str]) -> list[tuple]:
    """Effets de mouvement qui tombent sur l'unité elle-même (`self`, ou portée amie dont elle est cible)."""
    return [
        eff
        for scope, ftarget, excl, eff in entries
        if scope == "self" or (scope in FRIENDLY_SCOPES and not excl and matches_friendly_target(unit, ftarget, vocab))
    ]


_ACTION_SCOPES = ("one_enemy", "one_friendly", "friendly_aura", "enemy_aura")
_CHANNEL_OF_COST = {"Spell": "sort", "Prayer": "prière", "Command": "ordre"}


def _channel(cost_type: Optional[str], scope: str) -> str:
    return _CHANNEL_OF_COST.get(cost_type or "", "aura" if scope.endswith("aura") else "ciblage")


def action_abilities(con) -> tuple[dict[tuple[str, str], list[tuple]], dict[tuple[str, str], tuple]]:
    """Portées d'action des aptitudes non anecdotiques (`mobility.action_reach`).

    Renvoie (par (faction, charte en minuscules) : [(canal, portée, probabilité)], par (faction, « sort » ou
    « prière ») : (portée médiane, probabilité médiane) des domaines de la faction, pour ses sorciers et
    prêtres — un lanceur a toujours un domaine à la composition)."""
    scopes = ", ".join(f"'{s}'" for s in _ACTION_SCOPES)
    rows = con.execute(
        f"""SELECT o.faction_name, lower(o.owner_name), a.cost_type, a.scope, a.range_inches,
                   coalesce(a.activation_prob, 1.0)
            FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
            WHERE o.owner_kind = 'warscroll' AND a.source_kind = 'warscroll'
              AND a.range_inches > 0 AND a.scope IN ({scopes}) AND a.verdict <> 'anecdotique'"""
    ).fetchall()
    own: dict[tuple[str, str], list[tuple]] = {}
    for fac, owner, cost, scope, rng, prob in rows:
        own.setdefault((fac, owner), []).append((_channel(cost, scope), float(rng), prob))
    lore_rows = con.execute(
        """SELECT o.faction_name, a.cost_type, median(a.range_inches), median(coalesce(a.activation_prob, 1.0))
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           WHERE o.owner_kind = 'faction_rule' AND a.source_kind IN ('spell', 'prayer', 'manifestation')
             AND a.cost_type IN ('Spell', 'Prayer') AND a.range_inches > 0 AND a.verdict <> 'anecdotique'
             AND coalesce(o.origin_kind, 'base') = 'base'   -- pas les domaines d'armée de renom, Spearhead…
           GROUP BY 1, 2"""
    ).fetchall()
    lores = {(fac, _CHANNEL_OF_COST[cost]): (float(rng), float(prob)) for fac, cost, rng, prob in lore_rows}
    return own, lores


def unit_action_abilities(unit: Unit, faction: str, own: dict, lores: dict) -> list[tuple]:
    """Canaux d'aptitudes d'une unité : sa charte, plus le domaine de sa faction si elle est sorcier/prêtre."""
    out = list(own.get((faction, unit.name.lower()), []))
    for keyword, chan in (("WIZARD", "sort"), ("PRIEST", "prière")):
        if keyword in unit.keywords and (faction, chan) in lores:
            rng, prob = lores[(faction, chan)]
            out.append((chan, rng, prob))
    return out


def weapon_channels(unit: Unit) -> list[tuple[str, float, float]]:
    """(type, portée, part des dégâts de l'unité) par profil d'arme (sonde save 4+, porteurs répartis)."""
    from .chassis import weapon_damages

    dmg = weapon_damages(unit)
    total = sum(dmg)
    if total <= 0:
        return []
    return [(w.kind, float(w.range_in or 0), d / total) for w, d in zip(unit.weapons, dmg)]


#: --- Valeur de soutien des héros (portée d'action, variante B — utilisateur, 2026-11-21) --------------------
#: Un héros vaut aussi par ce qu'il donne : ses buffs de charte sur les **autres** unités amies s'ajoutent à
#: ses dégâts et à sa durabilité (étape 1 : buffs mesurés par la couche 3, `ability_encounter`, relation
#: « allié »). Hypothèses à challenger :
#: Nombre d'unités amies qui profitent du buff : ciblage 1, bulle ≤ 12" 2, bulle plus grande 3, armée 3.
SUPPORT_RECEIVERS = {"one_friendly": 1.0, "aura_small": 2.0, "aura_large": 3.0, "army": 3.0}
AURA_SMALL_IN = 12
#: Le joueur pose le buff sur un bon receveur, pas sur la médiane : quantile des gains parmi les receveurs.
SUPPORT_RECEIVER_QUANTILE = 0.75


def support_receivers(scope: str, range_in: Optional[float]) -> float:
    if scope == "friendly_aura":
        return SUPPORT_RECEIVERS["aura_small" if (range_in or 0) <= AURA_SMALL_IN else "aura_large"]
    return SUPPORT_RECEIVERS.get(scope, 0.0)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


@dataclass(frozen=True)
class Support:
    """Apport d'une aptitude de soutien d'un héros (gains bruts, déjà × couverture × receveurs)."""

    ability: str
    channel: str
    range_in: float
    off: float
    def_: float


def _best_option(gains: dict[tuple, tuple[float, float]]) -> tuple[float, float]:
    """(Δoff, Δdef) d'un receveur : effets hors option + la meilleure option exclusive (clé[0] = option, v33)."""
    base = [g for k, g in gains.items() if not k[0]]
    by_opt: dict[str, list[tuple[float, float]]] = {}
    for k, g in gains.items():
        if k[0]:
            by_opt.setdefault(k[0], []).append(g)
    best = max(by_opt.values(), key=lambda gs: sum(a + b for a, b in gs), default=[])
    return sum(g[0] for g in base + best), sum(g[1] for g in base + best)


def support_values(con, share_melee: dict[int, float]) -> dict[tuple[str, str], list[Support]]:
    """Buffs de charte donnés aux autres unités amies, par (faction, charte en minuscules).

    Par aptitude : par receveur, somme des effets (paliers d'un même type : le plus fort ; options exclusives :
    la meilleure) pondérés comme
    les effets propres (frise × P(déclenchement), sans les effets conditionnels) ; puis quantile
    `SUPPORT_RECEIVER_QUANTILE` des receveurs × `support_receivers`."""
    rows = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.name, a.scope, a.range_inches, a.cost_type,
                  a.frequency, coalesce(a.activation_prob, 1.0), a.available_round, a.turn_side, a.resource_usage,
                  e.kind, e.stat, e.weapon_scope, e.weapon_name, e.duration, coalesce(x.conditions, ''),
                  x.unit_id, x.off_after - x.off_before, x.def_after - x.def_before, coalesce(e.option_group, '')
           FROM ability_encounter x
           JOIN ability a ON a.uid = x.ability_uid
           JOIN ability_effect e ON e.ability_uid = x.ability_uid AND e.seq = x.seq
           JOIN ability_owner o ON o.ability_uid = a.uid AND o.owner_kind = 'warscroll'
           WHERE x.relation = 'allié' AND a.source_kind NOT IN ('manifestation')"""
    ).fetchall()
    resource = {SPENDS_RESOURCE, RESOURCE_SCALED}
    # (faction, charte, aptitude) -> meta, et receveur -> type d'effet -> meilleur (Δoff, Δdef)
    meta: dict[tuple, tuple] = {}
    gains: dict[tuple, dict[int, dict[tuple, tuple[float, float]]]] = {}
    for (
        fac,
        owner,
        name,
        scope,
        rng,
        cost,
        freq,
        prob,
        avail,
        tside,
        usage,
        kind,
        stat,
        wscope,
        wname,
        dur,
        conds,
        unit_id,
        d_off,
        d_def,
        option,
    ) in rows:
        tokens = {c for c in conds.split(" | ") if c}
        # combat enchaîné (Brawlerguts, Lead Da Brutes…) : compté, à la part `CHAINED_FIGHT_SHARE` (utilisateur)
        chained = CHAINED_FIGHT_SHARE if CHAINED in tokens else 1.0
        tokens.discard(CHAINED)
        if tokens - resource or kind == "charge_bonus":
            continue
        spends = bool(tokens & resource)
        sm = share_melee.get(unit_id, 1.0)
        args = (freq or "", dur or "", avail, spends, tside or "any")
        w_off = coverage(*args, polarity="off", share_melee=sm, resource_usage=usage) * prob * chained
        w_def = coverage(*args, polarity="def", share_melee=sm, resource_usage=usage) * prob * chained
        key = (fac, owner, name)
        meta[key] = (scope, rng, _channel(cost, scope or ""))
        per = gains.setdefault(key, {}).setdefault(unit_id, {})
        k = (option, kind, stat, wscope, wname)
        cur = per.get(k, (0.0, 0.0))
        g = (max(d_off or 0.0, 0.0) * w_off, max(d_def or 0.0, 0.0) * w_def)
        if g[0] + g[1] > cur[0] + cur[1]:
            per[k] = g
    out: dict[tuple[str, str], list[Support]] = {}
    for (fac, owner, name), by_unit in gains.items():
        scope, rng, chan = meta[(fac, owner, name)]
        # pas plus de receveurs que de chartes éligibles (« Stormvermin » : une seule)
        n = min(support_receivers(scope or "", rng), len(by_unit))
        if n <= 0:
            continue
        offs, defs = zip(*(_best_option(d) for d in by_unit.values()))
        off = n * _quantile(offs, SUPPORT_RECEIVER_QUANTILE)
        dfn = n * _quantile(defs, SUPPORT_RECEIVER_QUANTILE)
        if off > 0 or dfn > 0:
            out.setdefault((fac, owner), []).append(Support(name, chan, float(rng or 0), off, dfn))
    return out


def direct_damage(con) -> dict[tuple[str, str], list[tuple]]:
    """Aptitudes de charte qui infligent des blessures mortelles à l'ennemi (étape 2 de la variante B), par
    (faction, charte en minuscules) : [(aptitude, canal, portée, texte, portée d'aptitude, fréquence,
    P(déclenchement), round dispo, ressource, côté du tour, conditionnelle, facteur d'usage de la ressource)]. L'espérance se lit dans
    `mortals.mortal_pmf` (le montant de la couche 1 n'est pas fiable pour ces textes)."""
    rows = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.name, a.cost_type, a.scope, a.range_inches, a.effect_text,
                  a.frequency, coalesce(a.activation_prob, 1.0), a.available_round, a.turn_side, a.resource_usage,
                  string_agg(DISTINCT coalesce(e.requires, ''), ' | '), coalesce(a.conditions, '')
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           JOIN ability_effect e ON e.ability_uid = a.uid
           WHERE o.owner_kind = 'warscroll' AND a.source_kind = 'warscroll' AND a.verdict <> 'anecdotique'
             AND e.kind = 'mortal_damage' AND e.side = 'enemy'
           GROUP BY ALL"""
    ).fetchall()
    from .mortals import CHARGED_RE

    resource = {SPENDS_RESOURCE, RESOURCE_SCALED}
    out: dict[tuple[str, str], list[tuple]] = {}
    for fac, owner, name, cost, scope, rng, text, freq, prob, avail, tside, usage, reqs, aconds in rows:
        tokens = {r.strip() for r in (reqs or "").split("|") if r.strip()}
        setup = {c.strip() for c in aconds.split("|") if c.strip()}
        if "doit avoir chargé" in setup or CHARGED_RE.match(" ".join((text or "").split())):
            tokens.add("a chargé")
        tokens |= {c for c in setup if c in _INTERACTION_CONDITIONS}
        # « au combat » (Carve a Path…) : contrainte de jeu que l'unité remplit elle-même en mêlée, comme ses
        # armes de mêlée — sans condition (hypothèse à challenger)
        tokens.discard(IN_COMBAT)
        out.setdefault((fac, owner), []).append(
            (
                name,
                _channel(cost, scope or ""),
                float(rng or 0),
                text or "",
                scope or "",
                freq or "",
                prob,
                avail,
                bool(tokens & resource),
                tside or "any",
                " | ".join(sorted(tokens - resource)),
                usage,
            )
        )
    return out


#: Conditions de mise en place (couche 1, `ability.conditions`) qui sont des interactions — carte, adversaire,
#: pertes — et non une contrainte de jeu : elles sortent l'effet du chiffre réalisé, comme les autres conditions.
_INTERACTION_CONDITIONS = {
    "dépend d'une charge ennemie",
    "déclenché par une mort",
    "dépend d'un kill préalable",
    "doit avoir subi des dégâts",
    "position (objectif/territoire/décor)",
    "unité en réserve",
}


def unit_direct_damage(unit: Unit, entries: list, share_melee: float = 1.0) -> tuple[list[Support], float]:
    """Dégâts directs pondérés d'une unité : (effets sans condition — un `Support` côté dégâts, à la portée de
    l'aptitude —, apport « selon châssis » des effets qui demandent une charge, × P(ce châssis charge),
    `marriage.trigger`). Les autres conditions ne comptent pas, comme pour les effets propres."""
    from . import encounter
    from .mortals import enemy_targets, mean, mortal_pmf

    out: list[Support] = []
    fit = 0.0
    for name, chan, rng, text, scope, freq, prob, avail, spends, tside, conds, usage in entries:
        p_fit = 1.0
        if conds:
            if conds != "a chargé":
                continue
            p_fit = trigger(unit, "a chargé", "a chargé", share_melee, melee_effect=True).p
            tside = "yours"
        q = mortal_pmf(text, unit.models)
        if q is None:
            continue
        # lu au même plancher que les dégâts d'armes (`encounter.FLOOR_COVERAGE`) : une rafale aléatoire
        # (« D3, sur 2+ ») vaut moins que sa moyenne
        cov = encounter.FLOOR_COVERAGE
        e = mean(q) if cov is None else encounter.smooth_floor(q, cov)
        if e <= 0:
            continue
        w = coverage(freq, "", avail, spends, tside, "off", share_melee, resource_usage=usage) * prob
        if w <= 0:
            continue
        if conds:
            fit += p_fit * e * enemy_targets(scope) * w
        else:
            out.append(Support(name, chan, rng, e * enemy_targets(scope) * w, 0.0))
    return out, fit


def hero_mobility(
    own_off: float,
    own_def: float,
    own_factor: float,
    move_reach: float,
    supports: list[Support],
    median: float,
) -> float:
    """Facteur de portée d'un héros (variante B) : chaque canal pondéré par ce qu'il apporte.

    Sa valeur propre garde le facteur de la variante A (`own_factor` : son plus long canal significatif —
    tant que les sorts de domaine n'ont pas de valeur, leur portée reste lue ainsi) ; chaque soutien compte à
    la portée de son aptitude (déplacement + portée, contact → charge). Facteur = √(moyenne côté dégâts ×
    moyenne côté durabilité), comme l'indicateur combiné. Sans soutien : exactement la variante A."""
    from .mobility import CHARGE_IN, CONTACT_IN, RUN_IN, mobility_factor

    move = move_reach - RUN_IN

    def avg(parts: list[tuple[float, float]]) -> float:
        tot = sum(v for v, _f in parts)
        if tot <= 0:
            return own_factor
        return sum(v * f for v, f in parts) / tot

    sup = [
        (s, mobility_factor(move + (CHARGE_IN if s.range_in <= CONTACT_IN else s.range_in), median)) for s in supports
    ]
    f_off = avg([(own_off, own_factor)] + [(s.off, f) for s, f in sup])
    f_def = avg([(own_def, own_factor)] + [(s.def_, f) for s, f in sup])
    return (f_off * f_def) ** 0.5


def combined(off_per_100: float, def_per_100: float) -> float:
    """Indicateur combiné (validé par l'utilisateur, 2026-11-19) : moyenne géométrique des dégâts et de
    la durabilité pour 100 pts — logique de Lanchester, ce qu'une unité inflige sur sa durée de vie
    dépend des deux ; un canon de verre (gros dégâts, aucune durabilité) ne domine plus."""
    return (max(off_per_100, 0.0) * max(def_per_100, 0.0)) ** 0.5


def build_realized_rows(con) -> list[tuple]:
    """Tuples `persistence.analysis_tables.REALIZED_COLS` pour toutes les unités payantes."""
    from ...persistence import repository
    from .chassis import pct_rank

    units_by_army = repository.load_all_units_with_weapons(con)
    army_names = dict(con.execute("SELECT id, name FROM army").fetchall())
    units = [(army_names[aid], u) for aid, us in units_by_army.items() for u in us if u.points > 0]
    vocab = frozenset(k for _f, u in units for k in u.keywords)
    effects = own_effects(con)
    share_melee = dict(con.execute("SELECT unit_id, coalesce(share_melee, 1.0) FROM unit_chassis").fetchall())

    from .mobility import action_reach, median_reach, mobility_factor, reach

    moves = mobility_effects(con)
    own_actions, lores = action_abilities(con)
    supports = support_values(con, share_melee)
    directs = direct_damage(con)
    results = []
    reaches = []
    sups: list[list[Support]] = []
    dirs: list[list[Support]] = []
    dir_fit: list[float] = []
    actions: list[tuple[float, str]] = []
    for fac, u in units:
        effs = applicable(u, effects.get((fac, u.name.lower()), []), vocab)
        results.append((u, realize(u, effs, share_melee.get(u.id, 1.0)), sorted({e.ability for e in effs})))
        reaches.append(reach(u, unit_mobility_effects(u, moves.get((fac, u.name.lower()), []), vocab)))
        wch = weapon_channels(u)
        actions.append(action_reach(reaches[-1], wch, unit_action_abilities(u, fac, own_actions, lores)))
        sups.append(supports.get((fac, u.name.lower()), []) if u.is_hero else [])
        ds, dfit = unit_direct_damage(u, directs.get((fac, u.name.lower()), []), share_melee.get(u.id, 1.0))
        dirs.append(ds)
        dir_fit.append(dfit)
    # Le facteur du score lit la **portée d'action** (`reach_in` reste la portée de déplacement, lue par le mariage) :
    # troupes, variante A (le plus long canal significatif) ; héros, variante B (canaux pondérés par leur apport).
    med = median_reach([a for a, _c in actions]) if actions else 0.0
    mob = []
    for i, (a, _c) in enumerate(actions):
        u, r, _n = results[i]
        if u.is_hero:
            mob.append(
                hero_mobility(
                    r.off_realized, r.def_realized, mobility_factor(a, med), reaches[i], sups[i] + dirs[i], med
                )
            )
        else:
            mob.append(mobility_factor(a, med))
    direct = [sum(d.off for d in ds) for ds in dirs]
    # dégâts directs : propres à l'unité (troupes comprises), comptés avec le soutien dans le score
    sup_off = [sum(s.off for s in ss) + direct[i] for i, ss in enumerate(sups)]
    sup_def = [sum(s.def_ for s in ss) for ss in sups]

    rows: list[tuple] = []
    ranks: dict[int, tuple[float, float, float, float, float]] = {}
    for hero in (True, False):
        idx = [i for i, (u, _r, _a) in enumerate(results) if u.is_hero == hero]
        offs = [results[i][1].off_realized * 100 / results[i][0].points for i in idx]
        defs = [results[i][1].def_realized * 100 / results[i][0].points for i in idx]
        orank, drank = pct_rank(offs), pct_rank(defs)
        crank = pct_rank([combined(o, d) for o, d in zip(offs, defs)])
        frank = pct_rank(
            [
                combined(
                    results[i][1].off_fit * 100 / results[i][0].points,
                    results[i][1].def_fit * 100 / results[i][0].points,
                )
                for i in idx
            ]
        )
        srank = pct_rank(
            [
                combined(o + sup_off[i] * 100 / results[i][0].points, d + sup_def[i] * 100 / results[i][0].points)
                * mob[i]
                for i, o, d in zip(idx, offs, defs)
            ]
        )
        for k, i in enumerate(idx):
            ranks[i] = (orank[k], drank[k], crank[k], frank[k], srank[k])
    for i, (u, r, names) in enumerate(results):
        per = 100.0 / u.points
        rows.append(
            (
                u.id,
                round(r.off_chassis, 3),
                round(r.def_chassis, 2),
                round(r.off_realized, 3),
                round(r.def_realized, 2),
                round(r.off_good_case, 3),
                round(r.def_good_case, 2),
                round(r.off_realized * per, 3),
                round(r.def_realized * per, 3),
                round(r.off_good_case * per, 3),
                round(r.def_good_case * per, 3),
                ranks[i][0],
                ranks[i][1],
                r.n_effects,
                r.n_conditional,
                " | ".join(names) or None,
                round(combined(r.off_realized * per, r.def_realized * per), 3),
                ranks[i][2],
                round(r.off_fit, 3),
                round(r.def_fit, 2),
                round(r.off_fit * per, 3),
                round(r.def_fit * per, 3),
                round(combined(r.off_fit * per, r.def_fit * per), 3),
                ranks[i][3],
                round(reaches[i], 2),
                round(mob[i], 3),
                round(combined((r.off_realized + sup_off[i]) * per, (r.def_realized + sup_def[i]) * per) * mob[i], 3),
                ranks[i][4],
                round(
                    combined((r.off_fit + sup_off[i] + dir_fit[i]) * per, (r.def_fit + sup_def[i]) * per) * mob[i], 3
                ),
                round(actions[i][0], 2),
                actions[i][1],
                round(sup_off[i] - direct[i], 3),
                round(sup_def[i], 2),
                " | ".join(f"{s.ability} ({s.channel})" for s in sorted(sups[i], key=lambda s: -(s.off + s.def_)))
                or None,
                round(direct[i], 3),
                " | ".join(f"{d.ability} ({d.off:.2f})" for d in sorted(dirs[i], key=lambda d: -d.off)) or None,
            )
        )
    return rows

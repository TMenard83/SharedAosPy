"""Couche 4 — l'assaut : combien de charges réussissent quand plusieurs unités chargent ensemble.

Étalonnage sur l'analyse de Hibou_2 par l'utilisateur (2026-11-18, `Listes Melusior.md`) : un plan de
charges groupées tient par la **redondance** (« le nombre de tentatives compense la fiabilité de chacune »)
et par des **secours** (l'ordre de relance si les Cogs ratent), pas par la fiabilité d'une charge isolée.
La couche 3 ne le voit pas : elle juge une unité seule. Ici :

* **les chargeurs** : unités de la liste majoritairement au corps à corps (`share_melee` ≥ 0,5), copies
  comprises, hors machines de guerre ;
* **les sources** de la liste : bonus de charge (`ability_effect.stat = 'charge'`, valeur > 0) et relances
  des jets de charge (`reroll` charge, analyseur v25 ; cible amie par effet, v26, le texte en repli), plus l'ordre générique
  « En Avant, vers la Victoire » (1 PC, une charge relancée par tour, règles de base) ;
* **le nombre de dés** (`dice_count`, analyseur v28) : 3D6 additionnés, 3 dés en gardant les 2 meilleurs ;
* **la fiabilité d'une source posée par un allié** : une aptitude portée par une manifestation n'existe que
  si l'invocation passe (`summon_prob`, P du sort SUMMON) — la dissipation adverse n'est pas comptée ;
* **P(au moins k réussites sur N)**, calcul exact (énumération des issues), l'ordre relançant le chargeur
  raté qui a le plus de chances.

Hypothèses (à challenger) : tous les chargeurs sont dans les bulles des sources (point de chute groupé,
cf. la contrainte de placement relevée par l'utilisateur) ; distance de charge après téléportation =
`TELEPORT_GAP` (posé à plus de 9" : un jet de 9 suffit, la charge finit à ½"). La charge à pied n'est pas
un plan mais une punition des erreurs adverses (utilisateur) : elle est rendue en **portée de menace**
(`Threat`), pas en P(≥ k).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Optional, Sequence

from ...domain.models import Unit

#: Charge après une téléportation « à plus de 9" des ennemis » : un jet de 9 suffit.
TELEPORT_GAP = 9.0
#: Seuil de part de mêlée pour compter une unité parmi les chargeurs.
CHARGER_MELEE_SHARE = 0.5
#: Portée de menace : plus long jet de charge réussi au moins à cette probabilité.
THREAT_P = 0.5
#: Un chargeur du plan frappe au moins à cette part des dégâts de mêlée du meilleur frappeur de la liste.
CHARGER_DAMAGE_SHARE = 0.5
COMMAND_REROLL = "En Avant, vers la Victoire (ordre, 1 PC, une charge par tour)"

_REROLL_RE = re.compile(r"re-?\s?roll (?:the )?charge rolls?(?: for (?P<who>[^.:\n]*?))?(?= while|\.|,|:|\n|$)", re.I)
_ONCE_PER_BATTLE_OPTION_RE = re.compile(
    r"(?:same|each) effect more than once per battle|"
    r"more than once per battle",
    re.I,
)
#: « You cannot pick the same HERO to be the target of this ability more than once per battle » (Ironjawz
#: Waaagh!) : limite par cible, l'aptitude se rejoue à chaque tour sur un autre héros — pas 1×/bataille (Darkjawz).
_SAME_TARGET_LIMIT_RE = re.compile(
    r"[^.]*\bcannot pick the same [^.]*\bmore than once per battle[^.]*\.?", re.I
)
#: L'utilisateur doit avoir chargé pour activer l'aptitude (« Pick a friendly non-UNIQUE PARAGON that charged this
#: turn … to use this ability ») : son bonus de charge ne sert pas sa propre charge.
_USER_CHARGED_RE = re.compile(r"\bPick a friendly [^.]*?\bthat charged this turn\b[^.]*\bto use this ability\b")
_PER_BATTLE_FREQ = ("once_per_battle", "once_per_battle_army")
_BONUS_TARGET_RE = re.compile(
    r"add \d+ to (?:run and )?charge rolls for friendly ((?:[A-Z][A-Z'-]* )*[A-Z][A-Z'-]*)"
    r" units",
    re.I,
)


@dataclass(frozen=True)
class ChargeSource:
    name: str
    origin: str
    kind: str  # « bonus » | « relance » | « dés »
    value: float  # +N au jet (bonus) ; 0 pour une relance
    receivers: tuple[str, ...]  # noms d'unités de la liste
    p_present: float  # P(la source existe ce tour) : invocation d'une manifestation, sinon 1
    per_battle: bool  # un seul round dans la partie
    dice: str = ""  # mode de jet pour « dés » (`DICE_MODES`)
    #: groupe exclusif entre aptitudes (`listing.EXCLUSIVE_KEYWORDS`) : un seul Délire à la fois (Von glutten)
    group: str = ""
    #: ne sert qu'après une charge du porteur (« Pick a friendly PARAGON that charged this turn », Chief of
    #: Revels) : pas un bonus permanent de la charge elle-même (Aeorl, 2026-11-25)
    after_charge: bool = False


@dataclass(frozen=True)
class AssaultCase:
    label: str
    at_least: tuple[float, ...]  # P(≥1), P(≥2), P(≥3)…


@dataclass(frozen=True)
class AssaultScenario:
    label: str
    chargers: tuple[tuple[str, float, float], ...]  # (unité, P sec, P avec bonus permanents)
    cases: tuple[AssaultCase, ...]


@dataclass(frozen=True)
class Threat:
    """Portée de menace à pied d'un chargeur : mouvement + plus long jet de charge réussi à `THREAT_P`.

    Ce n'est pas un plan (une charge à pied réussit presque toujours une fois à portée), c'est une
    **punition des erreurs** adverses (remarque utilisateur, 2026-11-20) : la distance à partir de laquelle
    l'adversaire qui se place mal se fait charger. Cible pour le joueur : rester au-delà."""

    unit: str
    move: float
    dry: float  # sans bonus ni relance
    bonus: float  # bonus permanents de la liste
    reroll: float  # + relance (ordre ou Cogs)


@dataclass(frozen=True)
class Assault:
    sources: tuple[ChargeSource, ...]
    scenarios: tuple[AssaultScenario, ...]
    threats: tuple[Threat, ...] = ()


# ----- cœur pur ---------------------------------------------------------------------

#: Modes de jet de charge (analyseur v28-v29, `dice_count`) : 2D6 normal, 3D6 additionnés (« somme »),
#: 3 dés dont on garde les 2 meilleurs (« garder »), le plus bas des 2D6 aligné sur le plus haut (« max » :
#: 2 × le plus haut), 1D6 imposé. Leur classement dépend de la distance : on prend le meilleur à chaque jet.
DICE_MODES = ("3d6", "3k2", "max", "2d6", "1d6")
_DETAIL_MODE = {"somme": "3d6", "garder": "3k2", "max": "max"}


@lru_cache(maxsize=None)
def _p_dice_at_least(n: int, dice: str) -> float:
    k = {"3d6": 3, "3k2": 3, "max": 2, "2d6": 2, "1d6": 1}[dice]
    ok = total = 0
    for roll in product(range(1, 7), repeat=k):
        v = sum(sorted(roll)[1:]) if dice == "3k2" else 2 * max(roll) if dice == "max" else sum(roll)
        ok += v >= n
        total += 1
    return ok / total


def p_roll(need: float, bonus: float = 0.0, reroll: bool = False, dice="2d6") -> float:
    """P(jet + bonus ≥ need), relance d'un échec comprise (relance avant modificateurs : Core Rules p. 6) ;
    `dice` : un des `DICE_MODES`, ou plusieurs (le joueur choisit le meilleur pour cette distance)."""
    n = int(-(-(need - bonus) // 1))  # plafond
    modes = (dice,) if isinstance(dice, str) else tuple(dice) or ("2d6",)
    p = max(_p_dice_at_least(n, m) for m in modes) if n > 1 else 1.0
    return 1 - (1 - p) ** 2 if reroll else p


def at_least(ps: Sequence[float], k: int, command: bool = False, reroll_ps: Optional[Sequence[float]] = None) -> float:
    """P(au moins k succès) sur des tentatives indépendantes ; `command` : une relance du raté le plus
    prometteur (`reroll_ps[i]` = P de réussir la relance, par défaut `ps[i]`)."""
    n = len(ps)
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    rp = list(reroll_ps) if reroll_ps is not None else list(ps)
    total = 0.0
    for outcome in product((True, False), repeat=n):
        pr = 1.0
        for ok, p in zip(outcome, ps):
            pr *= p if ok else 1 - p
        if pr == 0:
            continue
        s = sum(outcome)
        if s >= k:
            total += pr
        elif command and s == k - 1:
            total += pr * max(rp[i] for i, ok in enumerate(outcome) if not ok)
    return total


def reroll_receivers(text: str, units: list[Unit], vocab: frozenset[str]) -> Optional[tuple[str, ...]]:
    """Receveurs d'une relance des jets de charge lue dans `text`, None si le texte n'en donne pas."""
    from .encounter import matches_friendly_target

    m = _REROLL_RE.search(text or "")
    if not m:
        return None
    who = (m.group("who") or "").strip()
    target = re.sub(r"(?i)^(?:friendly|this unit and )\s*", "", who)
    target = re.sub(r"(?i)\bunits?\b", "", target).strip()
    if not who or target.lower() in ("", "this", "it"):
        return tuple(u.name for u in units)
    return tuple(u.name for u in units if matches_friendly_target(u, target, vocab))


def charge_sources(
    abilities, units: list[Unit], vocab: frozenset[str], dead: frozenset[str] = frozenset()
) -> list[ChargeSource]:
    """Bonus (`stat_mod` charge > 0) et relances complètes (`reroll` charge, analyseur v25) de la liste.

    Receveurs : la cible amie de l'effet (v26), sinon celle que la phrase écrit (« for friendly X units »,
    « for friendly units » = toutes), sinon celle de l'aptitude. Une relance partielle (un dé) n'est pas comptée."""
    from .encounter import matches_friendly_target
    from .listing import effect_ability, list_receivers

    def recv_of(ab, e, text_recv) -> tuple[str, ...]:
        if e.friendly_target:
            return tuple(u.name for u, _r in list_receivers(effect_ability(ab, e.friendly_target), units, vocab))
        if text_recv is not None:
            return text_recv
        return tuple(u.name for u, _r in list_receivers(ab, units, vocab))

    out: list[ChargeSource] = []
    for ab in abilities:
        if ab.uid in dead:
            continue
        per_battle = ab.frequency in _PER_BATTLE_FREQ or bool(
            _ONCE_PER_BATTLE_OPTION_RE.search(_SAME_TARGET_LIMIT_RE.sub("", ab.text))
        )
        after = bool(_USER_CHARGED_RE.search(ab.text))
        p = ab.summon_prob * (ab.activation_prob if ab.summon_prob == 1.0 else 1.0)
        m = _BONUS_TARGET_RE.search(ab.text)
        bonus_text = (
            tuple(u.name for u in units if matches_friendly_target(u, m.group(1).strip(), vocab)) if m else None
        )
        for e in ab.effects:
            if e.stat != "charge" or e.side == "enemy":
                continue
            if e.kind == "stat_mod" and e.value > 0:
                recv = recv_of(ab, e, bonus_text)
                if recv:
                    out.append(
                        ChargeSource(
                            ab.name, ab.source, "bonus", e.value, recv, p, per_battle,
                            group=ab.exclusive_group, after_charge=after,
                        )
                    )
            elif e.kind == "dice_count" and e.value > 0:
                recv = recv_of(ab, e, bonus_text)
                if recv:
                    mode = _DETAIL_MODE.get(e.detail, "3d6")
                    out.append(ChargeSource(ab.name, ab.source, "dés", 0.0, recv, p, per_battle, mode))
            elif e.kind == "reroll" and e.value >= 1.0:
                recv = recv_of(ab, e, reroll_receivers(ab.text, units, vocab))
                if recv:
                    out.append(ChargeSource(ab.name, ab.source, "relance", 0.0, recv, p, per_battle))
    return out


def move_bonuses(
    abilities, units: list[Unit], vocab: frozenset[str], dead: frozenset[str] = frozenset()
) -> dict[str, float]:
    """+N" de Mouvement permanents reçus par chaque unité de la liste (Kurnothi War-horn, Aspect of Harvestboon :
    épées de Kurnoth à 10" au lieu de 6", Zoko 2026-11-25) — passifs sans jet, une valeur par aptitude (la plus
    forte), les aptitudes s'additionnent ; leurs conditions de position (bulle, invasion) sont supposées tenues,
    comme les bonus de charge."""
    from .listing import effect_ability, list_receivers

    out: dict[str, dict[tuple[str, str], float]] = {}
    for ab in abilities:
        if ab.uid in dead or ab.frequency != "passive" or ab.summon_prob < 1.0:
            continue
        for e in ab.effects:
            if e.kind != "stat_mod" or e.stat != "move" or e.value <= 0 or e.side == "enemy":
                continue
            for u, _r in list_receivers(effect_ability(ab, e.friendly_target), units, vocab):
                per = out.setdefault(u.name, {})
                per[(ab.name, ab.source)] = max(e.value, per.get((ab.name, ab.source), 0.0))
    return {n: sum(v.values()) for n, v in out.items()}


#: « set it up again within ½" of an enemy unit and wholly within X" of a terrain feature …, where X is equal to the
#: charge roll. If you do so, this unit has charged » (Merciless Ambush, Drycha) : la charge part du décor, pas d'un
#: point à plus de 9" — `AMBUSH_GAP` = distance du décor à la cible (hypothèse : un décor à pion près de la cible).
_AMBUSH_RE = re.compile(r"\bwhere X is equal to the charge roll\b[^.]*\.\s*If you do so, this unit has charged\b", re.I)
AMBUSH_GAP = 6.0


def ambushers(abilities) -> frozenset[str]:
    """Porteurs d'une charge-embuscade (`_AMBUSH_RE`)."""
    return frozenset(c for a in abilities if _AMBUSH_RE.search(a.text or "") for c in a.carriers)


def chargers(units: list[Unit], share_melee: dict[str, float], melee_dmg: dict[str, float]) -> list[Unit]:
    """Les frappeurs de la liste : majoritairement au corps à corps, hors machines de guerre, et au moins
    `CHARGER_DAMAGE_SHARE` des dégâts de mêlée du meilleur d'entre eux (les autres chargent par opportunité)."""
    melee = [
        u
        for u in units
        if share_melee.get(u.name, 1.0) >= CHARGER_MELEE_SHARE
        and "WAR MACHINE" not in u.keywords
        and any(w.kind == "melee" for w in u.weapons)
    ]
    if not melee_dmg:
        return melee
    best = max((melee_dmg.get(u.name, 0.0) for u in melee), default=0.0)
    return [u for u in melee if melee_dmg.get(u.name, 0.0) >= CHARGER_DAMAGE_SHARE * best]


def _usable(s: ChargeSource, u: Unit, per_battle: bool) -> bool:
    return (
        u.name in s.receivers
        and s.p_present >= 1.0
        and not s.after_charge
        and (per_battle or not s.per_battle)
    )


def _bonus(u: Unit, sources: Sequence[ChargeSource], per_battle: bool) -> float:
    """Somme des bonus de charge de `u` : paliers d'une même aptitude non cumulés (« Add 2 … instead », Defenders
    of the Kingdom : le plus fort), une seule aptitude par groupe exclusif (un Délire à la fois) — 2026-11-25."""
    by_ab: dict[tuple[str, str], tuple[str, float]] = {}
    for s in sources:
        if s.kind == "bonus" and _usable(s, u, per_battle):
            k = (s.name, s.origin)
            by_ab[k] = (s.group, max(s.value, by_ab.get(k, ("", 0.0))[1]))
    plain = sum(v for g, v in by_ab.values() if not g)
    groups: dict[str, float] = {}
    for g, v in by_ab.values():
        if g:
            groups[g] = max(groups.get(g, 0.0), v)
    return plain + sum(groups.values())


def _dice(u: Unit, sources: Sequence[ChargeSource], per_battle: bool) -> tuple[str, ...]:
    """Modes de jet disponibles en permanence (ou ce round-là, `per_battle`) pour `u`, 2D6 compris."""
    modes = {s.dice for s in sources if s.kind == "dés" and _usable(s, u, per_battle)}
    return tuple(m for m in DICE_MODES if m in modes | {"2d6"})


def scenario(
    label: str,
    units: list[Unit],
    need,
    sources: Sequence[ChargeSource],
    k_max: int = 3,
    p_arrive: Optional[float] = None,
) -> AssaultScenario:
    """`need(u)` : jet de charge nécessaire pour l'unité `u` ; `p_arrive` : P que le chargeur arrive (sort de
    téléportation réussi, chacun le sien, sans 2e tentative) — ajoute une ligne « téléportation comprise »."""
    ks = range(1, min(k_max, len(units)) + 1)
    sec = [p_roll(need(u)) for u in units]
    bon = [p_roll(need(u), _bonus(u, sources, False), dice=_dice(u, sources, False)) for u in units]
    cases = [
        AssaultCase("sec", tuple(at_least(sec, k) for k in ks)),
        AssaultCase("bonus permanents", tuple(at_least(bon, k) for k in ks)),
        AssaultCase(f"+ {COMMAND_REROLL.split(' (')[0]} (1 PC)", tuple(at_least(bon, k, True) for k in ks)),
    ]
    for s in (x for x in sources if x.kind == "relance"):
        rr = [
            p_roll(need(u), _bonus(u, sources, False), u.name in s.receivers, _dice(u, sources, False)) for u in units
        ]
        with_src = [at_least(rr, k, True, bon) for k in ks]
        cases.append(AssaultCase(f"+ {s.name} (si en jeu) + ordre", tuple(with_src)))
        if s.p_present < 1.0:
            fallback = [at_least(bon, k, True) for k in ks]
            cases.append(
                AssaultCase(
                    f"attendu : {s.name} à {s.p_present:.0%}, sinon l'ordre",
                    tuple(s.p_present * a + (1 - s.p_present) * b for a, b in zip(with_src, fallback)),
                )
            )
            if p_arrive is not None and p_arrive < 1.0:
                pa = p_arrive
                a2 = [at_least([pa * x for x in rr], k, True, [pa * x for x in bon]) for k in ks]
                b2 = [at_least([pa * x for x in bon], k, True) for k in ks]
                cases.append(
                    AssaultCase(
                        f"idem, téléportation comprise (saut réussi à {pa:.0%})",
                        tuple(s.p_present * a + (1 - s.p_present) * b for a, b in zip(a2, b2)),
                    )
                )
    if any(s.per_battle and s.kind in ("bonus", "dés") for s in sources):
        pb = [p_roll(need(u), _bonus(u, sources, True), dice=_dice(u, sources, True)) for u in units]
        cases.append(
            AssaultCase(
                "round des bonus 1×/bataille (sans relance de source)", tuple(at_least(pb, k, True) for k in ks)
            )
        )
    return AssaultScenario(
        label, tuple((u.name, round(a, 3), round(b, 3)) for u, a, b in zip(units, sec, bon)), tuple(cases)
    )


def assault(
    abilities,
    units: list[Unit],
    vocab: frozenset[str],
    share_melee: dict[str, float],
    teleporters: frozenset[str],
    dead: frozenset[str] = frozenset(),
    melee_dmg: Optional[dict[str, float]] = None,
) -> Optional[Assault]:
    """`units` : la liste, copies comprises ; `teleporters` : noms des unités qui peuvent se téléporter ;
    `melee_dmg` : dégâts de mêlée par round (`unit_chassis.dmg_melee`) pour retenir les frappeurs."""
    from .marriage import reach

    distinct = list({u.name: u for u in units}.values())
    srcs = charge_sources(abilities, distinct, vocab, dead)
    ch = chargers(units, share_melee, melee_dmg or {})
    if len(ch) < 2:
        return None
    scen = []
    tp = [u for u in ch if u.name in teleporters]
    if len(tp) >= 2:
        # P du saut : le sort de téléportation le plus sûr de la liste (une aptitude propre, sans jet, vaut 1)
        tp_spells = [
            a.activation_prob
            for a in abilities
            if a.uid not in dead
            and (a.cost_type or "").lower() == "spell"
            and any(e.kind in ("deep_strike", "redeploy") for e in a.effects)
        ]
        p_tp = max(tp_spells) if tp_spells else None
        amb = ambushers(abilities)
        label = f'après téléportation (posés à plus de {TELEPORT_GAP:g}")'
        if any(u.name in amb for u in tp):
            label += f' ; embuscade : {AMBUSH_GAP:g}" depuis le décor'
        scen.append(
            scenario(
                label,
                tp,
                lambda u: AMBUSH_GAP if u.name in amb else TELEPORT_GAP,
                srcs,
                p_arrive=p_tp,
            )
        )
    mv = move_bonuses(abilities, distinct, vocab, dead)

    def move(u: Unit) -> float:
        return reach(u) + mv.get(u.name, 0.0)

    threats = tuple(
        Threat(
            u.name,
            move(u),
            move(u) + longest_charge(0.0, False),
            move(u) + longest_charge(_bonus(u, srcs, False), False, dice=_dice(u, srcs, False)),
            move(u) + longest_charge(_bonus(u, srcs, False), True, dice=_dice(u, srcs, False)),
        )
        for u in {x.name: x for x in ch}.values()
    )
    return Assault(tuple(srcs), tuple(scen), threats)


def longest_charge(bonus: float, reroll: bool, p: float = THREAT_P, dice: str = "2d6") -> float:
    """Plus longue distance de charge (pouces) réussie au moins avec la probabilité `p`."""
    return max((d for d in range(2, 24) if p_roll(d, bonus, reroll, dice) >= p), default=0)

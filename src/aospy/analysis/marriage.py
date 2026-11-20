"""Couche 3 — qualité du mariage châssis × aptitude : le châssis déclenche-t-il l'effet, le fait-il durer ?

Recadrage utilisateur (2026-11-20, mémoire `ability-marriage-quality`) : une bonne aptitude peut être mal
mariée (Oath of Supremacy sur la Darkoath Warqueen : 5" de mouvement, 5 PV — « si ça se met en place c'est
cool, mais ça n'arrive jamais »). Deux facteurs s'ajoutent à l'amplification déjà mesurée par
`encounter.py` :

* **D — déclenchement** : probabilité que le châssis remplisse une condition qui pèse sur **le porteur**
  (« a chargé », « en territoire », « sur objectif », « au combat », « sans mouvement »), et round où il le
  peut au plus tôt. Les conditions tenues par un allié (« près d'une unité amie », couche 4), par
  l'adversaire (« vs HERO », « cible ≥10 figurines », « charge ennemie » : matchups) ou par une ressource
  restent dans la colonne « bon cas » — partage validé par l'utilisateur ;
* **S — survie** : part des rounds pendant lesquels le porteur reste en vie pour tenir l'effet (bulle,
  aura), selon l'exposition qu'impose la portée — au contact (≤ 3"), courte (≤ 9"), longue (≥ 10",
  le porteur reste derrière un écran) — et les dégâts qu'il subit d'une unité ennemie moyenne
  (`unit_benchmark`, réparti mêlée/tir selon le profil de l'attaquant, `unit_chassis.share_melee`).

**Toutes les constantes ci-dessous sont des hypothèses de travail à challenger** (règle utilisateur :
signaler les classements contre-intuitifs et proposer de les réviser).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..domain.models import Unit

#: Distance moyenne à couvrir (mouvement + charge) au tour où l'unité charge. 14" : une charge à 9"
#: après un mouvement de 5" est un pari (mémoire `charge-9-is-a-gamble`), à 4" après 10" quasi sûre.
ENGAGE_GAP = 14.0
#: Distance à parcourir depuis le déploiement pour finir ENTIÈREMENT en territoire ennemi (hypothèse à
#: vérifier sur les plans de bataille du MdG 2026-27 : no man's land + emprise de l'unité).
TERRITORY_GAP = 15.0
#: Bonus de distance effectif du vol (ignore décors et écrans).
FLY_BONUS = 2.0
RUN_MEAN = 3.5
CHARGE_MEAN = 7.0

#: Conditions tenues par le porteur → probabilité estimée d'après le châssis. Les autres libellés
#: (`perimeter._REQUIRES` / `_TARGET_CONDITIONS`) ne dépendent pas de lui.
BEARER_CONDITIONS = ("a chargé", "en territoire", "sur objectif", "au combat", "sans mouvement", "sans charge")
#: Sans charge ce tour : part des combats d'une unité de mêlée hors de son tour de charge (combat
#: prolongé, tour adverse) ; un tireur qui ne charge pas l'est presque toujours.
P_NOT_CHARGED_MELEE, P_NOT_CHARGED_SHOOTER = 0.6, 0.9
#: Sur objectif : une troupe (≥ 3 figurines) tient un objectif par nature, un héros seul beaucoup moins.
P_OBJECTIVE_TROOP, P_OBJECTIVE_HERO = 0.75, 0.4
#: Au combat (effet non offensif de mêlée) : unité de mêlée / de tir.
P_IN_COMBAT_MELEE, P_IN_COMBAT_SHOOTER = 0.8, 0.3
#: Sans mouvement : un tireur reste volontiers immobile, une unité de mêlée rarement.
P_STILL_SHOOTER, P_STILL_MELEE = 0.6, 0.2

#: Exposition (part des dégâts de mêlée / de tir d'une unité ennemie moyenne subis par round).
EXPOSURE = {
    "contact": (1.0, 1.0),
    "courte": (0.5, 1.0),
    "longue": (0.15, 0.6),   # derrière un écran : chargé rarement, visé seulement si visible
}

ROUND_WEIGHTS = (1 / 3, 1.0, 1.0, 1 / 3, 1 / 3)


def p_2d6_at_least(n: float) -> float:
    n = int(-(-n // 1))   # plafond
    if n <= 2:
        return 1.0
    if n > 12:
        return 0.0
    return sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= n) / 36.0


def reach(unit: Unit) -> float:
    return unit.move + (FLY_BONUS if "FLY" in unit.keywords else 0.0)


def p_charge(unit: Unit) -> float:
    """P(réussir la charge) au tour où l'unité veut charger : 2D6 ≥ ENGAGE_GAP − mouvement."""
    return p_2d6_at_least(ENGAGE_GAP - reach(unit))


def territory_round(unit: Unit, with_charge: bool) -> int:
    """Premier round où l'unité peut finir entièrement en territoire ennemi (après charge si exigée)."""
    step = reach(unit) + RUN_MEAN
    last = reach(unit) + (CHARGE_MEAN if with_charge else RUN_MEAN)
    for r in range(1, 6):
        if (r - 1) * step + last >= TERRITORY_GAP:
            return r
    return 6


@dataclass(frozen=True)
class Trigger:
    """Facteur D : probabilité de remplir les conditions du porteur, à partir du round `start`."""

    p: float
    start: int = 1
    bearer_only: bool = True   # False : une condition ne dépend pas du porteur (reste « bon cas »)


def trigger(unit: Unit, requires: str, conditions: str, share_melee: float, melee_effect: bool,
            kind: str = "") -> Trigger:
    """D pour un effet : `requires` = prérequis de l'effet, `conditions` = toutes ses conditions.

    Un « Charge (+N) » (`kind == "charge_bonus"`) n'existe que si l'unité a chargé, même sans
    prérequis écrit."""
    conds = [c for c in conditions.split(" | ") if c]
    if kind == "charge_bonus" and "a chargé" not in conds and "charge ennemie" not in conds:
        conds.append("a chargé")
    others = [c for c in conds if c not in BEARER_CONDITIONS]
    p, start = 1.0, 1
    charged = "a chargé" in conds
    melee_unit = share_melee >= 0.5
    for c in conds:
        if c == "a chargé":
            p *= p_charge(unit)
        elif c == "en territoire":
            start = max(start, territory_round(unit, with_charge=charged))
        elif c == "sur objectif":
            p *= P_OBJECTIVE_HERO if unit.is_hero or unit.models < 3 else P_OBJECTIVE_TROOP
        elif c == "au combat":
            if not (melee_effect or charged):   # un buff de mêlée ne joue de toute façon qu'au combat
                p *= P_IN_COMBAT_MELEE if melee_unit else P_IN_COMBAT_SHOOTER
        elif c == "sans charge":
            p *= P_NOT_CHARGED_MELEE if melee_unit else P_NOT_CHARGED_SHOOTER
        elif c == "sans mouvement":
            p *= P_STILL_MELEE if melee_unit else P_STILL_SHOOTER
    return Trigger(p=p, start=start, bearer_only=not others)


def exposure_of(scope: str, range_inches: Optional[int], requires: str, family: str) -> str:
    """Exposition imposée au porteur pour tenir l'effet."""
    if "au combat" in requires or "a chargé" in requires:
        return "contact"
    if range_inches is None:
        return "contact" if family == "debuff" else "longue"
    if range_inches <= 3:
        return "contact"
    return "courte" if range_inches <= 9 else "longue"


def rounds_alive(hp_total: float, melee_in: float, ranged_in: float, exposure: str) -> float:
    """Rounds de survie attendus face à UNE unité ennemie moyenne, à cette exposition."""
    km, kr = EXPOSURE[exposure]
    dmg = km * melee_in + kr * ranged_in
    return hp_total / dmg if dmg > 0 else 5.0


def survival_coverage(alive: float, start: int = 1, lasting: bool = True) -> float:
    """S : part (pondérée par round) des rounds `start`..5 où le porteur tient encore l'effet.

    Survie linéaire : en vie à 100 % pendant `alive` rounds après le déclenchement, puis 0 (fraction au
    dernier round). Effet court (`lasting=False`) : seul le round de déclenchement compte."""
    rounds = range(start, 6) if lasting else range(start, min(start + 1, 6))
    nominal = sum(ROUND_WEIGHTS[r - 1] for r in rounds)
    if nominal == 0:
        return 0.0
    held = sum(ROUND_WEIGHTS[r - 1] * max(0.0, min(1.0, alive - (r - start))) for r in rounds)
    return held / nominal


def incoming_damage(con) -> dict[int, tuple[float, float]]:
    """unit_id → (dégâts de mêlée, dégâts de tir) subis par round d'une unité ennemie moyenne.

    `unit_benchmark.raw_b_to_a` = riposte du défenseur, lue à la moyenne (`defender_mode='mean'`),
    après sauvegarde/protection de l'unité ; répartie selon `unit_chassis.share_melee` du défenseur."""
    rows = con.execute(
        """SELECT b.attacker_id,
                  avg(b.raw_b_to_a * coalesce(c.share_melee, 1.0)),
                  avg(b.raw_b_to_a * (1 - coalesce(c.share_melee, 1.0)))
           FROM unit_benchmark b JOIN unit_chassis c ON c.unit_id = b.defender_id
           WHERE b.defender_mode = 'mean' AND b.attacker_mode = 'floor66'
             AND NOT b.attacker_reinforced AND NOT b.defender_reinforced
             AND NOT b.attacker_charged AND NOT b.defender_charged
           GROUP BY b.attacker_id"""
    ).fetchall()
    out = {uid: (m or 0.0, r or 0.0) for uid, m, r in rows}
    # Unités absentes du benchmark (héros hors `--include-heroes`, Scourge of Aqshy…) : estimées depuis
    # leurs PV effectifs (`unit_chassis.effective_wounds`, coups à porter) — dégâts subis ≈ PV × C / coups,
    # C et la part de mêlée étant les médianes des unités mesurées. Sans ça, l'absence de données passait
    # pour une immortalité (5 rounds de survie).
    chassis = con.execute("SELECT unit_id, health * models, effective_wounds FROM unit_chassis").fetchall()
    ratios, melee_shares = [], []
    for uid, hp, ew in chassis:
        if uid in out and hp and ew:
            m, r = out[uid]
            if m + r > 0:
                ratios.append((m + r) * ew / hp)
                melee_shares.append(m / (m + r))
    if ratios:
        c_hits = sorted(ratios)[len(ratios) // 2]
        sm = sorted(melee_shares)[len(melee_shares) // 2]
        for uid, hp, ew in chassis:
            if uid not in out and hp and ew:
                tot = hp * c_hits / ew
                out[uid] = (tot * sm, tot * (1 - sm))
    return out


# ----- table du mariage (aptitude de charte × porteur) ---------------------------------------------

#: « conditionnelle » (v19, effet d'état « While … ») : tient tant que l'état dure, donc tant que le porteur vit.
_LASTING_DURATIONS = {"bataille", "permanent", "conditionnelle"}
_LASTING_FREQUENCIES = {"passive"}

MARRIAGE_COLS = (
    "unit_id", "ability_uid", "ability_name", "family", "power", "verdict", "exposure", "p_trigger",
    "start_round", "bearer_only", "rounds_alive", "survival", "marriage", "good_case_conditions",
)


def _lasting(frequency: str, durations: set[str]) -> bool:
    """Le porteur doit-il rester en vie sur plusieurs rounds pour que l'aptitude rapporte ?

    Oui pour un passif, un effet durable, ET une aptitude réutilisable (chaque tour/phase) : il faut être
    vivant pour la rejouer. Non seulement pour une fois par bataille à effet court (joué au kairos)."""
    once = (frequency or "").startswith("once_per_battle")
    return not once or (frequency or "") in _LASTING_FREQUENCIES or bool(durations & _LASTING_DURATIONS)


def build_marriage_rows(con) -> list[tuple]:
    """Tuples `MARRIAGE_COLS` : chaque aptitude de charte jugée sur le châssis de chacun de ses porteurs.

    mariage = D (P(conditions du porteur) × part des rounds encore possibles) × S (rounds tenus / rounds
    nominaux). Les conditions tenues par d'autres (allié, adversaire, ressource) ne sont pas chiffrées :
    elles sont listées (`good_case_conditions`) et relèvent de la couche 4 / des matchups."""
    from ..persistence import repository
    from .realized import _start_share

    units = {(army, u.name.lower()): u
             for army, us in ((a, us) for a, us in _units_by_army_name(con, repository).items())
             for u in us if u.points > 0}
    chassis = {uid: (sm if sm is not None else 1.0)
               for uid, sm in con.execute("SELECT unit_id, share_melee FROM unit_chassis").fetchall()}
    incoming = incoming_damage(con)

    abil = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.uid, a.name, a.family, a.power, a.verdict, a.scope,
                  a.range_inches, a.frequency
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           WHERE o.owner_kind = 'warscroll' AND a.source_kind NOT IN ('manifestation')"""
    ).fetchall()
    effs: dict[str, list[tuple]] = {}
    for uid, kind, req, tcond, tkw, dur, wscope in con.execute(
            "SELECT ability_uid, kind, requires, target_condition, target_keywords, duration, weapon_scope "
            "FROM ability_effect").fetchall():
        effs.setdefault(uid, []).append((kind, req or "", tcond or "", tkw or "", dur or "", wscope or ""))

    rows: list[tuple] = []
    seen: set[tuple[int, str]] = set()
    for fac, owner, uid, name, family, power, verdict, scope, rng, freq in abil:
        u = units.get((fac, owner))
        if u is None or (u.id, uid) in seen:
            continue
        seen.add((u.id, uid))
        e_list = effs.get(uid, [])
        reqs = " | ".join(dict.fromkeys(r for e in e_list for r in e[1].split(" | ") if r))
        conds = [c for e in e_list for c in (e[1].split(" | ") + e[2].split(" | ")) if c]
        conds += [f"vs {e[3]}" for e in e_list if e[3]]
        conds = list(dict.fromkeys(conds))
        kinds = {e[0] for e in e_list}
        melee = bool(e_list) and all(e[5] == "melee" for e in e_list if e[5])
        sm = chassis.get(u.id, 1.0)
        t = trigger(u, reqs, " | ".join(conds), sm, melee_effect=melee,
                    kind="charge_bonus" if "charge_bonus" in kinds else "")
        fam = family or "autre"
        if fam in ("buff-perso-offensif", "buff-perso-defensif"):
            expo = "contact" if sm >= 0.5 else "longue"
        else:
            expo = exposure_of(scope or "", rng, reqs, fam)
        m_in, r_in = incoming.get(u.id, (0.0, 0.0))
        alive = rounds_alive(u.health * u.models, m_in, r_in, expo)
        lasting = _lasting(freq, {e[4] for e in e_list})
        # une fois par bataille courte : jouée au kairos (round 2 au plus tôt, cf. realized.py)
        surv = survival_coverage(alive, t.start if lasting else max(t.start, 2), lasting=lasting)
        d = t.p * _start_share(t.start, freq or "", "permanent" if lasting else "")
        others = [c for c in conds if c not in BEARER_CONDITIONS]
        rows.append((u.id, uid, name, fam, power, verdict, expo, round(t.p, 3), t.start, t.bearer_only,
                     round(alive, 2), round(surv, 3), round(d * surv, 3), " | ".join(others) or None))
    return rows


def _units_by_army_name(con, repository) -> dict[str, list[Unit]]:
    by_id = repository.load_all_units_with_weapons(con)
    names = dict(con.execute("SELECT id, name FROM army").fetchall())
    return {names[aid]: us for aid, us in by_id.items()}

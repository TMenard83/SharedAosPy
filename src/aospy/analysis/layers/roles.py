"""Couche 4 — rôle de chaque unité dans la liste, et composantes de la liste (château lent, aile rapide…).

Le rôle se lit sur le profil ET sur ce que l'unité reçoit dans la liste (leçon « contexte réel », mémoire
`list-building-concept`) : des Bloodletters moyens nus mais à +1 Attaque et +1 Perforation tout en place sont le
marteau de la liste. Six rôles (vocabulaire de l'utilisateur) : marteau, enclume, cordon, scoring, support,
mobilité ; « ajustement » pour une petite unité sans rôle net (les 1-2 dernières unités servent souvent à finir
les points).

Chaque rôle reçoit un score 0-1 ; le rôle principal est le meilleur, les rôles secondaires ceux ≥ `SECONDARY`.
Seuils réglés à la main sur les listes revues avec l'utilisateur (Hibou_2, Totosai, Haldahir) : c'est une
**suggestion** à confirmer par la lecture, pas un verdict.

Composantes (`components`) : groupes d'unités qui jouent ensemble, repérés par la vitesse (round d'engagement,
téléportation) et par les auras (un support dont les bulles tiennent plusieurs unités lentes = château).
"""

from __future__ import annotations

from dataclasses import dataclass

ROLES = ("marteau", "enclume", "cordon", "scoring", "support", "mobilité")
#: score minimal d'un rôle secondaire
SECONDARY = 0.6
#: en dessous, l'unité n'a pas de rôle net (« ajustement » si elle est petite)
WEAK = 0.45
#: contrôle par 100 points qui vaut un score de scoring de 1 (10 Saurus contrôle 1 à 120 pts ≈ 8)
CONTROL_PER_100_FULL = 8.0
#: engagée dès le round 1 à pied (bonus de mobilité)
FAST_ROUND = 1
#: unité rapide (composantes) : mouvement ≥ 10", ≥ 8" avec VOL, ou téléportée au moins un tour sur deux
FAST_MOVE = 10
#: handicap de la mobilité pour le rôle principal
MOB_HANDICAP = 0.15
_FRIENDLY_SCOPES = ("friendly_aura", "one_friendly", "army")


@dataclass(frozen=True)
class UnitRole:
    name: str
    points: int  # toutes copies
    copies: int
    role: str
    secondary: tuple[str, ...]
    scores: tuple[tuple[str, float], ...]  # (rôle, score) dans l'ordre de `ROLES`
    reasons: tuple[str, ...]
    fast: bool


@dataclass(frozen=True)
class Component:
    kind: str  # « château lent », « aile rapide », « deathstar », « écran »
    units: tuple[str, ...]
    points: int
    share: float  # part des points de la liste
    note: str


def _buffs_given(rep, name: str) -> dict[str, set[str]]:
    """Aptitudes amies portées par `name` → receveurs AUTRES que lui dans la liste (`rep.marriages`)."""
    mine = {a.name for a in rep.abilities if name in a.carriers and a.scope in _FRIENDLY_SCOPES}
    out: dict[str, set[str]] = {}
    for m in rep.marriages:
        if m.ability in mine and m.receiver != name and (m.off_gain_pct or 0) + (m.def_gain_pct or 0) > 1:
            out.setdefault(m.ability, set()).add(m.receiver)
    return out


def _caster_level(u) -> int:
    from .listing import wizard_level

    priest = max((int(k[-2]) for k in u.keywords if k.startswith("PRIEST (") and k[-2].isdigit()), default=0)
    if not priest and "PRIEST" in u.keywords:
        priest = 1
    return wizard_level(u) + priest


def teleport_share(rep) -> dict[str, float]:
    """Part de téléportation de chaque unité : utilisations par tour de chaque aptitude de redéploiement / réserve
    (une par porteur, par sorcier pour un sort de domaine, une par unité pour une aptitude sur soi) réparties sur
    ses receveurs. Transporting Vortex (un Windmage, une unité par tour) sur 5 unités = 0,2 chacune ; Skitterleap
    (6 sorciers Skaven) sur 5 héros = 1. Une arrivée de réserve (une fois) compte pour moitié."""
    from .listing import effect_ability, list_receivers, wizard_level

    units = [u for _n, _p, u in rep.units if u is not None]
    share: dict[str, float] = {}
    for a in rep.abilities:
        for e in a.effects:
            if e.kind not in ("deep_strike", "redeploy"):
                continue
            if a.scope in ("self", "unknown") and a.carriers:
                rec = {u.name for u in units if u.name in a.carriers}
                uses = float(len(rec))
            else:
                rec = {u.name for u, _r in list_receivers(effect_ability(a, e.friendly_target), units, rep.vocab)}
                if a.carriers:
                    uses = float(sum(1 for u in units if u.name in a.carriers))
                elif (a.cost_type or "").lower() == "spell":
                    uses = float(sum(1 for u in units if wizard_level(u) > 0))
                else:
                    uses = float(len(rec))
            if not rec:
                continue
            w = 1.0 if e.kind == "redeploy" and "battle" not in (a.frequency or "") else 0.5
            for n in rec:
                share[n] = share.get(n, 0.0) + w * uses / len(rec)
            break
    return {n: min(1.0, v) for n, v in share.items()}


def _offense_bare(u) -> float:
    from .encounter import CombatModifiers, EffectSpec, plan_offense, play_plan, probe_for_effect

    probe = probe_for_effect(EffectSpec("stat_mod", "hit", 1.0))
    mods = CombatModifiers(attacker_charged=True)  # même hypothèse que l'empilement
    return plan_offense(u, probe, mods, play_plan(u, probe, mods))


def _shares(rep, units, stacks) -> tuple[dict[str, float], dict[str, float]]:
    """Dégâts et PV effectifs « tout en place » d'une copie, rapportés à la moyenne par unité de la liste."""
    from .encounter import unit_durability

    counts: dict[str, int] = {}
    for _n, _p, u in rep.units:
        if u is not None:
            counts[u.name] = counts.get(u.name, 0) + 1
    off, dur = {}, {}
    for name, u in units.items():
        st = stacks.get(name)
        off[name] = st.off_after if st and st.off_before else _offense_bare(u)
        dur[name] = unit_durability(u) * (1 + (st.def_joint_pct if st else 0.0) / 100)
    n = sum(counts.values()) or 1
    mo = sum(off[k] * counts[k] for k in off) / n or 1.0
    md = sum(dur[k] * counts[k] for k in dur) / n or 1.0
    return {k: v / mo for k, v in off.items()}, {k: v / md for k, v in dur.items()}


def unit_roles(rep) -> list[UnitRole]:
    units = {u.name: u for _n, _p, u in rep.units if u is not None}
    stacks = {s.receiver: s for s in rep.stacks}
    rel_off, rel_def = _shares(rep, units, stacks)
    from .marriage import territory_round

    tele = teleport_share(rep)
    out: list[UnitRole] = []
    for sh in rep.sheets:
        u = units.get(sh.name)
        if u is None:
            continue
        st = stacks.get(sh.name)
        reasons: list[str] = []
        off_mult = st.off_after / st.off_before if st and st.off_before else 1.0
        def_mult = 1 + (st.def_joint_pct if st else 0.0) / 100
        # marteau : moitié rang offensif couche 3 (rendement par point), moitié dégâts « tout en place » face à la
        # moyenne de la liste (1 à deux fois la moyenne) : ce que la liste lui donne compte
        s_ham = 0.5 * sh.off_rank + 0.5 * min(1.0, rel_off[sh.name] / 2)
        if off_mult >= 1.3:
            reasons.append(f"dégâts ×{off_mult:.1f} tout en place")
        if sh.share_melee < 0.4 and sh.off_rank >= 0.5:
            reasons.append("tir")
        s_anv = 0.5 * sh.def_rank + 0.5 * min(1.0, rel_def[sh.name] / 2)
        if def_mult >= 1.3:
            reasons.append(f"PV effectifs ×{def_mult:.1f} tout en place")
        ctl = u.control * u.models
        ctl100 = 100 * ctl / sh.points if sh.points else 0.0  # sh.points : prix d'UNE copie
        s_sco = min(1.0, ctl100 / CONTROL_PER_100_FULL) * (0.6 + 0.4 * min(1.0, ctl / 10))
        # cordon : unité bon marché à plusieurs figurines, qui ne vaut pas par ses dégâts
        cheap = sh.points <= 150
        s_cor = (0.45 if cheap else 0.0) + min(0.35, 0.035 * u.models) + (0.2 if sh.off_rank < 0.5 else 0.0)
        s_cor = 0.0 if u.is_hero or u.models < 3 else min(1.0, s_cor)
        given = _buffs_given(rep, sh.name)
        lvl = _caster_level(u)
        s_sup = min(1.0, 0.3 * len(given) + 0.1 * sum(len(r) for r in given.values()) + 0.2 * lvl)
        if given:
            reasons.append("donne " + ", ".join(sorted(given)[:3]))
        if lvl:
            reasons.append(f"lanceur niv. {lvl}")
        natural = territory_round(u, with_charge=True)  # sans téléportation
        tp = tele.get(sh.name, 0.0)
        s_mob = min(1.0, 0.45 * tp + 0.3 * min(1.0, max(0, u.move - 4) / 8) + 0.1 * sh.fly
                    + 0.15 * (natural <= FAST_ROUND))
        if tp:
            reasons.append(f"téléportation {tp:.1f}/tour")
        scores = dict(zip(ROLES, (s_ham, s_anv, s_cor, s_sco, s_sup, s_mob)))
        # mobilité principale seulement si elle domine nettement : sinon un marteau rapide reste un marteau
        role = max(ROLES, key=lambda r: scores[r] - (MOB_HANDICAP if r == "mobilité" else 0.0))
        if scores[role] < WEAK:
            role = "ajustement" if sh.points <= 120 else role
        second = tuple(r for r in ROLES if r != role and scores[r] >= SECONDARY)
        out.append(UnitRole(
            sh.name, sh.points * sh.copies, sh.copies, role, second, tuple((r, round(scores[r], 2)) for r in ROLES),
            tuple(reasons), u.move >= FAST_MOVE or (sh.fly and u.move >= FAST_MOVE - 2) or tp >= 0.5,
        ))
    return out


def components(rep, roles: list[UnitRole]) -> list[Component]:
    total = sum(r.points for r in roles) or 1
    by = {r.name: r for r in roles}
    out: list[Component] = []

    def comp(kind: str, names, note: str) -> None:
        names = tuple(sorted(set(names)))
        pts = sum(by[n].points for n in names)
        out.append(Component(kind, names, pts, pts / total, note))

    # château : un support lent dont les bulles tiennent ≥ 2 unités lentes
    slow = {r.name for r in roles if not r.fast}
    castle: set[str] = set()
    for r in roles:
        if r.name not in slow or ("support" != r.role and "support" not in r.secondary):
            continue
        rec = set().union(*_buffs_given(rep, r.name).values()) & slow if _buffs_given(rep, r.name) else set()
        if len(rec) >= 2:
            castle |= rec | {r.name}
    if castle:
        anv = [n for n in castle if by[n].role == "enclume" or "enclume" in by[n].secondary]
        comp("château lent", castle, f"bulles de soutien sur {len(castle) - 1} unités lentes"
             + (f", enclume(s) : {', '.join(sorted(anv))}" if anv else ""))
    wing = [r.name for r in roles if r.fast and r.name not in castle
            and ({r.role} | set(r.secondary)) & {"marteau", "mobilité"}]
    if wing and sum(by[n].points for n in wing) >= 0.15 * total:
        comp("aile rapide", wing, "frappe ou scoring loin du gros de l'armée dès le round 1")
    # deathstar : une unité qui concentre les effets de la liste
    for st in rep.stacks:
        if (st.receiver in by and st.off_before and st.off_after / st.off_before >= 1.8 and len(st.items) >= 3
                and by[st.receiver].points >= 0.2 * total and dict(by[st.receiver].scores)["marteau"] >= 0.6):
            mult = st.off_after / st.off_before
            comp("deathstar", [st.receiver], f"{len(st.items)} effets reçus, dégâts ×{mult:.1f}")
    screens = [r.name for r in roles if r.role == "cordon"]
    if sum(by[n].copies for n in screens) >= 2:
        comp("écran", screens, "unités bon marché pour filtrer et tenir les objectifs")
    return out


def pattern(comps: list[Component]) -> str:
    """Lecture d'ensemble : « château lent + aile rapide », « deathstar + écran »… ; « » si aucune composante."""
    return " + ".join(dict.fromkeys(c.kind for c in comps))

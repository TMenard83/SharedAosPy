"""Couche 4 — aptitudes × armée : ce qu'une liste fait de ses aptitudes.

Architecture « aptitude ≠ châssis » (cf. analysis/README.md, « Architecture en quatre couches ») : les couches 1-3 jugent
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

from ...domain.models import Unit
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
    source: str  # « charte : Avalenor… », « formation : Warhost of Duality », « domaine : … »
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
    #: « doit avoir chargé » lu au niveau de l'aptitude (souvent dans l'Annonce : « Pick … units that charged
    #: this turn ») mais pas reporté sur l'effet par la couche 1.
    charge_required: bool = False
    #: texte d'effet (lectures que la couche 1 ne fait pas encore : relances de charge)
    text: str = ""
    #: P que la source existe : aptitude d'une manifestation = P(son sort SUMMON) ; 1 sinon
    summon_prob: float = 1.0

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
    option: str = ""  # option retenue d'une aptitude à choix exclusif (analyseur v33)
    #: fiabilité du donneur (déjà incluse dans `weight`) : D × S du porteur en couche 3 × suivi du receveur
    #: (× P(invocation) pour une manifestation) ; 1 pour un effet sur soi ou une règle d'armée
    giver: float = 1.0

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
    casters: tuple[tuple[str, int], ...]  # (sorcier, lancers par tour)
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
    dead: list[tuple[ListAbility, str]] = field(default_factory=list)
    sheets: list["UnitSheet"] = field(default_factory=list)
    picks: list["EnhancementPick"] = field(default_factory=list)
    assault: Optional[object] = None  # `assault.Assault` : charges groupées, redondance et secours
    vocab: frozenset[str] = frozenset()
    #: aptitudes « à lire » rejouées sur les receveurs de la liste (`listgrid.GridRow`), contreparties écartées
    grid: list = field(default_factory=list)
    drawbacks: list = field(default_factory=list)
    #: empilement par unité (`stacking.Stack`) : tous les effets reçus ensemble, plafonds ±1 compris
    stacks: list = field(default_factory=list)
    #: donneurs recalculés avec la liste (`givers.GiverRow`)
    givers: list = field(default_factory=list)


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
            return [
                (u, "porteur" if u in carriers else "allié")
                for u in units
                if matches_friendly_target(u, ab.friendly_target, vocab) and not (ab.excludes_self and u in carriers)
            ]
        return []
    return receivers(
        ab.source_kind, ab.scope, "faction_rule", ab.source, units, ab.friendly_target, vocab, ab.excludes_self
    )


def effect_ability(ab: ListAbility, effect_target: str) -> ListAbility:
    """L'aptitude vue depuis un de ses effets : la cible amie de l'effet (v26) prime sur celle de l'aptitude."""
    if not effect_target or effect_target == ab.friendly_target:
        return ab
    from dataclasses import replace

    return replace(ab, friendly_target=effect_target)


def _activation(ab: ListAbility, cast_prob: dict[tuple[str, str], float]) -> float:
    """P(déclenchement) : celle de la couche 1, ou P(lancement) du sort recalculée avec la liste (`givers`)."""
    vals = [cast_prob[(c, ab.uid)] for c in ab.carriers + ("*",) if (c, ab.uid) in cast_prob]
    return max(vals) if vals else ab.activation_prob


def giver_reliability(
    ab: ListAbility,
    receiver: Unit,
    relation: str,
    bearing: dict[tuple[str, str], float],
    reach: dict[str, float],
) -> float:
    """Fiabilité du donneur d'un buff (réponse utilisateur, 2026-11-23 : « D × S × suivi ») : le receveur n'en
    profite que si le donneur déclenche et tient l'aptitude (D × S couche 3, `ability_marriage.bearing`) et le
    suit (min(1, allonge du donneur ÷ allonge du receveur)) ; une manifestation n'existe que si son invocation
    passe (`summon_prob`). Effet sur soi ou règle d'armée sans porteur : 1. Le meilleur porteur s'il y en a
    plusieurs."""
    if relation == "porteur" or not ab.carriers:
        return 1.0
    best = 0.0
    for c in ab.carriers:
        ds = bearing.get((c, ab.uid), 1.0)
        r_c, r_u = reach.get(c), reach.get(receiver.name)
        follow = min(1.0, r_c / r_u) if r_c and r_u else 1.0
        best = max(best, ds * follow)
    return best * ab.summon_prob


def marriages(
    abilities: list[ListAbility],
    units: list[Unit],
    vocab: frozenset[str],
    share_melee: Optional[dict[str, float]] = None,
    dead: frozenset[str] = frozenset(),
    bearing: Optional[dict[tuple[str, str], float]] = None,
    reach: Optional[dict[str, float]] = None,
    cast_prob: Optional[dict[tuple[str, str], float]] = None,
) -> list[Marriage]:
    """Effets traduisibles posés sur chaque receveur de la liste, pondérés sur la frise (`timeline`) : tour où
    l'aptitude se joue, durée, pertinence attaque/défense, × P(déclenchement) × D (conditions du porteur
    remplies par CE châssis, `marriage.trigger`). Les conditions tenues par d'autres restent affichées."""
    from .marriage import trigger

    share_melee = share_melee or {}
    out: list[Marriage] = []
    seen: set[tuple] = set()
    for ab in abilities:
        effs = ab.translatable
        if not effs or ab.uid in dead:
            continue
        by_target: dict[str, list[EffectSpec]] = {}
        for eff in effs:  # cible amie propre à l'effet (option), sinon celle de l'aptitude
            by_target.setdefault(eff.friendly_target, []).append(eff)
        pairs = [
            (unit, rel, eff)
            for ft, group in by_target.items()
            for unit, rel in list_receivers(effect_ability(ab, ft), units, vocab)
            for eff in group
        ]
        for unit, rel, eff in pairs:
            sm = share_melee.get(unit.name, 1.0)
            key = (ab.uid, eff, unit.name)
            if key in seen:
                continue
            seen.add(key)
            enc = encounter(unit, eff)
            if enc is None:
                continue
            conds = eff.conditions
            if ab.charge_required and "a chargé" not in conds:
                conds = " | ".join(c for c in (conds, "a chargé") if c)  # condition lue dans l'Annonce
            t = trigger(unit, eff.requires, conds, sm, melee_effect=eff.weapon_scope == "melee", kind=eff.kind)
            pol = "off" if (enc.off_gain_pct or 0) >= (enc.def_gain_pct or 0) else "def"
            w = (
                coverage(
                    ab.frequency,
                    eff.duration,
                    ab.available_round,
                    turn_side=t.turn_side(ab.turn_side or "any"),
                    polarity=pol,
                    share_melee=sm,
                    start_round=t.start,
                )
                * _activation(ab, cast_prob or {})
            )
            w *= t.p if t.bearer_only else 1.0
            g = giver_reliability(ab, unit, rel, bearing or {}, reach or {})
            w *= g
            out.append(
                Marriage(
                    ab.name,
                    ab.source,
                    unit.name,
                    rel,
                    eff.kind,
                    enc.off_gain_pct,
                    enc.def_gain_pct,
                    round(w, 3),
                    conds,
                    eff.option_group,
                    round(g, 3),
                )
            )
    return sorted(_best_options(out), key=lambda m: -m.score)


def _best_options(rows: list[Marriage]) -> list[Marriage]:
    """Options exclusives (« pick 1 of the following », runes) : par aptitude et receveur, seule la meilleure
    option reste — elles ne se cumulent pas (analyseur v33)."""
    totals: dict[tuple[str, str, str], float] = {}
    for m in rows:
        if m.option:
            k = (m.ability, m.source, m.receiver)
            totals.setdefault(k + (m.option,), 0.0)
            totals[k + (m.option,)] += m.score
    best: dict[tuple[str, str, str], tuple[str, float]] = {}
    for (a, src, r, opt), sc in totals.items():
        if (a, src, r) not in best or sc > best[(a, src, r)][1]:
            best[(a, src, r)] = (opt, sc)
    return [m for m in rows if not m.option or best[(m.ability, m.source, m.receiver)][0] == m.option]


#: Condition remplie par un allié écrite dans le texte : « within 6" of a friendly Gnawhole », « while this unit is
#: within the combat range of a friendly non-HERO SKAVEN INFANTRY unit », « If a friendly X is on the battlefield ».
_PROVIDER_RE = re.compile(
    r"(?:wholly )?within (?:the combat ranges? of|\d+\" of) (?:a|an|any|another|any other)? ?(?:visible )?"
    # énumération « X, Y or Z » gardée entière (Wicked Wardens) ; coupe avant la proposition principale
    r"(?:damaged )?friendly ((?:non-)?[A-Z][^.:;]*?)"
    r"(?=, (?:this|that|it|its|each|add|subtract|you|the|they|those|while|if)\b"
    r"|,? (?:that|while|and|uses|is|has) |\.|:|;|$)"
    r"|\b(?:[Ii]f|[Ww]hile) (?:there (?:is|are) (?:any|a|one or more) )?friendly ([A-Z][^.,:;]*?) (?:is|are) on the "
    r"battlefield"
)


def provider_phrases(text: str) -> list[str]:
    """Alliés qu'exige le texte d'une aptitude (désignation brute, sans « unit(s) » final)."""
    out = []
    for m in _PROVIDER_RE.finditer(text or ""):
        ph = re.sub(r"\s+units?$", "", (m.group(1) or m.group(2) or "").strip())
        if ph:
            out.append(ph)
    return out


def missing_providers(
    abilities: list[ListAbility], units: list[Unit], vocab: frozenset[str]
) -> list[tuple[ListAbility, str]]:
    """Aptitudes dont la condition écrite exige un allié (unité, décor de faction, manifestation) que la liste
    n'a pas : un constat de composition (2026-11-23), comme `dead_rules`. Un porteur se fournit lui-même s'il
    satisfait la désignation ; les décors et manifestations de la liste comptent (porteurs d'aptitudes)."""
    present = {c.lower() for a in abilities for c in a.carriers}
    out = []
    manifs = any(a.source.startswith("manifestation") for a in abilities)
    for ab in abilities:
        for ph in provider_phrases(ab.text):
            alts = [re.sub(r"^(?:a|an|any) (?:friendly )?", "", x.strip()) for x in re.split(r", | or ", ph)]
            alts = [re.sub(r"\s+units?$", "", x) for x in alts if re.match(r"(?:non-)?[A-Z]", x)]
            if any(x.lower() in present or x.upper() == "MANIFESTATION" and manifs for x in alts):
                continue
            if not any(matches_friendly_target(u, x, vocab) for u in units for x in alts):
                out.append((ab, f"condition « à portée d'un allié {ph} » : aucun dans la liste"))
                break
    return out


def dead_rules(abilities: list[ListAbility], units: list[Unit], vocab: frozenset[str]) -> list[tuple[ListAbility, str]]:
    """Règles de la liste qui ne s'appliquent pas : à éliminer de la lecture (méthode utilisateur,
    mémoire `list-building-concept`) — jamais un jugement de valeur, un constat de composition."""
    priests = [u for u in units if any(k.startswith("PRIEST") for k in u.keywords)]
    wizards = [u for u in units if wizard_level(u) > 0]
    out: list[tuple[ListAbility, str]] = []
    for ab in abilities:
        ct = (ab.cost_type or "").lower()
        if ct == "prayer" and not ab.carriers and not priests:
            out.append((ab, "aucun PRÊTRE dans la liste"))
        elif ct == "spell" and not ab.carriers and not wizards:
            out.append((ab, "aucun SORCIER dans la liste"))
        elif (
            ab.scope in ("one_friendly", "friendly_aura")
            and ab.friendly_target
            and ab.carriers
            and not list_receivers(ab, units, vocab)
        ):
            out.append((ab, f"aucune cible « {ab.friendly_target} » dans la liste"))
    return out


_SCOPE_NOBODY = {
    "ranged": "aucune unité de la liste ne tire",
    "melee": "aucune unité de la liste ne combat au corps à corps",
}


def unprofitable_buffs(
    abilities: list[ListAbility], units: list[Unit], vocab: frozenset[str], dead: frozenset[str] = frozenset()
) -> list[tuple[ListAbility, str]]:
    """Buffs donnés dont personne dans la liste ne profite (couche 4, exemple de l'utilisateur : un porte-bannière
    « +3 touche au tir » en bulle de 12" excellent sur son châssis, nul si aucune unité de la liste ne tire).

    Une aptitude qui vise des alliés (`one_friendly` / `friendly_aura` / `army`) dont TOUS les effets traduisibles
    ne rapportent rien (gain d'attaque et de défense nuls, ou aucun profil concerné) sur TOUS ses receveurs de la
    liste, porteur compris. Les effets non traduits ne sont pas jugés : l'aptitude n'est retenue que si elle n'en
    a aucun ; ni ceux dont le gain dépend de l'adversaire (Anti-X, cible « vs HERO » : mesurés contre une cible
    standard sans mot-clé, ils vaudraient 0 à tort). Les aptitudes déjà mortes (`dead`) sont ignorées."""
    out: list[tuple[ListAbility, str]] = []
    for ab in abilities:
        if ab.uid in dead or ab.scope not in ("one_friendly", "friendly_aura", "army"):
            continue
        effs = ab.translatable
        if not effs or len(effs) < len(ab.effects):
            continue
        if any(e.kind == "anti" or e.target_keywords or e.target_condition for e in effs):
            continue  # gain selon l'adversaire (Anti-X, « vs HERO ») : matchups, pas composition de liste
        profit = False
        receivers_seen = False
        for eff in effs:
            for unit, _rel in list_receivers(effect_ability(ab, eff.friendly_target), units, vocab):
                receivers_seen = True
                enc = encounter(unit, eff)
                if enc is not None and ((enc.off_gain_pct or 0) > 0 or (enc.def_gain_pct or 0) > 0):
                    profit = True
                    break
            if profit:
                break
        if receivers_seen and not profit:
            scopes = {e.weapon_scope for e in effs}
            reason = _SCOPE_NOBODY.get(scopes.pop(), "") if len(scopes) == 1 else ""
            out.append((ab, reason or "aucun receveur de la liste n'en profite"))
    return out


def conflicts(abilities: list[ListAbility], unit_counts: dict[str, int]) -> list[Conflict]:
    """Aptitudes limitées à l'armée portées par plusieurs exemplaires d'unités de la liste."""
    out = []
    for ab in abilities:
        if ab.frequency in ARMY_LIMITED and ab.carriers:
            n = sum(unit_counts.get(c, 1) for c in ab.carriers)
            if n > 1:
                out.append(
                    Conflict(
                        ab.name,
                        ab.frequency,
                        tuple(f"{c} ×{unit_counts.get(c, 1)}" if unit_counts.get(c, 1) > 1 else c for c in ab.carriers),
                    )
                )
    return out


def magic_budget(abilities: list[ListAbility], units: list[Unit]) -> MagicBudget:
    casters = tuple((u.name, wizard_level(u)) for u in units if wizard_level(u) > 0)
    spells = tuple(
        (ab.name, ab.source, ab.cost_value or 0.0, round(ab.activation_prob, 2))
        for ab in abilities
        if (ab.cost_type or "").lower() == "spell"
    )
    return MagicBudget(casters, spells)


def analyse(
    title: str,
    faction: str,
    entries: list[tuple[str, int, Optional[Unit]]],
    abilities: list[ListAbility],
    vocab: frozenset[str],
    share_melee: Optional[dict[str, float]] = None,
    bearing: Optional[dict[tuple[str, str], float]] = None,
    reach: Optional[dict[str, float]] = None,
    cast_prob: Optional[dict[tuple[str, str], float]] = None,
) -> ListReport:
    units = [u for _n, _p, u in entries if u is not None]
    distinct = list({u.name: u for u in units}.values())
    counts: dict[str, int] = {}
    for u in units:
        counts[u.name] = counts.get(u.name, 0) + 1
    rep = ListReport(title, faction, entries, abilities, vocab=vocab)
    rep.dead = dead_rules(abilities, distinct, vocab)
    dead_now = {a.uid for a, _r in rep.dead}
    rep.dead += [(a, r) for a, r in missing_providers(abilities, distinct, vocab) if a.uid not in dead_now]
    rep.dead += unprofitable_buffs(abilities, distinct, vocab, frozenset(a.uid for a, _r in rep.dead))
    rep.marriages = marriages(
        abilities, distinct, vocab, share_melee, frozenset(a.uid for a, _r in rep.dead), bearing, reach, cast_prob
    )
    rep.conflicts = conflicts(abilities, counts)
    rep.magic = magic_budget(abilities, units)
    dead_uids = {a.uid for a, _r in rep.dead}
    rep.unresolved = [
        a
        for a in abilities
        if a.uid not in dead_uids and (not a.translatable and a.scope != "one_enemy" or a.verdict == "a-revoir")
    ]
    return rep


# ----- lecture en base -------------------------------------------------------------


def _rule_groups(parsed, renown: Optional[tuple[str, frozenset[str]]] = None) -> list[tuple[str, str]]:
    """(groupe `ability_owner.owner_name`, libellé d'origine) des règles d'armée choisies.

    `renown` = (nom Wahapedia de l'Armée de Renom, ses catégories) : chaque catégorie qu'elle porte REMPLACE
    celle de la faction de base (règle du kit de tournoi, `tournament_kit.resolution.rules_resolution._AOR_REPLACES`,
    validée par le test de référence du PDF) — ex. « Lords of the Clan › Spell Lore » au lieu de
    « Spell Lore › Lore of the Deepwood » ; une catégorie absente (la formation : aucune AoR n'en a) reste celle
    de base. Une AoR n'a qu'un domaine par catégorie : son nom dans l'export n'est pas nécessaire."""
    aor, cats = renown if renown else ("", frozenset())

    def pick(category: str, base_group: str, label: str) -> tuple[str, str]:
        if category in cats:
            return f"{aor} › {category}", f"{label} (armée de renom {aor})"
        return base_group, label

    # « › * » : tous les sous-types de traits de base (Khorne « Blood Tithe Abilities », Idoneth « Battle Traits1 »…)
    groups = [pick("Battle Traits", "Battle Traits › *", "trait de bataille")]
    from ...text import fold_name

    # export AoR : « Army of Renown », ou le nom de l'AoR elle-même (format compact) — pas une formation
    if parsed.allegiance and fold_name(parsed.allegiance) not in (fold_name("Army of Renown"), fold_name(aor)):
        groups.append(pick("Battle Formations", f"Battle Formations › {_base_name(parsed.allegiance)}", "formation"))
    for lore, kind, label in (
        (parsed.spell_lore, "Spell Lore", "domaine de sorts"),
        (parsed.prayer_lore, "Prayer Lore", "domaine de prières"),
        (parsed.manifestation_lore, "Manifestation Lore", "domaine de manifestations"),
    ):
        if kind in cats:
            groups.append(pick(kind, "", label))
        elif lore:
            groups.append((f"{kind} › {_base_name(lore)}", label))
    return groups


def renown_categories(con, faction: str, renown: Optional[str]) -> Optional[tuple[str, frozenset[str]]]:
    """(nom Wahapedia, catégories) de l'Armée de Renom `renown` de `faction`, None si absente de la base."""
    if not renown:
        return None
    from ...text import fold_name

    found: dict[str, set[str]] = {}
    for name, group in con.execute(
        """SELECT DISTINCT origin_name, owner_name FROM ability_owner
           WHERE origin_kind = 'army_of_renown' AND faction_name = ?""",
        [faction],
    ).fetchall():
        if fold_name(name) == fold_name(renown):
            found.setdefault(name, set()).add(group.split(" › ", 1)[1] if " › " in group else group)
    if not found:
        return None
    name, cats = next(iter(found.items()))
    return name, frozenset(cats)


def _ability_from_row(row, source: str, carriers: tuple[str, ...], effects) -> ListAbility:
    (
        uid,
        name,
        source_kind,
        scope,
        freq,
        turn,
        phase,
        ctype,
        cval,
        prob,
        avail,
        ft,
        excl,
        verdict,
        power,
        rel,
        ease,
        inter,
        charge,
        text,
    ) = row
    return ListAbility(
        uid,
        name,
        source,
        source_kind or "",
        carriers,
        scope or "",
        freq or "",
        turn or "",
        phase or "",
        ctype or "",
        cval,
        prob if prob is not None else 1.0,
        avail,
        ft or "",
        bool(excl),
        verdict or "",
        power or 0.0,
        rel or 0.0,
        ease or 0.0,
        inter or 0.0,
        tuple(effects.get(uid, ())),
        bool(charge),
        text or "",
    )


_ABILITY_SELECT = """SELECT DISTINCT a.uid, a.name, a.source_kind, a.scope, a.frequency, a.turn_side, a.phase,
       a.cost_type, a.cost_value, a.activation_prob, a.available_round, a.friendly_target, a.excludes_self,
       a.verdict, a.power, a.reliability, a.ease, a.interaction,
       coalesce(a.conditions, '') LIKE '%doit avoir chargé%', a.effect_text
FROM ability a JOIN ability_owner o ON o.ability_uid = a.uid"""


def _effects(con, uids: list[str]) -> dict[str, list[EffectSpec]]:
    if not uids:
        return {}
    out: dict[str, list[EffectSpec]] = {}
    for uid, kind, stat, value, detail, side, wscope, wname, comp, tkw, tcond, req, dur, ft, opt in con.execute(
        """SELECT ability_uid, kind, stat, value, detail, side, weapon_scope, weapon_name, includes_companion,
                      target_keywords, target_condition, requires, duration, friendly_target,
                      coalesce(option_group, '')
               FROM ability_effect WHERE ability_uid IN ? ORDER BY ability_uid, seq""",
        [uids],
    ).fetchall():
        out.setdefault(uid, []).append(
            EffectSpec(
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
                friendly_target=ft or "",
                option_group=opt,
            )
        )
    return out


def collect(con, parsed) -> tuple[list[tuple[str, int, Optional[Unit]]], list[ListAbility], frozenset[str]]:
    """Unités (nom, points, `Unit` en base ou None) et aptitudes de la liste."""
    from ...persistence import repository

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
        for row in con.execute(
            _ABILITY_SELECT + " WHERE o.owner_kind = 'warscroll' AND o.faction_name = ? "
            "AND lower(o.owner_name) = lower(?)",
            [faction, name],
        ).fetchall():
            rows.append((row, f"charte : {name}", (name,)))
    # export complet : « Faction | AoR » ; export compact : l'AoR occupe la place de la formation, mais une
    # formation de base peut porter le même nom qu'une AoR (Sylvaneth « Lords of the Clan ») : elle l'emporte.
    renown = renown_categories(con, faction, parsed.army_of_renown)
    if renown is None and parsed.allegiance:
        is_formation = con.execute(
            "SELECT 1 FROM ability_owner WHERE owner_kind = 'faction_rule' AND faction_name = ? AND owner_name = ?",
            [faction, f"Battle Formations › {_base_name(parsed.allegiance)}"],
        ).fetchone()
        if not is_formation:
            renown = renown_categories(con, faction, parsed.allegiance)
    owner_groups = [
        g
        for (g,) in con.execute(
            "SELECT DISTINCT owner_name FROM ability_owner WHERE owner_kind = 'faction_rule' AND faction_name = ?",
            [faction],
        ).fetchall()
    ]
    rule_groups = []
    for group, label in _rule_groups(parsed, renown):
        if group.endswith(" › *"):
            prefix = group[:-1]
            rule_groups.extend((g, label) for g in sorted(owner_groups) if g.startswith(prefix))
        else:
            rule_groups.append((group, label))
    for group, label in rule_groups:
        for row in con.execute(
            _ABILITY_SELECT + " WHERE o.owner_kind = 'faction_rule' AND o.owner_name = ? "
            "AND (o.faction_name = ? OR o.faction_name = 'Endless Spells')",
            [group, faction],
        ).fetchall():
            rows.append((row, f"{label} : {group.split(' › ', 1)[1]}", ()))
    # Optimisation nommée dans l'export : celle de l'AoR de la liste si elle en a une de ce nom, sinon celle de
    # base — jamais une homonyme d'une autre AoR, d'une armée Spearhead ou de Path to Glory.
    opt_where = " WHERE o.owner_kind = 'faction_rule' AND o.faction_name = ? AND upper(a.name) = upper(?) AND "
    for unit_name, opt in options:
        found = []
        if renown:
            found = con.execute(
                _ABILITY_SELECT + opt_where + "o.origin_kind = 'army_of_renown' AND o.origin_name = ?",
                [faction, opt, renown[0]],
            ).fetchall()
        if not found:
            found = con.execute(
                _ABILITY_SELECT + opt_where + "coalesce(o.origin_kind, 'base') = 'base'",
                [faction, opt],
            ).fetchall()
        for row in found:
            rows.append((row, f"amélioration : {opt}", (unit_name,)))
    # Aptitudes des manifestations invocables (domaine choisi) : elles n'existent que si l'invocation passe.
    summon_p: dict[str, float] = {}
    for row, _src, _c in list(rows):
        name, ctype, prob = row[1], row[7], row[9]
        if not (name or "").upper().startswith("SUMMON ") or (ctype or "").lower() != "spell":
            continue
        manif = name[len("SUMMON ") :].strip()
        for mrow in con.execute(
            _ABILITY_SELECT + " WHERE o.owner_kind = 'warscroll' AND lower(o.owner_name) = "
            "lower(?) AND o.faction_name IN (?, 'Endless Spells')",
            [manif, faction],
        ).fetchall():
            src = f"manifestation : {manif.title()}"
            summon_p[src] = prob if prob is not None else 1.0
            rows.append((mrow, src, (manif.title(),)))

    effects = _effects(con, sorted({r[0][0] for r in rows}))
    merged: dict[tuple[str, str], ListAbility] = {}
    for row, source, carr in rows:
        key = (row[0], source if not carr or source.startswith(("amélioration", "manifestation")) else "charte")
        prev = merged.get(key)
        if prev is None:
            ab = _ability_from_row(row, source, carr, effects)
            if source in summon_p:
                from dataclasses import replace

                ab = replace(ab, summon_prob=summon_p[source])
            merged[key] = ab
        else:  # même aptitude sur plusieurs chartes de la liste (ex. Battle Damaged)
            from dataclasses import replace

            merged[key] = replace(
                prev,
                carriers=tuple(dict.fromkeys(prev.carriers + carr)),
                source=prev.source if carr[0] in prev.source else f"{prev.source}, {carr[0]}",
            )
    return entries, list(merged.values()), vocab


@dataclass(frozen=True)
class UnitSheet:
    """Fiche couche 3 d'une unité de la liste : sa valeur, un rôle suggéré, ses aptitudes mal mariées."""

    name: str
    points: int
    copies: int
    off_per_100: float
    def_per_100: float
    fit_per_100: float
    good_per_100: float
    off_rank: float
    def_rank: float
    share_melee: float
    move: int
    fly: bool
    engage_round: int
    role: str
    weak_marriages: tuple[tuple[str, float, str], ...]  # (aptitude, mariage, exposition)


@dataclass(frozen=True)
class EnhancementPick:
    """Optimisation prise : son porteur face aux autres porteurs éligibles de la liste."""

    enhancement: str
    bearer: str
    bearer_value: Optional[float]
    bearer_marriage: float
    best_in_list: str
    best_value: Optional[float]
    best_marriage: float
    n_eligible: int


#: Rôle suggéré (à confirmer par la lecture humaine) : rangs centiles couche 3 dans le segment héros/troupes.
def suggest_role(
    off_rank: float,
    def_rank: float,
    share_melee: float,
    is_hero: bool,
    models: int,
    gives_buffs: bool,
    caster_level: int = 0,
) -> str:
    if share_melee < 0.4 and off_rank >= 0.5:
        return "artillerie / tir"
    if caster_level >= 2:
        return "lanceur"
    if off_rank >= 0.75 and def_rank >= 0.6:
        return "marteau"
    if off_rank >= 0.75:
        return "marteau fragile (canon de verre)"
    if def_rank >= 0.75:
        return "enclume"
    if is_hero and gives_buffs:
        return "soutien"
    if not is_hero and models >= 5:
        return "scoring / cordon"
    return "polyvalent / ajustement"


def teleporters(abilities: list[ListAbility], units: list[Unit]) -> frozenset[str]:
    """Unités qui peuvent se téléporter : leur propre aptitude, ou un sort/une règle d'armée qui vise un ami
    (approximation : un domaine de téléportation profite aux HÉROS)."""
    tp = [a for a in abilities if any(e.kind in ("deep_strike", "redeploy") for e in a.effects)]
    own = {c for a in tp for c in a.carriers}
    army = any(a.scope in ("one_friendly", "army") and not a.carriers or a.source.startswith("domaine") for a in tp)
    return frozenset(u.name for u in units if u.name in own or (army and u.is_hero))


def unit_sheets(con, entries, abilities: list[ListAbility], share_melee: dict[str, float]) -> list[UnitSheet]:
    from .marriage import territory_round

    units = [u for _n, _p, u in entries if u is not None]
    counts: dict[str, int] = {}
    for u in units:
        counts[u.name] = counts.get(u.name, 0) + 1
    givers = {c for a in abilities if a.scope in ("friendly_aura", "one_friendly", "army") for c in a.carriers}
    tele = teleporters(abilities, units)
    out: list[UnitSheet] = []
    for u in {x.name: x for x in units}.values():
        r = con.execute(
            "SELECT off_realized_per_100, def_realized_per_100, combined_fit_per_100, "
            "off_good_per_100, def_good_per_100, off_pct_rank, def_pct_rank FROM unit_realized "
            "WHERE unit_id = ?",
            [u.id],
        ).fetchone() or (0, 0, 0, 0, 0, 0, 0)
        weak = con.execute(
            "SELECT ability_name, marriage, exposure FROM ability_marriage WHERE unit_id = ? "
            "AND marriage < 0.4 AND verdict IN ('plan', 'correct', 'bonus', 'pari') "
            "ORDER BY marriage",
            [u.id],
        ).fetchall()
        sm = share_melee.get(u.name, 1.0)
        fly = "FLY" in u.keywords
        engage = 1 if u.name in tele else territory_round(u, with_charge=True)
        good = (r[3] * r[4]) ** 0.5 if r[3] and r[4] else 0.0
        role = suggest_role(r[5] or 0, r[6] or 0, sm, u.is_hero, u.models, u.name in givers, wizard_level(u))
        if r[2] and good >= 1.3 * r[2]:
            # gros écart réalisé / bon cas : l'unité vaut surtout sous condition (vs HÉROS, a chargé…)
            role = f"spécialiste (bon cas ×{good / r[2]:.1f})"
        out.append(
            UnitSheet(
                u.name,
                u.points,
                counts[u.name],
                r[0] or 0,
                r[1] or 0,
                r[2] or 0,
                good,
                r[5] or 0,
                r[6] or 0,
                sm,
                u.move,
                fly,
                engage,
                role,
                tuple((n, m, e) for n, m, e in weak),
            )
        )
    return out


def enhancement_picks(con, entries, abilities: list[ListAbility]) -> list[EnhancementPick]:
    """Pour chaque optimisation prise : où elle tombe face au meilleur porteur possible DANS la liste."""
    ids = {u.name: u.id for _n, _p, u in entries if u is not None}
    out: list[EnhancementPick] = []
    for a in abilities:
        if not a.source.startswith("amélioration") or not a.carriers:
            continue
        rows = con.execute(
            "SELECT u.name, b.value, b.marriage FROM enhancement_bearer b JOIN unit u ON u.id = b.unit_id "
            "WHERE b.ability_uid = ? AND b.unit_id IN ? ORDER BY b.value DESC NULLS LAST, b.marriage DESC, "
            "b.bearer_combined DESC",
            [a.uid, list(ids.values()) or [-1]],
        ).fetchall()
        if not rows:
            continue
        mine = next((r for r in rows if r[0] == a.carriers[0]), (a.carriers[0], None, 0.0))
        out.append(
            EnhancementPick(
                a.name, a.carriers[0], mine[1], mine[2] or 0.0, rows[0][0], rows[0][1], rows[0][2] or 0.0, len(rows)
            )
        )
    return out


def analyse_list(con, parsed) -> ListReport:
    entries, abilities, vocab = collect(con, parsed)
    sm = {
        u.name: (
            con.execute("SELECT coalesce(share_melee, 1.0) FROM unit_chassis WHERE unit_id = ?", [u.id]).fetchone()
            or (1.0,)
        )[0]
        for _n, _p, u in entries
        if u is not None
    }
    ids = {u.name: u.id for _n, _p, u in entries if u is not None}
    names = {v: k for k, v in ids.items()}
    uids = [a.uid for a in abilities] or [""]
    mrows = {
        (names[uid], aid): (expo, pt, start, surv, b)
        for uid, aid, expo, pt, start, surv, b in con.execute(
            "SELECT unit_id, ability_uid, exposure, p_trigger, start_round, survival, bearing FROM ability_marriage "
            "WHERE unit_id IN ? AND ability_uid IN ?",
            [list(ids.values()) or [-1], uids],
        ).fetchall()
        if b is not None
    }
    # couche 4 : lancement et survie des donneurs recalculés avec ce que la liste leur donne (`givers`)
    from .givers import giver_rows
    from .marriage import incoming_damage

    list_units = [u for _n, _p, u in entries if u is not None]
    giver_list = giver_rows(abilities, list_units, vocab, mrows, incoming_damage(con))
    by_uid = {a.name: a.uid for a in abilities}
    bearing = {k: v[4] for k, v in mrows.items()}
    cast_prob: dict[tuple[str, str], float] = {}
    for g in giver_list:
        uid = by_uid.get(g.ability)
        if uid:
            bearing[(g.giver, uid)] = g.bearing_list
            if g.cast_list is not None:
                cast_prob[(g.giver, uid)] = g.cast_list
    from .givers import best_list_cast

    for ab in abilities:  # sort de domaine : le meilleur sorcier de la liste, avec ce qu'il reçoit
        if not ab.carriers and (ab.cost_type or "").lower() == "spell":
            p_best = best_list_cast(ab, list_units, abilities, vocab)
            if p_best is not None:
                cast_prob[("*", ab.uid)] = p_best
    reach = {
        names[uid]: r
        for uid, r in con.execute(
            "SELECT unit_id, reach_in FROM unit_realized WHERE unit_id IN ?", [list(ids.values()) or [-1]]
        ).fetchall()
    }
    rep = analyse(parsed.title, parsed.base_faction, entries, abilities, vocab, sm, bearing, reach, cast_prob)
    rep.givers = giver_list
    rep.sheets = unit_sheets(con, entries, abilities, sm)
    rep.picks = enhancement_picks(con, entries, abilities)
    from .assault import assault

    units = [u for _n, _p, u in entries if u is not None]
    dmg = {
        u.name: (
            con.execute("SELECT coalesce(dmg_melee, 0) FROM unit_chassis WHERE unit_id = ?", [u.id]).fetchone()
            or (0.0,)
        )[0]
        for u in units
    }
    rep.assault = assault(
        abilities, units, vocab, sm, teleporters(abilities, units), frozenset(a.uid for a, _r in rep.dead), dmg
    )
    from .listgrid import collect_grid
    from .stacking import stacks

    rep.stacks = stacks(abilities, units, vocab, frozenset(a.uid for a, _r in rep.dead))

    collect_grid(con, entries, rep)
    return rep

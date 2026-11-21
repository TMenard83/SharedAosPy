"""Couche 3 — rencontre aptitude × châssis : ce qu'un effet rapporte vraiment sur CETTE charte.

Architecture « aptitude ≠ châssis » (cf. CLAUDE.md, « Ability analysis ») : la couche 1 décrit
l'effet hors contexte (`ability_effect` : stat, valeur, périmètre) ; la couche 2 décrit la charte
nue (`unit_chassis`). Ici on applique l'effet au châssis de chaque receveur possible et on relit
le moteur de combat avant/après — « +1 Damage » double une arme à 1 dégât mais ne fait que +33 %
sur une arme à 3 ; « +1 Attack » ne fait rien sur une arme Compagnon.

Un effet se traduit en **réécriture de profil** (copie `dataclasses.replace` de l'`Unit`, comme
`bonus_simulator.bonus.apply_bonus`), jamais en changement du moteur : `combat.py` lit déjà les
critiques (« Crit (2 Hits) », « Crits on 5+ »), Anti-X et Charge dans le texte `Weapon.abilities`.

Mesures (mêmes sondes que le châssis) : dégâts moyens d'un round vs sauvegarde 4+ (offense) et
coups à porter pour tuer l'unité (défense). Le gain est **conditionnel** : il vaut « si l'effet
s'applique » — fiabilité, durée, prérequis et ciblage sont reportés tels quels (colonnes
`conditions`, et les axes de couche 1 restent dans `ability`), la pondération pour les « meilleures
unités » se décide au-dessus.

Hors périmètre (v1) : activations enchaînées (`extra_fight`, tempo et non sortie), effets subis par l'ennemi (débuffs : leur valeur dépend de l'attaquant
adverse), relances (le moteur ne les modélise pas), « ignore le premier point de dégâts »,
manifestations (couche 1 les traite déjà comme une chaîne d'invocation).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Callable, Optional

from ..domain.models import Unit, Weapon
from ..engine.combat import CombatModifiers, unit_damage_moments
from .chassis import is_companion
from .features import _PROBE_SAVE4, _effective_wounds

#: AoS4 : les modificateurs aux jets de touche, de blessure et de sauvegarde sont plafonnés à ±1.
_CAPPED_STATS = {"hit", "wound", "save"}
_OFFENSIVE_STATS = {"hit", "wound", "rend", "damage", "attacks"}
_BEST_ROLL = 2
_NO_WARD = 7

#: Portées de couche 1 qui touchent d'autres unités amies que le porteur.
FRIENDLY_SCOPES = {"one_friendly", "friendly_aura", "army"}
#: Origines de règles de faction qui ne se posent que sur un héros (le porteur choisi).
HERO_ONLY_SOURCES = {"heroic_trait", "artefact", "enhancement", "monstrous_trait"}


@dataclass(frozen=True)
class EffectSpec:
    """Ligne `ability_effect` (+ portée de l'aptitude), ce que la rencontre a besoin de lire."""

    kind: str
    stat: str = ""
    value: float = 0.0
    detail: str = ""
    side: str = "friendly"
    weapon_scope: str = ""
    weapon_name: str = ""
    includes_companion: bool = False
    target_keywords: str = ""
    target_condition: str = ""
    requires: str = ""
    duration: str = ""
    #: cible amie propre à l'effet (ligne d'option, analyseur v26) ; vide = celle de l'aptitude
    friendly_target: str = ""

    @property
    def conditions(self) -> str:
        parts = [self.requires, self.target_condition]
        if self.target_keywords:
            parts.append(f"vs {self.target_keywords}")
        return " | ".join(p for p in parts if p)


@dataclass(frozen=True)
class Encounter:
    """Gain d'un effet sur un châssis (valeurs « si l'effet s'applique »)."""

    off_before: float
    off_after: float
    def_before: float
    def_after: float

    @property
    def off_gain_pct(self) -> Optional[float]:
        return None if self.off_before <= 0 else 100.0 * (self.off_after - self.off_before) / self.off_before

    @property
    def def_gain_pct(self) -> Optional[float]:
        return None if self.def_before <= 0 else 100.0 * (self.def_after - self.def_before) / self.def_before


# ----- périmètre d'armes ---------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def weapon_in_scope(w: Weapon, eff: EffectSpec) -> bool:
    """L'arme `w` est-elle concernée par l'effet ? (Compagnon exclues sauf « including … Companion »)."""
    if is_companion(w) and not eff.includes_companion:
        return False
    scope = eff.weapon_scope or "all"
    if scope == "melee":
        return w.kind == "melee"
    if scope == "ranged":
        return w.kind == "ranged"
    if scope == "named":
        a, b = _norm(w.name), _norm(eff.weapon_name)
        return bool(a and b) and (a == b or a in b or b in a)
    return True  # all / chosen (le choix d'arme est fait par `apply_effect`)


# ----- traduction effet → réécriture de profil -----------------------------------

_CRIT_TYPES = {"2 hits": "Crit (2 Hits)", "mortal": "Crit (Mortal)", "auto-wound": "Crit (Auto-wound)",
               "auto wound": "Crit (Auto-wound)"}
_CRIT_TEXT_RE = re.compile(r"crit\s*\([^)]*\)", re.I)
_CRIT_ON_RE = re.compile(r"(?:unmodified hit rolls? of|crits? on) ([2-5])\+", re.I)


def _with_text(w: Weapon, add: str, drop: Optional[re.Pattern] = None) -> Weapon:
    text = w.abilities or ""
    if drop is not None:
        text = drop.sub("", text)
    return dataclasses.replace(w, abilities=f"{text}, {add}".strip(", "))


def _weapon_transform(eff: EffectSpec) -> Optional[Callable[[Weapon], Weapon]]:
    """Réécriture d'une arme du périmètre, ou None si l'effet n'est pas offensif/traduisible."""
    if eff.kind == "stat_mod" and eff.stat in _OFFENSIVE_STATS:
        v = eff.value
        if eff.stat in _CAPPED_STATS:
            v = max(-1.0, min(1.0, v))
        iv = int(round(v))
        if eff.stat == "hit":
            return lambda w: dataclasses.replace(w, hit=max(_BEST_ROLL, w.hit - iv))
        if eff.stat == "wound":
            return lambda w: dataclasses.replace(w, wound=max(_BEST_ROLL, w.wound - iv))
        if eff.stat == "rend":
            return lambda w: dataclasses.replace(w, rend=max(0, w.rend + iv))
        if eff.stat == "damage":
            return lambda w: dataclasses.replace(w, damage=max(0, w.damage + v))
        return lambda w: dataclasses.replace(w, attacks=max(0, w.attacks + v))
    detail = (eff.detail or "").lower()
    if eff.kind == "crit":
        m = _CRIT_ON_RE.search(detail)
        crit = next((t for k, t in _CRIT_TYPES.items() if k in detail), None)
        if m and crit:
            return lambda w: _with_text(_with_text(w, crit, _CRIT_TEXT_RE), f"Crits on {m[1]}+")
        if m:
            return lambda w: _with_text(w, f"Crits on {m[1]}+")
        if crit:
            return lambda w: _with_text(w, crit, _CRIT_TEXT_RE)
        return None
    if eff.kind in ("anti", "charge_bonus") and "anti-charge" not in detail and eff.detail:
        return lambda w: _with_text(w, eff.detail)
    if eff.kind == "stat_set" and detail.startswith("double the damage"):
        return lambda w: dataclasses.replace(w, damage=w.damage * 2)
    if eff.kind == "stat_set" and detail.startswith("double the attacks"):
        return lambda w: dataclasses.replace(w, attacks=w.attacks * 2)
    if eff.kind == "fight_twice":
        # « can use 2 FIGHT abilities this phase/turn » (Gunnar Brand, Battle-fury…) : un vrai second
        # combat ≈ doubler la sortie de mêlée du round. La Frappe en dernier qui suit le premier combat
        # pèse sur la survie, pas sur les dégâts infligés : elle reste un effet `strike_last` à part.
        return lambda w: dataclasses.replace(w, attacks=w.attacks * 2) if w.kind == "melee" else w
    # `extra_fight` volontairement absent : c'est « peut combattre immédiatement après » (enchaînement
    # d'activations, valeur de tempo), pas un second combat — le double combat est `fight_twice`.
    return None


def _defensive_transform(eff: EffectSpec) -> Optional[Callable[[Unit], Unit]]:
    if eff.kind == "stat_mod" and eff.stat == "save":
        v = int(round(max(-1.0, min(1.0, eff.value))))
        return lambda u: dataclasses.replace(u, save=max(_BEST_ROLL, u.save - v))
    if eff.kind == "stat_mod" and eff.stat == "ward":
        v = int(round(eff.value))
        def f(u: Unit) -> Unit:
            n = max(_BEST_ROLL, (u.ward or _NO_WARD) - v)
            return dataclasses.replace(u, ward=None if n >= _NO_WARD else n)
        return f
    if eff.kind == "ward" and "vs " in eff.target_condition:
        # protection contre les seuls sorts/manifestations/blessures mortelles : nulle contre les attaques
        # d'armes que mesure la durabilité du châssis — un combo « contre », couche 4.
        return None
    if eff.kind == "ward" and eff.value and not eff.weapon_scope:
        # Protection N+ accordée : les protections ne se cumulent pas, on garde la meilleure.
        n = int(eff.value)
        return lambda u: dataclasses.replace(u, ward=min(u.ward or _NO_WARD, n))
    if eff.kind == "stat_mod" and eff.stat == "health" and eff.value > 0:
        # Un « −1 Health » ami est une erreur de lecture (ex. COLOSSAL SLAM : malus au jet de rampage).
        v = int(round(eff.value))
        return lambda u: dataclasses.replace(u, health=max(1, u.health + v))
    return None


def is_translatable(eff: EffectSpec) -> bool:
    return eff.side == "friendly" and (_weapon_transform(eff) is not None or _defensive_transform(eff) is not None)


# ----- mesure --------------------------------------------------------------------

def _probe(eff: EffectSpec) -> Unit:
    kws = frozenset(k.strip() for k in eff.target_keywords.split(",") if k.strip())
    return dataclasses.replace(_PROBE_SAVE4, keywords=kws) if kws else _PROBE_SAVE4


def _offense(unit: Unit, probe: Unit, mods: CombatModifiers) -> float:
    return unit_damage_moments(unit, unit.models, probe, mods)[0] if unit.weapons else 0.0


def _defense(unit: Unit) -> float:
    return _effective_wounds(unit.health * unit.models, unit.save, unit.ward or _NO_WARD)


def apply_effect(unit: Unit, eff: EffectSpec, probe: Optional[Unit] = None,
                 mods: Optional[CombatModifiers] = None) -> Optional[Unit]:
    """Copie de `unit` avec l'effet appliqué, ou None s'il ne la concerne pas.

    « that weapon » (`chosen`) : l'effet va sur l'arme du périmètre où il rapporte le plus.
    """
    if eff.side != "friendly":
        return None
    wt = _weapon_transform(eff)
    if wt is not None:
        idx = [i for i, w in enumerate(unit.weapons) if weapon_in_scope(w, eff)]
        if not idx:
            return None
        if eff.weapon_scope == "chosen":
            probe = probe or _probe(eff)
            mods = mods or CombatModifiers()
            candidates = []
            for i in idx:
                ws = list(unit.weapons)
                ws[i] = wt(ws[i])
                candidates.append(dataclasses.replace(unit, weapons=ws))
            return max(candidates, key=lambda u: _offense(u, probe, mods))
        ws = [wt(w) if i in idx else w for i, w in enumerate(unit.weapons)]
        return dataclasses.replace(unit, weapons=ws)
    dt = _defensive_transform(eff)
    return dt(unit) if dt is not None else None


def encounter(unit: Unit, eff: EffectSpec) -> Optional[Encounter]:
    """Gain de l'effet sur ce châssis, ou None s'il ne s'y applique pas (ex. arme nommée absente)."""
    probe = _probe(eff)
    mods = CombatModifiers(attacker_charged="a chargé" in eff.requires or eff.kind == "charge_bonus")
    after = apply_effect(unit, eff, probe, mods)
    if after is None:
        return None
    return Encounter(
        off_before=_offense(unit, probe, mods), off_after=_offense(after, probe, mods),
        def_before=_defense(unit), def_after=_defense(after),
    )


# ----- receveurs + construction de la table --------------------------------------

_PLURALS = {"HEROES": "HERO", "MONSTERS": "MONSTER", "WIZARDS": "WIZARD", "PRIESTS": "PRIEST"}


def _parse_keywords(tokens: list[str], vocab: frozenset[str]) -> tuple[list[str], list[str]]:
    """Découpe des jetons MAJUSCULES en mots-clés connus (plus long d'abord) ; inconnus à part."""
    tokens = [_PLURALS.get(t, t) for t in tokens]
    found, unknown, i = [], [], 0
    while i < len(tokens):
        for j in range(len(tokens), i, -1):
            cand = " ".join(tokens[i:j])
            if cand in vocab:
                found.append(cand)
                i = j
                break
        else:
            unknown.append(tokens[i])
            i += 1
    return found, unknown


def matches_friendly_target(unit: Unit, phrase: str, vocab: frozenset[str]) -> bool:
    """L'unité satisfait-elle la restriction de cible amie `ability.friendly_target` ?

    Alternatives séparées par « or » ; « non-X » exclut ; MAJUSCULES = mots-clés exigés (tous) ;
    Casse De Titre = nom de charte. Un mot-clé absent de toute charte (ex. « PLEDGED TO KHORNE »,
    gagné en jeu) ne restreint rien : on ne sait pas qui le portera. `'*'` (analyseur v27, cible d'un effet
    écrite « friendly units » sans mot-clé) = toute unité amie.
    """
    if not phrase or phrase.strip() == "*":
        return True
    name = unit.name.lower()
    for alt in re.split(r"\s+or\s+", phrase):
        toks = [t for t in alt.split() if t.lower() not in ("unified", "anointed", "other", "damaged", "visible", "and")]
        excl, req, title = [], [], []
        k = 0
        while k < len(toks):
            t = toks[k]
            if t.startswith("non-"):
                run = [t[4:]]
                k += 1
                while k < len(toks) and toks[k].isupper() and not toks[k].startswith("non-") and \
                        " ".join(run + [toks[k]]) in vocab | {" ".join(run + toks[k:k + 3])}:
                    run.append(toks[k])
                    k += 1
                excl.extend(_parse_keywords(run, vocab)[0] or run)
                continue
            if t.isupper() or not any(ch.islower() for ch in t):
                req.append(t)
            else:
                title.append(t)
            k += 1
        kws, _unknown = _parse_keywords(req, vocab)
        if any(e in unit.keywords for e in excl):
            continue
        if not all(kw in unit.keywords for kw in kws):
            continue
        if title:
            want = " ".join(title).lower()
            if not (name == want or name.startswith(want) or want.startswith(name)):
                continue
        return True
    return False


def receivers(source_kind: str, scope: str, owner_kind: str, owner_name: str, army_units: list[Unit],
              friendly_target: str = "", vocab: frozenset[str] = frozenset(),
              excludes_self: bool = False) -> list[tuple[Unit, str]]:
    """Unités de l'armée qui peuvent recevoir l'effet, avec leur relation (`porteur`/`allié`).

    Aptitude de charte : `self` → le porteur ; portée amie → les unités de l'armée qui satisfont la
    restriction de cible (porteur compris). Règle de faction : trait/artefact/amélioration → les
    héros ; le reste → l'armée filtrée. Manifestations ignorées.
    """
    def ok(u: Unit) -> bool:
        return matches_friendly_target(u, friendly_target, vocab)

    if owner_kind == "warscroll":
        own = [u for u in army_units if u.name.lower() == owner_name.lower()]
        if scope == "self":
            return [(u, "porteur") for u in own]
        if scope in FRIENDLY_SCOPES:
            return [(u, "porteur" if u in own else "allié") for u in army_units
                    if ok(u) and not (excludes_self and u in own)]
        return []
    if source_kind == "manifestation":
        return []
    if source_kind in HERO_ONLY_SOURCES:
        heroes = [u for u in army_units if u.is_hero]
        if source_kind == "monstrous_trait":
            heroes = [u for u in heroes if "MONSTER" in u.keywords]
        if scope in ("self", "unknown"):
            return [(u, "porteur") for u in heroes]
        if scope in FRIENDLY_SCOPES:
            return [(u, "allié") for u in army_units if ok(u)]
        return []
    if scope in FRIENDLY_SCOPES or scope == "self":
        return [(u, "allié") for u in army_units if ok(u)]
    return []


ENCOUNTER_COLS = (
    "ability_uid", "seq", "unit_id", "relation", "source", "off_before", "off_after", "off_gain_pct", "off_gain_per_100",
    "def_before", "def_after", "def_gain_pct", "def_gain_per_100", "conditions", "duration",
)


def build_encounter_rows(con) -> tuple[list[tuple], dict[str, int]]:
    """Tuples `ENCOUNTER_COLS` pour toutes les rencontres effet ami × receveur + compteurs."""
    from ..persistence import repository

    units_by_army = repository.load_all_units_with_weapons(con)
    army_names = dict(con.execute("SELECT id, name FROM army").fetchall())
    by_faction = {army_names[aid]: [u for u in us if u.points > 0] for aid, us in units_by_army.items()}
    vocab = frozenset(k for us in by_faction.values() for u in us for k in u.keywords)

    eff_rows = con.execute(
        """SELECT e.ability_uid, e.seq, e.kind, e.stat, e.value, e.detail, e.side, e.weapon_scope, e.weapon_name,
                  e.includes_companion, e.target_keywords, e.target_condition, e.requires, e.duration,
                  a.source_kind, a.scope, coalesce(e.friendly_target, a.friendly_target), a.excludes_self
           FROM ability_effect e JOIN ability a ON a.uid = e.ability_uid
           WHERE e.side = 'friendly'"""
    ).fetchall()
    owners: dict[str, list[tuple]] = {}
    for uid, kind, name, faction in con.execute(
            "SELECT ability_uid, owner_kind, owner_name, faction_name FROM ability_owner").fetchall():
        owners.setdefault(uid, []).append((kind, name, faction))

    stats = {"effets": 0, "traduits": 0, "rencontres": 0, "sans_arme": 0}
    rows: list[tuple] = []
    seen: set[tuple] = set()
    for (uid, seq, kind, stat, value, detail, side, wscope, wname, comp, tkw, tcond, req, dur,
         source_kind, scope, ftarget, excl) in eff_rows:
        stats["effets"] += 1
        eff = EffectSpec(kind=kind, stat=stat or "", value=value or 0.0, detail=detail or "", side=side or "",
                         weapon_scope=wscope or "", weapon_name=wname or "", includes_companion=bool(comp),
                         target_keywords=tkw or "", target_condition=tcond or "", requires=req or "",
                         duration=dur or "")
        if not is_translatable(eff):
            continue
        stats["traduits"] += 1
        for owner_kind, owner_name, faction in owners.get(uid, []):
            source = owner_name if owner_kind == "warscroll" else f"{source_kind}: {owner_name}"
            for unit, rel in receivers(source_kind, scope, owner_kind, owner_name, by_faction.get(faction, []),
                                       ftarget or "", vocab, bool(excl)):
                key = (uid, seq, unit.id)
                if key in seen:
                    continue
                seen.add(key)
                enc = encounter(unit, eff)
                if enc is None:
                    stats["sans_arme"] += 1
                    continue
                per100 = 100.0 / unit.points
                og, dg = enc.off_gain_pct, enc.def_gain_pct
                rows.append((
                    uid, seq, unit.id, rel, source, round(enc.off_before, 3), round(enc.off_after, 3),
                    None if og is None else round(og, 1), round((enc.off_after - enc.off_before) * per100, 3),
                    round(enc.def_before, 2), round(enc.def_after, 2),
                    None if dg is None else round(dg, 1), round((enc.def_after - enc.def_before) * per100, 3),
                    eff.conditions, eff.duration,
                ))
    stats["rencontres"] = len(rows)
    return rows, stats

"""Couche 3 — les bons porteurs d'une optimisation (trait héroïque, artefact, amélioration, trait monstrueux).

Demande utilisateur (2026-11-20) : tester chaque optimisation sur **toutes les unités éligibles** de sa faction
et en sortir **les bons porteurs** (une liste classée, pas un seul gagnant). La couche 4 dira ensuite lequel
prendre dans une liste donnée.

* **Éligibilité** : `ability.bearer_restriction`, lue dans l'export Wahapedia (description du groupe, sinon du
  type : « HERO only », « Non-OGOR IRONSUNZ HERO only », « … can be given to non-Hero Blades of Khorne Infantry
  or Cavalry units », « Mancrusher Gargants », « … units with the STANDARD BEARER keyword »…), à défaut un
  HÉROS pour les traits héroïques/artefacts, un HÉROS MONSTRE pour un trait monstrueux. Les unités UNIQUE ne
  peuvent recevoir aucune optimisation (Core Rules p. 37, « UNIQUE units cannot be given enhancements »).
* **Gain** : les effets traduisibles appliqués ensemble au profil du porteur (`encounter.apply_effect`), mesurés
  au moteur ; `delta_combined` = gain de l'indicateur combiné √(dégâts × durabilité), en absolu (une optimisation
  ne coûte pas de points : +20 % sur un monstre à 400 pts vaut plus que sur un héros à 80).
* **Mariage** : D × S × F × A × R (`marriage.marriage_of`) sur ce porteur ; la valeur chiffrée n'applique que
  D × S (`Marriage.bearing`), le gain mesuré et la frise portant déjà l'amplification et le tempo.
* **Valeur** = delta_combined (gains d'attaque et de défense pondérés chacun par leur couverture sur la frise,
  `timeline`) × D × S. Les optimisations
  sans effet traduisible (bulles, sorts, mobilité…) n'ont pas de valeur chiffrée : leurs porteurs sont classés
  par mariage (tenir l'effet) puis par l'indicateur combiné du porteur.
"""

from __future__ import annotations

import re
from typing import Optional

from ...domain.models import Unit
from ...engine.combat import CombatModifiers
from .encounter import (
    _PLURALS,
    EffectSpec,
    apply_effect,
    is_translatable,
    parse_keywords,
    plan_offense,
    play_plan,
    probe_for_effect,
    unit_durability,
)
from .marriage import (
    ChassisProfile,
    chassis_profiles,
    incoming_damage,
    load_effects,
    marriage_of,
    receiver_reach,
    role_fit,
    share_melee_by_unit,
)

ENHANCEMENT_SOURCES = ("heroic_trait", "artefact", "enhancement", "monstrous_trait")
_UNIT_TYPES = ("INFANTRY", "CAVALRY", "MONSTER", "BEAST", "WAR MACHINE")


def _norm_kw(tok: str, vocab: frozenset[str]) -> str:
    t = _PLURALS.get(tok, tok)
    if t not in vocab and t.endswith("S") and t[:-1] in vocab:
        t = t[:-1]
    return t


def eligible(unit: Unit, restriction: str, source_kind: str, vocab: frozenset[str]) -> bool:
    """`unit` peut-elle recevoir cette optimisation ?"""
    if "UNIQUE" in unit.keywords:
        return False
    # « non- HERO non- MONSTER » : espace parasite après « non- » dans l'export Wahapedia
    r = re.sub(r"(?i)\bnon-\s+", "non-", (restriction or "").strip())
    if not r or r.lower().startswith("give your general"):
        if source_kind == "monstrous_trait":
            return unit.is_hero and "MONSTER" in unit.keywords
        return unit.is_hero

    excluded_names: list[str] = []
    m = re.search(r"\bexcluding (.+)$", r, re.I)
    if m:
        excluded_names = [n.strip().lower().rstrip("s") for n in re.split(r",| and ", m.group(1)) if n.strip()]
        r = r[: m.start()].strip(" ,")
    with_kw = ""
    m = re.search(r"\bwith the ([A-Z][A-Z ]+?) keyword", r)
    if m:
        with_kw = m.group(1).strip()
        r = r[: m.start()].strip()
    m = re.search(r"can (?:only )?be given to (.+)$", r, re.I)
    phrase = m.group(1) if m else re.sub(r"\s+on?ly\b.*$", "", r, flags=re.I)
    phrase = re.sub(r"\b(?:units?|models?)\b\.?$", "", phrase.strip(), flags=re.I).strip()

    if any(unit.name.lower().startswith(n) for n in excluded_names):
        return False
    if with_kw and with_kw not in unit.keywords:
        return False

    words = phrase.split()
    # Noms de charte au pluriel (« Mancrusher Gargants », « Cannonade Cogforts and Conqueror Cogforts ») :
    # aucun mot en MAJUSCULES ni « non-… ».
    if words and not any(w.isupper() or w.lower().startswith("non-") for w in words):
        names = [n.strip().lower().rstrip("s") for n in re.split(r",| and | or ", phrase) if n.strip()]
        return any(unit.name.lower().startswith(n) for n in names)

    up = phrase.upper()
    excl: list[str] = []
    for nm in re.findall(r"NON-([A-Z']+(?: MACHINE)?)", up):
        excl.append(_norm_kw(nm, vocab))
    up = re.sub(r"NON-[A-Z']+(?: MACHINE)?", " ", up)
    types = [t for t in _UNIT_TYPES if re.search(rf"\b{t}S?\b", up)]
    for t in _UNIT_TYPES:
        up = re.sub(rf"\b{t}S?\b", " ", up)
    toks = [_norm_kw(t, vocab) for t in re.split(r"\s+|\bOR\b|\bAND\b", up) if t and t not in ("OR", "AND")]
    required, _unknown = parse_keywords(toks, vocab)

    if any(k in unit.keywords for k in excl):
        return False
    if types and not any(t in unit.keywords for t in types):
        return False
    return all(k in unit.keywords for k in required)


def _combined(off: float, de: float) -> float:
    return (max(off, 0.0) * max(de, 0.0)) ** 0.5


def bearer_gain(unit: Unit, specs: list[EffectSpec]) -> Optional[tuple[float, float, float, float]]:
    """(off_avant, off_après, dur_avant, dur_après) avec les effets traduisibles appliqués ensemble, ou None."""
    specs = [s for s in specs if is_translatable(s)]
    if not specs:
        return None
    charged = any("a chargé" in s.requires or s.kind == "charge_bonus" for s in specs)
    mods = CombatModifiers(attacker_charged=charged)
    kws = ",".join(dict.fromkeys(k for s in specs for k in s.target_keywords.split(",") if k))
    probe = probe_for_effect(EffectSpec("none", target_keywords=kws))
    after, applied = unit, False
    for s in specs:
        nxt = apply_effect(after, s, probe, mods)
        if nxt is not None:
            after, applied = nxt, True
    if not applied:
        return None
    plan = play_plan(unit, probe, mods)
    return (
        plan_offense(unit, probe, mods, plan),
        plan_offense(after, probe, mods, plan),
        unit_durability(unit),
        unit_durability(after),
    )


def build_bearer_rows(con) -> list[tuple]:
    """Tuples `persistence.analysis_tables.BEARER_COLS` : chaque optimisation × chaque unité éligible de sa faction."""
    from ...persistence import repository
    from .realized import coverage

    by_id = repository.load_all_units_with_weapons(con)
    army_names = dict(con.execute("SELECT id, name FROM army").fetchall())
    by_faction = {army_names[aid]: [u for u in us if u.points > 0] for aid, us in by_id.items()}
    vocab = frozenset(k for us in by_faction.values() for u in us for k in u.keywords)
    sm = share_melee_by_unit(con)
    incoming = incoming_damage(con)
    effs = load_effects(con)
    profiles = chassis_profiles(con)
    recv = receiver_reach(con)
    specs: dict[str, list[EffectSpec]] = {}
    for uid, kind, stat, value, detail, side, wscope, wname, comp, tkw, tcond, req, dur in con.execute(
        """SELECT ability_uid, kind, stat, value, detail, side, weapon_scope, weapon_name, includes_companion,
                      target_keywords, target_condition, requires, duration FROM ability_effect"""
    ).fetchall():
        specs.setdefault(uid, []).append(
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
            )
        )
    comb = dict(
        con.execute(
            "SELECT unit_id, combined_per_100 * points / 100 FROM unit_realized r JOIN unit u ON u.id = r.unit_id"
        ).fetchall()
    )

    abil = con.execute(
        f"""SELECT DISTINCT a.uid, a.name, a.source_kind, o.faction_name, a.bearer_restriction, a.family, a.scope,
                   a.range_inches, a.frequency, a.turn_side, a.activation_prob, a.available_round
            FROM ability a JOIN ability_owner o ON o.ability_uid = a.uid
            WHERE a.source_kind IN ({",".join("'" + k + "'" for k in ENHANCEMENT_SOURCES)})
              AND coalesce(o.origin_kind, '') NOT IN ('spearhead', 'path_to_glory')"""
    ).fetchall()
    rows: list[tuple] = []
    for uid, name, kind, fac, restr, family, scope, rng, freq, tside, prob, avail in abil:
        e_list = effs.get(uid, [])
        durations = [e[4] for e in e_list if e[4]]
        dur = next(
            (d for d in ("bataille", "permanent", "conditionnelle") if d in durations),
            durations[0] if durations else "",
        )
        p_act = prob if prob is not None else 1.0
        for u in by_faction.get(fac, []):
            if not eligible(u, restr or "", kind, vocab):
                continue
            s_m = sm.get(u.id, 1.0)
            prof = profiles.get(u.id, ChassisProfile(share_melee=s_m))
            m = marriage_of(
                u,
                e_list,
                family or "autre",
                scope or "",
                rng,
                freq or "",
                s_m,
                incoming.get(u.id, (0.0, 0.0)),
                tside or "any",
                role=role_fit(family or "autre", prof, recv.get(uid)),
                chassis_profile=prof,
            )
            cov_off = coverage(freq or "", dur, avail, False, tside or "any", "off", s_m) * p_act
            cov_def = coverage(freq or "", dur, avail, False, tside or "any", "def", s_m) * p_act
            g = bearer_gain(u, specs.get(uid, []))
            og = dg = dc = val = None
            if g is not None:
                ob, oa, db, da = g
                og = round((oa / ob - 1) * 100, 1) if ob else None
                dg = round((da / db - 1) * 100, 1) if db else None
                # gain pondéré par la frise : l'attaque et la défense n'ont pas les mêmes demi-tours utiles
                dc = _combined(ob + cov_off * (oa - ob), db + cov_def * (da - db)) - _combined(ob, db)
                # gain mesuré sur CE porteur et pondéré par la frise : A et F y sont déjà, seul D × S s'applique
                val = round(dc * m.bearing, 3)
                dc = round(dc, 3)
            cov = cov_off if (og or 0) >= (dg or 0) else cov_def
            rows.append(
                (
                    uid,
                    name,
                    kind,
                    fac,
                    u.id,
                    og,
                    dg,
                    dc,
                    round(cov, 3),
                    round(m.p_trigger, 3),
                    round(m.survival, 3),
                    round(m.marriage, 3),
                    val,
                    round(comb.get(u.id) or 0.0, 3),
                    " | ".join(m.others) or None,
                )
            )
    return rows

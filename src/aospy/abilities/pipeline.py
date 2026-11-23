"""Orchestration : CSV Wahapedia → `AbilityAnalysis` (sans accès DB)."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

from .extract import extract, p_2d6
from .families import effect_family, main_family
from .models import AbilityAnalysis, Extraction, RawAbility
from .overrides import DEFAULT_OVERRIDES_PATH, apply_override, load_overrides
from .references import RESOLUTION_PASSES, pending_references, resolve_references
from .resources import RESOURCE_RATES  # noqa: F401  (réexport)
from .scoring import score
from .source import DEFAULT_DATA_DIR, load_raw_abilities
from .tags import tags_for

#: Incrémenter à chaque changement des règles d'extraction/notation : stocké en
#: base (`ability.analyzer_version`) pour savoir quelle version a produit une ligne.
ANALYZER_VERSION = 39


#: Rythmes des ressources de faction : `abilities.resources` (réexporté ici pour les appelants existants).


def resolve_resource_costs(raws: list[RawAbility], extractions: list[Extraction]) -> None:
    """Coût cumulé (chaîne de déblocage la moins chère) et round de disponibilité estimé.

    Le coût d'une aptitude « débloquable » inclut le moins cher de ses prérequis
    (eux-mêmes cumulés) ; disponibilité = 1 + ⌈coût / gain par round⌉ (points gagnés
    pendant les rounds précédents). Résolu par faction, noms insensibles à la casse.
    """
    by_key: dict[tuple[str, str], int] = {}
    for i, raw in enumerate(raws):
        if raw.cost_type.lower() in RESOURCE_RATES:
            fid = raw.owners[0].faction_id if raw.owners else ""
            by_key[(fid, raw.name.lower())] = i

    memo: dict[int, int] = {}

    def cumulative(i: int, seen: frozenset[int] = frozenset()) -> int:
        if i in memo:
            return memo[i]
        own = int(
            re.match(r"\d+", raws[i].cost_value or "0").group() if re.match(r"\d+", raws[i].cost_value or "") else 0
        )
        fid = raws[i].owners[0].faction_id if raws[i].owners else ""
        prereq = [
            by_key[(fid, n.lower())]
            for n in extractions[i].unlock_prereqs
            if (fid, n.lower()) in by_key and by_key[(fid, n.lower())] not in seen
        ]
        total = own + (min(cumulative(j, seen | {i}) for j in prereq) if prereq else 0)
        memo[i] = total
        return total

    for i in by_key.values():
        cost = cumulative(i)
        rate = RESOURCE_RATES[raws[i].cost_type.lower()]
        extractions[i].resource_cost = cost
        extractions[i].available_round = 1 + math.ceil(cost / rate) if cost else 1


#: Rôles Wahapedia d'une unité « normale » ; tout autre rôle de warscroll (Manifestation,
#: Endless Spell, nom d'un domaine générique…) est une manifestation à invoquer.
_NON_MANIFESTATION_ROLES = frozenset(
    {
        "Infantry",
        "Infantry Hero",
        "Cavalry",
        "Cavalry Hero",
        "Beast",
        "Beast Hero",
        "Monster",
        "Monster Hero",
        "War Machine",
        "War Machine Hero",
        "Hero",
        "Regiment of Renown",
        "Faction Terrain",
        "",
    }
)
#: Valeur de lancement supposée quand le sort d'invocation n'est pas retrouvé.
DEFAULT_SUMMON_VALUE = 7
#: Une manifestation invoquée reste en jeu plusieurs tours : l'échec d'invocation ne pèse
#: que pour moitié sur chaque utilisation (facteur = 1 − (1 − P(invocation)) × poids).
SUMMON_FAILURE_WEIGHT = 0.5
MANIFESTATION_PLACE_PENALTY = 0.25  # il faut l'invoquer et la placer
MANIFESTATION_MELEE_PENALTY = 0.5  # … puis l'amener au corps à corps


def resolve_manifestations(
    raws: list[RawAbility], extracted: list[tuple[Extraction, float]]
) -> list[tuple[Extraction, float]]:
    """Aptitude portée par une manifestation : fiabilité × P(invocation), mise en place pénalisée.

    La valeur du sort « SUMMON <nom> » est cherchée parmi toutes les aptitudes ;
    à défaut `DEFAULT_SUMMON_VALUE`. Une aptitude passive ou de placement
    (« Summon ») n'est pas concernée par le coût de sa propre invocation.
    """
    summon = {
        r.name.lower().removeprefix("summon ").strip(): r.cost_value
        for r in raws
        if r.name.lower().startswith("summon ") and r.cost_value
    }
    out = []
    for raw, (ex, penalty) in zip(raws, extracted):
        carriers = [o for o in raw.owners if o.owner_kind == "warscroll"]
        if carriers and all(o.role not in _NON_MANIFESTATION_ROLES for o in carriers):
            name = carriers[0].owner_name.lower()
            cv = summon.get(name)
            value = int(re.match(r"\d+", cv).group()) if cv and re.match(r"\d+", cv) else DEFAULT_SUMMON_VALUE
            prob = p_2d6(value)
            factor = 1 - (1 - prob) * SUMMON_FAILURE_WEIGHT
            ex.activation_prob = round(ex.activation_prob * factor, 4)
            ex.activation_notes.insert(
                0, f"manifestation à invoquer (sort à {value} : {prob:.0%}, reste en jeu → facteur {factor:.0%})"
            )
            if re.search(r"in combat with this|combat range of this", raw.declare + " " + raw.effect):
                ex.conditions.append("manifestation à amener au corps à corps")
                penalty += MANIFESTATION_PLACE_PENALTY + MANIFESTATION_MELEE_PENALTY
            else:
                ex.conditions.append("manifestation à invoquer et placer")
                penalty += MANIFESTATION_PLACE_PENALTY
        out.append((ex, penalty))
    return out


def _finish(raw: RawAbility, ex: Extraction, penalty: float) -> AbilityAnalysis:
    sc = score(ex, penalty, raw.cost_type, raw.is_reaction, raw.effect)
    return AbilityAnalysis(raw, ex, sc, tags_for(raw, ex, sc), understood=bool(ex.effects))


def analyze_one(raw: RawAbility) -> AbilityAnalysis:
    """Analyse isolée (sans résolution des chaînes de ressource, qui exige toute la faction)."""
    ex, penalty = extract(raw)
    return _finish(raw, ex, penalty)


def analyze_all(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    overrides_path: str | Path = DEFAULT_OVERRIDES_PATH,
) -> tuple[list[AbilityAnalysis], list[str]]:
    """Toutes les aptitudes analysées + uids d'overrides orphelins."""
    overrides = load_overrides(overrides_path)
    raws = load_raw_abilities(data_dir)
    extracted = [extract(raw) for raw in raws]
    resolve_resource_costs(raws, [ex for ex, _ in extracted])
    extracted = resolve_manifestations(raws, extracted)
    out = [_finish(raw, ex, penalty) for raw, (ex, penalty) in zip(raws, extracted)]
    # v34 (B) : effets qui renvoient à d'autres aptitudes (méta, statut, décor, enhancement) → renotés
    pending = pending_references(out)
    for _ in range(RESOLUTION_PASSES):
        left = resolve_references(out, pending)
        for i in pending:
            out[i] = _finish(raws[i], out[i].extraction, extracted[i][1])
        pending = left
        if not pending:
            break
    out = [apply_override(a, overrides[a.raw.uid]) if a.raw.uid in overrides else a for a in out]
    known = {a.raw.uid for a in out}
    return out, sorted(set(overrides) - known)


def to_rows(
    analyses: list[AbilityAnalysis], analyzed_at: datetime | None = None
) -> tuple[list[tuple], list[tuple], list[tuple], list[tuple]]:
    """`AbilityAnalysis` → tuples des 4 tables (ordre de `repository.ABILITY_*_COLS`)."""
    when = analyzed_at or datetime.now()
    abilities, owners, tags, effects = [], [], [], []
    for a in analyses:
        r, ex, sc = a.raw, a.extraction, a.score
        first = r.owners[0] if r.owners else None
        abilities.append(
            (
                r.uid,
                r.name,
                r.source_kind,
                r.group_name or None,
                first.faction_id if first else None,
                first.faction_name if first else None,
                r.condition,
                r.phase,
                r.wahapedia_type,
                r.is_reaction,
                r.keywords or None,
                r.cost_type or None,
                r.cost_value or None,
                r.declare or None,
                r.effect,
                ex.frequency,
                ex.turn,
                ex.scope,
                ex.range_inches,
                ex.wholly_within,
                ex.activation_prob,
                ex.variance,
                ex.scales_with_size,
                ",".join(ex.target_keywords) or None,
                " | ".join(ex.conditions) or None,
                sc.ease,
                sc.power,
                sc.reliability,
                sc.interaction,
                sc.verdict,
                "\n".join(sc.rationale),
                a.understood,
                a.overridden,
                ANALYZER_VERSION,
                when,
                ex.resource_cost,
                ex.available_round,
                ex.friendly_target or None,
                ex.excludes_self,
                main_family(effect_family(e, ex.scope) for e in ex.effects),
                r.bearer_restriction or None,
                ex.resource_usage,
            )
        )
        seen = set()
        for o in r.owners:
            key = (o.faction_id, o.owner_kind, o.owner_name)
            if key not in seen:
                seen.add(key)
                owners.append(
                    (
                        r.uid,
                        o.faction_id,
                        o.faction_name,
                        o.owner_kind,
                        o.owner_name,
                        o.warscroll_id,
                        o.origin_kind or None,
                        o.origin_name or None,
                        o.category or None,
                    )
                )
        tags.extend((r.uid, t) for t in a.tags)
        effects.extend(
            (
                r.uid,
                i,
                e.kind,
                e.stat or None,
                float(e.value),
                e.dice or None,
                e.side or None,
                e.detail or None,
                e.weapon_scope or None,
                e.weapon_name or None,
                e.includes_companion,
                e.target_keywords or None,
                e.target_condition or None,
                e.requires or None,
                e.duration or None,
                effect_family(e, ex.scope),
                e.friendly_target or None,
                e.option_group or None,
            )
            for i, e in enumerate(ex.effects)
        )
    return abilities, owners, tags, effects

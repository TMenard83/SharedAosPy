"""Situe une unité hypothétique (ex. modifiée par un bonus, cf. `bonus.py`)
dans les mêmes classements combat/coût que `reports/best_unites.py`/`best_heros.py`,
en direct — sans persister de duel ni régénérer de PDF. Cœur de `app.py`.

Réplique la méthodologie de `reports/aggregate.py` (attaquant lu au plancher
pessimiste 66%, défenseur à l'espérance, `DuelRules(double_shoot=True,
charge_move_threshold=True)` — les défauts effectifs de la CLI
`aospy unit benchmark-all`, cf. `cli/commands.py::_duel_rules`) et de
`reports/best_unites.py::compute_ranked()` (score combiné = z-scores ROI +
sous-cotation + impact, `cost_common.combined_score`), mais lit le pool de combat
*live* depuis `unit_benchmark` (`repository.get_ranking_pool`) plutôt que depuis
son export JSON figé (`scratch/per_unit_nocharge_floor66_TM.json`) — l'unité
hypothétique n'y figurant jamais, un snapshot statique ne suffirait pas.
"""

from __future__ import annotations

import dataclasses
import statistics
from dataclasses import dataclass

import duckdb
import numpy as np

from ..analysis import cost_model
from ..analysis.features import UnitFeatures, compute_features
from ..domain.models import Unit
from ..orchestration.benchmark import DuelRules, benchmark_attacker
from ..persistence import repository

#: Mêmes règles optionnelles que celles effectivement utilisées pour peupler
#: `unit_benchmark` par la CLI (`_duel_rules` par défaut : `--rule-double-shoot`/
#: `--rule-charge-threshold` valent `True` par défaut sur `benchmark-all`) — à
#: méthodologie différente, un classement live ne serait pas comparable au pool.
RANKING_DUEL_RULES = DuelRules(double_shoot=True, charge_move_threshold=True)

#: Cf. `reports/best_unites.py`/`best_heros.py` : écarte les prédictions de coût
#: trop faibles (dénominateur proche de zéro rendrait le résidu relatif peu fiable).
MIN_PREDICTED = 40.0
ROI_WEIGHT = 2.0
IMBALANCE_WEIGHT = 1.0
IMPACT_WEIGHT = 1.0


@dataclass(frozen=True)
class CombatRow:
    """Métriques de combat d'une unité contre tout le reste de la base, mêmes
    colonnes que `repository.get_ranking_pool` pour une unité *non persistée*."""

    avg_roi_pct: float
    avg_pts_net: float
    roi_floor95_pct: float
    roi_floor66_pct: float
    roi_floor20_pct: float
    avg_floor_roi_pct: float


@dataclass(frozen=True)
class RankedNeighbor:
    rank: int
    name: str
    army: str
    score: float
    is_target: bool = False


@dataclass(frozen=True)
class WhatIfResult:
    """Où l'unité (hypothétique ou réelle) se classe dans le pool troupe/héros."""

    rank: int
    total: int
    score: float
    combat: CombatRow
    predicted_points: float
    residual_pct: float
    neighbors: list[RankedNeighbor]


def live_combat_row(
    con: duckdb.DuckDBPyConnection, unit: Unit, *, include_heroes: bool = True,
) -> CombatRow:
    """Duel `unit` contre toutes les unités des autres armées (méthodologie de
    `reports/aggregate.py`) et agrège en direct — fonctionne pour une `Unit` en
    mémoire, jamais persistée (aucune écriture DB)."""
    results = benchmark_attacker(
        con, unit,
        exclude_army_id=unit.army_id,
        include_heroes=include_heroes,
        mode_a="floor66", mode_b="mean",
        rules=RANKING_DUEL_RULES,
    )
    if not results:
        return CombatRow(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    rois = np.array([r.roi for r in results], dtype=float)
    avg_pts_net = statistics.mean(r.pts_net for r in results)
    p95, p66, p20 = np.percentile(rois, [5, 34, 80], method="linear") * 100.0
    avg_floor = (p95 + p66 + p20) / 3.0
    return CombatRow(
        avg_roi_pct=float(rois.mean() * 100.0),
        avg_pts_net=float(avg_pts_net),
        roi_floor95_pct=float(p95),
        roi_floor66_pct=float(p66),
        roi_floor20_pct=float(p20),
        avg_floor_roi_pct=float(avg_floor),
    )


def _z_pool(pool_rows: list[dict], cost_by_id: dict[int, "cost_model.UnitResidual"]) -> list[dict]:
    """Réplique `best_unites.compute_ranked()`/`best_heros.compute_ranked()` :
    joint pool de combat + résidu de coût par `unit_id`, filtre, calcule les
    z-scores et le score combiné. `pool_rows` peut contenir une ligne
    hypothétique (`unit_id=None`) portée par `cost_by_id[None]` en plus des
    résidus réels."""
    joined_src = [
        (row, cost_by_id[row["unit_id"]])
        for row in pool_rows
        if row["unit_id"] in cost_by_id and cost_by_id[row["unit_id"]].predicted >= MIN_PREDICTED
    ]
    roi_values = [c["avg_floor_roi_pct"] for c, _ in joined_src]
    resid_values = [r.residual_pct for _, r in joined_src]
    impact_values = [c["avg_pts_net"] for c, _ in joined_src]
    roi_mean, roi_std = statistics.mean(roi_values), statistics.pstdev(roi_values)
    resid_mean, resid_std = statistics.mean(resid_values), statistics.pstdev(resid_values)
    impact_mean, impact_std = statistics.mean(impact_values), statistics.pstdev(impact_values)

    def z(value, mean, std):
        return (value - mean) / std if std else 0.0

    from ..reports.cost_common import combined_score

    joined = []
    for c, r in joined_src:
        z_roi = z(c["avg_floor_roi_pct"], roi_mean, roi_std)
        z_undercost = -z(r.residual_pct, resid_mean, resid_std)
        z_impact = z(c["avg_pts_net"], impact_mean, impact_std)
        joined.append({
            "unit_id": r.unit_id, "name": c["name"], "army": c["army"],
            "residual_pct": r.residual_pct,
            "score": combined_score(
                [(z_roi, ROI_WEIGHT), (z_undercost, 1.0), (z_impact, IMPACT_WEIGHT)],
                IMBALANCE_WEIGHT,
            ),
        })
    joined.sort(key=lambda r: r["score"], reverse=True)
    for rank, r in enumerate(joined, start=1):
        r["rank"] = rank
    return joined


def rank_against_pool(
    con: duckdb.DuckDBPyConnection, unit: Unit, *, neighbors: int = 3,
) -> WhatIfResult:
    """Classe `unit` (hypothétique ou réelle) dans le même pool que
    `reports/best_unites.py`/`best_heros.py::compute_ranked()` (troupes et héros
    restent deux pools distincts, cf. leurs modèles de coût ajustés séparément).

    Nécessite `unit_benchmark` peuplée (`aospy unit benchmark-all --charge none
    --attacker-mode floor66 --defender-mode mean --include-heroes`) pour le reste
    du pool — lève `ValueError` sinon.
    """
    combat = live_combat_row(con, unit)

    frame = cost_model.feature_frame(con)
    is_hero = unit.is_hero
    segment_frame = frame.query("is_hero == @is_hero").copy()
    cost_result = cost_model.fit_cost_model_factorial(con, frame=segment_frame)
    cost_by_id: dict = {r.unit_id: r for r in cost_result.residuals}

    # `army_name`/`grand_alliance` sont résolus depuis la DB par `all_features`
    # (pas `compute_features` lui-même, pur) — un `army_name` vide serait une
    # modalité catégorielle absente de l'entraînement, que `predict_one` ne
    # saurait pas encoder (cf. `features.py::all_features`).
    army = next((a for a in repository.list_armies(con) if a.id == unit.army_id), None)
    hyp_features = dataclasses.replace(
        compute_features(unit),
        army_name=army.name if army else "?",
        grand_alliance=army.grand_alliance if army else "Order",
    )
    predicted = cost_model.predict_one(cost_result, hyp_features)
    residual = unit.points - predicted
    residual_pct = (residual / predicted * 100.0) if predicted else 0.0
    hyp_residual = cost_model.UnitResidual(
        unit_id=None, army_id=unit.army_id, name=unit.name, points=unit.points,
        predicted=predicted, residual=residual, residual_pct=residual_pct,
    )
    cost_by_id[None] = hyp_residual

    pool_rows = repository.get_ranking_pool(con)
    pool_rows = [r for r in pool_rows if r["is_hero"] == unit.is_hero and r["unit_id"] != unit.id]
    if not pool_rows:
        raise ValueError(
            "pool de classement vide — lancer `aospy unit benchmark-all --charge none "
            "--attacker-mode floor66 --defender-mode mean --include-heroes` d'abord"
        )
    pool_rows.append({
        "unit_id": None, "name": unit.name, "army": "", "grand_alliance": "",
        "points": unit.points, "is_hero": unit.is_hero,
        "avg_roi_pct": combat.avg_roi_pct, "avg_pts_net": combat.avg_pts_net,
        "roi_floor95_pct": combat.roi_floor95_pct, "roi_floor66_pct": combat.roi_floor66_pct,
        "roi_floor20_pct": combat.roi_floor20_pct, "avg_floor_roi_pct": combat.avg_floor_roi_pct,
    })

    joined = _z_pool(pool_rows, cost_by_id)
    if not joined:
        raise ValueError(
            "pool de classement vide — lancer `aospy unit benchmark-all --charge none "
            "--attacker-mode floor66 --defender-mode mean --include-heroes` d'abord"
        )

    target_idx = next(i for i, r in enumerate(joined) if r["unit_id"] is None)
    target = joined[target_idx]
    lo, hi = max(0, target_idx - neighbors), min(len(joined), target_idx + neighbors + 1)
    neighbor_rows = [
        RankedNeighbor(rank=r["rank"], name=r["name"], army=r["army"], score=r["score"],
                        is_target=(i == target_idx))
        for i, r in enumerate(joined[lo:hi], start=lo)
    ]

    return WhatIfResult(
        rank=target["rank"], total=len(joined), score=target["score"],
        combat=combat, predicted_points=predicted, residual_pct=residual_pct,
        neighbors=neighbor_rows,
    )

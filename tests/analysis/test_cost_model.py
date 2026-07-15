"""Tests du modèle de coût (cost_model.py) — cœur pur, sans DuckDB."""

from __future__ import annotations

import pytest

pytest.importorskip("statsmodels")

from aospy.analysis.cost_model import (
    Coefficient,
    CostModelResult,
    UnitResidual,
    feature_frame,
    fit_cost_model,
    fit_segmented,
)
from aospy.analysis.features import UnitFeatures


def _uf(i: int, **overrides) -> UnitFeatures:
    base = dict(
        unit_id=i, army_id=1, name=f"U{i}", points=100, is_hero=False,
        dmg_vs_save2=1.0, dmg_vs_save4=2.0, dmg_vs_nosave=3.0,
        dmg_ranged_vs_nosave=0.0, dmg_pen=0.33, dmg_cv_vs_save4=0.5, charge_bonus_save2=0.0,
        wounds_total=10, save_num=4, ward_num=7, move=5, control=1, unit_size=5,
        grand_alliance="Order", army_name="TestArmy", weapon_mix="melee",
        unit_type="INFANTRY", is_flying=False, wizard_level=0, priest_level=0, is_unique=False,
        crit_type="none",
    )
    base.update(overrides)
    return UnitFeatures(**base)


def _training_set() -> list[UnitFeatures]:
    # 30 unités (pas quelques-unes) : un jeu plus large dilue l'effet de levier
    # d'un seul point sous/sur-cotée injecté par les tests ci-dessous (sinon un
    # unique outlier peut à lui seul faire pivoter la droite de régression).
    # Seuls dmg_vs_nosave/wounds_total varient (et déterminent linéairement les
    # points) : les autres caractéristiques restent constantes pour ne pas
    # introduire de corrélation accidentelle avec l'indice `i`. `dmg` varie en
    # cycle (pas linéairement en `i`) pour ne pas être parfaitement colinéaire
    # avec `wounds` — une colinéarité parfaite laisserait l'OLS un degré de
    # liberté libre qui absorbe exactement un futur point aberrant injecté par
    # les tests (au lieu de le faire ressortir comme résidu).
    units = []
    for i in range(30):
        dmg = 1.0 + (i % 7) * 0.8
        wounds = 8 + i
        points = round(10 * dmg + 3 * wounds + 20)
        units.append(_uf(i, dmg_vs_nosave=dmg, wounds_total=wounds, points=points, is_hero=(i % 4 == 0)))
    return units


def test_feature_frame_has_one_row_per_unit():
    frame = feature_frame(features=_training_set())
    assert len(frame) == 30
    assert "points" in frame.columns


def test_feature_frame_excludes_free_companion_units():
    # Compagnon gratuit d'un héros payé (ex. Neave's Companions) : points=0,
    # pas un point d'entraînement/résidu valable (cf. docstring de feature_frame).
    companion = _uf(500, points=0)
    frame = feature_frame(features=[*_training_set(), companion])
    assert len(frame) == 30
    assert 500 not in frame["unit_id"].values


def test_fit_cost_model_recovers_near_perfect_fit_on_linear_data():
    result = fit_cost_model(frame=feature_frame(features=_training_set()))
    assert result.r_squared > 0.99
    assert result.n_obs == 30


def test_fit_cost_model_raises_on_too_few_units():
    with pytest.raises(ValueError):
        fit_cost_model(frame=feature_frame(features=_training_set()[:5]))


def _residual(unit_id, predicted, residual_pct):
    return UnitResidual(
        unit_id=unit_id, army_id=1, name=f"U{unit_id}", points=100,
        predicted=predicted, residual=predicted * residual_pct / 100, residual_pct=residual_pct,
    )


def _dummy_result(residuals: list[UnitResidual]) -> CostModelResult:
    coef = Coefficient("const", 0.0, 0.0, 1.0)
    return CostModelResult(
        features=[], intercept=coef, coefficients=[], r_squared=1.0,
        adj_r_squared=1.0, n_obs=len(residuals), residuals=residuals,
    )


def test_undercosted_sorts_by_most_negative_residual_pct():
    result = _dummy_result([
        _residual(1, 100.0, -5.0),
        _residual(2, 100.0, -40.0),
        _residual(3, 100.0, 10.0),
    ])
    top = result.undercosted(n=2)
    assert [r.unit_id for r in top] == [2, 1]


def test_overcosted_sorts_by_most_positive_residual_pct():
    result = _dummy_result([
        _residual(1, 100.0, -5.0),
        _residual(2, 100.0, 60.0),
        _residual(3, 100.0, 10.0),
    ])
    top = result.overcosted(n=2)
    assert [r.unit_id for r in top] == [2, 3]


def test_undercosted_filters_out_low_predicted_units():
    result = _dummy_result([
        _residual(1, 5.0, -90.0),  # prédiction trop faible : dénominateur non fiable
        _residual(2, 100.0, -20.0),
    ])
    top = result.undercosted(min_predicted=40.0)
    assert [r.unit_id for r in top] == [2]


def test_fit_cost_model_flags_a_clearly_underpriced_unit():
    units = _training_set()
    # Copie d'une unité normale mais vendue à une fraction de son prix prédit :
    # doit ressortir comme nettement sous-cotée (résidu négatif marqué), sans
    # exiger qu'elle soit le rang #1 absolu (un seul outlier parmi 30 points
    # propres influence légèrement le reste de l'ajustement OLS).
    bargain = _uf(999, dmg_vs_nosave=8.0, wounds_total=35, points=20, is_hero=False)
    result = fit_cost_model(frame=feature_frame(features=[*units, bargain]))
    bargain_residual = next(r for r in result.residuals if r.unit_id == 999)
    assert bargain_residual.residual < 0
    assert bargain_residual.residual_pct < -30.0


def test_fit_segmented_splits_by_is_hero():
    units = _training_set()
    results = fit_segmented(frame=feature_frame(features=units))
    assert set(results) <= {"hero", "troupe"}
    n_hero = sum(1 for u in units if u.is_hero)
    n_troupe = len(units) - n_hero
    if "hero" in results:
        assert results["hero"].n_obs == n_hero
    if "troupe" in results:
        assert results["troupe"].n_obs == n_troupe

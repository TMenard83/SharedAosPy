"""Modèle de coût — régression ``points ~ features`` et résidus.

Port du principe de StatHammer (voir son `cost_model.py`) sur le vecteur de
caractéristiques natif d'aospy (`features.py`). On ajuste une régression
linéaire interprétable (OLS) des points d'une unité sur son profil, pour
répondre à deux questions :

* les **coefficients** (avec p-value) : comment le prix est-il construit —
  combien vaut, en points, un dégât attendu de plus, un point de vie, une
  case de mobilité… ?
* le **résidu** (points réels − points prédits) : quelles unités sont
  **sous-cotées** ? Un résidu nettement négatif = l'unité coûte *moins* que
  ne le prédit son profil → bonne affaire.

Périmètre volontairement plus restreint que StatHammer : pas d'axe
« puissance d'aptitudes » (aospy ne stocke pas le texte des aptitudes par
unité, seulement un tag Crit par arme) et pas de second avis Gradient
Boosting — voir la note de `features.py` sur les limites du schéma aospy.

Dépendance optionnelle : ``pip install -e ".[analysis]"`` (pandas, statsmodels).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import duckdb

from .features import UnitFeatures, all_features

#: Prédicteurs par défaut. ``is_hero`` n'y figure pas : c'est la clé de
#: segmentation de `fit_segmented`, pas un prédicteur continu.
MODEL_FEATURES: tuple[str, ...] = (
    "unit_size",
    "dmg_vs_nosave",
    "dmg_ranged_vs_nosave",
    "dmg_pen",
    "dmg_cv_vs_save4",
    "wounds_total",
    "save_num",
    "ward_num",
    "move",
    "control",
)

#: Segments de prix : GW chiffre héros et troupes selon des logiques distinctes
#: (durabilité premium côté héros, stats brutes + rabais de volume côté troupe).
SEGMENTS: dict[str, str] = {"hero": "is_hero == True", "troupe": "is_hero == False"}


@dataclass(frozen=True)
class Coefficient:
    """Un coefficient de la régression : effet en points d'une unité de la feature."""

    name: str
    coef: float
    std_err: float
    p_value: float


@dataclass(frozen=True)
class UnitResidual:
    """Écart entre points réels et points prédits pour une unité.

    ``residual = points − predicted`` ; négatif ⇒ sous-costée (coûte moins que
    prédit). ``residual_pct = residual / predicted × 100`` (lecture relative).
    """

    unit_id: int | None
    army_id: int
    name: str
    points: int
    predicted: float
    residual: float
    residual_pct: float


@dataclass
class CostModelResult:
    """Résultat ajusté : qualité, coefficients et résidus par unité."""

    features: list[str]
    intercept: Coefficient
    coefficients: list[Coefficient]
    r_squared: float
    adj_r_squared: float
    n_obs: int
    residuals: list[UnitResidual] = field(default_factory=list)

    def undercosted(self, n: int = 20, *, min_predicted: float = 40.0) -> list[UnitResidual]:
        """Unités les plus sous-cotées : résidu relatif le plus négatif.

        On écarte les prédictions trop faibles (``min_predicted``) pour éviter
        qu'un ``residual_pct`` n'explose sur un dénominateur proche de zéro.
        """
        pool = [r for r in self.residuals if r.predicted >= min_predicted]
        return sorted(pool, key=lambda r: r.residual_pct)[:n]

    def overcosted(self, n: int = 20, *, min_predicted: float = 40.0) -> list[UnitResidual]:
        """Unités les plus sur-cotées : résidu relatif le plus positif."""
        pool = [r for r in self.residuals if r.predicted >= min_predicted]
        return sorted(pool, key=lambda r: r.residual_pct, reverse=True)[:n]


def feature_frame(con: duckdb.DuckDBPyConnection | None = None, *, features: list[UnitFeatures] | None = None):
    """DataFrame d'entraînement : une ligne par unité. Nécessite pandas.

    Les unités à ``points <= 0`` sont écartées : ce sont des figurines gratuites
    embarquées par un héros payé (ex. compagnons de Neave, Shadow Queen de
    Morathi — cf. `bundles.py` côté StatHammer, non porté ici). Sans profil de
    prix propre, elles ne sont ni de bons points d'entraînement ni de bonnes
    candidates au résidu (leur résidu serait mécaniquement ≈ -100 %).
    """
    import pandas as pd

    if features is None:
        if con is None:
            raise ValueError("feature_frame nécessite `con` ou `features`")
        features = all_features(con)
    return pd.DataFrame([vars(f) for f in features if f.points > 0])


def fit_cost_model(
    con: duckdb.DuckDBPyConnection | None = None,
    features: tuple[str, ...] | list[str] = MODEL_FEATURES,
    *,
    frame=None,
) -> CostModelResult:
    """Ajuste l'OLS ``points ~ features`` et calcule les résidus par unité.

    ``frame`` permet d'injecter un DataFrame prêt (tests, segments) ; sinon il
    est construit depuis la base. Lève ``ValueError`` si le jeu est trop petit.
    """
    import statsmodels.api as sm

    if frame is None:
        frame = feature_frame(con)
    feats = list(features)
    if len(frame) <= len(feats) + 1:
        raise ValueError(f"jeu insuffisant ({len(frame)} unités) pour {len(feats)} prédicteurs")

    frame = frame.reset_index(drop=True)
    # Une feature constante sur le jeu (ex. `ward_num` si aucune unité n'a de ward)
    # rend la matrice singulière : on la retire de l'ajustement.
    feats = [f for f in feats if frame[f].astype(float).std() > 0]

    x = sm.add_constant(frame[feats].astype(float))
    y = frame["points"].astype(float)
    model = sm.OLS(y, x).fit()

    predicted = model.predict(x)
    resid = y - predicted
    residuals = [
        UnitResidual(
            unit_id=row["unit_id"],
            army_id=row["army_id"],
            name=row["name"],
            points=int(row["points"]),
            predicted=float(predicted[i]),
            residual=float(resid[i]),
            residual_pct=float(resid[i] / predicted[i] * 100) if predicted[i] else 0.0,
        )
        for i, row in frame.iterrows()
    ]

    coefs = [
        Coefficient(name, float(model.params[name]), float(model.bse[name]), float(model.pvalues[name]))
        for name in feats
    ]
    intercept = Coefficient(
        "const", float(model.params["const"]), float(model.bse["const"]), float(model.pvalues["const"]),
    )

    return CostModelResult(
        features=feats,
        intercept=intercept,
        coefficients=coefs,
        r_squared=float(model.rsquared),
        adj_r_squared=float(model.rsquared_adj),
        n_obs=int(model.nobs),
        residuals=residuals,
    )


def fit_segmented(
    con: duckdb.DuckDBPyConnection | None = None,
    features: tuple[str, ...] | list[str] = MODEL_FEATURES,
    *,
    frame=None,
) -> dict[str, CostModelResult]:
    """Ajuste un modèle de coût par segment (``hero`` / ``troupe``, clé ``is_hero``).

    Renvoie un dict segment → ``CostModelResult`` ; un segment trop petit est
    omis avec un avertissement plutôt que de lever une exception.
    """
    if frame is None:
        frame = feature_frame(con)
    out: dict[str, CostModelResult] = {}
    for name, query in SEGMENTS.items():
        sub = frame.query(query)
        try:
            out[name] = fit_cost_model(features=features, frame=sub.copy())
        except ValueError as exc:
            warnings.warn(f"segment '{name}' ignoré : {exc}", stacklevel=2)
    return out

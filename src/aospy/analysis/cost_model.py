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
#: ``dmg_vs_save6`` (pool de dégâts bruts mêlée+tir) a été retiré au profit du seul
#: ``dmg_ranged_vs_save6`` : `analysis/experiments/melee_ranged_split.py` montre que
#: `dmg_vs_save6` et `dmg_ranged_vs_save6` étaient déjà mécaniquement colinéaires
#: (le second est un sous-ensemble exact du premier), et qu'une fois reparamétrés en
#: deux pools disjoints mêlée/tir, le pool mêlée seul (`dmg_melee_vs_save6`) n'a
#: aucun effet-prix distinguable de zéro (p=0.65) — probablement déjà absorbé par
#: `dmg_vs_save2`/`effective_wounds` — alors que le pool tir reste significatif
#: (p=0.004-0.06 selon la variante). Retirer le pool mêlée du modèle laisse le R²
#: ajusté inchangé, voire légèrement meilleur (0.9173 → 0.9175).
#: ``dmg_vs_save2`` (dégât absolu contre une save 2+) remplace l'ancien ``dmg_pen``
#: (ratio sans dimension dmg_vs_save2/dmg_vs_save6) : le ratio est aveugle à la
#: magnitude — un profil à dégât quasi nul avec 100 % de rend obtenait le même score
#: qu'un gros cogneur avec 100 % de rend. `dmg_vs_save2` grandit avec les deux à la
#: fois, plus fidèle à ce que GW valorise en points. Essais comparatifs dans
#: `analysis/experiments/dmg_pen_weighted.py` (R² ajusté 0.8765 → 0.8794) ; deux
#: variantes par ligne d'arme (moyenne simple, moyenne pondérée par le nombre
#: d'attaques) ont aussi été testées (`scratch/experiment_dmg_pen_lineavg*.py`) et
#: font moins bien que la somme sur les lignes — la moyenne dilue le poids des
#: lignes à peu de porteurs, la somme (ce que fait `dmg_vs_save2`) pondère chaque
#: ligne exactement par son dégât réel.
#: ``charge_bonus_save2`` (supplément de ``dmg_vs_save2`` apporté par un texte d'arme
#: `Charge (+N <Stat>)`) rejoint ces prédicteurs suite à `analysis/experiments/weapon_tags.py` :
#: la magnitude est significative (+11.7 pts par point de dégât de charge, p=0.001) alors
#: qu'un simple indicateur de présence (`has_charge`) ne l'était pas (p=0.150) — même
#: enseignement que le remplacement `dmg_pen`→`dmg_vs_save2` ci-dessus, la magnitude
#: explique le prix, pas la présence. `Anti-<MOT-CLÉ>` a été testé dans le même essai
#: (présence et magnitude) et écarté : ni l'un ni l'autre n'étaient significatifs.
#: ``effective_wounds`` remplace le trio ``wounds_total``/``save_num``/``ward_num`` : au lieu
#: de trois effets additifs indépendants, on normalise les PV par la probabilité qu'un coup
#: passe la save ET le ward — plus fidèle à ce que ces trois stats *font ensemble* en jeu
#: (durabilité multiplicative, pas additive). ``dmg_vs_save2_sq`` (terme quadratique de
#: ``dmg_vs_save2``) capte des rendements croissants au-delà d'un certain seuil de dégât
#: perçant, que le terme linéaire seul sous-estime. Essais comparatifs dans
#: `analysis/experiments/durability_and_saturation.py` (R² ajusté 0.9067 → 0.9173 combiné,
#: interaction héros incluse — voir `FACTORIAL_INTERACTIONS`) ; ``wounds_total``/``save_num``/
#: ``ward_num`` restent des champs de `UnitFeatures` (utiles hors régression, notamment
#: l'affichage) mais ne sont plus des prédicteurs du modèle de coût.
#: ``unit_size_sq`` (terme quadratique de ``unit_size``) rejoint ces prédicteurs suite à un
#: balayage de rendements croissants sur tous les indicateurs numériques principaux (seul
#: `unit_size` était significatif, p=0.002, gain R² ajusté +0.0009, robuste au retrait des
#: unités à 20 modèles) — cf. `analysis/experiments/unit_size_saturation.py`. Le coefficient
#: linéaire de ``unit_size`` devient franchement négatif une fois ce terme ajouté (rabais de
#: volume marqué en dessous d'une dizaine de modèles), compensé par le carré positif au-delà —
#: GW semble facturer une prime sur les très grosses hordes, pas juste un rabais continu.
#: ``dmg_cv_vs_save4`` et ``move`` ont été retirés par élimination arrière pas-à-pas (à chaque
#: étape, retirer le prédicteur dont le retrait dégrade le moins le R² ajusté, jusqu'à ce que
#: plus rien ne puisse partir sans perte) sur l'ensemble `MODEL_FEATURES`/`CATEGORICAL_FEATURES` :
#: les deux étaient de purs poids morts (p=0.444 pour `move`, coefficient +0.57 pts/pouce avec un
#: écart-type de 0.75 — plus grand que l'estimation elle-même), leur retrait améliore même
#: légèrement le R² ajusté (0,9213 → 0,9214 pour les deux ensemble) grâce à la pénalité de
#: parcimonie. Un retrait "un par un" isolé avait aussi repéré `dmg_vs_save2`/`weapon_mix`/
#: `unit_type`/`is_unique` comme candidats individuellement peu coûteux, mais les retirer
#: ensemble dégrade le R² ajusté de -0.0010 : leur contribution, faible, n'est pas nulle une
#: fois les vrais doublons partis — gardés. Cf. `analysis/experiments/backward_elimination.py`.
MODEL_FEATURES: tuple[str, ...] = (
    "unit_size",
    "unit_size_sq",
    "dmg_ranged_vs_save6",
    "dmg_vs_save2",
    "dmg_vs_save2_sq",
    "charge_bonus_save2",
    "effective_wounds",
    "control",
    "wizard_level",
    "priest_level",
)

#: Segments de prix : GW chiffre héros et troupes selon des logiques distinctes
#: (durabilité premium côté héros, stats brutes + rabais de volume côté troupe).
SEGMENTS: dict[str, str] = {"hero": "is_hero == True", "troupe": "is_hero == False"}

#: Facteurs catégoriels du plan d'expérience factoriel (voir `fit_cost_model_factorial`).
#: ``army_name`` (≈25 modalités) remplace ``grand_alliance`` (4 modalités, dont il est le
#: sur-ensemble strict — armée ⊂ alliance, les deux ensemble seraient colinéaires) :
#: essai comparatif dans `analysis/experiments/army_factor.py`, F-test emboîté significatif
#: (p≈4e-9) et R² ajusté +0.012 (0.865 → 0.877) pour le remplacement. Prudence : les armées
#: à très peu d'unités importées (ex. Sons of Behemat, n≈7) ont un coefficient à fort effet
#: de levier, moins fiable que celui des factions bien peuplées.
#: ``is_unique`` (mot-clé UNIQUE, personnage nommé) proxy une part de la prime "aptitudes/
#: narratif" qu'aospy ne modélise pas autrement — essai dans `analysis/experiments/unique_factor.py`,
#: +16.6 pts significatif (p<0.001), R² ajusté +0.0025, peu colinéaire avec is_hero (corr. 0.24 :
#: 38/144 UNIQUE ne sont pas des héros, ex. monstres/machines de guerre nommés).
#: ``crit_type`` (type de Crit dominant, cf. `features._dominant_crit_type`) rejoint ces
#: facteurs suite à `analysis/experiments/weapon_tags.py` : significatif au-delà de la magnitude
#: de dégât déjà captée par `dmg_vs_save2` (autowound +17.1 pts, mortal -15.9 pts vs 2hits
#: comme modalité de référence, p<0.05 sur les deux), gain de R² ajusté +0.0058 combiné à
#: `charge_bonus_save2`.
CATEGORICAL_FEATURES: tuple[str, ...] = (
    "army_name", "is_hero", "weapon_mix", "unit_type", "is_flying", "is_unique", "crit_type",
)

#: Interactions bloc×continu : au lieu de deux régressions séparées héros/troupe
#: (`fit_segmented`), on module directement, dans un seul modèle, l'effet des
#: points de vie selon que l'unité est un héros (durabilité "premium") ou une
#: troupe (stats brutes + rabais de volume). L'interaction héros × dégât brut
#: (`C(is_hero):dmg_vs_save6`) a été retirée avec `dmg_vs_save6` lui-même (voir
#: la note de `MODEL_FEATURES`) : son propre coefficient n'était pas significatif
#: (p=0.79) avant même le retrait du pool mêlée.
FACTORIAL_INTERACTIONS: tuple[str, ...] = (
    "C(is_hero):effective_wounds",
)


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


def fit_cost_model_factorial(
    con: duckdb.DuckDBPyConnection | None = None,
    features: tuple[str, ...] | list[str] = MODEL_FEATURES,
    categorical: tuple[str, ...] | list[str] = CATEGORICAL_FEATURES,
    interactions: tuple[str, ...] | list[str] = FACTORIAL_INTERACTIONS,
    *,
    frame=None,
) -> CostModelResult:
    """Ajuste l'OLS via un plan d'expérience factoriel : features continues +
    facteurs catégoriels (alliance, rôle héros/troupe, mix d'armes) + interactions
    bloc×continu, en une seule régression (formule ``statsmodels``/patsy).

    Remplace la logique de `fit_segmented` (deux régressions héros/troupe
    séparées) par des termes d'interaction ``C(is_hero):...`` dans un modèle
    unique — un seul R², des résidus directement comparables entre héros et
    troupes, et un facteur `grand_alliance` qui absorbe un éventuel biais de
    tarification systématique par faction.
    """
    import statsmodels.formula.api as smf

    if frame is None:
        frame = feature_frame(con)
    frame = frame.reset_index(drop=True)

    feats = [f for f in features if frame[f].astype(float).std() > 0]
    cats = [c for c in categorical if frame[c].nunique() > 1]

    inter = []
    for term in interactions:
        cat_part, _, cont_part = term.partition(":")
        cat_name = cat_part[len("C(") : -1]
        if cat_name in cats and cont_part in feats:
            inter.append(term)

    terms = feats + [f"C({c})" for c in cats] + inter
    formula = "points ~ " + " + ".join(terms)
    model = smf.ols(formula, data=frame).fit()

    predicted = model.fittedvalues
    resid = model.resid
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
        for name in model.params.index
        if name != "Intercept"
    ]
    intercept = Coefficient(
        "const", float(model.params["Intercept"]), float(model.bse["Intercept"]), float(model.pvalues["Intercept"]),
    )

    return CostModelResult(
        features=terms,
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

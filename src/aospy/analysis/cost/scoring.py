"""Score composite des classements « meilleures unités »/« meilleurs héros »
(`reports/best_report.py`) et du simulateur de bonus (`bonus_simulator/whatif.py`),
placé sous les deux paquets pour qu'ils le partagent sans dépendre l'un de l'autre."""

from collections.abc import Sequence


def combined_score(components: Sequence[tuple[float, float]], imbalance_weight: float) -> float:
    """Score composite à partir de N z-scores orientés « plus haut = meilleur »
    (ex. combat, sous-cotation, impact absolu), chacun fourni comme un couple
    ``(z, poids)`` : moyenne pondérée, pénalisée par la semi-déviation pondérée
    *vers le bas* des composantes. Sans le terme de pénalité, une moyenne
    pondérée est pleinement compensatoire — un excès sur une composante peut
    masquer une faiblesse arbitrairement grande sur une autre (ex. une unité
    très sous-cotée mais médiocre en combat peut dominer une unité équilibrée
    à moyenne égale). La semi-déviation ne compte que les composantes
    *en dessous* de la moyenne pondérée (à la façon d'un ratio de Sortino) —
    une composante au-dessus de la moyenne n'est jamais pénalisée pour son
    écart, seule une composante faible coûte des points, ce qui favorise les
    profils équilibrés sur les profils extrêmes d'un seul côté sans jamais
    rogner sur un axe où l'unité excelle."""
    total_weight = sum(w for _, w in components)
    mean = sum(z * w for z, w in components) / total_weight
    downside_variance = sum(w * min(z - mean, 0.0) ** 2 for z, w in components) / total_weight
    return mean - imbalance_weight * downside_variance**0.5

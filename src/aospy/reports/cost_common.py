"""Étiquettes françaises et tableau de coefficients partagés par les registres
de coût (cost_unites.py / cost_heros.py), plus le score composite partagé par
les registres « meilleures unités »/« meilleurs héros » (best_unites.py /
best_heros.py) — factorisé pour ne pas dupliquer entre les deux paires de
modules."""
import re
from collections.abc import Sequence

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle

from .common import NIGHT_BLUE, GOLD_BRIGHT, GOLD_DIM, GOLD, PARCHMENT, PARCHMENT_2

FEATURE_LABELS = {
    "unit_size": "Taille d'unité",
    "dmg_vs_save6": "Dégât vs save 6+",
    "dmg_ranged_vs_save6": "Dégât à distance vs save 6+",
    "dmg_vs_save2": "Dégât perçant (vs save 2+)",
    "dmg_vs_save2_sq": "Dégât perçant² (rendement croissant)",
    "dmg_cv_vs_save4": "Irrégularité (écart-type/moy.) vs save 4+",
    "effective_wounds": "PV effectifs (PV / proba. coup passant)",
    "move": "Mouvement",
    "control": "Contrôle",
    "wizard_level": "Niveau de sorcier (Wizard N)",
    "priest_level": "Niveau de prêtre (Priest N)",
    "C(is_hero)[T.True]:effective_wounds": "Héros × PV effectifs",
}

#: Formatage générique des coefficients catégoriels ``C(champ)[T.modalité]`` non
#: listés explicitement ci-dessus — surtout `army_name` (~24 modalités, trop
#: nombreuses pour un libellé par entrée). La modalité de référence (omise de la
#: régression) est signalée une fois pour toutes dans le texte de la page, pas
#: répétée sur chaque ligne.
CATEGORICAL_FIELD_LABELS = {
    "army_name": "Armée",
    "unit_type": "Type",
    "weapon_mix": "Armement",
    "is_flying": "Vol",
    "is_hero": "Rôle",
    "is_unique": "Unique",
}
CATEGORICAL_VALUE_LABELS = {
    "unit_type": {
        "CAVALRY": "Cavalerie", "INFANTRY": "Infanterie", "MONSTER": "Monstre",
        "OTHER": "Autre", "WAR MACHINE": "Machine de guerre",
    },
    "weapon_mix": {"mixed": "mixte", "ranged": "distance", "melee": "mêlée"},
    "is_hero": {"True": "Héros", "False": "Troupe"},
    "is_flying": {"True": "Oui", "False": "Non"},
    "is_unique": {"True": "Oui", "False": "Non"},
}
_CATEGORICAL_COEF_RE = re.compile(r"^C\((\w+)\)\[T\.(.+)\]$")


def label_for(name: str) -> str:
    if name in FEATURE_LABELS:
        return FEATURE_LABELS[name]
    m = _CATEGORICAL_COEF_RE.match(name)
    if not m:
        return name
    field, level = m.groups()
    field_label = CATEGORICAL_FIELD_LABELS.get(field, field)
    level_label = CATEGORICAL_VALUE_LABELS.get(field, {}).get(level, level)
    return f"{field_label} : {level_label}"


def coef_table(result, n_cols: int = 3):
    entries = [("const (base)", result.intercept.coef, result.intercept.p_value)]
    entries += [(label_for(c.name), c.coef, c.p_value) for c in result.coefficients]

    per_col = -(-len(entries) // n_cols)  # ceil
    blocks = [entries[i * per_col:(i + 1) * per_col] for i in range(n_cols)]

    def col(block):
        rows = [["Caractéristique", "Coef.", "p-val."]]
        rows += [[name, f"{coef:+.2f}", f"{p:.3f}"] for name, coef, p in block]
        while len(rows) < per_col + 1:
            rows.append(["", "", ""])
        return rows

    col_rows = [col(b) for b in blocks]
    combined = [sum(rows, []) for rows in zip(*col_rows)]

    label_w, coef_w, pval_w = 52 * mm, 16 * mm, 14 * mm
    col_widths = [label_w, coef_w, pval_w] * n_cols
    t = Table(combined, colWidths=col_widths)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NIGHT_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), GOLD_BRIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PARCHMENT, PARCHMENT_2]),
        ("GRID", (0, 0), (-1, -1), 0.35, GOLD_DIM),
        ("BOX", (0, 0), (-1, -1), 0.9, GOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for i in range(n_cols):
        base = i * 3
        style.append(("ALIGN", (base + 1, 0), (base + 2, -1), "CENTER"))
        if i > 0:
            style.append(("LINEBEFORE", (base, 0), (base, -1), 0.9, GOLD))
    t.setStyle(TableStyle(style))
    return t


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

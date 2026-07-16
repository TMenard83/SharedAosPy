"""Étiquettes françaises et tableau de coefficients partagés par les registres
de coût (cost_unites.py / cost_heros.py) — factorisé pour ne pas dupliquer le
mapping nom-de-variable → libellé entre les deux modules."""
import re

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle

from .common import NIGHT_BLUE, GOLD_BRIGHT, GOLD_DIM, GOLD, PARCHMENT, PARCHMENT_2

FEATURE_LABELS = {
    "unit_size": "Taille d'unité",
    "dmg_vs_nosave": "Dégât vs aucune save",
    "dmg_ranged_vs_nosave": "Dégât à distance vs aucune save",
    "dmg_vs_save2": "Dégât perçant (vs save 2+)",
    "dmg_cv_vs_save4": "Irrégularité (écart-type/moy.) vs save 4+",
    "wounds_total": "PV totaux (health × modèles)",
    "save_num": "Sauvegarde",
    "ward_num": "Ward (7 = aucun)",
    "move": "Mouvement",
    "control": "Contrôle",
    "wizard_level": "Niveau de sorcier (Wizard N)",
    "priest_level": "Niveau de prêtre (Priest N)",
    "C(is_hero)[T.True]:dmg_vs_nosave": "Héros × dégât vs aucune save",
    "C(is_hero)[T.True]:wounds_total": "Héros × PV totaux",
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

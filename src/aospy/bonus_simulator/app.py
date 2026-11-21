"""IHM Streamlit — simulateur de bonus « what-if ».

Sélectionne une armée puis une unité, applique un bonus (listé depuis
`data/json/army_rules.json` et/ou libre) et affiche en direct l'impact sur les stats,
sur un duel de référence et sur le classement combat×coût
(`reports/best_unites.py`/`best_heros.py`) — sans écrire en base ni régénérer de
PDF (voir `whatif.py` pour la méthodologie).

Lancement : ``streamlit run src/aospy/bonus_simulator/app.py`` (nécessite
l'extra `[gui]`, ``pip install -e ".[gui]"``) — voir `README.md` dans ce
dossier pour le guide complet (dont le prompt e-mail au premier lancement de
Streamlit).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

# `streamlit run` execs this file as a standalone script (no package context),
# so relative imports (used elsewhere in aospy) would fail here — absolute
# imports instead, relying on the editable install (`pip install -e ".[gui]"`).
from aospy.bonus_simulator.army_rules import load_army_rules
from aospy.bonus_simulator.bonus import StatDelta, apply_bonus, combine
from aospy.bonus_simulator.whatif import WhatIfResult, live_combat_row, rank_against_pool
from aospy.persistence import db, repository

st.set_page_config(page_title="AoSPy — Simulateur de bonus", layout="wide")


@st.cache_resource(show_spinner="Connexion à la base…")
def _connect(db_path: str):
    return db.connect(db_path)


@st.cache_data(show_spinner=False)
def _army_rules():
    return load_army_rules()


def _weapon_table(unit) -> pd.DataFrame:
    if not unit.weapons:
        return pd.DataFrame(columns=["Arme", "Att.", "Toucher", "Blesser", "Rend", "Dégât"])
    return pd.DataFrame(
        [
            {
                "Arme": w.name,
                "Att.": w.attacks,
                "Toucher": f"{w.hit}+",
                "Blesser": f"{w.wound}+",
                "Rend": f"-{w.rend}" if w.rend else "-",
                "Dégât": w.damage,
            }
            for w in unit.weapons
        ]
    )


def main() -> None:
    st.title("Simulateur de bonus")
    st.caption(
        "Applique un bonus (règle d'armée ou libre) à une unité et regarde son "
        "impact sur les duels et les classements — rien n'est écrit en base."
    )

    db_path = st.sidebar.text_input("Base de données", str(db.DEFAULT_DB_PATH))
    con = _connect(db_path)

    armies = repository.list_armies(con)
    if not armies:
        st.error("Aucune armée en base — lancer `aospy init` d'abord.")
        return
    army_names = [a.name for a in armies]
    army_name = st.sidebar.selectbox("Armée", army_names)
    army = next(a for a in armies if a.name == army_name)

    units = repository.list_units_for_army(con, army.id)
    if not units:
        st.warning(f"Aucune unité pour {army_name}.")
        return
    unit_name = st.sidebar.selectbox("Unité", [u.name for u in units])
    base_unit = next(u for u in units if u.name == unit_name)

    st.sidebar.divider()
    st.sidebar.caption(
        f"{base_unit.points} pts · x{base_unit.models} · M{base_unit.move} "
        f"Sv{base_unit.save}+ Ward{f'{base_unit.ward}+' if base_unit.ward else ' -'} "
        f"HP{base_unit.health}"
    )

    deltas: list[StatDelta] = []

    st.subheader("Bonus d'armée")
    rules_by_army = _army_rules()
    available = rules_by_army.get(army_name, [])
    if not available:
        st.caption(f"Aucun bonus curaté pour {army_name} pour l'instant.")
    for bonus in available:
        checked = st.checkbox(f"**{bonus.name}** — {bonus.description}", key=f"rule_{army_name}_{bonus.name}")
        if checked:
            deltas.append(bonus.delta)

    st.subheader("Bonus libre")
    cols = st.columns(7)
    labels = [
        ("hit", "Toucher"),
        ("wound", "Blesser"),
        ("rend", "Rend"),
        ("save", "Save"),
        ("ward", "Ward"),
        ("damage", "Dégât"),
        ("attacks", "Attaques"),
    ]
    free_values = {}
    for col, (field, label) in zip(cols, labels):
        free_values[field] = col.number_input(label, min_value=-3, max_value=3, value=0, key=f"free_{field}")
    deltas.append(StatDelta(**free_values))

    delta = combine(deltas)
    bonus_unit = apply_bonus(base_unit, delta)

    st.subheader("Profil avant / après")
    col_before, col_after = st.columns(2)
    with col_before:
        st.markdown("**Avant**")
        st.dataframe(_weapon_table(base_unit), hide_index=True, width="stretch")
        st.caption(f"Save {base_unit.save}+ · Ward {f'{base_unit.ward}+' if base_unit.ward else '—'}")
    with col_after:
        st.markdown("**Après bonus**")
        st.dataframe(_weapon_table(bonus_unit), hide_index=True, width="stretch")
        st.caption(f"Save {bonus_unit.save}+ · Ward {f'{bonus_unit.ward}+' if bonus_unit.ward else '—'}")

    if delta == StatDelta():
        st.info("Aucun bonus sélectionné — coche une règle ou ajuste le bonus libre pour voir l'impact.")
        return

    st.subheader("Impact en duel")
    with st.spinner("Calcul des duels de référence…"):
        combat_before = live_combat_row(con, base_unit)
        combat_after = live_combat_row(con, bonus_unit)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "": "Avant",
                    "ROI moyen (plancher 66%)": f"{combat_before.avg_floor_roi_pct:+.1f}%",
                    "Pts net moyen": f"{combat_before.avg_pts_net:+.1f}",
                },
                {
                    "": "Après bonus",
                    "ROI moyen (plancher 66%)": f"{combat_after.avg_floor_roi_pct:+.1f}%",
                    "Pts net moyen": f"{combat_after.avg_pts_net:+.1f}",
                },
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Classement combat × coût")
    st.caption(
        "Position dans le même pool que « Panthéon des Champions » "
        "(reports/best_unites.py / best_heros.py) — troupes et héros séparés."
    )
    try:
        with st.spinner("Recalcul du classement…"):
            result_before: WhatIfResult = rank_against_pool(con, base_unit)
            result_after: WhatIfResult = rank_against_pool(con, bonus_unit)
    except ValueError as exc:
        st.warning(str(exc))
        return

    c1, c2 = st.columns(2)
    c1.metric("Rang avant bonus", f"{result_before.rank} / {result_before.total}")
    c2.metric(
        "Rang après bonus",
        f"{result_after.rank} / {result_after.total}",
        delta=result_before.rank - result_after.rank,
        delta_color="normal",
    )

    st.markdown("**Voisins de classement (après bonus)**")
    neighbor_rows = [
        {
            "#": n.rank,
            "Unité": (bonus_unit.name + " (avec bonus)") if n.is_target else n.name,
            "Armée": n.army or army_name,
            "Score": f"{n.score:+.2f}",
        }
        for n in result_after.neighbors
    ]
    st.dataframe(pd.DataFrame(neighbor_rows), hide_index=True, width="stretch")


if __name__ == "__main__":
    main()

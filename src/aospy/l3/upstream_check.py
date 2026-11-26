"""Contrôle des données en amont du modèle de scénario : listes parsées (PDF orga), unités absentes, points,
liste texte présente, indicateurs bruts aberrants, cache des indicateurs, clés des notes.

    aospy l3 verif-amont
"""

from __future__ import annotations

import json
import re


def main(argv: list[str] | None = None) -> int:
    from . import layer4, tactics
    from . import matchups as mu
    from . import scenario_model as sm

    pool, lists = sm.build_pool()
    txt = mu.FOLDER / "Listes texte"
    print("listes :", len(lists), "| manquantes :", sorted(set(mu.PLAYERS) - set(lists)) or "aucune")
    for p, al in lists.items():
        pb = []
        if al.unmatched:
            pb.append(f"non trouvé {al.unmatched}")
        if not 1900 <= al.points + al.missing_points <= 2000:
            pb.append(f"{al.points}+{al.missing_points} pts")
        if al.l4 is None:
            pb.append("pas de liste texte (couche 4 en repli)")
        else:
            if al.l4.missing:
                pb.append(f"couche 4 : absentes {al.l4.missing}")
            f = layer4.list_file(txt, al.team, p)
            n_txt = len(re.findall(r"^\s*[^•\n][^\n]*\((\d+)\)\s*$", f.read_text(encoding="utf-8"), re.M)) if f else 0
            if f and abs(n_txt - al.n_units) > 2:
                pb.append(f"unités PDF {al.n_units} / texte ~{n_txt}")
        if pb:
            print(f"  {p} ({al.faction}) : " + " ; ".join(pb))
    print("\nIndicateurs bruts hors de ±2,5 σ :")
    for p, ind in pool.items():
        out = [f"{k}={ind.raw[k]:.2f} (z {ind.z[k]:+.1f})" for k in sm.INDICATORS if abs(ind.z[k]) > 2.5]
        if out:
            print(f"  {p} ({lists[p].faction}) : " + ", ".join(out))
    cache = tactics.load_pool()
    cache = cache[0] if isinstance(cache, tuple) else cache
    d = max(abs(cache[p].raw[k] - pool[p].raw[k]) for p in pool for k in sm.INDICATORS)
    print("\ncache des indicateurs : écart max au recalcul", round(d, 4))
    notes = json.loads((sm.DATA / "notes_scenarios.json").read_text(encoding="utf-8"))
    scen, _ = sm.load_models()
    bad = [
        (p, k)
        for T in notes["equipes"].values()
        for p, j in T["joueurs"].items()
        for k, v in j["notes"].items()
        if k not in scen or v[0] not in sm.NUM
    ]
    unk = [p for T in notes["equipes"].values() for p in T["joueurs"] if p not in lists]
    print("notes : clés/notes invalides", bad or "aucune", "| joueurs inconnus", unk or "aucun")
    return 0

"""Modèle de scénario par carte (L3 Centre 2026-27) : note ++ … −− d'une liste sur une carte ou une tactique.

Entrées : le scénario (ou la tactique) et l'analyse de liste.

* **Analyse de liste** (`Indicators`) : indicateurs tirés de `matchups.ArmyList`, en z-scores sur les
  54 listes de la ligue, rangés en trois axes (plus un axe de soutien pour les tactiques) :
  - *objectifs* : contrôle total, nombre d'unités, aptitudes d'objectif ;
  - *mobilité* : indice de mobilité, set-up / téléportations, part qui VOLE ;
  - *contrôle après les combats* : dégâts d'un round, PV effectifs, tir — le contrôle se compte après les
    combats, une liste qui tue ce qui conteste reprend l'objectif, une liste qui encaisse le garde ;
  - *soutien* : HÉROS, magie (tactiques surtout).
* **Modèle** (`Model`) : poids sur ces indicateurs, curés à la main dans `Données/modele_scenarios.json`,
  un par carte et un par tactique (mêmes indicateurs, plus une base de difficulté et un décalage par scénario).

Note = z-score (sur les 54 listes) de Σ poids × z + base + décalage. Indicatif : comme `notes_scenarios.json`,
elle ne lit ni le déploiement ni les décors. `--compare` la confronte aux notes rédigées à la main.

Usage : aospy l3 scenario-model [--team T] [--player P] [--tactiques] [--compare]
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

DATA = Path(__file__).resolve().parents[3] / "data" / "2026-27 L3 Aller" / "Données"
MODEL_FILE = DATA / "modele_scenarios.json"

AXES = {
    "objectifs": ("controle", "activations", "apt_objectifs"),
    "mobilité": ("mobilite", "frappe", "vol"),
    "après combats": ("degats", "durabilite", "tir"),
    "soutien": ("heros", "magie"),
}
INDICATORS = tuple(k for keys in AXES.values() for k in keys)
DIFFICULTY = {"facile": 0.6, "moyen": 0.0, "difficile": -0.6}
NOTES = ((0.9, "++"), (0.3, "+"), (-0.3 + 1e-9, "="), (-0.9 + 1e-9, "−"))
NUM = {"++": 2, "+": 1, "=": 0, "−": -1, "−−": -2}


def note_of(value: float) -> str:
    return next((n for thr, n in NOTES if value >= thr), "−−")


# --- Analyse de liste ----------------------------------------------------------------------


@dataclass
class Indicators:
    player: str
    raw: dict[str, float]
    z: dict[str, float] = field(default_factory=dict)


def raw_indicators(al) -> dict[str, float]:
    """Indicateurs bruts d'une `matchups.ArmyList` (déjà passée par `rate_lists`)."""
    from .matchups import _REF, _ward_fail, unit_damage

    dmg = rng = ehp = 0.0
    for e in al.entries:
        total, ranged, _direct = unit_damage(e.unit, e.models, _REF)
        dmg, rng = dmg + total, rng + ranged
        fail = min(1.0, e.unit.save / 6) * _ward_fail(e.unit)  # sauvegarde contre perforation 1
        ehp += e.hp / max(fail, 1e-3)
    prof = al.prof
    return {
        "controle": math.log(al.control + 1),
        "activations": float(al.n_units),
        "apt_objectifs": prof.score["objectifs"] ** 0.5,
        "mobilite": al.mob,
        "frappe": prof.score["mobilité"] ** 0.5,
        "vol": prof.fly_share,
        "degats": math.log(dmg + 1),
        "durabilite": math.log(ehp + 1),
        "tir": math.log(rng + 1),
        "heros": float(sum(1 for e in al.entries if e.unit.is_hero)),
        "magie": (1.5 * prof.wizard_levels + prof.priest_levels) ** 0.5,
    }


def standardize(raws: Mapping[str, Mapping[str, float]]) -> dict[str, Indicators]:
    """Joueur -> `Indicators`, z-scores calculés sur toutes les listes données."""
    out = {p: Indicators(p, dict(r)) for p, r in raws.items()}
    for k in INDICATORS:
        vals = [r[k] for r in raws.values()]
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        for ind in out.values():
            ind.z[k] = (ind.raw[k] - mu) / sd
    return out


# --- Modèle ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Model:
    name: str
    kind: str  # « scénario » ou « tactique »
    weights: Mapping[str, float]
    base: float = 0.0  # tactiques : difficulté
    per_scenario: Mapping[str, float] = field(default_factory=dict)
    card: str = ""
    reason: str = ""
    against: Mapping[str, float] = field(default_factory=dict)  # tactiques : poids sur les z-scores adverses


def centered_weights(scenarios: Mapping[str, Mapping], alpha: float) -> dict[str, dict[str, float]]:
    """Poids des cartes moins `alpha` × leur moyenne sur les 12 cartes.

    Sans centrage (alpha = 0), le socle commun (dégâts, contrôle… pondérés partout) domine et la note
    d'une liste est presque la même sur toutes les cartes. alpha = 1 ne garde que la spécificité de la
    carte ; entre les deux, une part du socle reste (la puissance de frappe compte toujours : c'est la guerre).
    """
    keys = {k for m in scenarios.values() for k in m["poids"]}
    mean = {k: sum(m["poids"].get(k, 0.0) for m in scenarios.values()) / len(scenarios) for k in keys}
    return {
        name: {k: m["poids"].get(k, 0.0) - alpha * mean[k] for k in keys if m["poids"].get(k, 0.0) - alpha * mean[k]}
        for name, m in scenarios.items()
    }


def load_models(path: Path = MODEL_FILE) -> tuple[dict[str, Model], dict[str, Model]]:
    """(scénarios, tactiques) de `modele_scenarios.json`."""
    d = json.loads(path.read_text(encoding="utf-8"))
    for section in ("scenarios", "tactiques"):
        for name, m in d[section].items():
            unknown = (set(m["poids"]) | set(m.get("contre", {}))) - set(INDICATORS)
            if unknown:
                raise ValueError(f"{name} : indicateurs inconnus {sorted(unknown)}")
    scen = {
        k: Model(k, "scénario", w, reason=d["scenarios"][k].get("raison", ""))
        for k, w in centered_weights(d["scenarios"], d.get("_centrage", 0.0)).items()
    }
    tact = {
        k: Model(
            k,
            "tactique",
            m["poids"],
            DIFFICULTY[m["difficulte"]],
            m.get("par_scenario", {}),
            m.get("carte", ""),
            against=m.get("contre", {}),
        )
        for k, m in d["tactiques"].items()
    }
    return scen, tact


@dataclass
class Rating:
    value: float
    note: str
    axes: dict[str, float]  # contribution de chaque axe (en écarts types du total)
    top: list[tuple[str, float]]  # indicateurs qui pèsent le plus, signés


def _raw_score(model: Model, ind: Indicators) -> float:
    return sum(w * ind.z[k] for k, w in model.weights.items())


def opposition(model: Model, opponent: Optional[Indicators]) -> float:
    """Décalage d'une tactique dû à la liste adverse : Σ poids « contre » × z adverse (0 sans adversaire)."""
    return sum(w * opponent.z[k] for k, w in model.against.items()) if opponent else 0.0


def evaluate(
    model: Model,
    analyse: Indicators,
    pool: Mapping[str, Indicators],
    scenario: Optional[str] = None,
    opponent: Optional[Indicators] = None,
) -> Rating:
    """Note de la liste `analyse` sur le scénario ou la tactique `model`.

    `pool` : les listes de référence (les 54 de la ligue) qui fixent l'échelle de la note.
    `scenario` : pour une tactique, la carte jouée (décalage `par_scenario`).
    `opponent` : pour une tactique, la liste adverse (décalage `contre`, voir `opposition`).
    """
    scores = [_raw_score(model, i) for i in pool.values()]
    mu = sum(scores) / len(scores)
    sd = (sum((s - mu) ** 2 for s in scores) / len(scores)) ** 0.5 or 1.0
    contrib = {k: w * analyse.z[k] / sd for k, w in model.weights.items()}
    value = (
        (_raw_score(model, analyse) - mu) / sd
        + model.base
        + model.per_scenario.get(scenario or "", 0.0)
        + opposition(model, opponent)
    )
    axes = {a: sum(contrib.get(k, 0.0) for k in keys) for a, keys in AXES.items()}
    top = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:3]
    return Rating(value, note_of(value), axes, top)


# --- CLI -------------------------------------------------------------------------------------


def build_pool() -> tuple[dict[str, Indicators], dict]:
    """Indicateurs des 54 listes (`matchups.build_lists`, base en lecture seule) et les listes."""
    import duckdb

    from . import matchups as mu

    con = duckdb.connect(str(mu.DB), read_only=True)
    mu._DIRECT.update(mu.load_direct_abilities())
    lists = mu.build_lists(con)
    return standardize({p: raw_indicators(al) for p, al in lists.items()}), lists


def _fmt(v: float) -> str:
    return f"{v:+.1f}".replace("-", "−")


def _explain(r: Rating) -> str:
    return ", ".join(f"{k} {_fmt(v)}" for k, v in r.top)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 scenario-model", description=__doc__.split("\n")[0])
    ap.add_argument("--team", help="équipe (défaut : toutes)")
    ap.add_argument("--player", help="une seule liste : détail par carte et par tactique")
    ap.add_argument("--tactiques", action="store_true", help="grille des tactiques au lieu des cartes")
    ap.add_argument("--compare", action="store_true", help="écart aux notes de notes_scenarios.json")
    a = ap.parse_args(argv)
    scen, tact = load_models()
    pool, lists = build_pool()
    players = [p for p, al in lists.items() if not a.team or al.team == a.team]
    if a.player:
        ind = pool[a.player]
        print(f"## {a.player} ({lists[a.player].faction})\n")
        print("| Carte | Note | Valeur | Objectifs | Mobilité | Après combats | Ce qui pèse |")
        print("|---|---|---|---|---|---|---|")
        for m in scen.values():
            r = evaluate(m, ind, pool)
            ax = r.axes
            print(
                f"| {m.name} | {r.note} | {_fmt(r.value)} | {_fmt(ax['objectifs'])} | {_fmt(ax['mobilité'])} "
                f"| {_fmt(ax['après combats'])} | {_explain(r)} |"
            )
        print("\n| Tactique | Carte | Note | Valeur | Ce qui pèse |\n|---|---|---|---|---|")
        for m in tact.values():
            r = evaluate(m, ind, pool)
            print(f"| {m.name} | {m.card} | {r.note} | {_fmt(r.value)} | {_explain(r)} |")
        return 0
    models = tact if a.tactiques else scen
    print("| Liste | " + " | ".join(models) + " |")
    print("|---|" + "---|" * len(models))
    for p in players:
        print(f"| {p} | " + " | ".join(evaluate(m, pool[p], pool).note for m in models.values()) + " |")
    if a.compare:
        notes = json.loads((DATA / "notes_scenarios.json").read_text(encoding="utf-8"))
        hand = {p: j["notes"] for t in notes["equipes"].values() for p, j in t["joueurs"].items()}
        pairs = [
            (NUM[hand[p][k][0]], NUM[evaluate(scen[k], pool[p], pool).note])
            for p in players
            if p in hand
            for k in scen
            if k in hand[p]
        ]
        if pairs:
            same = sum(h == m for h, m in pairs) / len(pairs)
            near = sum(abs(h - m) <= 1 for h, m in pairs) / len(pairs)
            mh = sum(h for h, _ in pairs) / len(pairs)
            mm = sum(m for _, m in pairs) / len(pairs)
            cov = sum((h - mh) * (m - mm) for h, m in pairs)
            sh = sum((h - mh) ** 2 for h, _ in pairs) ** 0.5
            sm = sum((m - mm) ** 2 for _, m in pairs) ** 0.5
            r = cov / (sh * sm) if sh and sm else 0.0
            print(
                f"\nNotes à la main : {len(pairs)} couples, identiques {same:.0%}, à un cran {near:.0%}, "
                f"corrélation {r:+.2f} (moyenne main {mh:+.2f}, modèle {mm:+.2f})."
            )
    return 0


if __name__ == "__main__":
    main()

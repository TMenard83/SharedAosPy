"""Composante scénario d'un matchup (L3 Centre 2026-27) : ce que la carte jouée change au score d'une paire.

La grille du moteur (`matchups.evaluate`) ne voit pas la carte : sa part « scénario » (contrôle, unités, mobilité)
est la même sur les 12 cartes. Ici, pour une paire (A, B) et une carte :

* **aisance** d'une liste sur une carte, en crans (++ = +2 … −− = −2) : note à la main de
  `Données/notes_scenarios.json` si elle existe (analyse liste × scénario, validée), sinon la note du modèle
  `scenario_model` (indicateurs de la liste, poids de `modele_scenarios.json`) ;
* **correction** = `K` pts de victoire × (écart d'aisance de A − écart d'aisance de B), où l'écart d'aisance est
  l'aisance sur la carte **moins l'aisance moyenne de la liste sur les 12 cartes** (`centre=True`, défaut) : la
  facilité générale d'une liste à jouer les objectifs est déjà dans la grille (pas de double compte), seule la
  part propre à la carte s'ajoute. `centre=False` = écart brut des notes (ancien `pairing_scores.notes_model`).

Pour l'appariement, seules les 3 cartes de la ronde comptent (`pairing_scores.build_input` ne demande qu'elles).

Usage : aospy l3 scenario-match A B [--ronde N | --cartes C …] [--brut]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import scenario_model as sm

DATA = Path(__file__).resolve().parents[3] / "data" / "2026-27 L3 Aller" / "Données"
K = 2.0  # pts de victoire par cran (même valeur que `scenarios.K`)


@dataclass(frozen=True)
class Aisance:
    cran: int  # −2 … +2
    source: str  # "main" | "modèle"
    commentaire: str = ""


class ScenarioMatchup:
    """Aisance de chaque liste sur chaque carte et correction de paire par carte."""

    def __init__(
        self,
        hand: Mapping[str, Mapping[str, list]],
        model: Callable[[str, str], int],
        maps: list[str],
        k: float = K,
        centre: bool = True,
    ):
        self.hand, self.model, self.maps, self.k, self.centre = hand, model, list(maps), k, centre
        self._mean: dict[str, float] = {}

    def aisance(self, player: str, carte: str) -> Aisance:
        h = self.hand.get(player, {}).get(carte)
        if h:
            return Aisance(sm.NUM[h[0]], "main", h[1] if len(h) > 1 else "")
        return Aisance(self.model(player, carte), "modèle")

    def moyenne(self, player: str) -> float:
        if player not in self._mean:
            self._mean[player] = sum(self.aisance(player, m).cran for m in self.maps) / len(self.maps)
        return self._mean[player]

    def ecart(self, player: str, carte: str) -> float:
        a = self.aisance(player, carte).cran
        return a - self.moyenne(player) if self.centre else float(a)

    def correction(self, a: str, b: str, carte: str) -> float:
        """pts de victoire à ajouter au score (vu de A) de la paire A – B jouée sur `carte`."""
        return self.k * (self.ecart(a, carte) - self.ecart(b, carte))

    __call__ = correction  # MapModel de `pairing_scores`


def hand_notes(data: Path = DATA) -> dict[str, dict[str, list]]:
    """Joueur → {carte: [note, commentaire]} (toutes équipes)."""
    N = json.loads((data / "notes_scenarios.json").read_text(encoding="utf-8"))
    return {p: j.get("notes", {}) for t in N["equipes"].values() for p, j in t["joueurs"].items()}


def all_maps(data: Path = DATA) -> list[str]:
    return [s["cle"] for s in json.loads((data / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]]


def model_notes(refresh: bool = False) -> Callable[[str, str], int]:
    """Note du modèle `scenario_model` (indicateurs en cache, voir `tactics.load_pool`), en crans."""
    from .tactics import load_pool

    pool = load_pool(refresh)
    scen, _ = sm.load_models()
    cache: dict[tuple[str, str], int] = {}

    def note(player: str, carte: str) -> int:
        if (player, carte) not in cache:
            if player not in pool or carte not in scen:
                cache[(player, carte)] = 0
            else:
                cache[(player, carte)] = sm.NUM[sm.evaluate(scen[carte], pool[player], pool).note]
        return cache[(player, carte)]

    return note


def default(centre: bool = True, k: float = K) -> ScenarioMatchup:
    return ScenarioMatchup(hand_notes(), model_notes(), all_maps(), k, centre)


# --- CLI -------------------------------------------------------------------------------------


def _fmt(v: float) -> str:
    return f"{v:+.1f}".replace("-", "−")


NOTE = {2: "++", 1: "+", 0: "=", -1: "−", -2: "−−"}


def rows(sm_: ScenarioMatchup, a: str, b: str, cartes: list[str]):
    for c in cartes:
        yield c, sm_.aisance(a, c), sm_.aisance(b, c), sm_.correction(a, b, c)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 scenario-match", description=__doc__.split("\n")[0])
    ap.add_argument("a", help="notre liste (joueur)")
    ap.add_argument("b", help="liste adverse (joueur)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--ronde", type=int, choices=range(1, 6), help="seulement les 3 cartes de la ronde")
    g.add_argument("--cartes", nargs="+", help="cartes à afficher (clés de scenarios.json)")
    ap.add_argument("--brut", action="store_true", help="écart brut des notes, sans retirer la moyenne de la liste")
    x = ap.parse_args(argv)

    S = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    cartes = S["rondes"][str(x.ronde)] if x.ronde else (x.cartes or all_maps())
    model = default(centre=not x.brut)
    known = set(model.hand) | _pool_names()
    for p in (x.a, x.b):
        if p not in known:
            raise SystemExit(f"« {p} » : liste inconnue")
    print(f"# Composante scénario {x.a} – {x.b}" + (f" (ronde {x.ronde})" if x.ronde else ""))
    print()
    print(f"Aisance moyenne sur les 12 cartes : {x.a} {_fmt(model.moyenne(x.a))}, {x.b} {_fmt(model.moyenne(x.b))}"
          + (" · correction = écart brut" if x.brut else " · correction = part propre à la carte"))
    print()
    print(f"| Carte | {x.a} | {x.b} | Correction (pts de victoire, vue de {x.a}) |")
    print("|---|---|---|---|")
    for c, aa, ab, corr in rows(model, x.a, x.b, cartes):
        sa = "" if aa.source == "main" else " (modèle)"
        sb = "" if ab.source == "main" else " (modèle)"
        print(f"| {c} | {NOTE[aa.cran]}{sa} | {NOTE[ab.cran]}{sb} | {_fmt(corr)} |")
    print()
    print("*Note sans mention = analyse liste × scénario à la main (notes_scenarios.json) ; (modèle) = estimée par "
          "`aospy l3 scenario-model` en attendant l'analyse.*")
    return 0


def _pool_names() -> set[str]:
    from .tactics import load_pool

    return set(load_pool())


if __name__ == "__main__":
    main()

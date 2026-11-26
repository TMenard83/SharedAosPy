"""Contrat d'interface entre le solveur d'appariement AOSFF et le modèle de scénario par carte (L3 Centre 2026-27).

Deux producteurs, un consommateur :

  grille de matchups (aospy l3 matchups) ──┐
                                           ├─► PairingInput ──► solveur d'appariement
  modèle de scénario par carte (MapModel) ─┘

Règles du contrat :

* **Le solveur ne lit que `PairingInput`** : jamais les Markdown, les JSON de `Données/` ni la base. Il ne sait pas
  d'où viennent les scores ; changer de modèle de scénario ne le touche pas.
* **Unité et signe** : `score[(nous, eux, map)]` = écart de points de victoire attendu, vu de **notre** équipe
  (positif = avantage pour nous). Le solveur ne recalcule pas le point de vue adverse : il prend l'opposé.
* **Complétude** : la table couvre tout le produit `ours × theirs × maps` (vérifié à la construction).
* **Le modèle de scénario renvoie une correction**, pas un score complet : `MapModel(nous, eux, map)` → pts de
  victoire à ajouter à la grille du moteur (qui, elle, ne voit pas la carte). Correction indépendante de la carte
  = 0. Un futur modèle calculé remplace `notes_model` sans changer cette signature.
* **Modèle actuel** (`l3.scenario_matchup`, 2026-11-26) : `K` pts de victoire par cran d'écart entre l'aisance de
  notre liste et celle de la liste adverse sur la carte ; aisance = note à la main (`notes_scenarios.json`) sinon
  note du modèle `scenario_model` ; par défaut **centrée** (aisance moins la moyenne de la liste sur les 12 cartes :
  la facilité générale est déjà dans la grille). `scenario="brut"` = écart brut ; `scenario="notes"` = ancien
  `notes_model` (notes à la main seules, note absente = « = »).
* **Tactiques de bataille** (`l3.tactics`, 2026-11-25, à valider) : correction ajoutée à la précédente
  (`combine`) : `WEIGHT` × écart des pts de tactique attendus des deux listes, selon leurs 2 cartes, la carte jouée
  et la liste adverse.

Où lire et corriger chaque terme (fichiers de données, commandes de détail, régénération) : skill
`pairing-analysis`, § 0 « D'où vient une case ».

Usage (bibliothèque) : `build_input("Melusior", 1)` → `PairingInput` de la ronde 1 ; `None` si BYE.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

from .scenarios import BASE, FILE_NAME, NUM, K, grid

Key = tuple[str, str, str]  # (notre liste, leur liste, carte)

MapModel = Callable[[str, str, str], float]
"""Correction en pts de victoire (vue de nous) pour la paire (nous, eux) jouée sur la carte."""


@dataclass(frozen=True)
class PairingInput:
    """Tout ce que le solveur d'appariement a le droit de savoir pour une ronde."""

    team: str
    opponent: str
    round: int
    ours: tuple[str, ...]
    theirs: tuple[str, ...]
    maps: tuple[str, ...]  # clés de scénario (`scenarios.json`), dans l'ordre de la ronde
    score: Mapping[Key, float]  # base + correction, vue de nous
    base: Mapping[Key, float] = field(default_factory=dict)  # grille du moteur seule (même valeur pour chaque carte)
    detail: Mapping[Key, str] = field(default_factory=dict)  # explication courte de la correction, facultative

    def __post_init__(self) -> None:
        missing = [(u, t, m) for u in self.ours for t in self.theirs for m in self.maps if (u, t, m) not in self.score]
        if missing:
            raise ValueError(f"PairingInput incomplet : {len(missing)} cases manquantes, ex. {missing[0]}")

    def at(self, us: str, them: str, mp: str) -> float:
        return self.score[(us, them, mp)]


def assemble(
    team: str,
    opponent: str,
    round_: int,
    ours: list[str],
    theirs: list[str],
    maps: list[str],
    base_grid: Mapping[tuple[str, str], float],
    map_model: MapModel,
) -> PairingInput:
    """Partie pure : grille (nous, eux) + correction par carte → `PairingInput`."""
    score, base, detail = {}, {}, {}
    for u in ours:
        for t in theirs:
            for m in maps:
                b = float(base_grid[(u, t)])
                c = float(map_model(u, t, m))
                base[(u, t, m)] = b
                score[(u, t, m)] = b + c
                if c:
                    detail[(u, t, m)] = f"{b:+g} grille {c:+g} carte"
    return PairingInput(team, opponent, round_, tuple(ours), tuple(theirs), tuple(maps), score, base, detail)


def notes_model(our_notes: Mapping[str, dict], their_notes: Mapping[str, dict], k: float = K) -> MapModel:
    """Modèle actuel : `k` pts de victoire par cran d'écart entre nos notes scénario et les leurs."""

    def n(players: Mapping[str, dict], p: str, mp: str) -> int:
        return NUM[players.get(p, {}).get("notes", {}).get(mp, ["="])[0]]

    return lambda us, them, mp: k * (n(our_notes, us, mp) - n(their_notes, them, mp))


def combine(*models: MapModel) -> MapModel:
    """Somme de corrections indépendantes (ex. notes scénario + tactiques de bataille)."""
    return lambda us, them, mp: sum(m(us, them, mp) for m in models)


def build_input(
    team: str,
    round_: int,
    map_model: Optional[MapModel] = None,
    notes: bool = True,
    tactics: bool = True,
    scenario: str = "centre",
) -> Optional[PairingInput]:
    """`PairingInput` d'une ronde à partir des fichiers de la L3 ; `None` si l'équipe est au BYE.

    Sans `map_model`, la correction = composante scénario (`scenario` : `centre` | `brut` →
    `scenario_matchup.ScenarioMatchup`, `notes` → `notes_model`) + tactiques de bataille
    (`l3.tactics.TacticsModel`, pts de tactique attendus des deux listes sur la carte), chacune désactivable.
    """
    if team not in FILE_NAME:
        raise ValueError(f"équipe inconnue : {team!r} (attendu : {', '.join(FILE_NAME)})")
    S = json.loads((BASE / "Données" / "scenarios.json").read_text())
    N = json.loads((BASE / "Données" / "notes_scenarios.json").read_text())
    opponent = S["calendrier"][team].get(str(round_))
    if not opponent:
        return None
    ours, theirs = N["equipes"][team]["joueurs"], N["equipes"][opponent]["joueurs"]
    if map_model is None:
        parts: list[MapModel] = []
        if notes and scenario == "notes":
            parts.append(notes_model(ours, theirs))
        elif notes:
            from .scenario_matchup import default as scenario_default

            parts.append(scenario_default(centre=scenario == "centre"))
        if tactics:
            from .tactics import default_model

            parts.append(default_model())
        map_model = combine(*parts)
    model = map_model
    maps = S["rondes"][str(round_)]
    return assemble(team, opponent, round_, list(ours), list(theirs), maps, grid(team, round_), model)

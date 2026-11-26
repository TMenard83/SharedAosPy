"""Tactiques de bataille dans le score de paire (L3 Centre 2026-27) : pts de victoire de tactique attendus.

Règle (utilisateur, 2026-11-23) : à chacun de ses tours, un joueur tente **une tactique par famille**
(Échauffourée, Frappe, Domination) parmi les sous-tactiques de ses 2 cartes ; 5 pts de victoire chacune.
Sur 5 tours, une liste marque donc en moyenne `5 × 5 × Σ_famille p(meilleure tactique de la famille)`.

p(tactique) vient d'une **valeur** (échelle de `scenario_model` : facile +0,6, moyen 0, difficile −0,6) :

* niveau écrit à la main (`tactiques.niveaux` des combos de nos équipes, ou `Données/auto/<équipe>/<joueur>.json`
  pour les adversaires), sinon le modèle `scenario_model` (indicateurs de la liste, poids de
  `modele_scenarios.json`), dont la part « liste » est comprimée et recentrée (`MODEL_SHRINK`, `MODEL_OFFSET`) ;
  une Domination estimée par le modèle est multipliée par `DOMINATION_REALISM` (souvent irréalisable à notre
  niveau, voir `tactiques.json`) ;
* \+ décalage de la carte jouée (`par_scenario`) + décalage dû à la liste adverse (`contre`, ex. Sauvetage
  Audacieux plus dur contre une liste durable) : le niveau à la main est absolu, ces deux termes s'y ajoutent.

`p = clamp(0,45 + 0,25 × valeur, P_MIN, P_MAX)`. Score de paire = `WEIGHT × (nos pts − leurs pts)`, en
correction `MapModel` de `pairing_scores` (le solveur ne voit que le score final).

Les indicateurs des 54 listes demandent `matchups.build_lists` (~25 s, base en lecture seule) : ils sont mis en
cache dans `Données/indicateurs_listes.json` (fichier généré, `--rafraichir` pour le refaire après un changement
de liste ou de base).

Usage : aospy l3 tactiques [--team T] [--ronde N] [--player P] [--rafraichir]
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from . import scenario_model as sm

BASE = Path(__file__).resolve().parents[3] / "data" / "2026-27 L3 Aller"
DATA = BASE / "Données"
CACHE = DATA / "indicateurs_listes.json"
CARDS = Path(__file__).resolve().parents[3] / "data" / "json" / "battle_tactic_cards.json"

WEIGHT = 0.5  # part des pts de tactique comptée dans le score de paire (estimation grossière, à valider)
ROUNDS = 5
POINTS = 5
P_MIN, P_MAX = 0.02, 0.85
DOMINATION_REALISM = 0.5
#: le modèle ne reproduit pas nos 12 lectures à la main (corrélation des pts attendus ≈ 0 le 2026-11-25) et les
#: étale bien plus (écart type 10,8 contre 2,6) : sa part « liste » est comprimée, puis recentrée pour que sa
#: moyenne sur nos 12 listes égale celle des niveaux à la main (sinon le terme favorise un camp par construction).
MODEL_SHRINK = 0.4
MODEL_OFFSET = 0.27
FAMILIES = ("Échauffourée", "Frappe", "Domination")
CARD_ALIASES = {"Smokescreen": "Smoke Screen"}  # orthographe de l'App → battle_tactic_cards.json
LEVELS = {"facile": 0.6, "moyen-facile": 0.3, "moyen": 0.0, "difficile": -0.6, "abandon": -1.6}


def _key(name: str) -> str:
    return name.replace("’", "'").strip()


def card_tactics(path: Path = CARDS) -> dict[str, dict[str, str]]:
    """Carte (nom anglais) -> {famille: nom français de la sous-tactique}."""
    return {
        c["name_en"]: {s["kind"]: _key(s["name"]) for s in c["sub_tactics"]}
        for c in json.loads(path.read_text(encoding="utf-8"))
    }


def list_cards(rapport: Path = BASE / "Listes texte" / "rapport.json") -> dict[str, tuple[str, ...]]:
    """Joueur -> ses 2 cartes de tactique (ligne « Battle Tactic Cards: » de sa liste texte)."""
    root = Path(__file__).resolve().parents[3]
    out = {}
    for player, r in json.loads(rapport.read_text(encoding="utf-8")).items():
        for line in (root / r["txt"]).read_text(encoding="utf-8").splitlines():
            if line.startswith("Battle Tactic Cards:"):
                names = re.split(r"[,/]", line.split(":", 1)[1])
                out[player] = tuple(CARD_ALIASES.get(c.strip(), c.strip()) for c in names)
                break
    return out


def hand_levels(data: Path = DATA) -> dict[str, dict[str, str]]:
    """Joueur -> {tactique: niveau} écrits à la main (combos de nos équipes, puis `auto/` des adversaires)."""
    out: dict[str, dict[str, str]] = {}
    files = sorted((data / "combos").glob("*.json")) + sorted((data / "auto").glob("*/*.json"))
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        entries = {f.stem: d} if f.parent.parent.name == "auto" else d
        for player, j in entries.items():
            if player.startswith("_") or not isinstance(j, dict):
                continue
            niv = (j.get("tactiques") or {}).get("niveaux")
            if niv and player not in out:
                bad = set(niv.values()) - set(LEVELS)
                if bad:
                    raise ValueError(f"{f.name} {player} : niveaux inconnus {sorted(bad)}")
                out[player] = {_key(k): v for k, v in niv.items()}
    return out


def load_pool(refresh: bool = False, cache: Path = CACHE) -> dict[str, sm.Indicators]:
    """Indicateurs (z-scores) des 54 listes, depuis le cache ou `scenario_model.build_pool`.

    Le cache est recalculé tout seul s'il est plus vieux que la base ou qu'une liste texte (`l3.freshness`).
    """
    from .freshness import list_sources, newer_sources

    if not refresh and cache == CACHE and newer_sources(cache, list_sources()):
        refresh = True
    if refresh or not cache.exists():
        pool, _lists = sm.build_pool()
        cache.write_text(
            json.dumps(
                {
                    "_genere": f"aospy l3 tactiques, {datetime.date.today().isoformat()} (généré, ne pas éditer)",
                    "listes": {p: i.raw for p, i in pool.items()},
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        return pool
    raws = json.loads(cache.read_text(encoding="utf-8"))["listes"]
    if any(set(sm.INDICATORS) - set(r) for r in raws.values()):  # indicateur ajouté depuis le cache
        return load_pool(refresh=True, cache=cache)
    return sm.standardize(raws)


def probability(value: float) -> float:
    return min(P_MAX, max(P_MIN, 0.45 + 0.25 * value))


@dataclass(frozen=True)
class Choice:
    family: str
    tactic: str
    p: float
    source: str  # « main » ou « modèle »


class TacticsModel:
    """pts de tactique attendus d'une liste contre une autre sur une carte, et correction de paire."""

    def __init__(
        self,
        pool: Mapping[str, sm.Indicators],
        cards: Mapping[str, tuple[str, ...]],
        hand: Mapping[str, Mapping[str, str]],
        models: Optional[Mapping[str, sm.Model]] = None,
        tactics_of: Optional[Mapping[str, Mapping[str, str]]] = None,
        weight: float = WEIGHT,
    ):
        self.pool, self.cards, self.hand, self.weight = pool, cards, hand, weight
        self.models = models if models is not None else sm.load_models()[1]
        self.tactics_of = tactics_of if tactics_of is not None else card_tactics()

    def value(self, player: str, tactic: str, opponent: Optional[str], mp: Optional[str]) -> tuple[float, str]:
        m = self.models[tactic]
        opp = self.pool.get(opponent) if opponent else None
        level = self.hand.get(player, {}).get(tactic)
        if level is not None:
            v = LEVELS[level] + m.per_scenario.get(mp or "", 0.0) + sm.opposition(m, opp)
            return v, "main"
        listed = sm.evaluate(m, self.pool[player], self.pool).value - m.base  # part « liste » (z-score)
        v = m.base + MODEL_OFFSET + MODEL_SHRINK * listed + m.per_scenario.get(mp or "", 0.0) + sm.opposition(m, opp)
        return v, "modèle"

    def choices(self, player: str, opponent: Optional[str] = None, mp: Optional[str] = None) -> list[Choice]:
        """Par famille, la meilleure sous-tactique des 2 cartes de la liste (celle qu'on tente chaque tour)."""
        out = []
        for fam in FAMILIES:
            best = None
            for card in self.cards[player]:
                t = self.tactics_of[card][fam]
                v, src = self.value(player, t, opponent, mp)
                p = probability(v)
                if fam == "Domination" and src == "modèle":
                    p *= DOMINATION_REALISM
                if best is None or p > best.p:
                    best = Choice(fam, t, p, src)
            out.append(best)
        return out

    def expected(self, player: str, opponent: Optional[str] = None, mp: Optional[str] = None) -> float:
        return ROUNDS * POINTS * sum(c.p for c in self.choices(player, opponent, mp))

    def correction(self, us: str, them: str, mp: str) -> float:
        """Correction de paire (pts de victoire, vue de nous) : `weight` × écart de pts de tactique attendus."""
        return self.weight * (self.expected(us, them, mp) - self.expected(them, us, mp))

    __call__ = correction


def default_model(refresh: bool = False, weight: float = WEIGHT) -> TacticsModel:
    return TacticsModel(load_pool(refresh), list_cards(), hand_levels(), weight=weight)


# --- CLI -------------------------------------------------------------------------------------


def _fmt(v: float) -> str:
    return f"{v:+.1f}".replace("-", "−")


def main(argv: list[str] | None = None) -> int:
    from .scenarios import FILE_NAME

    ap = argparse.ArgumentParser(prog="aospy l3 tactiques", description=__doc__.split("\n")[0])
    ap.add_argument("--team", default="Melusior", help="Melusior ou « Vae Victis Vernou »")
    ap.add_argument("--ronde", type=int, choices=range(1, 6), help="grille de correction contre l'adversaire")
    ap.add_argument("--player", help="détail par tactique d'une liste (toutes cartes de la ronde si --ronde)")
    ap.add_argument("--rafraichir", action="store_true", help="refaire le cache des indicateurs (~25 s)")
    a = ap.parse_args(argv)
    team = next((t for t in FILE_NAME if t.lower().startswith(a.team.lower())), None)
    if team is None:
        raise SystemExit(f"équipe inconnue : {a.team!r}")
    T = default_model(a.rafraichir)
    S = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    N = json.loads((DATA / "notes_scenarios.json").read_text(encoding="utf-8"))
    ours = list(N["equipes"][team]["joueurs"])

    if a.player:
        p = a.player
        print(f"## {p} — cartes : {', '.join(T.cards[p])}\n")
        print("| Tactique | Famille | Source | Valeur | p/tour |\n|---|---|---|---|---|")
        for card in T.cards[p]:
            for fam, t in T.tactics_of[card].items():
                v, src = T.value(p, t, None, None)
                print(f"| {t} | {fam} | {src} | {_fmt(v)} | {probability(v):.0%} |")
        print(f"\npts de tactique attendus (sans carte ni adversaire) : {T.expected(p):.1f}")
        return 0

    if a.ronde:
        opp = S["calendrier"][team].get(str(a.ronde))
        if not opp:
            raise SystemExit(f"{team} au BYE à la ronde {a.ronde}.")
        theirs = list(N["equipes"][opp]["joueurs"])
        for mp in S["rondes"][str(a.ronde)]:
            print(f"\n## {mp} — correction tactiques (pts de victoire, vue de {team}, poids {T.weight:g})\n")
            print("| Nous \\ Eux | " + " | ".join(theirs) + " |\n|---|" + "---|" * len(theirs))
            for u in ours:
                print(f"| {u} | " + " | ".join(_fmt(T.correction(u, t, mp)) for t in theirs) + " |")
        return 0

    # Sans ronde : pts attendus hors carte et hors adversaire, et biais main/modèle sur nos listes.
    print("| Liste | Cartes | pts attendus | modèle seul | tentatives |\n|---|---|---|---|---|")
    bare = TacticsModel(T.pool, T.cards, {}, T.models, T.tactics_of, T.weight)
    gaps = []
    for u in ours:
        e, b = T.expected(u), bare.expected(u)
        gaps.append(e - b)
        tries = ", ".join(f"{c.tactic} {c.p:.0%}" for c in T.choices(u))
        print(f"| {u} | {' + '.join(T.cards[u])} | {e:.1f} | {b:.1f} | {tries} |")
    print(f"\nÉcart moyen niveaux à la main − modèle : {_fmt(sum(gaps) / len(gaps))} pts par partie.")
    return 0


if __name__ == "__main__":
    main()

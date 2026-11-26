"""Robustesse de l'appariement, version « fourchette » : toute la grille bruitée selon sa confiance (L3 2026-27).

Complète les cases pivot (`pairing_robust`, une case à la fois). Ici, à chaque tirage, **chaque paire** (nous, eux)
reçoit une erreur gaussienne, la même sur les 3 maps (l'erreur du moteur porte sur la paire), d'écart-type

    σ(paire) = √(σ_grille² + σ(notre liste)² + σ(leur liste)²)

* `σ_grille` : erreur du moteur, commune à toutes les cases ;
* `σ(liste)` selon ce qui a été relu (`confidence`) : analyse stratégique de l'utilisateur dans
  `Données/combos/<équipe>.json` (clé `strategie`, auteur ≠ claude) < brouillon d'agent (`Données/auto/`) <
  textes de Claude seuls ; + `SIGMA_NO_TACTICS` si les niveaux de tactique ne sont pas écrits (estimés par le modèle).

Valeurs par défaut **proposées par Claude le 2026-11-25, à valider** (`SIGMA`).

Pour chaque tirage on résout la grille bruitée et on rejoue notre mélange de défenseurs de référence (étape 1) :
on en tire la valeur de la ronde en fourchette (10e / 50e / 90e centiles), le regret du plan de référence
(moyen, et part des tirages où il dépasse le seuil) et, pour chaque défenseur, la part des tirages où il est le
choix le plus probable.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .pairing import Pairing
from .pairing_robust import guaranteed, step1

DATA = Path(__file__).resolve().parents[3] / "data" / "2026-27 L3 Aller" / "Données"

SIGMA = {"grille": 2.0, "validee": 1.0, "brouillon": 1.5, "claude": 2.0}
SIGMA_NO_TACTICS = 0.5


def confidence(data: Path = DATA) -> dict[str, str]:
    """Joueur → `validee` | `brouillon` | `claude` (niveau de relecture de son analyse)."""
    out: dict[str, str] = {}
    for f in sorted((data / "combos").glob("*.json")):
        for player, j in json.loads(f.read_text(encoding="utf-8")).items():
            if player.startswith("_") or not isinstance(j, dict):
                continue
            author = str((j.get("strategie") or {}).get("auteur", "")).lower()
            out[player] = "validee" if author and "claude" not in author else "claude"
    for f in sorted((data / "auto").glob("*/*.json")):
        if out.get(f.stem) == "claude":
            out[f.stem] = "brouillon"
    return out


def pair_sigmas(inp, conf: dict[str, str], tactics_written: set[str]) -> dict[tuple[str, str], float]:
    def s(p):
        return SIGMA[conf.get(p, "claude")] ** 2 + (0.0 if p in tactics_written else SIGMA_NO_TACTICS ** 2)

    return {(u, t): (SIGMA["grille"] ** 2 + s(u) + s(t)) ** 0.5 for u in inp.ours for t in inp.theirs}


def _draw(args):
    inp, mode, noise, x0 = args

    def score(u, t, m):
        return inp.at(u, t, m) + noise[(u, t)]

    M, Ds, v, x = step1(Pairing(score, inp.ours, inp.theirs, inp.maps, mode))
    return v, v - guaranteed(M, x0), Ds[max(range(len(Ds)), key=lambda k: x[k])]


def simulate(inp, sigmas, draws=200, mode="mixte", seed=0):
    """Référence `(valeur, mélange)` et tirages `(valeur, regret du plan de référence, défenseur en tête)`."""
    _, Ds, v0, x0 = step1(Pairing(inp.at, inp.ours, inp.theirs, inp.maps, mode))
    rnd = random.Random(seed)
    jobs = [(inp, mode, {k: rnd.gauss(0.0, s) for k, s in sigmas.items()}, x0) for _ in range(draws)]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(_draw, jobs, chunksize=4))
    return (v0, {Ds[i]: x0[i] for i in range(len(Ds)) if x0[i] > 0.005}), rows


def quantile(xs, q):
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def report(inp, sigmas, conf, ref, rows, seuil, sgn) -> list[str]:
    (v0, mix) = ref
    vals, regs = [r[0] for r in rows], [r[1] for r in rows]
    n = len(rows)
    tops: dict[str, int] = {}
    for r in rows:
        tops[r[2]] = tops.get(r[2], 0) + 1
    plan = ", ".join(f"{d} {p:.0%}" for d, p in sorted(mix.items(), key=lambda t: -t[1]))
    lvl = lambda p: {"validee": "validée", "brouillon": "brouillon", "claude": "Claude seul"}[conf.get(p, "claude")]  # noqa: E731
    out = [
        f"## Fourchette ({n} tirages, grille bruitée selon la confiance)",
        "",
        f"Référence : valeur {sgn(v0)} · plan de défenseurs : {plan}",
        "",
        f"- Valeur de la ronde : {sgn(quantile(vals, .1))} / **{sgn(quantile(vals, .5))}** / {sgn(quantile(vals, .9))} "
        "(10e / 50e / 90e centiles)",
        f"- Regret du plan de référence : moyen {sum(regs) / n:.2f}, > {seuil:g} dans "
        f"{sum(r > seuil for r in regs) / n:.0%} des tirages, pire {max(regs):.1f}",
        "- Défenseur en tête : " + ", ".join(f"{d} {c / n:.0%}" for d, c in sorted(tops.items(), key=lambda t: -t[1])),
        "",
        "Confiance des listes (σ par paire = √(σ grille² + σ nous² + σ eux²), défauts proposés à valider) :",
        "",
        "- Nous : " + ", ".join(f"{p} ({lvl(p)})" for p in inp.ours),
        "- Eux : " + ", ".join(f"{p} ({lvl(p)})" for p in inp.theirs),
        f"- σ par paire : {min(sigmas.values()):.1f} à {max(sigmas.values()):.1f} pts de victoire",
    ]
    return out

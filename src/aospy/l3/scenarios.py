"""Génère « Scénarios/Scénarios <équipe>.md » (L3 Centre 2026-27, aller) pour nos deux équipes.

Entrées (à modifier à la main, puis relancer) :
- Données/scenarios.json        : les 12 cartes (objectifs, score, aptitudes, ce qui gagne), maps par ronde, calendrier.
- Données/notes_scenarios.json  : note (++ … −−) et commentaire de chaque liste (nôtres et adverses) par scénario.
- Matchups/Matchups <équipe>/Ronde N — contre X/00 Grille et profils.md : grilles du moteur (aospy l3 matchups).

Défenseur conseillé (nous comme eux) : un défenseur joue contre le 2e meilleur contre adverse ;
score = écart prévu contre ce 2e contre + 2 pts de victoire par cran de note scénario.

Usage : aospy l3 scenarios [--team Melusior|"Vae Victis Vernou"]
"""

import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[3] / "data" / "2026-27 L3 Aller"
NUM = {"++": 2, "+": 1, "=": 0, "−": -1, "−−": -2}
K = 2  # pts de victoire par cran de note scénario
FILE_NAME = {"Melusior": "Melusior", "Vae Victis Vernou": "Vae Victis"}


def sgn(v):
    return f"+{v}" if v > 0 else str(v)


def grid(team, n):
    d = BASE / "Matchups" / f"Matchups {FILE_NAME[team]}"
    f = next(d.glob(f"Ronde {n} — */00 Grille et profils.md"))
    from .freshness import describe, grid_sources, newer_sources

    stale = newer_sources(f, grid_sources())
    if stale:
        raise SystemExit(
            f"Grille périmée : {f.relative_to(BASE)} est plus vieille que {describe(stale)}. "
            "Relancer `aospy l3 matchups` (puis `aospy l3 scenarios`) avant de l'utiliser."
        )
    text = f.read_text().split("## Grille", 1)[1]
    lines = [l for l in text.splitlines() if l.startswith("|") and not l.startswith("|---")]
    cols = [c.strip() for c in lines[0].strip().strip("|").split("|")][1:]
    g = {}
    for l in lines[1:]:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        us = cells[0].strip("*")
        for c, v in zip(cols, cells[1:]):
            if c.startswith("Moy") or not v:
                continue
            g[(us, c)] = int(v.replace("−", "-"))
    return g


def note(players, p, sc):
    return players[p]["notes"].get(sc, ["=", "—"])


def best_defenders(players, maps, safety):
    """Liste ordonnée de candidats par map ; choix séquentiel sans réutiliser une liste."""
    used, out = [], []
    for mp in maps:
        sc = {p: safety[p] + K * NUM[note(players, p, mp)[0]] for p in players}
        ranked = [p for p in sorted(sc, key=lambda p: -sc[p]) if p not in used]
        used.append(ranked[0])
        out.append((mp, ranked, sc))
    return out


def scen_block(s, again):
    rep = f" *(revient en ronde {', '.join(map(str, again))})*" if again else ""
    lines = [
        f"### {s['fr']} ({s['vo']}){rep}",
        "",
        f"- **Objectifs** : {s['objectifs']}",
        f"- **Score** (fin de chacun de ses tours) : {s['score']}",
        "- **Aptitudes du scénario** :",
    ]
    lines += [f"  - {a}" for a in s["aptitudes"]]
    lines += [f"- **Ce qui gagne** : {s['gagne']}", ""]
    return lines


def build(team, S, N):
    scen = {s["cle"]: s for s in S["scenarios"]}
    rondes = {int(k): v for k, v in S["rondes"].items()}
    cal = {int(k): v for k, v in S["calendrier"][team].items()}
    ours = N["equipes"][team]["joueurs"]
    T = N["equipes"][team]
    out = [
        f"# {FILE_NAME[team]} — nos listes face aux scénarios (L3 Centre 2026-27, aller)",
        "",
        "*Généré par `aospy l3 scenarios` à partir de `Données/scenarios.json` (cartes), `Données/notes_scenarios.json` (notes par liste, à corriger avec les joueurs) "
        "et des grilles de `Matchups/`. Ne pas modifier ce fichier : corriger les données puis relancer. Chaque ronde se lit seule, quitte à répéter un scénario qui revient.*",
        "",
        "## À savoir avant de lire",
        "",
    ]
    out += [f"- {r}" for r in S["rappels"]]
    out += [
        "- **Notes** : ++ très favorable · + favorable · = neutre · − défavorable · −− très défavorable.",
        f"- **Défenseur conseillé** : un défenseur joue contre le 2e meilleur contre adverse. Score = écart prévu contre ce 2e contre (grille du moteur) + {K} pts de victoire par cran de note scénario. Indicatif : le moteur ne voit pas le scénario, la note le corrige.",
        "",
    ]
    for n in range(1, 6):
        opp = cal.get(n)
        maps = rondes[n]
        if not opp:
            out += [
                f"## Ronde {n} — pas de match (BYE)",
                "",
                f"{FILE_NAME[team]} ne joue pas cette ronde : la poule compte un nombre impair d'équipes, donc chaque ronde une équipe attend. "
                f"Scénarios de la ronde : {', '.join(scen[m]['fr'] for m in maps)} (voir l'annexe pour nos notes).",
                "",
            ]
            continue
        theirs = N["equipes"][opp]["joueurs"]
        g = grid(team, n)
        # notre défenseur : contre leur 2e meilleur contre (2e plus petite valeur de notre ligne)
        our_safety = {p: sorted(g[(p, q)] for q in theirs)[1] for p in ours}
        their_safety = {q: -sorted((g[(p, q)] for p in ours), reverse=True)[1] for q in theirs}
        out += [f"## Ronde {n} — contre {opp}", ""]
        # nos défenseurs
        out += [
            "### Nos défenseurs conseillés",
            "",
            "| Map | Défenseur conseillé (score) | Autres candidats | À éviter (note −) |",
            "|---|---|---|---|",
        ]
        roles = ["Map 1 (étape 1)", "Map 2 (étape 2)", "Map 3 (notre oublié)"]
        for i, (mp, ranked, sc) in enumerate(best_defenders(ours, maps, our_safety)):
            avoid = [p for p in ours if NUM[note(ours, p, mp)[0]] < 0]
            out.append(
                f"| {roles[i]} — {scen[mp]['fr']} | **{ranked[0]}** ({sgn(sc[ranked[0]])}) | "
                + ", ".join(f"{p} ({sgn(sc[p])})" for p in ranked[1:3])
                + " | "
                + (", ".join(avoid) or "—")
                + " |"
            )
        out += [
            "",
            "*Map 3 : c'est notre oublié (la liste restée en main à l'étape 2) qui la joue. Choix séquentiel : une liste déjà posée n'est plus proposée ensuite.*",
            "",
        ]
        # leurs défenseurs
        out += [f"### Leurs défenseurs probables ({opp})", ""]
        for i, (mp, ranked, sc) in enumerate(best_defenders(theirs, maps, their_safety)):
            pick = ranked[0]
            att = sorted(ours, key=lambda u: -(g[(u, pick)] + K * NUM[note(ours, u, mp)[0]]))
            att_txt = ", ".join(f"**{u}** (matchup {sgn(g[(u, pick)])}, map {note(ours, u, mp)[0]})" for u in att[:3])
            out.append(
                f"- **{roles[i].replace('notre', 'leur')} — {scen[mp]['fr']}** : **{pick}** ({theirs[pick]['faction']}, score {sgn(sc[pick])}) ; sinon "
                + ", ".join(f"{p} ({sgn(sc[p])})" for p in ranked[1:3])
                + f". → Nos meilleurs attaquants contre lui (on en propose 2) : {att_txt}."
            )
        out += [
            "",
            "*Une liste n'attaque qu'une fois : si la même revient en tête sur plusieurs maps, la garder là où son avance est la plus nette.*",
            "",
            "| Joueur | Faction | Écart contre notre 2e contre | " + " | ".join(scen[m]["fr"] for m in maps) + " |",
            "|---|---|---|" + "---|" * len(maps),
        ]
        for q in sorted(theirs, key=lambda q: -their_safety[q]):
            out.append(
                f"| **{q}** | {theirs[q]['faction']} | {sgn(their_safety[q])} | "
                + " | ".join(note(theirs, q, m)[0] for m in maps)
                + " |"
            )
        out.append("")
        # les maps
        for i, mp in enumerate(maps):
            again = [k for k, v in rondes.items() if mp in v and k != n and cal.get(k)]
            block = scen_block(scen[mp], again)
            block[0] = block[0].replace("### ", f"### Map {i + 1} — ", 1)
            out += block
            out += ["**Chez nous**", "", "| Joueur | Note | Comment le jouer |", "|---|---|---|"]
            for p in sorted(ours, key=lambda p: -NUM[note(ours, p, mp)[0]]):
                nt, tx = note(ours, p, mp)
                out.append(f"| **{p}** | {nt} | {tx} |")
            out += [
                "",
                f"**Chez eux ({opp})**",
                "",
                "| Joueur | Note | Ce qu'ils feront sur cette map |",
                "|---|---|---|",
            ]
            for q in sorted(theirs, key=lambda q: (-NUM[note(theirs, q, mp)[0]], -their_safety[q])):
                nt, tx = note(theirs, q, mp)
                out.append(f"| **{q}** ({theirs[q]['faction']}) | {nt} | {tx} |")
            out.append("")
    # annexes
    order = [m for n in range(1, 6) for m in rondes[n]]
    order = list(dict.fromkeys(order))
    out += [
        "## Annexe — nos listes sur les 12 scénarios",
        "",
        "| | " + " | ".join(scen[m]["fr"] for m in order) + " |",
        "|---|" + "---|" * len(order),
    ]
    for p, j in ours.items():
        cells = []
        for m in order:
            nt = note(ours, p, m)[0]
            cells.append(f"**{nt}**" if nt in ("++", "−−") else nt)
        out.append(f"| **{p}** | " + " | ".join(cells) + " |")
    out += ["", "Ce que la grille montre :", ""] + [f"- {b}" for b in T.get("grille_montre", [])] + [""]
    if any(n not in cal or not cal[n] for n in range(1, 6)):
        bye = [m for n in range(1, 6) if not cal.get(n) for m in rondes[n]]
        out += ["Scénarios joués pendant notre BYE (pour mémoire) :", ""]
        for m in bye:
            out.append(f"- **{scen[m]['fr']}** : " + " · ".join(f"{p} {note(ours, p, m)[0]}" for p in ours))
        out.append("")
    out += ["## Annexe — profil scénario de chaque liste", ""]
    out += [f"- **{p} — {j['faction']}** — {j.get('profil', '')}" for p, j in ours.items()]
    out += ["", "## À vérifier avec les joueurs", ""] + [f"- {a}" for a in T.get("a_verifier", [])] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 scenarios", description=__doc__.split("\n")[0])
    ap.add_argument("--team", choices=list(FILE_NAME), help="une seule équipe (défaut : les deux)")
    a = ap.parse_args(argv)
    S = json.loads((BASE / "Données" / "scenarios.json").read_text())
    N = json.loads((BASE / "Données" / "notes_scenarios.json").read_text())
    for team in [a.team] if a.team else list(FILE_NAME):
        path = BASE / "Scénarios" / f"Scénarios {FILE_NAME[team]}.md"
        path.write_text(build(team, S, N))
        print(path)


if __name__ == "__main__":
    main()

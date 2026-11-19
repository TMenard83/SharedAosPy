"""Analyse de toutes les listes de la L3 Centre 2026-27 (aller) : un fichier par équipe.

Pour chaque liste : métriques du moteur aospy mesurées contre les 53 autres listes de la ligue
(score moyen, attrition infligée/subie, profil offensif/défensif, objectifs), puis l'analyse des
choix et combos internes, rédigée à la main dans `combos/<équipe>.json` (à corriger par l'équipe).

Usage : python scripts/l3_listes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l3_matchups as mx  # noqa: E402

OUT = mx.FOLDER / "Listes"
COMBOS = mx.FOLDER / "Données" / "combos"
TACTICS = mx.FOLDER / "Données" / "tactiques.json"


def slug(team: str) -> str:
    return team.replace("'", "").replace(" ", "_")


METHODE = [
    "## Méthode", "",
    "- **Score ligue** = écart de points de victoire attendu pour la liste sur une partie, **moyenné contre "
    "les 53 autres listes de la ligue** (+ = elle gagne de tant en moyenne). Échelle de −20 à +20 : ±3 "
    "équilibré, ±8 net. Le rang (sur 54) classe les listes par ce score.",
    "- **Attrition infligée / subie** : part de l'armée adverse (en points) retirée par round si toutes les "
    "unités frappent, moyenne sur la ligue ; et l'inverse, ce que la ligue lui retire.",
    *mx.method_body(),
]

PROFILE_HEAD = ("| Joueur | Faction | Rang | Score ligue | Attrition inf. / subie | Unités | PV | Svg moy. | "
                "Ward (pts) | Perf. moy. | Mortelles | Tir | Contrôle | Mvt | Monstres | Sorciers/Prêtres |")


CP_REMINDER = ("Budget générique : 4 PC par round (5 pour l'outsider). L'essentiel des ordres est générique "
               "et commun à toutes les listes : relance de charge (1), Attaque/Défense en Règle (1), Redéploiement (1), "
               "Au Pas de Course (1), Ralliement (1), Enfoncement (1), Contre-Charge (2), Intervention Magique (1) ; "
               "chaque ordre une fois par tour. Les exceptions propres à une liste sont surtout des résurrections "
               "(même modèle que le Slann : moitié de l'effectif).")


def cp_section(pr) -> list[str]:
    """Points de commandement : inventaire automatique (Wahapedia) + question à trancher."""
    out = ["### Points de commandement", "",
           "- *Aptitudes propres à la liste qui coûtent des PC* : " + ("; ".join(pr.cp_costs) or "aucune") + ".",
           "- *Ordres rendus gratuits (économie de PC)* : " + ("; ".join(pr.cp_gains) or "aucun") + ".",
           "- *Déni ou taxe sur les ordres adverses* : " + ("; ".join(pr.cp_deny) or "aucun") + ".",
           f"- *Rappel* : {CP_REMINDER}",
           "- *À trancher dans l'analyse* : à quoi la liste dépense-t-elle ses PC à chaque round, qu'est-ce qui "
           "entre en concurrence (même round, même tour), et que perd-elle si on la force à dépenser ailleurs ?", ""]
    return out


def strategy_section(s: dict | None) -> list[str]:
    """3e regard : l'analyse stratégique du joueur, puis sa discussion (clé `strategie` des combos)."""
    if not s or not s.get("analyse"):
        return ["### Analyse stratégique", "", "*Pas encore fournie.*", ""]
    head = "### Analyse stratégique" + (f" ({s['auteur']}, {s['date']})" if s.get("auteur") else "")
    out = [head, "", "> " + s["analyse"].replace("\n", "\n> "), ""]
    for key, title in (("challenge", "Points challengés (stats et textes)"), ("conclusions", "Retenu après discussion"),
                       ("en_suspens", "En suspens"), ("impact", "Effet sur les grilles")):
        if s.get(key):
            out += [f"**{title}**", ""] + [f"- {x}" for x in s[key]] + [""]
    return out


TIERS = ("Échauffourée", "Frappe", "Domination")


def tactics_general(t: dict) -> list[str]:
    """Lecture commune des 6 cartes de tactique (`Données/tactiques.json`), une fois par fichier d'équipe."""
    if not t:
        return []
    out = ["## Tactiques de bataille : lecture générale", "",
           "*Rédigé par Claude, à valider. Difficulté pour une liste « moyenne » ; la lecture par liste est dans "
           "chaque section joueur.*", ""]
    out += [f"- {x}" for x in t.get("regles", [])] + [""]
    for name, card in t.get("cartes", {}).items():
        out += [f"### {card['fr']} ({name})", "", card["lecture"], ""]
        out += [f"- *{tier}* — **{tac}** ({level}) : {txt}"
                for tier, (tac, (level, txt)) in zip(TIERS, card["tactiques"].items())] + [""]
    if t.get("scenarios"):
        out += ["### Scénarios qui changent la donne", ""]
        out += [f"- **{k}** : {v}" for k, v in t["scenarios"].items()] + [""]
    return out


def tactics_section(tac: dict | None, cards_fr: dict[str, str]) -> list[str]:
    """Facilité à scorer ses tactiques (clé `tactiques` des combos) : général, puis scénarios notables."""
    if not tac:
        return ["### Tactiques de bataille", "", "*Pas encore analysées.*", ""]
    cards = ", ".join(f"{cards_fr.get(c, c)} ({c})" for c in tac.get("cartes", []))
    real = f" — **{tac['realistes']} tactiques réalistes** (Échauffourées + Frappes)" if tac.get("realistes") else ""
    out = ["### Tactiques de bataille", "", f"**Cartes** : {cards}{real}.", "", f"**Bilan** : {tac['bilan']}", ""]
    for key, title in (("faciles", "Faciles pour cette liste"), ("difficiles", "Difficiles ou coûteuses"),
                       ("scenarios", "Scénarios notables")):
        if tac.get(key):
            out += [f"**{title}**", ""] + [f"- {x}" for x in tac[key]] + [""]
    if tac.get("plan"):
        out += [f"**Ordre conseillé** : {tac['plan']}", ""]
    return out


def main() -> int:
    con = duckdb.connect(str(mx.DB), read_only=True)
    mx._DIRECT.update(mx.load_direct_abilities())
    lists = mx.build_lists(con)
    adjustments = mx.load_adjustments()
    cache: dict = {}
    players = list(lists)
    grid: dict[tuple[str, str], mx.Matchup] = {}
    for a in players:
        for b in players:
            if a != b:
                grid[(a, b)] = mx.evaluate(lists[a], lists[b], adjustments, cache)
    stats = {}
    for p in players:
        ms = [(q, grid[(p, q)]) for q in players if q != p]
        best_units: dict[str, list[float]] = {}
        for _, mm in ms:
            for name, v in mm.att_a.best:
                best_units.setdefault(name, []).append(v)
        stats[p] = {
            "score": mean(mm.score for _, mm in ms),
            "combat": mean(mm.combat for _, mm in ms),
            "board": mean(mm.board for _, mm in ms),
            "apt": mean(mm.apt for _, mm in ms),
            "att_in": mean(mm.att_a.index for _, mm in ms),
            "att_out": mean(mm.att_b.index for _, mm in ms),
            "ranged": mean(mm.att_a.ranged_share for _, mm in ms),
            "best": sorted(ms, key=lambda x: -x[1].score)[:3],
            "worst": sorted(ms, key=lambda x: x[1].score)[:3],
            "stars": sorted(best_units.items(), key=lambda kv: -len(kv[1]))[:3],
        }
    ranking = sorted(players, key=lambda p: -stats[p]["score"])
    rank = {p: i + 1 for i, p in enumerate(ranking)}
    OUT.mkdir(exist_ok=True)
    tactics = json.loads(TACTICS.read_text(encoding="utf-8")) if TACTICS.exists() else {}
    cards_fr = {k: v["fr"] for k, v in tactics.get("cartes", {}).items()}

    def row(al: mx.ArmyList) -> str:
        s, o, d = stats[al.player], mx.offense(al), mx.defense(al)
        return (f"| **{al.player}** | {al.faction} | {rank[al.player]} | {mx.fmt(round(s['score']))} | "
                f"{s['att_in']:.0%} / {s['att_out']:.0%} | {al.n_units} | {al.hp} | {mx._save_txt(d.save)} | "
                f"{d.ward_share:.0%} | {mx._rend_txt(o.rend)} | {o.mortal_share:.0%} | {s['ranged']:.0%} | "
                f"{al.control} | {al.avg_move:.0f}\" | {al.monsters} | "
                f"{al.casters('WIZARD')}/{al.casters('PRIEST')} |")

    league = ["## Classement ligue (54 listes)", "",
              "| Rang | Joueur | Équipe | Faction | Score ligue |", "|---|---|---|---|---|"]
    league += [f"| {rank[p]} | {p} | {lists[p].team} | {lists[p].faction} | {mx.fmt(round(stats[p]['score']))} |"
               for p in ranking]
    teams_avg = sorted(mx._TEAMS, key=lambda t: -mean(stats[p]["score"] for p in mx._TEAMS[t]))
    team_tbl = ["## Équipes", "", "| Équipe | Score ligue moyen | Meilleure liste | Plus faible |",
                "|---|---|---|---|"]
    for t in teams_avg:
        ps = sorted(mx._TEAMS[t], key=lambda p: -stats[p]["score"])
        team_tbl.append(f"| {t} | {mx.fmt(round(mean(stats[p]['score'] for p in ps)))} | "
                        f"{ps[0]} ({lists[ps[0]].faction}) | {ps[-1]} ({lists[ps[-1]].faction}) |")

    for team, members in mx._TEAMS.items():
        combos_path = COMBOS / f"{slug(team)}.json"
        combos = json.loads(combos_path.read_text(encoding="utf-8")) if combos_path.exists() else {}
        ours = [lists[p] for p in members]
        out = [f"# {team} — analyse des listes, L3 Centre 2026-27 (aller)", "",
               "*Document de travail : métriques du moteur + lecture des choix et combos de chaque liste. "
               "Les combos sont à relire et corriger par l'équipe.*", ""]
        out += METHODE
        team_note = combos.get("_équipe")
        out += ["## Vue d'ensemble", ""]
        if team_note:
            out += [team_note, ""]
        out += [PROFILE_HEAD, "|---" * 16 + "|"] + [row(al) for al in ours] + [""]
        for al in sorted(ours, key=lambda x: rank[x.player]):
            s, o, d = stats[al.player], mx.offense(al), mx.defense(al)
            c = combos.get(al.player, {})
            out += [f"## {al.player} — {al.faction}" + (f" ({c['archetype']})" if c.get("archetype") else ""), ""]
            if c.get("choix"):
                out += ["**Choix de liste** : " + c["choix"], ""]
            out += ["**Composition** : " + ", ".join(f"{e.label} ({e.points})" for e in al.entries)
                    + (f". *Absent de la base, non compté* : {', '.join(al.unmatched)}" if al.unmatched else "")
                    + ".", ""]
            stars = ", ".join(f"{n} ({mean(v):.0f} pts/round, dans le top 2 de la liste sur {len(v)} matchups)"
                              for n, v in s["stars"])
            anti = sorted({f"Anti-{kw} {bonus}" for _, kw, bonus in o.anti})
            out += [
                "### Métriques", "",
                f"- *Rang ligue* : **{rank[al.player]}/54**, score moyen {s['score']:+.1f} "
                f"(combat {s['combat']:+.1f}, scénario {s['board']:+.1f}, aptitudes et plan {s['apt']:+.1f}).",
                f"- *Attrition* : inflige {s['att_in']:.0%} de l'armée adverse par round en moyenne, en subit "
                f"{s['att_out']:.0%}. Unités qui portent les dégâts : {stars}.",
                f"- *Perforation* : moyenne {mx._rend_txt(o.rend)} ({o.rend2_share:.0%} des dégâts à −2 ou mieux) ; "
                f"{o.mortal_share:.0%} des dégâts ignorent l'armure ; tir {s['ranged']:.0%}"
                + (f" (portée max {o.max_range}\")" if o.max_range else "") + ".",
                f"- *Défense* : sauvegarde moyenne {mx._save_txt(d.save)} ({d.heavy_share:.0%} des points en 3+ "
                f"ou mieux), ward sur {d.ward_share:.0%} des points"
                + (f" ({mx._save_txt(d.ward_avg)})" if d.ward_share else "") + f", {al.hp} PV.",
                f"- *Scénario* : contrôle {al.control}, {al.n_units} unités, mouvement moyen {al.avg_move:.0f}\", "
                f"vol {al.prof.fly_share:.0%}, indice de mobilité {al.mob:+.1f} ; {al.monsters} monstre(s).",
                f"- *Aptitudes* : indice {al.apt:+.1f} ({mx._apt_summary(al)}) ; note de plan {al.plan}/3.",
                "- *Anti-X* : " + (", ".join(anti) if anti else "aucun")
                + (f" ; Anti-charge : {', '.join(o.anti_charge)}" if o.anti_charge else "") + ".",
                "- *Meilleurs matchups (moteur)* : " + ", ".join(
                    f"{q} ({lists[q].faction}, {mx.fmt(mm.score)})" for q, mm in s["best"])
                + ". *Pires* : " + ", ".join(f"{q} ({lists[q].faction}, {mx.fmt(mm.score)})" for q, mm in s["worst"])
                + ".", ""]
            if c:
                out += ["### Choix et combos", ""]
                if c.get("plan"):
                    out += ["**Plan de jeu** : " + c["plan"], ""]
                for k, title in (("combos", "Combos internes"), ("interactions", "Choix et interactions"),
                                 ("limites", "Points faibles / à surveiller"),
                                 ("moteur", "Ce que le score ligue rate")):
                    if c.get(k):
                        out += [f"**{title}**", ""] + [f"- {x}" for x in c[k]] + [""]
            else:
                out += ["*Choix et combos : pas encore rédigés.*", ""]
            out += tactics_section(c.get("tactiques"), cards_fr)
            out += cp_section(al.prof)
            out += strategy_section(c.get("strategie"))
        out += tactics_general(tactics)
        out += team_tbl + [""] + league + [""]
        path = OUT / f"Listes {team}.md"
        path.write_text("\n".join(out), encoding="utf-8")
        print("écrit :", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

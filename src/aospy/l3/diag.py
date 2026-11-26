"""Diagnostic compact des matchups L3 Centre 2026-27 (aller), sans relire les fichiers Markdown.

Sorties courtes, pensées pour être lues en quelques lignes :

  aospy l3 diag                     corrélations du score ligue + composantes (vérifie les biais)
  aospy l3 diag --rank [N]          classement ligue (N premières lignes, défaut 54) avec composantes
  aospy l3 diag --player P [P...]   indices d'un joueur : mobilité, aptitudes par famille, plan, détail
  aospy l3 diag --match A B         décomposition d'un matchup A contre B (combat, scénario, aptitudes, ajustements)
  aospy l3 diag --team Melusior     grille compacte d'une équipe contre tous ses adversaires de la phase aller

Toutes les options partagent un seul calcul des 1 431 paires (~quelques secondes).
"""

from __future__ import annotations

import argparse
import statistics as st
import sys

import duckdb

from . import matchups as mx


def load():
    con = duckdb.connect(str(mx.DB), read_only=True)
    mx._DIRECT.update(mx.load_direct_abilities())
    lists = mx.build_lists(con)
    return lists, mx.load_adjustments(), {}


def league(lists, adj, cache):
    """Joueur -> moyennes (score, combat, board, apt, adj) contre les 53 autres."""
    players = list(lists)
    acc = {p: [0.0] * 5 for p in players}
    for i, a in enumerate(players):
        for b in players[i + 1 :]:
            m = mx.evaluate(lists[a], lists[b], adj, cache)
            vals = (m.score, m.combat, m.board, m.apt, sum(v for v, _ in m.adj))
            for k, v in enumerate(vals):
                acc[a][k] += v
                acc[b][k] -= v
    return {p: [v / (len(players) - 1) for v in acc[p]] for p in players}


def cmd_corr(lists, stats):
    P = list(lists)
    score = [stats[p][0] for p in P]
    feats = {
        "PV": lambda al: al.hp,
        "mouvement": lambda al: al.avg_move,
        "contrôle": lambda al: al.control,
        "sorciers (niv.)": lambda al: al.prof.wizard_levels,
        "unités": lambda al: al.n_units,
        "indice mobilité": lambda al: al.mob,
        "indice aptitudes": lambda al: al.apt,
        "note plan": lambda al: al.plan,
    }
    print("Corrélation du score ligue avec :")
    for name, f in feats.items():
        print(f"  {name:17s} {st.correlation(score, [f(lists[p]) for p in P]):+.2f}")
    print(
        "Écart-type des composantes (moyennes ligue) :",
        ", ".join(
            f"{n} {st.pstdev([stats[p][k] for p in P]):.2f}"
            for k, n in enumerate(("score", "combat", "scénario", "aptitudes", "ajust."))
        ),
    )


def cmd_rank(lists, stats, n):
    order = sorted(lists, key=lambda p: -stats[p][0])
    print("rang joueur        équipe                       faction                score  comb  scén  apt  ajust")
    for i, p in enumerate(order[:n], 1):
        s, al = stats[p], lists[p]
        print(
            f"{i:4d} {p:13s} {al.team[:28]:28s} {al.faction[:22]:22s} {s[0]:+5.1f} {s[1]:+5.1f} {s[2]:+5.1f} "
            f"{s[3]:+5.1f} {s[4]:+5.1f}"
        )


def cmd_player(lists, stats, players):
    order = sorted(lists, key=lambda p: -stats[p][0])
    for p in players:
        al = lists[p]
        pr = al.prof
        print(f"== {p} ({al.team}, {al.faction}) — rang {order.index(p) + 1}/54, score {stats[p][0]:+.1f}")
        print(
            f'   {al.points} pts, {al.n_units} unités, {al.hp} PV, contrôle {al.control}, mvt {al.avg_move:.1f}", '
            f"vol {pr.fly_share:.0%}, sorciers {pr.wizard_levels}, prêtres {pr.priest_levels}"
        )
        print(f"   indice mobilité {al.mob:+.2f}, indice aptitudes {al.apt:+.2f}, note plan {al.plan}")
        print("   familles : " + ", ".join(f"{f} {pr.score[f]:.1f}" for f in sorted(pr.score) if pr.score[f]))
        for f in sorted(pr.detail):
            names = sorted(set(pr.detail[f]))
            print(f"   - {f} : " + "; ".join(names[:8]) + (f" (+{len(names) - 8})" if len(names) > 8 else ""))
        if al.l4 is not None:
            l4 = al.l4
            print(
                f"   couche 4 : dégâts ×{l4.off_stack:.2f} (montée ×{l4.off_time:.2f}), durabilité ×{l4.def_stack:.2f} "
                f"(montée ×{l4.def_time:.2f}), indice {l4.value:.2f} ; assaut groupé P(≥2) {l4.assault_p2:.0%}"
            )
            print("   empilement : " + "; ".join(f"{n} ×{m:.2f}" for n, m in l4.top))
            print(
                f"   soins (couche 4) : durabilité +{l4.heal:.0%}"
                + (" — " + "; ".join(f"{n} +{v:.0%}" for n, v in l4.heal_top) if l4.heal_top else "")
            )
            print(
                f"   contrôle (couche 4) : +{l4.control:.1f}"
                + (" — " + "; ".join(f"{n} +{v:.1f}" for n, v in l4.control_top) if l4.control_top else "")
            )
            ch = {n: v for n, v in l4.charge.items() if v}
            print("   charge (couche 4) : " + ("; ".join(f'{n} +{v:.1f}"' for n, v in ch.items()) or "aucun bonus"))
            if l4.missing:
                print("   ! unités absentes de la base : " + ", ".join(l4.missing))
        else:
            print(
                "   charge : " + ("; ".join(pr.charge_detail) or "aucune amélioration")
                + f' (armée +{pr.charge_army:.1f}")'
            )
        print(
            "   PC — coûts : "
            + ("; ".join(pr.cp_costs) or "aucune aptitude propre")
            + " | ordres gratuits : "
            + ("; ".join(pr.cp_gains) or "aucun")
            + " | déni adverse : "
            + ("; ".join(pr.cp_deny) or "aucun")
        )
        if al.unmatched:
            print("   absents de la base : " + ", ".join(al.unmatched))
        if p in mx.BT_RULES:
            print("   règles BT (BT_RULES) : " + "; ".join(d for _, _, d in mx.BT_RULES[p].get("aptitudes", [])))


def cmd_match(lists, adj, cache, a, b):
    m = mx.evaluate(lists[a], lists[b], adj, cache)
    A, B = lists[a], lists[b]
    print(f"{a} – {b} : {mx.fmt(m.score)} ({mx.verdict(m.score)})")
    print(
        f"  combat    {m.combat:+.1f}  (attrition {m.att_a.index:.0%} contre {m.att_b.index:.0%} ; "
        f"charge ~{m.att_a.charge_share:.0%} / ~{m.att_b.charge_share:.0%})"
    )
    print(
        f"  scénario  {m.board:+.1f}  (contrôle {A.control}/{B.control}, unités {A.n_units}/{B.n_units}, "
        f"mobilité {A.mob:+.2f}/{B.mob:+.2f})"
    )
    print(f"  aptitudes {m.apt:+.1f}  (indice {A.apt:+.2f}/{B.apt:+.2f}, plan {A.plan}/{B.plan})")
    for v, r in m.adj:
        print(f"  ajust.    {v:+g}  {r[:110]}")


def cmd_team(lists, adj, cache, team):
    ours = mx._TEAMS[team]
    for i, opp in enumerate(mx.SCHEDULE[team], 1):
        if opp is None:
            print(f"Ronde {i} — BYE")
            continue
        theirs = list(mx._TEAMS[opp])
        print(f"Ronde {i} — {opp}")
        print("  " + " " * 13 + " ".join(f"{q[:7]:>7s}" for q in theirs) + "    moy")
        for p in ours:
            sc = [mx.evaluate(lists[p], lists[q], adj, cache).score for q in theirs]
            print(f"  {p:13s}" + " ".join(f"{s:+7d}" for s in sc) + f"  {sum(sc) / len(sc):+5.1f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 diag", description=__doc__.splitlines()[0])
    ap.add_argument("--rank", nargs="?", const=54, type=int)
    ap.add_argument("--player", nargs="+")
    ap.add_argument("--match", nargs=2, metavar=("A", "B"))
    ap.add_argument("--team", choices=list(mx.SCHEDULE))
    args = ap.parse_args(argv)
    lists, adj, cache = load()
    if args.match:
        cmd_match(lists, adj, cache, *args.match)
    if args.team:
        cmd_team(lists, adj, cache, args.team)
    if args.player or args.rank or not (args.match or args.team):
        stats = league(lists, adj, cache)
        if args.player:
            cmd_player(lists, stats, args.player)
        if args.rank:
            cmd_rank(lists, stats, args.rank)
        if not (args.player or args.rank or args.match or args.team):
            cmd_corr(lists, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())

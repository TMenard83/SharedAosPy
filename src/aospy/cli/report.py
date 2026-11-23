"""Formatage texte du rapport de bataille."""

from __future__ import annotations

from io import StringIO
from typing import Iterable

from ..orchestration.benchmark import DuelResult, DuelRules
from ..orchestration.simulation import BattleReport, SideOptions, SideReport

_MODE_LABEL = {"mean": "moyenne", "floor80": "plancher 80%", "floor95": "plancher 95%"}


def _rules_line(rules: DuelRules) -> str:
    """Ligne listant les règles optionnelles actives (vide si aucune)."""
    active = []
    if rules.double_shoot:
        active.append("tir double")
    if rules.charge_move_threshold:
        active.append("seuil de charge 30%")
    return f"  Règles optionnelles : {', '.join(active)}\n" if active else ""


def _opts_line(label: str, opts: SideOptions) -> str:
    parts = []
    parts.append("charge" if opts.charged else "no charge")
    if opts.all_out_attack:
        parts.append("AoA")
    if opts.all_out_defense:
        parts.append("AoD")
    return f"  {label} : " + ", ".join(parts)


def _side_table(side: SideReport, header: str) -> str:
    buf = StringIO()
    buf.write(f"\n=== {header} ===\n")
    buf.write(f"  {'Attaquant':<28} {'Défenseur':<28} {'E[dmg]':>8} {'/ HP':>6} {'E[kill]':>9}\n")
    buf.write(f"  {'-' * 28} {'-' * 28} {'-' * 8} {'-' * 6} {'-' * 9}\n")
    for pr in side.pairs:
        att = f"{pr.attacker_label} (x{pr.attacker_models})"
        dfn = f"{pr.defender_label} (HP {pr.defender_total_hp})"
        buf.write(
            f"  {att:<28} {dfn:<28} {pr.expected_damage:>8.2f} "
            f"{pr.defender_total_hp:>6d} {pr.expected_models_killed:>9.2f}\n"
        )
    return buf.getvalue()


def _per_attacker_best(side: SideReport) -> str:
    buf = StringIO()
    buf.write("\n  Meilleure cible par attaquant :\n")
    best: dict[int, tuple[str, float, str]] = {}
    for pr in side.pairs:
        if pr.attacker_entry_id is None:
            continue
        key = pr.attacker_entry_id
        cur = best.get(key)
        if cur is None or pr.expected_damage > cur[1]:
            best[key] = (pr.attacker_label, pr.expected_damage, pr.defender_label)
    for label, dmg, target in best.values():
        buf.write(f"    - {label:<28} → {target:<28} {dmg:>8.2f} dmg\n")
    buf.write(f"  Total (somme des meilleures cibles) : {side.best_target_total:.2f}\n")
    return buf.getvalue()


def _per_defender_total(side: SideReport, who: str) -> str:
    buf = StringIO()
    buf.write(f"\n  Dégâts reçus par chaque unité de {who} (sommé sur tous les attaquants) :\n")
    totals: dict[int, tuple[str, float, int]] = {}
    for pr in side.pairs:
        if pr.defender_entry_id is None:
            continue
        key = pr.defender_entry_id
        prev = totals.get(key)
        if prev is None:
            totals[key] = (pr.defender_label, pr.expected_damage, pr.defender_total_hp)
        else:
            totals[key] = (prev[0], prev[1] + pr.expected_damage, prev[2])
    for label, dmg, hp in totals.values():
        pct = 100.0 * dmg / hp if hp else 0.0
        cap = " (cap atteint si focus unique)" if dmg >= hp else ""
        buf.write(f"    - {label:<28} {dmg:>8.2f} / {hp:>4d} HP  ({pct:5.1f}%){cap}\n")
    return buf.getvalue()


def format_report(report: BattleReport) -> str:
    buf = StringIO()
    a = report.a_to_b.composition
    b = report.b_to_a.composition

    buf.write("\n================ Bataille =================\n")
    buf.write(f"  A : #{a.id} {a.name}  ({a.total_points} pts)\n")
    buf.write(f"  B : #{b.id} {b.name}  ({b.total_points} pts)\n")
    buf.write("  Modificateurs :\n")
    buf.write(_opts_line("A", report.options_a) + "\n")
    buf.write(_opts_line("B", report.options_b) + "\n")

    buf.write(_side_table(report.a_to_b, "A → B (matrice complète)"))
    buf.write(_per_attacker_best(report.a_to_b))
    buf.write(_per_defender_total(report.a_to_b, "B"))

    buf.write(_side_table(report.b_to_a, "B → A (matrice complète)"))
    buf.write(_per_attacker_best(report.b_to_a))
    buf.write(_per_defender_total(report.b_to_a, "A"))

    net = report.a_to_b.best_target_total - report.b_to_a.best_target_total
    buf.write("\n=== Synthèse (cibles optimales) ===\n")
    buf.write(f"  A → B : {report.a_to_b.best_target_total:8.2f}\n")
    buf.write(f"  B → A : {report.b_to_a.best_target_total:8.2f}\n")
    buf.write(f"  Net (A − B) : {net:+.2f}\n")
    return buf.getvalue()


# ----- Benchmark unit-vs-unit ----------------------------------------------


def _duel_opts_line(opts_a: SideOptions, opts_b: SideOptions) -> str:
    def side(opts: SideOptions) -> str:
        parts = ["charge" if opts.charged else "no charge"]
        if opts.all_out_attack:
            parts.append("AoA")
        if opts.all_out_defense:
            parts.append("AoD")
        return ", ".join(parts)

    return f"  A : {side(opts_a)}    B : {side(opts_b)}"


def format_benchmark_table(
    results: Iterable[DuelResult],
    sort_by: str = "pts-net",
) -> str:
    """Tableau condensé : un duel par ligne, trié."""
    items = list(results)
    keys = {
        "pts-net": lambda r: -r.pts_net,
        "roi": lambda r: -r.roi,
        "net": lambda r: -r.net,
        "atb": lambda r: -r.expected_a_to_b,
        "bta": lambda r: -r.expected_b_to_a,
        "points": lambda r: (r.defender.points, r.defender_army_name),
        "army": lambda r: (r.defender_army_name, -r.pts_net),
    }
    items.sort(key=keys.get(sort_by, keys["pts-net"]))

    buf = StringIO()
    buf.write(
        f"  {'Défenseur':<28} {'Armée':<22} {'Pts':>4} {'HP':>4} "
        f"{'E[A→B]':>7} {'%B':>4} {'E[B→A]':>7} {'%A':>4} "
        f"{'Pts net':>8} {'ROI':>6}\n"
    )
    buf.write(
        f"  {'-' * 28} {'-' * 22} {'-' * 4} {'-' * 4} {'-' * 7} {'-' * 4} {'-' * 7} {'-' * 4} {'-' * 8} {'-' * 6}\n"
    )
    for r in items:
        name = r.defender.name + (" (R)" if r.defender_reinforced else "")
        pct_b = 100.0 * r.expected_a_to_b / r.defender_total_hp if r.defender_total_hp else 0.0
        pct_a = 100.0 * r.expected_b_to_a / r.attacker_total_hp if r.attacker_total_hp else 0.0
        buf.write(
            f"  {name[:28]:<28} {r.defender_army_name[:22]:<22} "
            f"{r.defender.points:>4d} {r.defender_total_hp:>4d} "
            f"{r.expected_a_to_b:>7.2f} {pct_b:>3.0f}% "
            f"{r.expected_b_to_a:>7.2f} {pct_a:>3.0f}% "
            f"{r.pts_net:>+8.1f} {r.roi * 100:>+5.0f}%\n"
        )
    return buf.getvalue()


def format_duel_detail(r: DuelResult) -> str:
    """Rapport détaillé d'un duel : profils + résultats par direction."""
    buf = StringIO()
    a, d = r.attacker, r.defender
    buf.write(
        f"\n--- {a.name} (x{r.attacker_models}, M{a.move} Sv{a.save}+ "
        f"HP{a.health} pts{a.points})"
        f"  vs  {d.name} [{r.defender_army_name}] "
        f"(x{r.defender_models}, M{d.move} Sv{d.save}+ HP{d.health} pts{d.points}) ---\n"
    )
    buf.write(
        f"  A → B ({_MODE_LABEL[r.mode_a]}) : E[dmg]={r.expected_a_to_b:6.2f} (brut {r.raw_a_to_b:6.2f}) "
        f"/ HP {r.defender_total_hp} → E[models killed]={r.expected_models_killed_b:5.2f}\n"
    )
    buf.write(
        f"  B → A ({_MODE_LABEL[r.mode_b]}) : E[dmg]={r.expected_b_to_a:6.2f} (brut {r.raw_b_to_a:6.2f}) "
        f"/ HP {r.attacker_total_hp} → E[models killed]={r.expected_models_killed_a:5.2f}\n"
    )
    buf.write(_rules_line(r.rules))
    buf.write(f"  Net (HP)  : {r.net:+6.2f}\n")
    buf.write(
        f"  Pts détruits chez B : {r.pts_destroyed:6.1f} "
        f"({r.defender.points} pts × {r.expected_a_to_b / max(r.defender_total_hp, 1):4.0%})\n"
    )
    buf.write(
        f"  Pts perdus chez A   : {r.pts_lost:6.1f} "
        f"({r.attacker.points} pts × {r.expected_b_to_a / max(r.attacker_total_hp, 1):4.0%})\n"
    )
    buf.write(f"  Pts net   : {r.pts_net:+6.1f}   ROI : {r.roi * 100:+.0f}%\n")
    return buf.getvalue()


def format_unit_stats(
    unit,
    army_name: str,
    rows: list[tuple[str, float, float, float]],
    *,
    charged: bool,
) -> str:
    """Moyenne / écart-type / plancher 95 % d'une unité contre des cibles standard."""
    buf = StringIO()
    buf.write(
        f"\n--- {unit.name} [{army_name}] (x{unit.models}, M{unit.move} "
        f"Sv{unit.save}+ HP{unit.health} pts{unit.points})"
        f"{'  (charge)' if charged else ''} ---\n"
    )
    buf.write(f"  {'Cible':<12} {'E[dmg]':>8} {'σ':>7} {'Plancher 95%':>13}\n")
    buf.write(f"  {'-' * 12} {'-' * 8} {'-' * 7} {'-' * 13}\n")
    for label, mean, std, floor95 in rows:
        buf.write(f"  {label:<12} {mean:8.2f} {std:7.2f} {floor95:13.2f}\n")
    return buf.getvalue()


def format_benchmark(
    attacker_label: str,
    results: list[DuelResult],
    opts_a: SideOptions,
    opts_b: SideOptions,
    sort_by: str = "pts-net",
    detail: bool = False,
    top: int | None = None,
) -> str:
    """Sortie complète : entête + tableau + (optionnel) détails."""
    buf = StringIO()
    buf.write(f"\n=========== Benchmark : {attacker_label} ===========\n")
    buf.write(_duel_opts_line(opts_a, opts_b) + "\n")
    if results:
        buf.write(_rules_line(results[0].rules))
    buf.write(f"  {len(results)} défenseurs testés\n\n")
    buf.write(format_benchmark_table(results, sort_by=sort_by))
    if detail:
        items = sorted(results, key=lambda r: -r.pts_net)
        if top is not None:
            items = items[:top]
        buf.write("\n=== Détails ===\n")
        for r in items:
            buf.write(format_duel_detail(r))
    return buf.getvalue()


def format_list_report(rep) -> str:
    """Fiche couche 4 chiffrée d'une liste (`analysis.layers.listing.ListReport`) en Markdown : la matière que
    l'analyse humaine (concept, plan round par round) reprend — jamais une analyse en soi."""
    out = [f"# {rep.title} — {rep.faction} — fiche couche 4 chiffrée", ""]
    out += [
        "## Unités (couche 3)",
        "",
        "| unité | pts | × | dég/100 | dur/100 | rang dég | rang dur | ch.comb | bon cas | mêlée | mv | "
        "engagement | rôle suggéré |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in rep.sheets:
        out.append(
            f"| {s.name} | {s.points} | {s.copies} | {s.off_per_100:.1f} | {s.def_per_100:.1f} | "
            f"{s.off_rank:.2f} | {s.def_rank:.2f} | {s.fit_per_100:.1f} | {s.good_per_100:.1f} | "
            f"{s.share_melee:.0%} | {s.move}{' vol' if s.fly else ''} | R{s.engage_round} | {s.role} |"
        )
    weak = [(s.name, w) for s in rep.sheets for w in s.weak_marriages]
    if weak:
        out += ["", "### Aptitudes mal mariées à leur porteur (mariage < 0,4)", ""]
        out += [f"- **{n}** — {a} : {m:.2f} ({e})" for n, (a, m, e) in weak]
    if rep.picks:
        out += [
            "",
            "## Optimisations prises vs meilleurs porteurs de la liste",
            "",
            "| optimisation | porteur | valeur | mariage | meilleur dans la liste | valeur | mariage | éligibles |",
            "|---|---|---|---|---|---|---|---|",
        ]
        f = lambda v: "—" if v is None else f"{v:.2f}"
        for p in rep.picks:
            out.append(
                f"| {p.enhancement} | {p.bearer} | {f(p.bearer_value)} | {p.bearer_marriage:.2f} | "
                f"{p.best_in_list} | {f(p.best_value)} | {p.best_marriage:.2f} | {p.n_eligible} |"
            )
    if rep.dead:
        out += ["", "## Règles mortes (composition)", ""]
        out += [f"- {a.name} ({a.source}) — {r}" for a, r in rep.dead]
    if rep.marriages:
        out += [
            "",
            "## Mariages chiffrés (effet de la liste × receveur de la liste)",
            "",
            "| aptitude | origine | receveur | dég % | dur % | poids | conditions |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in rep.marriages[:40]:
            og = "—" if m.off_gain_pct is None else f"{m.off_gain_pct:+.0f}"
            dg = "—" if m.def_gain_pct is None else f"{m.def_gain_pct:+.0f}"
            name = f"{m.ability} ({m.option})" if m.option else m.ability
            out.append(f"| {name} | {m.source} | {m.receiver} | {og} | {dg} | {m.weight:.2f} | {m.conditions} |")
    if rep.assault:
        a = rep.assault
        out += [
            "",
            "## Assaut : charges groupées (redondance et secours)",
            "",
            "Hypothèse : tous les chargeurs dans les bulles des sources (point de chute groupé) ; "
            "dissipation adverse non comptée.",
            "",
        ]
        if a.sources:
            out += ["Sources de la liste :", ""]
            for s in a.sources:
                what = {
                    "bonus": f"+{s.value:g} au jet",
                    "relance": "relance des jets de charge",
                    "dés": {
                        "3d6": "charge sur 3D6",
                        "3k2": "3 dés, on garde les 2 meilleurs",
                        "max": "le plus bas des 2D6 aligné sur le plus haut",
                    }.get(s.dice, s.dice),
                }[s.kind]
                extra = [f"existe à {s.p_present:.0%}"] if s.p_present < 1 else []
                if s.per_battle:
                    extra.append("1×/bataille")
                out.append(
                    f"- **{s.name}** ({s.origin}) : {what} → {', '.join(s.receivers)}"
                    + (f" ({', '.join(extra)})" if extra else "")
                )
            out.append("")
        for sc in a.scenarios:
            n = len(sc.cases[0].at_least)
            out += [
                f"### {sc.label} — {len(sc.chargers)} chargeurs",
                "",
                "Par chargeur (sec → bonus permanents) : "
                + " ; ".join(f"{c} {p:.0%} → {b:.0%}" for c, p, b in sc.chargers),
                "",
                "| cas | " + " | ".join(f"≥ {k}" for k in range(1, n + 1)) + " |",
                "|---|" + "---|" * n,
            ]
            out += [f"| {c.label} | " + " | ".join(f"{p:.0%}" for p in c.at_least) + " |" for c in sc.cases]
            out.append("")
        if a.threats:
            out += [
                "### À pied : portée de menace (punition des erreurs adverses)",
                "",
                "Mouvement + plus long jet de charge réussi à 50 % : un adversaire plus près se fait charger.",
                "",
                "| chargeur | mouvement | sec | bonus permanents | + relance |",
                "|---|---|---|---|---|",
            ]
            out += [f'| {t.unit} | {t.move:g}" | {t.dry:g}" | {t.bonus:g}" | {t.reroll:g}" |' for t in a.threats]
            out.append("")
    stacked = getattr(rep, "stacks", None)
    if stacked:
        out += [
            "",
            "## Empilement : tout ce que chaque unité reçoit en même temps",
            "",
            "Tous les effets traduisibles qu'elle peut recevoir, plus All-out Attack / All-out Defence, appliqués "
            "ENSEMBLE (plafond ±1 sur le total des modificateurs de toucher, blessure, sauvegarde ; une option par "
            "aptitude à choix ; protections non cumulées). Cas « tout en place », sans fiabilité. « Produit » = gains "
            "pris un par un multipliés (référence sans interaction) : ensemble < produit → plafonds, ensemble > "
            "produit → effet de seuil. « Plafonné » = n'ajoute rien une fois les autres en place.",
            "",
            "| unité | effets | dégâts/round nu → tout en place | dég. ensemble | dég. produit | dur. ensemble | "
            "dur. produit | plafonnés | PC |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for st in stacked:
            capped = ", ".join(i.ability for i in st.items if i.capped) or "—"
            out.append(
                f"| {st.receiver} | {len(st.items)} | {st.off_before:.1f} → {st.off_after:.1f} | "
                f"{st.off_joint_pct:+.0f} % | {st.off_prod_pct:+.0f} % | "
                f"{st.def_joint_pct:+.0f} % | {st.def_prod_pct:+.0f} % | {capped} | {st.cp} |"
            )
        for st in stacked[:3]:
            out += ["", f"**{st.receiver}** (dég. {st.off_joint_pct:+.0f} %, dur. {st.def_joint_pct:+.0f} %) :", ""]
            for i in st.items:
                tag = " — plafonné" if i.capped else ""
                cond = f" ; si {i.conditions}" if i.conditions else ""
                cp = f" ; {i.cp} PC" if i.cp else ""
                out.append(
                    f"- {i.ability} ({i.source}) : dég. {i.off_alone_pct:+.0f} %, dur. {i.def_alone_pct:+.0f} %"
                    f"{cond}{cp}{tag}"
                )
    if rep.conflicts:
        out += ["", "## Limites d'armée (un seul usage pour plusieurs porteurs)", ""]
        out += [f"- {c.ability} ({c.frequency}) : {', '.join(c.carriers)}" for c in rep.conflicts]
    if rep.magic:
        out += ["", f"## Magie : {rep.magic.casts_per_turn} lancers par tour", ""]
        out += [f"- {c} : {n}" for c, n in rep.magic.casters]
        out += [f"- sort {n} ({src}) : valeur {v}, P {p:.0%}" for n, src, v, p in rep.magic.spells]
    grid = getattr(rep, "grid", None)
    if grid:
        out += [
            "",
            "## Aptitudes non traduites, rejouées sur la liste",
            "",
            "Mariage du porteur (couche 3) ; suivi = allonge du porteur ÷ allonge médiane de ses receveurs DANS la "
            "liste (1 = il suit) ; ce que chaque receveur de la liste en tire, mesuré par la grille de sa famille.",
            "",
            "| aptitude | origine | famille | verdict | porteur (mariage) | suivi | receveurs de la liste |",
            "|---|---|---|---|---|---|---|",
        ]
        for g in grid:
            bearer = f"{g.bearer} ({g.bearer_marriage:.2f})" if g.bearer and g.bearer_marriage is not None else g.bearer
            ku = f"{g.keep_up:.2f}" if g.keep_up is not None else ""
            recv = "; ".join(f"{n} : {lab}" if lab else n for n, lab in g.receivers)
            if g.note:
                recv = f"{recv} — {g.note}" if recv else g.note
            out.append(f"| {g.ability} | {g.source} | {g.family} | {g.verdict} | {bearer} | {ku} | {recv} |")
        if rep.drawbacks:
            out += ["", "Contreparties écartées : " + ", ".join(f"{a.name} ({a.source})" for a in rep.drawbacks)]
    elif rep.unresolved:
        out += ["", "## À lire (non chiffré : tempo, mobilité, ressources, débuffs…)", ""]
        out += [f"- {a.name} ({a.source}) — {a.verdict}" for a in rep.unresolved]
    return "\n".join(out) + "\n"

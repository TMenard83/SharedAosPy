"""Formatage texte du rapport de bataille."""

from __future__ import annotations

from collections import defaultdict
from io import StringIO
from typing import Iterable

from .benchmark import DuelResult
from .simulation import BattleReport, SideOptions, SideReport


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
    buf.write(
        f"  {'Attaquant':<28} {'Défenseur':<28} {'E[dmg]':>8} "
        f"{'/ HP':>6} {'E[kill]':>9}\n"
    )
    buf.write(f"  {'-'*28} {'-'*28} {'-'*8} {'-'*6} {'-'*9}\n")
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

    buf.write(f"\n================ Bataille =================\n")
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
    buf.write(f"  {'-'*28} {'-'*22} {'-'*4} {'-'*4} "
              f"{'-'*7} {'-'*4} {'-'*7} {'-'*4} {'-'*8} {'-'*6}\n")
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
        f"  A → B : E[dmg]={r.expected_a_to_b:6.2f} (brut {r.raw_a_to_b:6.2f}) "
        f"/ HP {r.defender_total_hp} → E[models killed]={r.expected_models_killed_b:5.2f}\n"
    )
    buf.write(
        f"  B → A : E[dmg]={r.expected_b_to_a:6.2f} (brut {r.raw_b_to_a:6.2f}) "
        f"/ HP {r.attacker_total_hp} → E[models killed]={r.expected_models_killed_a:5.2f}\n"
    )
    buf.write(f"  Net (HP)  : {r.net:+6.2f}\n")
    buf.write(
        f"  Pts détruits chez B : {r.pts_destroyed:6.1f} "
        f"({r.defender.points} pts × {r.expected_a_to_b / max(r.defender_total_hp, 1):4.0%})\n"
    )
    buf.write(
        f"  Pts perdus chez A   : {r.pts_lost:6.1f} "
        f"({r.attacker.points} pts × {r.expected_b_to_a / max(r.attacker_total_hp, 1):4.0%})\n"
    )
    buf.write(f"  Pts net   : {r.pts_net:+6.1f}   "
              f"ROI : {r.roi * 100:+.0f}%\n")
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

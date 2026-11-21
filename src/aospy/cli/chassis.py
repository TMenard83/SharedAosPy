"""Commande `chassis` : couche 2, la charte nue (analysis/layers/chassis.py)."""

from __future__ import annotations

import argparse

from ..persistence import repository
from .common import _connect


def cmd_chassis_build(args: argparse.Namespace) -> int:
    from ..analysis.layers.chassis import build_chassis_rows

    con = _connect(args)
    rows, notes = build_chassis_rows(con)
    repository.replace_chassis(con, rows)
    con.close()
    print(f"{len(rows)} châssis construits.")
    for n in notes:
        print(f"⚠ {n}")
    return 0


def _pct(v) -> str:
    return "  -  " if v is None else f"{v:+5.0f}%"


def cmd_chassis_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    hero = True if args.heroes else False if args.troops else None
    rows = repository.list_chassis(
        con, army=args.army, hero=hero, order_by=args.sort, ascending=args.asc, limit=args.limit
    )
    con.close()
    if not rows:
        print("Aucun châssis (lancez `aospy chassis build`).")
        return 1
    print(
        "dég/100 = dégâts moyens d'un round vs save 4+ pour 100 pts ; dur/100 = coups à porter pour tuer, "
        "pour 100 pts ; rang = centile dans le segment ; résidu < 0 = moins cher que prédit ; "
        "%D1/%Comp = part des dégâts d'armes à 1 dégât / Compagnon"
    )
    print(
        f"{'unité':<38}{'armée':<22}{'pts':>5}{'dég/100':>8}{'rang':>6}{'dur/100':>8}{'rang':>6}"
        f"{'résidu':>8}{'duel':>7}{'%D1':>5}{'%Comp':>6}"
    )
    for r in rows:
        print(
            f"{r['name'][:37]:<38}{r['army_name'][:21]:<22}{r['points']:>5}{r['dmg_per_100']:>8.1f}"
            f"{r['dmg_pct_rank']:>6.2f}{r['ewounds_per_100']:>8.1f}{r['ewounds_pct_rank']:>6.2f}"
            f"{_pct(r['cost_residual_pct']):>8}{_pct(r['duel_roi_pct']):>7}"
            f"{r['share_damage1']:>5.0%}{r['share_companion']:>6.0%}"
        )
    return 0


def cmd_chassis_show(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_chassis(con, name=args.name, order_by="name", ascending=True, limit=5)
    con.close()
    if not rows:
        print(f"Aucun châssis ne correspond à {args.name!r}.")
        return 1
    for r in rows:
        seg = "héros" if r["is_hero"] else "troupes"
        ward = f", protection {r['ward']}+" if r["ward"] else ""
        print(f"=== {r['name']} [{r['army_name']}] — {r['points']} pts, {r['unit_type']}, {seg}")
        print(
            f"Profil : {r['models']} fig. × {r['health']} PV, sauvegarde {r['save']}+{ward}, "
            f'mouvement {r["move"]}"{" (vol)" if r["is_flying"] else ""}'
        )
        print(
            f"Attaque : {r['dmg_melee']:.1f} en mêlée + {r['dmg_ranged']:.1f} au tir (vs save 4+), "
            f"{r['attacks_total']:.0f} attaques — {r['dmg_per_100']:.1f} pour 100 pts (centile {r['dmg_pct_rank']:.0%})"
        )
        print(
            f"Défense : {r['effective_wounds']:.0f} coups à porter — {r['ewounds_per_100']:.1f} pour 100 pts "
            f"(centile {r['ewounds_pct_rank']:.0%})"
        )
        print(
            f"Compatibilité : {r['share_melee']:.0%} des dégâts en mêlée, {r['share_damage1']:.0%} d'armes à 1 dégât, "
            f"{r['share_companion']:.0%} d'armes Compagnon, critique dominant {r['crit_type']}"
        )
        print(f"Prix : résidu {_pct(r['cost_residual_pct']).strip()} ; duel : {_pct(r['duel_roi_pct']).strip()}\n")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `chassis` : couche 2, la charte nue (analysis/layers/chassis.py)."""
    p_ch = sub.add_parser("chassis", help="Châssis des unités : la charte nue, sans aptitudes.")
    sch = p_ch.add_subparsers(dest="action", required=True)
    p = sch.add_parser("build", help="(Re)construit la table unit_chassis.")
    p.set_defaults(func=cmd_chassis_build)
    p = sch.add_parser("list", help="Liste les châssis filtrés et triés.")
    p.add_argument("--army", help="Sous-chaîne du nom d'armée.")
    seg = p.add_mutually_exclusive_group()
    seg.add_argument("--heroes", action="store_true", help="Héros seulement.")
    seg.add_argument("--troops", action="store_true", help="Troupes seulement.")
    p.add_argument(
        "--sort",
        default="dmg_per_100",
        choices=[
            "dmg_per_100",
            "ewounds_per_100",
            "cost_residual_pct",
            "duel_roi_pct",
            "share_damage1",
            "share_companion",
            "points",
            "name",
        ],
    )
    p.add_argument("--asc", action="store_true", help="Tri croissant (ex. résidu le plus négatif).")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_chassis_list)
    p = sch.add_parser("show", help="Fiche de châssis d'une unité.")
    p.add_argument("name", help="Nom (sous-chaîne).")
    p.set_defaults(func=cmd_chassis_show)

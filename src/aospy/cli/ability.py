"""Commande `ability` : analyse hors contexte de toutes les aptitudes (src/aospy/abilities/)."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..persistence import repository
from .common import _connect

_VERDICT_FR = {
    "plan": "PLAN",
    "correct": "correct",
    "pari": "PARI",
    "bonus": "BONUS",
    "anecdotique": "anecdotique",
    "a-revoir": "à revoir",
}


def cmd_ability_analyze(args: argparse.Namespace) -> int:
    from ..abilities.pipeline import ANALYZER_VERSION, analyze_all, to_rows
    from ..abilities.source import DEFAULT_DATA_DIR

    analyses, orphans = analyze_all(args.data_dir or DEFAULT_DATA_DIR)
    con = _connect(args)
    repository.replace_ability_analyses(con, *to_rows(analyses))
    stats = repository.ability_stats(con)
    con.close()
    print(f"{len(analyses)} aptitudes analysées (analyseur v{ANALYZER_VERSION}).")
    print("  " + ", ".join(f"{_VERDICT_FR.get(v, v)} {n}" for v, n in stats["verdict"]))
    if orphans:
        print(f"⚠ {len(orphans)} correction(s) manuelle(s) orpheline(s) (texte modifié ?) : {', '.join(orphans)}")
    return 0


def _ability_line(r: dict, with_text: bool) -> str:
    axes = f"P{r['power']:.1f} F{r['reliability']:.1f} M{r['ease']:.1f} I{r['interaction']:.1f}"
    head = (
        f"{_VERDICT_FR.get(r['verdict'], r['verdict']):<11} {axes}  {r['name']}"
        f"  [{r['faction_id']}] {r['owners'] or ''}"[:160]
    )
    out = head + f"\n            {r['tags']}"
    if with_text:
        out += f"\n            {(r['effect_text'] or '')[:300]}"
    return out


def cmd_ability_search(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.search_abilities(
        con,
        name=args.name,
        faction=args.faction,
        owner=args.owner,
        tags=args.tag,
        verdict=args.verdict,
        source_kind=args.kind,
        order_by=args.sort,
        limit=args.limit,
    )
    con.close()
    if not rows:
        print("Aucune aptitude (lancez `aospy ability analyze` si les tables sont vides).")
        return 1
    print("P=puissance F=fiabilité M=mise en place I=interaction (0-3)")
    for r in rows:
        print(_ability_line(r, args.text))
    return 0


def cmd_ability_show(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = [
        r
        for r in repository.search_abilities(con, faction=args.faction, limit=5000, order_by="name")
        if r["uid"] == args.name or args.name.lower() in r["name"].lower()
    ]
    if not rows:
        con.close()
        print(f"Aucune aptitude ne correspond à {args.name!r}.")
        return 1
    for r in rows[:5]:
        print(f"=== {r['name']} — {r['source_kind']} [{r['faction_name']}] uid={r['uid']}")
        print(f"Porteurs : {r['owners']}")
        cost = f" | coût {r['cost_type']} {r['cost_value']}" if r["cost_type"] else ""
        print(f"Timing : {r['condition_text']}{cost}")
        if r["declare_text"]:
            print(f"Annonce : {r['declare_text']}")
        print(f"Effet : {r['effect_text']}")
        print(
            f"Verdict : {_VERDICT_FR.get(r['verdict'], r['verdict'])}"
            f"{' (corrigé à la main)' if r['overridden'] else ''}"
        )
        print(r["rationale"])
        print(f"Tags : {r['tags']}")
        effects = repository.get_ability_effects(con, r["uid"])
        if effects:
            print("Effets :")
        for e in effects:
            what = f"{e['kind']}{' ' + e['stat'] if e['stat'] else ''}"
            if e["kind"] == "stat_mod":
                what += f" {e['value']:+g}"
            elif e["dice"]:
                what += f" {e['dice']}"
            elif e["value"]:
                what += f" {e['value']:g}"
            scope = e["weapon_scope"] or ""
            if e["weapon_name"]:
                scope += f" « {e['weapon_name']} »"
            if e["includes_companion"]:
                scope += " (Compagnon incluses)"
            bits = [
                b
                for b in (
                    f"{e['side']}" if e["side"] else "",
                    f"armes : {scope}" if scope else "",
                    f"cible : {e['target_keywords']}" if e["target_keywords"] else "",
                    e["target_condition"] or "",
                    f"si : {e['requires']}" if e["requires"] else "",
                    f"durée : {e['duration']}" if e["duration"] else "",
                )
                if b
            ]
            print(f"  - {what} — {', '.join(bits)}")
        print()
    con.close()
    if len(rows) > 5:
        print(f"… {len(rows) - 5} autre(s) ; affinez avec --faction.")
    return 0


def cmd_ability_stats(args: argparse.Namespace) -> int:
    con = _connect(args)
    st = repository.ability_stats(con)
    con.close()
    print("Verdicts : " + ", ".join(f"{_VERDICT_FR.get(v, v)} {n}" for v, n in st["verdict"]))
    print("Origine (total / non comprises) :")
    for kind, n, unknown in st["source_kind"]:
        print(f"  {kind:<16} {n:>5} {unknown:>5}")
    print("Tags : " + ", ".join(f"{t} {n}" for t, n in st["tag"]))
    for version, when, n in st["version"]:
        print(f"Analyseur v{version} — {n} lignes, {when:%Y-%m-%d %H:%M}")
    return 0


def cmd_ability_review(args: argparse.Namespace) -> int:
    from ..abilities.overrides import load_overrides

    reviewed = list(load_overrides())
    con = _connect(args)
    if not args.category:
        print("Familles de cas suspects (hors aptitudes déjà tranchées dans ability_overrides.json) :")
        for key, (label, _sql) in repository.ABILITY_REVIEW_CATEGORIES.items():
            total, _ = repository.ability_review_queue(con, key, reviewed, limit=1)
            print(f"  {key:<11} {total:>4}  {label}")
        con.close()
        return 0
    total, rows = repository.ability_review_queue(con, args.category, reviewed, limit=args.limit)
    con.close()
    label = repository.ABILITY_REVIEW_CATEGORIES[args.category][0]
    print(f"{args.category} — {label} : {total} restant(s), {len(rows)} affiché(s)")
    for i, r in enumerate(rows, 1):
        print(
            f"\n{i}. {r['name']} [{r['faction_id']}] — {_VERDICT_FR.get(r['verdict'], r['verdict'])} — uid {r['uid']}"
        )
        print(f"   Timing : {r['condition_text']}")
        if r["declare_text"]:
            print(f"   Annonce : {r['declare_text'][:220]}")
        print(f"   Effet : {(r['effect_text'] or '')[:320]}")
    return 0


def cmd_ability_tags(args: argparse.Namespace) -> int:
    from ..abilities.tags import ALL_TAGS

    for tag, desc in ALL_TAGS.items():
        print(f"{tag:<22} {desc}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `ability` : analyse hors contexte de toutes les aptitudes (src/aospy/abilities/)."""
    p_ab = sub.add_parser("ability", help="Analyse des aptitudes (plan / pari / anecdotique, tags).")
    sab = p_ab.add_subparsers(dest="action", required=True)
    p = sab.add_parser("analyze", help="(Re)construit les tables ability* depuis les CSV Wahapedia.")
    p.add_argument("--data-dir", type=Path, default=None, help="Dossier des CSV (défaut: data/wahapedia).")
    p.set_defaults(func=cmd_ability_analyze)
    p = sab.add_parser("search", help="Cherche des aptitudes par tag/faction/porteur/verdict.")
    p.add_argument("--name", help="Sous-chaîne du nom de l'aptitude.")
    p.add_argument("--faction", help="Sous-chaîne du nom de faction, ou son code (SE, StD…).")
    p.add_argument("--owner", help="Sous-chaîne du porteur (warscroll ou groupe de règle).")
    p.add_argument("--tag", action="append", default=[], help="Tag exigé (répétable : tous requis).")
    p.add_argument("--verdict", choices=["plan", "correct", "pari", "bonus", "anecdotique", "a-revoir"])
    p.add_argument("--kind", help="Origine : warscroll, battle_trait, spell, prayer…")
    p.add_argument("--sort", default="power", choices=["power", "ease", "reliability", "interaction", "name"])
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--text", action="store_true", help="Affiche aussi le texte de l'effet.")
    p.set_defaults(func=cmd_ability_search)
    p = sab.add_parser("show", help="Fiche complète (texte, axes, justification) d'une aptitude.")
    p.add_argument("name", help="Nom (sous-chaîne) ou uid.")
    p.add_argument("--faction", help="Restreint à une faction.")
    p.set_defaults(func=cmd_ability_show)
    p = sab.add_parser("stats", help="Décomptes (verdicts, origines non comprises, tags).")
    p.set_defaults(func=cmd_ability_stats)
    p = sab.add_parser("review", help="File des cas suspects à revoir (hors aptitudes déjà corrigées).")
    p.add_argument("category", nargs="?", help="Famille (sans argument : liste des familles et décomptes).")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_ability_review)
    p = sab.add_parser("tags", help="Vocabulaire des tags.")
    p.set_defaults(func=cmd_ability_tags)

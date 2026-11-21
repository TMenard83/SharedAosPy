"""Commande `encounter` : couche 3, rencontre aptitude × châssis (analysis/layers/encounter.py)."""

from __future__ import annotations

import argparse

from ..persistence import repository
from .common import _connect


def cmd_encounter_build(args: argparse.Namespace) -> int:
    from ..analysis.layers.encounter import build_encounter_rows

    con = _connect(args)
    from ..analysis.layers.realized import build_realized_rows

    rows, stats = build_encounter_rows(con)
    repository.replace_encounters(con, rows)
    realized = build_realized_rows(con)
    repository.replace_realized(con, realized)
    from ..analysis.layers.marriage import build_marriage_rows

    marriage = build_marriage_rows(con)
    repository.replace_ability_marriage(con, marriage)
    from ..analysis.layers.bearers import build_bearer_rows

    bearers = build_bearer_rows(con)
    repository.replace_enhancement_bearers(con, bearers)
    con.close()
    print(f"{len(bearers)} couples optimisation × porteur éligible.")
    print(f"{len(realized)} valeurs réalisées (châssis + aptitudes propres pondérées).")
    print(f"{len(marriage)} mariages aptitude × porteur (déclenchement × survie × tempo × amplification × rôle).")
    print(
        f"{stats['rencontres']} rencontres aptitude × châssis ({stats['traduits']} effets amis traduits "
        f"sur {stats['effets']} ; {stats['sans_arme']} paires sans arme concernée)."
    )
    return 0


def cmd_encounter_marriage(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_marriage(
        con, ability=args.ability, unit=args.unit, family=args.family, worst=args.worst, limit=args.limit
    )
    con.close()
    if not rows:
        print("Aucun mariage (lancez `aospy encounter build`).")
        return 1
    print(
        "Mariage = D × S × F × A × R. D = P(conditions tenues par le porteur : charge, territoire, objectif…) "
        "× rounds encore possibles ; S = part des rounds où il survit pour tenir l'effet, à l'exposition imposée "
        '(contact ≤3", courte ≤9", longue derrière un écran) face à une unité ennemie moyenne ; F = tempo '
        "(la fenêtre de l'effet tombe quand le châssis agit) ; A = amplification (gain ici / gain médian du même "
        "effet) ; R = rôle (buff offensif sur un marteau, défensif sur qui encaisse, bulle : le porteur suit). "
        "A et R bornés 0,5-1,5 ; familles hors buffs : F = A = R = 1.\n"
        "Hypothèses (marriage.py) à challenger. « bon cas » : conditions tenues par d'autres (couche 4/matchups)."
    )
    print(
        f"{'aptitude':<28}{'porteur':<30}{'pts':>5}{'mv':>4}{'PV':>4}{'sv':>4}{'fam.':>20}{'P':>6}"
        f"{'expo':>9}{'rnd':>4}{'vie':>6}{'S':>6}{'F':>6}{'A':>6}{'R':>6}{'mariage':>8}  bon cas"
    )
    for r in rows:
        sv = f"{r['save']}+" + (f"/{r['ward']}+" if r["ward"] else "")
        print(
            f"{r['ability_name'][:27]:<28}{r['unit_name'][:29]:<30}{r['points']:>5}{r['move']:>4}{r['hp']:>4}"
            f"{sv:>7}{(r['family'] or '')[:19]:>17}{r['p_trigger']:>6.2f}{r['exposure']:>9}{r['start_round']:>4}"
            f"{r['rounds_alive']:>6.1f}{r['survival']:>6.2f}{_g(r['tempo'])}{_g(r['amplification'])}"
            f"{_g(r['role_fit'])}{r['marriage']:>8.2f}  {r['good_case_conditions'] or ''}"
        )
    return 0


def _g(v) -> str:
    """Facteur de la grille (absent avant `encounter build`)."""
    return f"{'—':>6}" if v is None else f"{v:>6.2f}"


def cmd_encounter_bearers(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_enhancement_bearers(
        con, ability=args.ability, unit=args.unit, army=args.army, kind=args.kind, limit=args.limit
    )
    con.close()
    if not rows:
        print("Aucun porteur (lancez `aospy encounter build`).")
        return 1
    print(
        "Bons porteurs des optimisations : unités éligibles de la faction (UNIQUE exclues, restriction du "
        "groupe/type).\nvaleur = gain absolu de √(dég × dur) × couverture × mariage (D × S) ; sans effet "
        "chiffrable (bulle, sort…), classés par mariage puis par l'indicateur combiné du porteur."
    )
    current = None
    for r in rows:
        if r["ability_uid"] != current:
            current = r["ability_uid"]
            print(f"\n== {r['ability_name']} ({r['source_kind']}, {r['faction_name']} › {r['group_name']})")
            print(
                f"   {'porteur':<34}{'pts':>5}{'mv':>4}{'PV':>4}{'sv':>7}{'dég%':>7}{'dur%':>7}{'Δcomb':>7}"
                f"{'P':>6}{'S':>6}{'mariage':>8}{'valeur':>8}{'comb.':>7}  bon cas"
            )
        sv = f"{r['save']}+" + (f"/{r['ward']}+" if r["ward"] else "")
        f = lambda v, fmt: "—" if v is None else format(v, fmt)
        print(
            f"   {r['unit_name'][:33]:<34}{r['points']:>5}{r['move']:>4}{r['hp']:>4}{sv:>7}"
            f"{f(r['off_gain_pct'], '+.0f'):>7}{f(r['def_gain_pct'], '+.0f'):>7}{f(r['delta_combined'], '.2f'):>7}"
            f"{r['p_trigger']:>6.2f}{r['survival']:>6.2f}{r['marriage']:>8.2f}{f(r['value'], '.2f'):>8}"
            f"{r['bearer_combined']:>7.1f}  {r['good_case_conditions'] or ''}"
        )
    return 0


def _effect_label(r: dict) -> str:
    if r["kind"] == "stat_mod":
        lab = f"{r['value']:+g} {r['stat']}"
    elif r["kind"] == "ward":
        lab = f"protection {r['value']:g}+"
    else:
        lab = r["kind"]
    scope = r["weapon_name"] or r["weapon_scope"]
    return f"{lab} ({scope})" if scope else lab


def cmd_encounter_list(args: argparse.Namespace) -> int:
    con = _connect(args)
    rows = repository.list_encounters(
        con,
        unit=args.unit,
        ability=args.ability,
        relation="porteur" if args.own else None,
        order_by=args.sort,
        limit=args.limit,
    )
    con.close()
    if not rows:
        print("Aucune rencontre (lancez `aospy encounter build`).")
        return 1
    print(
        "gain = sur CE châssis, si l'effet s'applique (dégâts d'un round vs save 4+ / coups à porter) ; "
        "/100 = pour 100 pts du receveur ; P = probabilité de déclenchement (couche 1)"
    )
    print(
        f"{'unité':<30}{'aptitude':<32}{'effet':<26}{'rel.':<8}{'off':>7}{'déf':>7}{'off/100':>8}"
        f"{'P':>5}  {'verdict':<11}conditions / durée"
    )
    for r in rows:
        off = "" if r["off_gain_pct"] is None or not r["off_gain_pct"] else f"{r['off_gain_pct']:+.0f}%"
        dfn = "" if not r["def_gain_pct"] else f"{r['def_gain_pct']:+.0f}%"
        cond = " ; ".join(x for x in (r["conditions"], r["duration"]) if x)
        print(
            f"{r['unit_name'][:29]:<30}{r['ability_name'][:31]:<32}{_effect_label(r)[:25]:<26}"
            f"{r['relation']:<8}{off:>7}{dfn:>7}{r['off_gain_per_100']:>8.2f}{r['activation_prob']:>5.0%}  "
            f"{(r['verdict'] or '')[:10]:<11}{cond}"
        )
    return 0


def _gain(after: float, before: float) -> str:
    return "   -  " if not before else f"{100 * (after - before) / before:+5.0f}%"


def _num(v, digits: int = 1) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _print_best(rows: list[dict], detail: bool) -> None:
    print(
        f"{'#':>3} {'unité':<36}{'armée':<20}{'pts':>5}{'score':>7}{'rang':>6}{'comb.':>7}{'portée':>7}"
        f"{'mob.':>6}{'dég/100':>8}{'+%':>7}{'bon cas':>8}{'dur/100':>8}{'+%':>7}{'bon cas':>8}"
        f"  │{'ch.dég':>7}{'ch.dur':>7}{'ch.score':>9}"
    )
    for i, r in enumerate(rows, 1):
        print(
            f"{i:>3} {r['name'][:35]:<36}{r['army_name'][:19]:<20}{r['points']:>5}{_num(r.get('score_per_100')):>7}"
            f"{_num(r.get('score_pct_rank'), 2):>6}{r['combined_per_100']:>7.1f}{_num(r.get('reach_in')):>7}"
            f"{_num(r.get('mobility'), 2):>6}{r['off_realized_per_100']:>8.1f}"
            f"{_gain(r['off_realized'], r['off_chassis']):>7}{r['off_good_per_100']:>8.1f}"
            f"{r['def_realized_per_100']:>8.1f}{_gain(r['def_realized'], r['def_chassis']):>7}"
            f"{r['def_good_per_100']:>8.1f}  │{_num(r.get('off_fit_per_100')):>7}{_num(r.get('def_fit_per_100')):>7}"
            f"{_num(r.get('score_fit_per_100')):>9}"
        )
        if detail and r["abilities"]:
            print(f"      aptitudes : {r['abilities']}")


def cmd_encounter_best(args: argparse.Namespace) -> int:
    con = _connect(args)
    segments = [True] if args.heroes else [False] if args.troops else [False, True]
    results = {
        hero: repository.list_realized(
            con, army=args.army, hero=hero, name=args.name, order_by=args.sort, limit=args.limit
        )
        for hero in segments
    }
    con.close()
    if not any(results.values()):
        print("Aucune valeur réalisée (lancez `aospy encounter build`).")
        return 1
    print(
        "Châssis + aptitudes propres qui boostent l'unité, pondérées (rounds 2-3 = 1, 1/4/5 = 1/3 ; "
        "1/bataille courte = 1/2 ; × P(déclenchement)).\n"
        "score = comb. × mob. ; comb. = √(dég/100 × dur/100) ; mob. = (portée / portée médiane)^0,35, portée = "
        "mouvement + course + vol + aptitudes de mouvement (pouces/tour) ;\n"
        "rang = centile du score dans le segment ; dég = dégâts d'un round vs save 4+ (plancher 75 %) ; "
        "dur = coups à porter ; +% = gain sur le châssis nu ; bon cas = avec les effets conditionnels ;\n"
        "ch. = selon châssis : conditions du porteur (charge, territoire, objectif…) × P(ce châssis les remplit)"
    )
    for hero in segments:
        if results[hero]:
            print(f"\n== {'Héros' if hero else 'Troupes'} ==")
            _print_best(results[hero], args.detail)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `encounter` : couche 3, rencontre aptitude × châssis (analysis/layers/encounter.py)."""
    p_en = sub.add_parser("encounter", help="Rencontre aptitude × châssis : gain réel d'un effet sur une charte.")
    sen = p_en.add_subparsers(dest="action", required=True)
    p = sen.add_parser("build", help="(Re)construit la table ability_encounter (après `ability analyze`).")
    p.set_defaults(func=cmd_encounter_build)
    p = sen.add_parser("list", help="Rencontres filtrées, triées par gain.")
    p.add_argument("--unit", help="Receveur (sous-chaîne).")
    p.add_argument("--ability", help="Aptitude (sous-chaîne).")
    p.add_argument("--own", action="store_true", help="Seulement les aptitudes de la charte elle-même.")
    p.add_argument("--sort", default="gain", choices=["gain", "off_per_100", "def_per_100"])
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_encounter_list)
    p = sen.add_parser(
        "best",
        help="Meilleures unités (troupes et héros séparés) : châssis + aptitudes propres, "
        "indicateur combiné dégâts × durabilité pour 100 pts.",
    )
    p.add_argument("--army", help="Sous-chaîne du nom d'armée.")
    p.add_argument("--name", help="Sous-chaîne du nom d'unité.")
    seg = p.add_mutually_exclusive_group()
    seg.add_argument("--heroes", action="store_true", help="Héros seulement.")
    seg.add_argument("--troops", action="store_true", help="Troupes seulement.")
    p.add_argument(
        "--sort",
        default="score_per_100",
        help="score_per_100 (défaut) = dégâts × durabilité × mobilité ; combined_per_100 = sans mobilité.",
        choices=[
            "score_per_100",
            "score_fit_per_100",
            "reach_in",
            "combined_per_100",
            "combined_fit_per_100",
            "off_fit_per_100",
            "def_fit_per_100",
            "off_realized_per_100",
            "def_realized_per_100",
            "off_good_per_100",
            "def_good_per_100",
            "off_gain",
            "def_gain",
        ],
    )
    p.add_argument("--detail", action="store_true", help="Liste les aptitudes prises en compte.")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_encounter_best)
    p = sen.add_parser(
        "marriage",
        help="Mariage châssis × aptitude : le porteur déclenche-t-il l'effet et "
        "survit-il pour le tenir ? (bons porteurs d'une aptitude, aptitudes "
        "mal mariées d'une unité)",
    )
    p.add_argument("--ability", help="Sous-chaîne du nom d'aptitude.")
    p.add_argument("--unit", help="Sous-chaîne du nom du porteur.")
    p.add_argument("--family", help="Famille (buff-donne, debuff, buff-perso-offensif…).")
    p.add_argument("--worst", action="store_true", help="Pires mariages d'abord.")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_encounter_marriage)
    p = sen.add_parser(
        "bearers",
        help="Bons porteurs des optimisations (traits héroïques, artefacts, "
        "améliorations) : chaque unité éligible classée.",
    )
    p.add_argument("--ability", help="Sous-chaîne du nom de l'optimisation.")
    p.add_argument("--unit", help="Sous-chaîne du nom du porteur.")
    p.add_argument("--army", help="Sous-chaîne du nom de faction.")
    p.add_argument("--kind", choices=["heroic_trait", "artefact", "enhancement", "monstrous_trait"])
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_encounter_bearers)

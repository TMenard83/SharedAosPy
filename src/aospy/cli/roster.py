"""Commande `roster` : fiche chiffrée d'une liste (`analyze`) et kit de tournoi PDF (`pdf`, extra `[roster]`)."""

from __future__ import annotations

import argparse

from ..tournament_kit.modes import MODES
from .common import _connect


def cmd_roster_pdf(args: argparse.Namespace) -> int:
    try:
        from ..tournament_kit import pdf_builder
    except ImportError:
        print("Le kit de tournoi nécessite l'extra [roster] : pip install -e '.[roster]'")
        return 1

    result = pdf_builder.build_roster_pdf(args.list, out_path=args.out, mode=args.mode)
    print(f"PDF généré : {result.output_path}")
    if result.scenario_output_path is not None:
        print(f"PDF avec scénarios : {result.scenario_output_path}")
    if result.absent_references:
        print("  À vérifier (aptitude qui cite une unité absente de la liste) :")
        for ref in result.absent_references:
            print(f"    - {ref.ability} ({ref.owner}) -> {ref.unit}")
    if result.absent_keywords:
        print("  À vérifier (aptitude qui vise un type d'unité amie absent de la liste) :")
        for ref in result.absent_keywords:
            print(f"    - {ref.ability} ({ref.owner}) -> {ref.unit}")
    print(f"  {len(result.units_matched)} profil(s) trouvé(s).")
    print(f"  {len(result.rules_included)} section(s) de règles incluse(s).")
    if result.units_unmatched:
        print(f"  {len(result.units_unmatched)} profil(s) non trouvé(s) dans l'index :")
        for name in result.units_unmatched:
            print(f"    - {name}")
    if result.rules_unmatched:
        print(f"  {len(result.rules_unmatched)} règle(s) non trouvée(s) dans l'index :")
        for name in result.rules_unmatched:
            print(f"    - {name}")
    if result.wahapedia_used:
        print(f"  {len(result.wahapedia_used)} élément(s) complété(s) en anglais via Wahapedia (voir annexe) :")
        for name in result.wahapedia_used:
            print(f"    - {name}")
    return 0


def cmd_roster_analyze(args: argparse.Namespace) -> int:
    from ..analysis.layers.listing import analyse_list
    from ..tournament_kit.list_parser import parse_list_file
    from .report import format_list_report

    con = _connect(args)
    rep = analyse_list(con, parse_list_file(args.list))
    con.close()
    text = format_list_report(rep)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Fiche écrite : {args.out}")
    else:
        print(text)
    return 0


def write_dossier(con, list_path, out) -> tuple[str, list[str]]:
    """Dossier d'analyse d'une liste dans `out` : `couche 4.md`, `textes.md`, `liste.txt` (noms fixes).

    Noms fixes pour qu'un dossier n'ait qu'une version de chaque fichier : les anciennes variantes
    (`<stem> - couche 4.md`, `<stem> - textes.md`, `couche 4 (ancienne).md`) sont supprimées à chaque écriture.

    Renvoie (stem, unités non reconnues). Utilisé par `aospy roster dossier` et `scratch/list_dossier.py`
    (consignes d'agent `l3-matchups/*_agent.md`, `l3/draft_pack.py`).
    """
    from pathlib import Path

    from ..analysis.layers.listing import analyse_list, collect
    from ..persistence.repository import get_ability_text
    from ..tournament_kit.list_parser import parse_list_file
    from .report import format_list_report, format_list_texts

    f, out = Path(list_path), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    parsed = parse_list_file(f)
    stem = f.name.split(" ")[0].strip()
    raw = f.read_text(encoding="utf-8")
    for old in [*out.glob("* - couche 4.md"), *out.glob("* - textes.md"), *out.glob("couche 4 (*).md")]:
        old.unlink()
    (out / "couche 4.md").write_text(format_list_report(analyse_list(con, parsed)), encoding="utf-8")
    entries, abilities, _vocab = collect(con, parsed)
    texts = {ab.uid: get_ability_text(con, ab.uid) for ab in abilities}
    (out / "textes.md").write_text(format_list_texts(parsed.title, raw, entries, abilities, texts),
                                             encoding="utf-8")
    (out / "liste.txt").write_text(raw, encoding="utf-8")
    return stem, [f"{n} ({p})" for n, p, u in entries if u is None]


def cmd_roster_dossier(args: argparse.Namespace) -> int:
    from pathlib import Path

    out = args.out or str(Path("scratch/output/liste_analyse") / Path(args.list).stem)
    con = _connect(args)
    stem, missing = write_dossier(con, args.list, out)
    con.close()
    print(f"Dossier écrit : {out} (couche 4.md, textes.md, liste.txt)")
    if missing:
        print(f"ATTENTION : {len(missing)} unité(s) non reconnue(s) en base, chiffres faux tant qu'elles manquent :")
        for m in missing:
            print(f"  - {m}")
        return 2
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Sous-commande `roster` : compile une liste + ses profils d'unité en PDF
    (nécessite l'extra `[roster]`)."""
    p_roster = sub.add_parser("roster", help="Kit de tournoi (liste + profils d'unité) en PDF.")
    sr = p_roster.add_subparsers(dest="action", required=True)
    p = sr.add_parser(
        "analyze",
        help="Fiche couche 4 chiffrée d'une liste (unités, optimisations, règles "
        "mortes, mariages, limites d'armée, magie) en Markdown.",
    )
    p.add_argument("--list", dest="list", required=True, help="Fichier de liste (export texte de l'App).")
    p.add_argument("--out", help="Fichier Markdown de sortie (défaut : affichage).")
    p.set_defaults(func=cmd_roster_analyze)
    p = sr.add_parser(
        "dossier",
        help="Dossier d'analyse d'une liste (skill list-analysis) : fiche couche 4 + profils et textes complets.",
    )
    p.add_argument("--list", dest="list", required=True, help="Fichier de liste (export texte de l'App).")
    p.add_argument("--out", help="Dossier de sortie (défaut : scratch/output/liste_analyse/<liste>/ ; "
                   "rangement conseillé : liste_analyse/<équipe>/<joueur>-<faction>/<liste>/).")
    p.set_defaults(func=cmd_roster_dossier)
    p = sr.add_parser("pdf", help="Compile une liste (export brut de l'App) en PDF.")
    p.add_argument(
        "--list",
        dest="list",
        required=True,
        help="Chemin du fichier de liste (export texte de Warhammer Age of Sigmar: The App).",
    )
    p.add_argument(
        "--out",
        help="Chemin du PDF de sortie (défaut : scratch/output/roster/<équipe>/<liste>/<liste> (<mode>).pdf, "
        "<équipe> = sous-dossier de data/Proposition de listes/, "
        "<mode> = 'defaut' pour --mode hybrid).",
    )
    p.add_argument(
        "--mode",
        choices=list(MODES),
        default="hybrid",
        help="hybrid (défaut, FR/EN historique) / en (Wahapedia uniquement) / "
        "fr (vérbatim français intégral, repli Wahapedia) / "
        "fr-extended (fr + aptitudes génériques MdG) / "
        "fr-split (fr-extended, aptitudes de toute l'armée en 2 cartes Mon tour / "
        "Tour adverse par phase, warscrolls réduits aux profils) / "
        "fr-split-simple (fr-split + simplifications propres à la liste) / "
        "en-split-simple (même mise en page, en anglais : Wahapedia, Core Rules GW, "
        "simplifications de la section « en »).",
    )
    p.set_defaults(func=cmd_roster_pdf)

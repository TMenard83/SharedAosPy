"""Dossier d'analyse d'une liste (couche 4 + textes) et régénération en série des dossiers de la L3.

`write_dossier` écrit `couche 4.md`, `textes.md` et `liste.txt` ; elle sert à `aospy roster dossier`,
`aospy cascade --list`, `l3/draft_pack.py` et à `aospy l3 dossiers`, qui régénère le dossier de chaque
`analyse.md` trouvé sous `--root` (source : le `liste.txt` du dossier), une seule connexion, la cascade
vérifiée une fois.

usage : aospy l3 dossiers [--root scratch/output/liste_analyse] [--team T] [--dry-run] [--db data/aospy.duckdb]
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = ROOT / "scratch" / "output" / "liste_analyse"
DEFAULT_DB = ROOT / "data" / "aospy.duckdb"


def write_dossier(con, list_path, out, check_fresh: bool = True) -> tuple[str, list[str]]:
    """Dossier d'analyse d'une liste dans `out` : `couche 4.md`, `textes.md`, `liste.txt` (noms fixes).

    Noms fixes pour qu'un dossier n'ait qu'une version de chaque fichier : les anciennes variantes
    (`<stem> - couche 4.md`, `<stem> - textes.md`, `couche 4 (ancienne).md`) sont supprimées à chaque écriture.
    `check_fresh=False` : l'appelant a déjà vérifié la cascade (`require_fresh(con, 4)`).

    Renvoie (stem, unités non reconnues).
    """
    from ..analysis.layers.cascade import require_fresh
    from ..analysis.layers.listing import analyse_list, collect
    from ..analysis.layers.listing_report import format_list_report, format_list_texts
    from ..persistence.repository import get_ability_text
    from ..tournament_kit.list_parser import parse_list_file

    if check_fresh:
        require_fresh(con, 4)
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


def find_dossiers(root: Path, team: str | None = None) -> list[Path]:
    """Dossiers (parents d'un `analyse.md`) sous `root`, triés ; `team` = premier sous-dossier de `root`."""
    root = Path(root)
    dirs = sorted({p.parent for p in root.rglob("analyse.md")})
    if team:
        dirs = [d for d in dirs if d.relative_to(root).parts[:1] == (team,)]
    return dirs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 dossiers", description="Régénère le dossier couche 4 "
                                 "(couche 4.md, textes.md, liste.txt) de chaque dossier contenant un analyse.md.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT),
                    help="Racine des dossiers (défaut : scratch/output/liste_analyse).")
    ap.add_argument("--team", help="Une seule équipe (premier sous-dossier de --root).")
    ap.add_argument("--dry-run", action="store_true", help="Liste les dossiers trouvés sans rien écrire.")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Base DuckDB (ouverte en lecture seule).")
    args = ap.parse_args(argv)
    root = Path(args.root)
    dirs = find_dossiers(root, args.team)
    if not dirs:
        print(f"Aucun analyse.md sous {root}" + (f" (équipe {args.team})" if args.team else ""))
        return 1
    if args.dry_run:
        for d in dirs:
            print(f"{'ok ' if (d / 'liste.txt').exists() else 'SANS liste.txt'} {d.relative_to(root)}")
        print(f"{len(dirs)} dossier(s) (dry-run, rien d'écrit).")
        return 0

    import duckdb

    from ..analysis.layers.cascade import require_fresh

    con = duckdb.connect(args.db, read_only=True)
    try:
        require_fresh(con, 4)
        ok, ko, unknown = 0, [], {}
        for d in dirs:
            name = str(d.relative_to(root))
            src = d / "liste.txt"
            if not src.exists():
                ko.append(f"{name} : liste.txt absent")
                continue
            try:
                _stem, missing = write_dossier(con, src, d, check_fresh=False)
            except Exception as e:  # une liste en échec ne bloque pas les autres
                ko.append(f"{name} : {type(e).__name__}: {e}")
                continue
            ok += 1
            if missing:
                unknown[name] = missing
    finally:
        con.close()
    print(f"{ok} OK, {len(ko)} KO sur {len(dirs)} dossier(s).")
    for k in ko:
        print(f"  KO {k}")
    for name, missing in unknown.items():
        print(f"  ATTENTION {name} : {len(missing)} unité(s) non reconnue(s) en base")
        for m in missing:
            print(f"    - {m}")
    return 2 if unknown else (1 if ko else 0)


if __name__ == "__main__":
    raise SystemExit(main())

"""Audite data/json/faction_rules_fr.json contre la dernière « Mises à jour de Règles » GW.

Les « Mises à jour de Règles » sont cumulatives : chaque nouvelle version doit
être repassée sur *toutes* les factions déjà curées, pas seulement celle en
cours de curation. Un vérbatim français périmé masque en plus le texte anglais
de Wahapedia, souvent déjà corrigé — l'erreur passe inaperçue dans le PDF.

Script en lecture seule (n'écrit rien dans data/), deux contrôles :

1. **Citations du PDF** : pour chaque faction curée, chaque texte de
   remplacement cité (“…”, au moins 6 mots) dans ses pages d'errata doit se
   retrouver dans les descriptions françaises de cette faction. Les pages
   « Autres Téléchargements » (Fléau d'Aqshy, suppléments...) sont comparées à
   l'ensemble des factions. Ne voit pas les remplacements d'aptitude entière
   non guillemetés (« Remplacez “X” par : X : ... ») — une relecture manuelle
   des pages reste nécessaire, ce contrôle ne fait que trier.
2. **Diff Wahapedia** (`--old-wahapedia`) : toute aptitude dont le texte
   anglais a changé entre deux exports Wahapedia *et* qui porte un correctif
   français est suspecte (Wahapedia a sans doute appliqué un errata que notre
   vérbatim n'a pas). Les différences cosmétiques (balises, identifiants
   d'infobulle, champ CSV tronqué en fin de texte) sont ignorées.

Usage :
    uv run --with pymupdf python scripts/audit_rules_updates.py   # PDF le plus récent de Download GW
    python scripts/audit_rules_updates.py --pdf chemin.pdf
    python scripts/audit_rules_updates.py --faction "Nighthaunt" --faction Skaven
    python scripts/audit_rules_updates.py --old-wahapedia data/wahapedia/2026-08-25_1430
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FR_RULES = REPO_ROOT / "data" / "json" / "faction_rules_fr.json"
DOWNLOAD_DIR = REPO_ROOT / "data" / "Battle tome" / "Download GW"
WAHAPEDIA_DIR = REPO_ROOT / "data" / "wahapedia"
_RULES_UPDATE_RE = re.compile(r"rules?_updates?", re.I)

# En-tête de page « TOME DE BATAILLE : <NOM> » → factions de faction_rules_fr.json.
# Par défaut le nom de l'en-tête est comparé sans casse aux clés du JSON ; ne
# lister ici que les en-têtes qui ne correspondent pas tels quels.
_HEADER_ALIASES = {
    "ORRUK WARCLANS": ["Ironjawz", "Kruleboyz"],
}
# Sous-titres des pages « PACKS DE FACTION » (pas d'en-tête de tome).
_PACK_HEADINGS = {"PYROTUEURS": "Fyreslayers", "SÉRAPHONS": "Seraphon"}
_MIN_QUOTE_WORDS = 6
# Les barres de timing citées ne sont pas transcrites dans le JSON (Wahapedia
# fait foi, cf. skill faction-rules-fr) : les ignorer ici.
_TIMING_RE = re.compile(r"^(Une Fois|Passif|Votre Phase|N.importe|Réaction|Fin de|Début de|Phase)", re.I)
# Les domaines de manifestations génériques n'ont pas de pages dédiées : leurs
# errata sont noyés dans les sections « Manuel du Général » (règles de base,
# plans de bataille...), trop bruyantes pour ce contrôle — relecture manuelle.
_GENERIC_FACTION = "Endless Spells"


def _norm(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = text.replace("­", "")
    text = re.sub(r"-\n", "", text)
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+\"]+", " ", text)).strip()


def _latest_rules_update() -> Path:
    candidates = [p for p in DOWNLOAD_DIR.glob("*.pdf") if _RULES_UPDATE_RE.search(p.name)]
    if not candidates:
        sys.exit(f"Aucune « Mises à jour de Règles » dans {DOWNLOAD_DIR}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _pdf_pages(path: Path) -> list[str]:
    # pymupdf extrait le texte de ces PDF bien plus proprement que pypdf (qui
    # coupe des mots : « E ffet ») ; pypdf ([roster]) n'est qu'un repli.
    try:
        import pymupdf
    except ImportError:
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("pymupdf ou pypdf requis : uv run --with pymupdf python scripts/audit_rules_updates.py")
        print("(pymupdf absent : extraction pypdf, plus de faux positifs)\n")
        return [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def _faction_texts(factions: dict) -> dict[str, str]:
    """Faction → toutes ses descriptions/noms français, normalisés."""
    out = {}
    for name, faction in factions.items():
        entries = [a for cat in faction.get("rules", {}).values() for a in cat]
        entries += [a for u in faction.get("units", {}).values() for a in u.get("abilities", [])]
        out[name] = _norm(" ".join(a.get("name", "") + " " + a.get("description", "") for a in entries))
    return out


def _pages_by_faction(pages: list[str], factions: list[str]) -> tuple[dict[str, list[int]], list[int]]:
    by_lower = {f.lower(): f for f in factions}
    mapping: dict[str, list[int]] = {}
    other: list[int] = []
    for i, text in enumerate(pages):
        if "AUTRES TÉLÉCHARGEMENTS" in text:
            other.append(i)
            continue
        targets = set()
        for header in re.findall(r"TOME DE BATAILLE\s*:\s*([^\n]+)", text):
            header = header.strip()
            targets.update(_HEADER_ALIASES.get(header, [by_lower.get(header.lower())]))
        if "PACKS DE FACTION" in text:
            targets.update(f for h, f in _PACK_HEADINGS.items() if re.search(rf"^{h}\s*$", text, re.M))
        for f in targets - {None}:
            if f in factions:
                mapping.setdefault(f, []).append(i)
    return mapping, other


def _missing_quotes(text: str, haystack: str) -> list[str]:
    missing = []
    for quote in re.findall(r"“([^”]+?)”", text, re.S):
        words = _norm(quote).split()
        if len(words) < _MIN_QUOTE_WORDS or _TIMING_RE.match(quote.strip()):
            continue
        windows = [" ".join(words[i : i + 6]) for i in range(0, max(1, len(words) - 5), 3)]
        if sum(w in haystack for w in windows) / len(windows) < 0.6:
            missing.append(re.sub(r"\s+", " ", quote).strip())
    return missing


def _check_pdf(pdf: Path, factions: dict, only: set[str] | None) -> None:
    pages = _pdf_pages(pdf)
    texts = _faction_texts(factions)
    mapping, other = _pages_by_faction(pages, list(factions))
    print(f"# Citations absentes — {pdf.name}\n")
    for faction in sorted(factions):
        if only and faction not in only:
            continue
        idx = mapping.get(faction)
        if not idx:
            hint = " (relire les sections « Manuel du Général » à la main)" if faction == _GENERIC_FACTION else ""
            print(f"## {faction} : aucune page d'errata trouvée{hint}\n")
            continue
        missing = _missing_quotes("\n".join(pages[i] for i in idx), texts[faction])
        pages_label = ", ".join(str(i + 1) for i in idx)
        print(f"## {faction} (p. {pages_label}) : {len(missing)} citation(s) absente(s)")
        for quote in missing:
            print(f"  - {quote[:220]}")
        print()
    if not only:
        everything = " ".join(texts.values())
        missing = _missing_quotes("\n".join(pages[i] for i in other), everything)
        pages_label = ", ".join(str(i + 1) for i in other)
        print(f"## Autres Téléchargements (p. {pages_label}) : {len(missing)} citation(s) absente(s)")
        print("   (Fléau d'Aqshy, suppléments, Légendes, Renom... — beaucoup hors périmètre)")
        for quote in missing:
            print(f"  - {quote[:220]}")
        print()


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter="|"))


def _words(text: str) -> list[str]:
    text = html.unescape(re.sub(r"<[^>]*>?", " ", text)).replace("’", "'")
    return re.findall(r"\w+", text.lower())


def _wahapedia_index(directory: Path) -> tuple[dict, dict]:
    names = {}
    for row in _read_csv(directory / "Warscrolls.csv"):
        names.setdefault(row["id"], row["name"].lower())
    faction_rows: dict = {}
    for row in _read_csv(directory / "Faction_abilities.csv"):
        faction_rows.setdefault((row["faction_id"], row["name"].lower()), []).append(row)
    unit_rows: dict = {}
    for row in _read_csv(directory / "Warscrolls_abilities.csv"):
        key = (names.get(row["warscroll_id"], "?"), row["name"].lower())
        unit_rows.setdefault(key, []).append(row)
    return faction_rows, unit_rows


def _real_changes(old_rows: list[dict], new_rows: list[dict]) -> list[tuple[str, str]]:
    """Différences de mots hors fin de texte (souvent tronquée dans le CSV)."""
    old = [w for r in old_rows for w in _words(r["description"]) + ["##"] + _words(r["condition"])]
    new = [w for r in new_rows for w in _words(r["description"]) + ["##"] + _words(r["condition"])]
    noise = re.compile(r"tooltip\w*|span|class|kwbu?2?|a|href|aos4|data|div|lt|gt|ky|\d{5,}\w*")
    changes = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal" or i2 >= len(old) - 1 or j2 >= len(new) - 1:
            continue
        before = [w for w in old[i1:i2] if not noise.fullmatch(w)]
        after = [w for w in new[j1:j2] if not noise.fullmatch(w)]
        if before != after:
            changes.append((" ".join(before), " ".join(after)))
    return changes


def _check_wahapedia(old_dir: Path, factions: dict, only: set[str] | None) -> None:
    ids = {r["name"].lower(): r["id"] for r in _read_csv(WAHAPEDIA_DIR / "Factions.csv")}
    old_f, old_u = _wahapedia_index(old_dir)
    new_f, new_u = _wahapedia_index(WAHAPEDIA_DIR)
    print(f"# Aptitudes modifiées chez Wahapedia ({old_dir.name} → actuel) et portant un correctif FR\n")
    count = 0
    for faction, data in sorted(factions.items()):
        if only and faction not in only:
            continue
        entries = [
            (cat, (ids.get(faction.lower()), a.get("wahapedia_name", "").lower()), a, True)
            for cat, lst in data.get("rules", {}).items()
            for a in lst
        ]
        entries += [
            (unit, (unit.lower(), a.get("wahapedia_name", "").lower()), a, False)
            for unit, u in data.get("units", {}).items()
            for a in u.get("abilities", [])
        ]
        for where, key, ability, is_rule in entries:
            old_rows = (old_f if is_rule else old_u).get(key)
            new_rows = (new_f if is_rule else new_u).get(key)
            if not old_rows or not new_rows:
                continue
            changes = _real_changes(old_rows, new_rows)
            if not changes:
                continue
            count += 1
            source = (ability.get("provenance") or {}).get("errata_source") or "aucun errata appliqué"
            print(f"## {faction} | {where} | {ability.get('wahapedia_name')} → {ability.get('name')}")
            print(f"   source FR : {source}")
            for before, after in changes:
                print(f"   - {before[:200]}\n   + {after[:200]}")
            print()
    print(f"{count} aptitude(s) à relire.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pdf", type=Path, help="PDF « Mises à jour de Règles » (défaut : le plus récent de Download GW)"
    )
    parser.add_argument("--faction", action="append", help="limiter à une faction (répétable)")
    parser.add_argument("--old-wahapedia", type=Path, help="ancien export Wahapedia à comparer à data/wahapedia/")
    parser.add_argument("--no-pdf", action="store_true", help="sauter le contrôle des citations du PDF")
    args = parser.parse_args()

    factions = json.loads(FR_RULES.read_text(encoding="utf-8"))["factions"]
    only = set(args.faction) if args.faction else None
    if only and (unknown := only - set(factions)):
        sys.exit(f"Faction(s) inconnue(s) dans faction_rules_fr.json : {', '.join(sorted(unknown))}")
    if not args.no_pdf:
        _check_pdf(args.pdf or _latest_rules_update(), factions, only)
    if args.old_wahapedia:
        _check_wahapedia(args.old_wahapedia, factions, only)


if __name__ == "__main__":
    main()

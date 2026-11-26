"""Lecture des CSV Wahapedia (`data/wahapedia/*.csv`) et filtres communs à tous leurs lecteurs.

Format : séparateur `|`, BOM UTF-8. Filtres : warscrolls Legends (`legends_warscroll_ids`), dédoublonnage
canonique des warscrolls homonymes (`canonical_ids`), variantes de pack narratif expiré
(`is_expired_variant`, partagé avec l'importeur BSData qui filtre sur les noms BattleScribe).

Couche basse : n'importe rien d'autre d'aospy, pour que `importers/`, `abilities/` et `tournament_kit/`
puissent tous s'en servir.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

DEFAULT_DATA_DIR = Path("data") / "wahapedia"

ROR_ROLE = "Regiment of Renown"

#: Fragments de nom (minuscules) signalant une variante de pack narratif expiré.
#: Seul "Scourge of Ghyran" (le pack narratif saisonnier en cours) est écarté :
#: absent des règles matched play courantes, mais BSData continue de l'exposer
#: (suffixe « (Scourge of Ghyran) » côté BSData, préfixe « Scourge of Ghyran »
#: côté Wahapedia — cf. `importers/wahapedia.py::import_faction`).
#: "Scourge of Aqshy" (pack antérieur) n'est PAS filtré : ces entrées ciblent un
#: `targetId` distinct de l'unité de base (points/profil différents), ce ne sont
#: donc pas de simples doublons mais des unités à part entière toujours valides.
EXPIRED_VARIANT_MARKERS: frozenset[str] = frozenset(
    {
        "scourge of ghyran",
    }
)


def _rejoin_broken_rows(lines: list[str]) -> list[str]:
    """Recolle les lignes coupées par un saut de ligne brut dans un champ (non échappé par Wahapedia).

    Une ligne complète porte autant de `|` que l'en-tête : tant qu'une ligne en a moins et que la suivante
    ne la fait pas déborder, la suivante en est la suite (« Belga the Cystwitch », dont la description
    contient un saut de ligne : sans recollage, la charte entière était illisible, 2026-11-25). Une ligne
    courte suivie d'une ligne entière (pas de `|` final) reste seule."""
    if not lines:
        return lines
    n = lines[0].count("|")
    out: list[str] = [lines[0]]
    i = 1
    while i < len(lines):
        buf = lines[i]
        while buf.strip() and buf.count("|") < n and i + 1 < len(lines) and (
            buf.count("|") + lines[i + 1].count("|") <= n
        ) and lines[i + 1].strip():
            i += 1
            buf = f"{buf} {lines[i]}"
        out.append(buf)
        i += 1
    return out


def read_csv(path: Path) -> list[dict[str, str]]:
    """Lignes d'un CSV Wahapedia (séparateur `|`, BOM UTF-8), une `dict` par ligne."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        # pas `splitlines()` : il couperait aussi sur U+2028 & co., que le module csv garde dans le champ
        lines = [ln.removesuffix("\r") for ln in fh.read().split("\n")]
    return list(csv.DictReader(_rejoin_broken_rows(lines), delimiter="|"))


def is_expired_variant(name: str) -> bool:
    lname = name.strip().lower()
    return any(marker in lname for marker in EXPIRED_VARIANT_MARKERS)


_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), start=1)}
#: « This unit will move to Warhammer Legends on 1 June 2027. » : retrait annoncé, daté.
_LEGENDS_DATE_RE = re.compile(r"legends on (\d{1,2}) ([a-z]+) (\d{4})")


def is_legends_note(notes: str, today: date | None = None) -> bool:
    """Note Wahapedia d'une charte Legends : « Legends Warscroll », ou retrait annoncé **dont la date est passée**.

    Une charte « will move to Warhammer Legends on 1 June 2027 » reste jouable jusque-là : la lire comme
    Legends dès l'annonce écartait 52 chartes encore valides (Frost Sabres, 2026-11-25)."""
    # espaces insécables dans la date (« 1\xa0June\xa02027 », Tzaangor Enlightened on Foot, 2026-11-26)
    low = re.sub(r"\s+", " ", (notes or "").lower())
    if "legend" not in low:
        return False
    m = _LEGENDS_DATE_RE.search(low)
    if m and m.group(2) in _MONTHS:
        when = date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        return when <= (today or date.today())
    return True


def legends_warscrolls(data_dir: Path, today: date | None = None) -> list[dict[str, str]]:
    """Lignes de `Warscrolls.csv` Legends : source de type Legends, ou note de retrait (`is_legends_note`)."""
    sources = read_csv(data_dir / "Source.csv")
    legend_sources = {s["id"] for s in sources if "legends" in (s.get("name") or "").lower()}
    return [
        w
        for w in read_csv(data_dir / "Warscrolls.csv")
        if w.get("source_id") in legend_sources or is_legends_note(w.get("notes") or "", today)
    ]


def legends_warscroll_ids(data_dir: Path) -> set[str]:
    """Warscrolls Legends à exclure : source de type Legends, ou note d'annonce de retrait."""
    return {w["id"] for w in legends_warscrolls(data_dir)}


def canonical_ids(warscrolls: list[dict[str, str]]) -> set[str]:
    """Élit, par groupe (faction, nom) homonyme, la ou les warscroll(s) de référence.

    Port de `StatHammer/ingest/dedupe.py::mark_canonical` : une entrée est une
    « coquille » dominée si une version jouable (`virtual='false'`) existe, ou si
    une version non-RoR existe alors qu'elle référence un Regiment of Renown.
    """
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for w in warscrolls:
        key = (w.get("faction_id") or "", (w.get("name") or "").lower())
        groups.setdefault(key, []).append(w)

    canonical: set[str] = set()
    for ws in groups.values():
        if len(ws) == 1:
            canonical.add(ws[0]["id"])
            continue

        has_real = any((w.get("virtual") or "") == "false" for w in ws)
        has_non_ror = any((w.get("role") or "") != ROR_ROLE for w in ws)
        survivors = [
            w
            for w in ws
            if not (has_real and (w.get("virtual") or "") != "false")
            and not (has_non_ror and (w.get("role") or "") == ROR_ROLE)
        ] or ws  # filet de sécurité : ne devrait jamais être vide

        if len(survivors) == 1:
            canonical.add(survivors[0]["id"])
            continue

        # Plusieurs candidats canoniques sont légitimes s'ils se distinguent par
        # leur coût (ex. variantes ×5/×10 d'une même unité) ; sinon, ambigu.
        costs = [w.get("Cost") for w in survivors]
        if all(costs) and len(set(costs)) == len(costs):
            canonical.update(w["id"] for w in survivors)
        else:
            print(
                f"⚠ Ambigu : {ws[0].get('name')!r} → {len(survivors)} candidats "
                f"canoniques non départageables, le premier est retenu "
                f"({survivors[0]['id']})."
            )
            canonical.add(survivors[0]["id"])
    return canonical

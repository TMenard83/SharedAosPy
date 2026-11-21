"""Lecture des CSV Wahapedia (`data/wahapedia/*.csv`) et filtres communs à tous leurs lecteurs.

Format : séparateur `|`, BOM UTF-8. Filtres : warscrolls Legends (`legends_warscroll_ids`), dédoublonnage
canonique des warscrolls homonymes (`canonical_ids`), variantes de pack narratif expiré
(`is_expired_variant`, partagé avec l'importeur BSData qui filtre sur les noms BattleScribe).

Couche basse : n'importe rien d'autre d'aospy, pour que `importers/`, `abilities/` et `tournament_kit/`
puissent tous s'en servir.
"""

from __future__ import annotations

import csv
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


def read_csv(path: Path) -> list[dict[str, str]]:
    """Lignes d'un CSV Wahapedia (séparateur `|`, BOM UTF-8), une `dict` par ligne."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="|"))


def is_expired_variant(name: str) -> bool:
    lname = name.strip().lower()
    return any(marker in lname for marker in EXPIRED_VARIANT_MARKERS)


def legends_warscrolls(data_dir: Path) -> list[dict[str, str]]:
    """Lignes de `Warscrolls.csv` Legends : source de type Legends, ou note d'annonce de retrait."""
    sources = read_csv(data_dir / "Source.csv")
    legend_sources = {s["id"] for s in sources if "legends" in (s.get("name") or "").lower()}
    return [
        w
        for w in read_csv(data_dir / "Warscrolls.csv")
        if w.get("source_id") in legend_sources or "legend" in (w.get("notes") or "").lower()
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

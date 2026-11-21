"""Vérification croisée des sources d'une faction : Wahapedia × BattleScribe (× scan, à la main).

Trois sources décrivent une charte : Wahapedia (`data/wahapedia/*.csv`, importée en base), BSData
(`.cat` BattleScribe) et les scans des battletomes (`data/Battle tome/`, sans couche texte). Ce module
compare les deux premières et liste les écarts — caractéristiques, mots-clés (niveau de lanceur
compris), profils d'arme. Chaque écart se tranche **sur le scan** ; la valeur retenue va dans
`data/json/source_corrections.json` (cf. `importers.corrections`), qui l'emporte sur tout.

Le shell n'a pas d'accès réseau : les `.cat` se lisent dans un dossier local
(`data/bsdata/`, fichiers `KNOWN_ARMIES[faction]` déposés par l'utilisateur).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_BSDATA_DIR = Path("data") / "bsdata"

#: Mots-clés « techniques » que les deux sources n'écrivent pas pareil, sans enjeu de règle.
_IGNORED_KEYWORDS = {"WARD"}


@dataclass(frozen=True)
class Discrepancy:
    unit: str
    field: str
    wahapedia: str
    bsdata: str


def _norm(name: str) -> str:
    return " ".join(name.replace("’", "'").lower().split())


def compare_units(waha: dict, bs: dict) -> list[Discrepancy]:
    """Écarts entre deux dictionnaires nom → unité (`Unit` Wahapedia, `ParsedUnit` BSData)."""
    out: list[Discrepancy] = []
    bs_by = {_norm(n): u for n, u in bs.items()}
    for name, w in sorted(waha.items()):
        b = bs_by.get(_norm(name))
        if b is None:
            out.append(Discrepancy(name, "absente de BSData", "présente", "—"))
            continue
        for f in ("move", "save", "health", "control", "ward"):
            wv, bv = getattr(w, f), getattr(b, f)
            if (wv or None) != (bv or None):
                out.append(Discrepancy(name, f, str(wv), str(bv)))
        wk = {k for k in w.keywords if not k.startswith("WARD")} - _IGNORED_KEYWORDS
        bk = {k for k in b.keywords if not k.startswith("WARD")} - _IGNORED_KEYWORDS
        # BSData écrit « WIZARD (2) » seul ; Wahapedia garde aussi « WIZARD » nu (cf. keyword_variants).
        bk_full = bk | {k.split(" (", 1)[0] for k in bk if k.startswith(("WIZARD (", "PRIEST ("))}
        missing, extra = sorted(bk_full - wk), sorted(wk - bk_full)
        if missing or extra:
            out.append(
                Discrepancy(
                    name,
                    "mots-clés",
                    "+" + ",".join(extra) if extra else "",
                    "+" + ",".join(missing) if missing else "",
                )
            )
        bw = {_norm(x.name): x for x in b.weapons}
        for x in w.weapons:
            y = bw.get(_norm(x.name))
            if y is None:
                out.append(Discrepancy(name, f"arme {x.name}", "présente", "absente"))
                continue
            for f in ("range_in", "attacks", "hit", "wound", "rend", "damage"):
                if getattr(x, f) != getattr(y, f):
                    out.append(Discrepancy(name, f"{x.name}.{f}", str(getattr(x, f)), str(getattr(y, f))))
    return out


def verify_faction(con, faction: str, bsdata_dir: str | Path = DEFAULT_BSDATA_DIR) -> list[Discrepancy]:
    """Compare les unités Wahapedia en base à la bibliothèque BSData locale de la faction."""
    from ..persistence import repository
    from .bsdata import KNOWN_ARMIES, parse_library_units

    if faction not in KNOWN_ARMIES:
        raise ValueError(f"faction inconnue de BSData : {faction}")
    _main, library, _ga = KNOWN_ARMIES[faction]
    path = Path(bsdata_dir) / library
    if not path.exists():
        raise FileNotFoundError(
            f"{path} absent : télécharger « {library} » depuis github.com/BSData/age-of-sigmar-4th "
            f"et le déposer dans {bsdata_dir}/"
        )
    bs = {u.name: u for u in parse_library_units(path.read_text(encoding="utf-8")).values() if not u.is_legends}
    army = repository.get_army_by_name(con, faction)
    units = repository.load_all_units_with_weapons(con).get(army.id, []) if army else []
    return compare_units({u.name: u for u in units if u.points > 0}, bs)

"""Non-régression des PDF de tournoi (`aospy roster pdf`) : filet de sécurité du refactor.

Pour chaque liste de `tests/fixtures/lists/` et chaque mode, `build_roster_pdf` est
lancé dans un répertoire temporaire ; le texte extrait page par page (pypdf), le nombre
de pages (y compris la variante « scénarios » des modes `*-split-simple`) et les champs
de `RosterPdfResult` sont comparés à `tests/fixtures/golden/<liste>__<mode>.txt`.

Régénérer les références (uniquement pour un changement de comportement voulu) :

    pytest tests/tournament_kit/test_pdf_golden.py --update-golden

Ignoré si les sources sous droits (`data/Battle tome/`, `data/Manuel du général/`) ou
l'export Wahapedia ne sont pas présents localement.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("reportlab")

from aospy.tournament_kit import warscroll_card  # noqa: E402
from aospy.tournament_kit.pdf_builder import build_roster_pdf  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LISTS_DIR = ROOT / "tests" / "fixtures" / "lists"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
REQUIRED_SOURCES = (
    ROOT / "data" / "Battle tome",
    ROOT / "data" / "Manuel du général",
    ROOT / "data" / "wahapedia" / "Warscrolls.csv",
)
MODES = ("hybrid", "en", "fr", "fr-extended", "fr-split", "fr-split-simple", "en-split-simple")
LISTS = sorted(LISTS_DIR.glob("*.txt"))

# horodatage de la couverture (`pdf_theme.today_str`), seul élément non déterministe
_TIMESTAMP_RE = re.compile(r"\d{2}/\d{2}/\d{4} à \d{2}h\d{2}")


_STATE_NAME_RE = re.compile(r"^_[A-Z][A-Z0-9_]*$")


@pytest.fixture(autouse=True)
def _restore_render_state():
    """`build_roster_pdf` positionne des drapeaux de module de `warscroll_card`
    (`set_english_labels`, `set_french_keywords`…, cf. lot 4a) sans les remettre à
    zéro : on restaure l'état d'avant pour ne pas contaminer les tests suivants."""
    saved = {
        name: copy.copy(value)
        for name, value in vars(warscroll_card).items()
        if _STATE_NAME_RE.match(name) and isinstance(value, (bool, set, frozenset, dict, list, type(None)))
    }
    yield
    for name, value in saved.items():
        setattr(warscroll_card, name, value)


def _page_count(path: Path | None) -> int | None:
    return None if path is None else len(pypdf.PdfReader(path).pages)


def _snapshot(result) -> str:
    """Représentation texte stable d'un `RosterPdfResult` et du PDF produit."""
    reader = pypdf.PdfReader(result.output_path)
    lines = [
        f"pages: {len(reader.pages)}",
        f"pages_scenario: {_page_count(result.scenario_output_path)}",
        f"units_matched: {result.units_matched!r}",
        f"units_unmatched: {result.units_unmatched!r}",
        f"rules_included: {result.rules_included!r}",
        f"rules_unmatched: {result.rules_unmatched!r}",
        f"wahapedia_used: {result.wahapedia_used!r}",
        f"absent_references: {result.absent_references!r}",
        f"absent_keywords: {result.absent_keywords!r}",
    ]
    for number, page in enumerate(reader.pages, start=1):
        lines.append(f"===== page {number} =====")
        lines.append(_TIMESTAMP_RE.sub("<horodatage>", page.extract_text() or ""))
    return "\n".join(lines) + "\n"


@pytest.mark.skipif(
    not all(p.exists() for p in REQUIRED_SOURCES),
    reason="sources sous droits (data/Battle tome/, data/Manuel du général/) ou export Wahapedia absents",
)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("list_path", LISTS, ids=lambda p: p.stem.strip())
def test_pdf_golden(list_path: Path, mode: str, tmp_path: Path, request) -> None:
    result = build_roster_pdf(list_path, tmp_path / f"{list_path.stem.strip()}.pdf", mode=mode)
    actual = _snapshot(result)
    golden = GOLDEN_DIR / f"{list_path.stem.strip()}__{mode}.txt"
    if request.config.getoption("--update-golden"):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8")
        return
    assert golden.exists(), f"référence absente : {golden.name} (lancer avec --update-golden)"
    expected = golden.read_text(encoding="utf-8")
    assert actual == expected, f"le PDF {list_path.stem} ({mode}) a changé par rapport à {golden.name}"

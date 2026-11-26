"""Conversion Markdown → PDF et tableau récapitulatif du plan d'appariement L3."""

import pytest

from aospy.l3.pdf_pack import summarize_round, summary_table

SOLVER_MD = """# Appariement X contre Y — ronde 1 (mixte)

**Valeur de la ronde** (somme des 6 parties) : +1.5

| Notre choix | Plancher (pire réponse) | Contre leur meilleur jeu | Proba. |
|---|---|---|---|
| Alice | −2.0 (si Bob) | +1.0 | 60% |
| Carl | −3.0 (si Bob) | +0.5 | 40% |
| Dan | −5.0 (si Bob) | −1.0 | 0% |

Valeur : +1.5 · leur jeu attendu : Bob 70%, Eve 30%
"""


def test_summarize_round():
    r = summarize_round(SOLVER_MD)
    assert r == {"valeur": "+1.5", "defenseurs": ["Alice 60 %", "Carl 40 %"], "leurs": "Bob 70%, Eve 30%"}


def test_summary_table_bye():
    rows = [{"ronde": 1, "adversaire": "Y", **summarize_round(SOLVER_MD)}, {"ronde": 2, "adversaire": None}]
    lines = summary_table(rows).splitlines()
    assert lines[0].startswith("| Ronde")
    assert "Alice 60 %, Carl 40 %" in lines[2]
    assert lines[3] == "| 2 | BYE | | | |"


def test_build_pdf(tmp_path):
    pytest.importorskip("reportlab")
    from aospy.reports.markdown_pdf import build

    md = tmp_path / "a.md"
    md.write_text(
        "# Titre\n\nTexte **gras** et *italique*.\n\n- un\n- deux\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    out = build(tmp_path / "a.pdf", [md], titre="Essai")
    assert out.stat().st_size > 0
    pypdf = pytest.importorskip("pypdf")
    assert len(pypdf.PdfReader(str(out)).pages) >= 1

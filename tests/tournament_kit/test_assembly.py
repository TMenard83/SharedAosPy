"""Assemblage du PDF (`tournament_kit/assembly.py`) : pages de scénario."""

from __future__ import annotations

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pypdf")


def test_scenario_cards_go_four_per_a4_page(tmp_path):
    from pypdf import PdfWriter

    from aospy.tournament_kit.assembly import _append_scenario_pages

    src = PdfWriter()
    for _ in range(5):
        src.add_blank_page(width=308, height=464)
    path = tmp_path / "scen.pdf"
    with open(path, "wb") as fh:
        src.write(fh)
    out = PdfWriter()
    _append_scenario_pages(out, path)
    assert len(out.pages) == 2
    assert round(float(out.pages[0].mediabox.width)) == 595
    _append_scenario_pages(out, tmp_path / "absent.pdf")
    assert len(out.pages) == 2


def test_scenario_variant_path():
    from pathlib import Path

    from aospy.tournament_kit.assembly import scenario_variant_path

    assert scenario_variant_path(Path("d/L (fr-split-simple).pdf")) == Path("d/L (fr-split-simple-scenar).pdf")
    assert scenario_variant_path(Path("d/out.pdf")) == Path("d/out (scenar).pdf")

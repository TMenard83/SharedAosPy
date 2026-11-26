import os

from aospy.l3.freshness import newer_sources


def test_derived_older_than_a_source_is_stale(tmp_path):
    src, old, derived = tmp_path / "liste.txt", tmp_path / "vieux.txt", tmp_path / "grille.md"
    for p, t in ((old, 100), (derived, 200), (src, 300)):
        p.write_text("x")
        os.utime(p, (t, t))
    assert newer_sources(derived, [src, old, tmp_path / "absent"]) == [src]
    os.utime(derived, (400, 400))
    assert newer_sources(derived, [src, old]) == []


def test_missing_derived_is_stale(tmp_path):
    src = tmp_path / "liste.txt"
    src.write_text("x")
    assert newer_sources(tmp_path / "grille.md", [src]) == [src]

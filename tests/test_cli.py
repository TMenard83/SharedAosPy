"""Tests Phase 3 : CLI (init, listing, création, ajout, clone, delete)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aospy import db, repository
from aospy.cli import main


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cli.duckdb"


def run(argv: list[str]) -> int:
    return main(argv)


def test_init_then_army_list(db_path, capsys):
    assert run(["--db", str(db_path), "init"]) == 0
    capsys.readouterr()
    assert run(["--db", str(db_path), "army", "list"]) == 0
    out = capsys.readouterr().out
    assert "Stormcast Eternals" in out
    assert "Skaven" in out


def test_unit_list(db_path, capsys):
    run(["--db", str(db_path), "init", "--no-compositions"])
    capsys.readouterr()
    assert run(["--db", str(db_path), "unit", "list", "--army", "Skaven"]) == 0
    out = capsys.readouterr().out
    assert "Clanrats" in out
    assert "Grey Seer" in out


def test_comp_create_and_add_unit(db_path, capsys):
    run(["--db", str(db_path), "init", "--no-compositions"])
    capsys.readouterr()

    assert run([
        "--db", str(db_path), "comp", "create",
        "--army", "Skaven", "--name", "MaListe",
        "--format-points", "1000",
    ]) == 0

    con = db.connect(db_path)
    comp = repository.get_composition_by_name(con, _army_id(con, "Skaven"), "MaListe")
    assert comp is not None and comp.id is not None
    con.close()
    comp_id = comp.id

    assert run([
        "--db", str(db_path), "comp", "add-unit",
        "--comp", str(comp_id), "--unit", "Grey Seer",
        "--general", "--trait", "Master of Magic", "--artefact", "Warpstone Charm",
    ]) == 0
    assert run([
        "--db", str(db_path), "comp", "add-unit",
        "--comp", str(comp_id), "--unit", "Clanrats", "--reinforced",
    ]) == 0

    con = db.connect(db_path)
    comp = repository.get_composition(con, comp_id)
    assert comp is not None
    assert comp.total_points == 140 + 2 * 120
    assert len(comp.entries) == 2
    general = next(e for e in comp.entries if e.is_general)
    assert general.heroic_trait_id is not None
    assert general.artefact_id is not None
    con.close()


def test_comp_clone_then_delete(db_path, capsys):
    run(["--db", str(db_path), "init"])  # avec compositions de tournoi
    capsys.readouterr()

    con = db.connect(db_path)
    tournaments = repository.list_compositions(con, kind="tournament")
    assert tournaments, "le seed doit fournir au moins une compo de tournoi"
    src_id = tournaments[0].id
    con.close()

    assert run([
        "--db", str(db_path), "comp", "clone",
        "--from", str(src_id), "--name", "Variante Test",
    ]) == 0

    con = db.connect(db_path)
    customs = repository.list_compositions(con, kind="custom")
    assert any(c.name == "Variante Test" for c in customs)
    cloned = next(c for c in customs if c.name == "Variante Test")
    cloned_id = cloned.id
    con.close()

    assert run(["--db", str(db_path), "comp", "delete", str(cloned_id)]) == 0
    con = db.connect(db_path)
    assert repository.get_composition(con, cloned_id) is None
    con.close()


def test_comp_remove_entry(db_path, capsys):
    run(["--db", str(db_path), "init", "--no-compositions"])
    run([
        "--db", str(db_path), "comp", "create",
        "--army", "Skaven", "--name", "T", "--format-points", "1000",
    ])
    run([
        "--db", str(db_path), "comp", "add-unit",
        "--comp", "1", "--unit", "Clanrats",
    ])
    capsys.readouterr()

    con = db.connect(db_path)
    comp = repository.get_composition(con, 1)
    assert comp is not None and comp.entries
    entry_id = comp.entries[0].id
    con.close()

    assert run([
        "--db", str(db_path), "comp", "remove-entry", "--entry", str(entry_id),
    ]) == 0

    con = db.connect(db_path)
    comp = repository.get_composition(con, 1)
    assert comp is not None and not comp.entries
    assert comp.total_points == 0
    con.close()


def _army_id(con, name: str) -> int:
    a = repository.get_army_by_name(con, name)
    assert a is not None and a.id is not None
    return a.id

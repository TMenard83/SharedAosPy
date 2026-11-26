"""`aospy l3 dossiers` : découverte des dossiers à régénérer (dry-run) et filtre par équipe."""

from __future__ import annotations

from aospy import cli
from aospy.l3.dossier import find_dossiers, main


def _fake_root(tmp_path):
    for rel, with_list in [("Melusior/joueur1-Faction/L3 aller", True), ("Vae/joueur2-Faction/L3 aller", False)]:
        d = tmp_path / rel
        d.mkdir(parents=True)
        (d / "analyse.md").write_text("x", encoding="utf-8")
        if with_list:
            (d / "liste.txt").write_text("x", encoding="utf-8")
    (tmp_path / "Vae" / "sans-analyse").mkdir()
    return tmp_path


def test_find_dossiers_et_filtre_equipe(tmp_path):
    root = _fake_root(tmp_path)
    assert len(find_dossiers(root)) == 2
    only = find_dossiers(root, "Melusior")
    assert len(only) == 1 and "joueur1-Faction" in str(only[0])


def test_dry_run_n_ecrit_rien(tmp_path, capsys):
    root = _fake_root(tmp_path)
    assert main(["--root", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "2 dossier(s)" in out and "SANS liste.txt" in out
    assert not (root / "Melusior/joueur1-Faction/L3 aller/couche 4.md").exists()


def test_via_cli_aospy_l3(tmp_path, capsys):
    root = _fake_root(tmp_path)
    assert cli.main(["l3", "dossiers", "--root", str(root), "--team", "Melusior", "--dry-run"]) == 0
    assert "1 dossier(s)" in capsys.readouterr().out


def test_aucun_dossier(tmp_path):
    assert main(["--root", str(tmp_path), "--dry-run"]) == 1

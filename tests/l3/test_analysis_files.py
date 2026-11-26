"""Tests des réécritures de sections d'analyse.md et de la fusion de notes (fichiers factices)."""

from __future__ import annotations

import json

from aospy.l3 import analysis_files as af
from aospy.l3 import notes_fusion

EXPORT = """Jean - Stormcast (2000/2000)
Spell Lore - Lore of Fire
Battle Tactic Cards: A, B
General's Regiment
Lord (300)
• General
• Sword
Created with the App
"""

ENTRY = {"profil": "Profil.", "notes": {"s1": ["+", "bien | ok"], "s2": ["=", "moyen"]}}


def _data(tmp_path, entry=ENTRY):
    d = tmp_path / "data" / "Données"
    d.mkdir(parents=True)
    (d / "scenarios.json").write_text(json.dumps({"scenarios": [{"cle": "s1"}, {"cle": "s2"}]}), encoding="utf-8")
    notes = {"equipes": {"T": {"joueurs": {"Jean": {"profil": "old", "notes": {}, "autre": 1}}}}}
    (d / "notes_scenarios.json").write_text(json.dumps(notes), encoding="utf-8")
    return tmp_path / "data"


def _analyse(tmp_path, body):
    p = tmp_path / "an" / "T" / "Jean-Stormcast" / "liste1" / "analyse.md"
    p.parent.mkdir(parents=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_section10_idempotente(tmp_path):
    data = _data(tmp_path)
    json_path = data / "Données" / "notes_scenarios.json"
    notes = json.loads(json_path.read_text(encoding="utf-8"))
    notes["equipes"]["T"]["joueurs"]["Jean"].update(ENTRY)
    json_path.write_text(json.dumps(notes), encoding="utf-8")
    p = _analyse(tmp_path, "# T\n\n## 1. A\n\ntexte\n\n## 10. Scénarios\n\nancien\n\n## 11. Fin\n\nx\n")
    root = tmp_path / "an"
    changed, miss = af.refresh_section10(root, data, dry_run=True)
    assert changed == [p] and not miss
    assert "ancien" in p.read_text(encoding="utf-8")
    af.refresh_section10(root, data)
    txt = p.read_text(encoding="utf-8")
    assert "| s1 | + | bien / ok |" in txt and "## 11. Fin" in txt and "ancien" not in txt
    changed, _ = af.refresh_section10(root, data)
    assert changed == [] and p.read_text(encoding="utf-8") == txt


def test_section10_absente_signalee(tmp_path):
    data = _data(tmp_path)
    _analyse(tmp_path, "# T\n")
    _, miss = af.refresh_section10(tmp_path / "an", data)
    assert miss == ["T/Jean : pas de section 10"]


def test_section0_inseree_puis_mise_a_jour(tmp_path):
    exports = tmp_path / "data" / "Listes texte" / "T"
    exports.mkdir(parents=True)
    exp = exports / "Jean.txt"
    exp.write_text(EXPORT, encoding="utf-8")
    p = _analyse(tmp_path, "# Titre\n\nsuite\n")
    root = tmp_path / "an"
    changed, no_export = af.refresh_header(root, tmp_path / "data" / "Listes texte")
    assert changed == [p] and not no_export
    txt = p.read_text(encoding="utf-8")
    assert txt.startswith("# Titre\n\n" + af.START) and "## 0. La liste" in txt
    assert "- Battle Tactic Cards : A, B" in txt and "  - General" in txt and "Created with" not in txt
    assert txt.endswith("suite\n")
    assert af.refresh_header(root, tmp_path / "data" / "Listes texte")[0] == []
    exp.write_text(EXPORT.replace("Lord (300)", "Lord (310)"), encoding="utf-8")
    af.refresh_header(root, tmp_path / "data" / "Listes texte")
    new = p.read_text(encoding="utf-8")
    assert "Lord (310)" in new and "Lord (300)" not in new and new.count(af.START) == 1


def test_fusion_notes(tmp_path):
    data = _data(tmp_path)
    p = _analyse(tmp_path, "# T\n\n## 10. Scénarios\n\nvieux\n")
    assign = tmp_path / "assign.json"
    assign.write_text(json.dumps({"T": {"Jean": {"analyse": str(p), "scenarios": ["s1", "s2"]}}}), encoding="utf-8")
    lot = tmp_path / "lot.json"
    lot.write_text(json.dumps({"T": {"Jean": ENTRY}}), encoding="utf-8")
    assert notes_fusion.fusion(assign, [lot], data) == []
    notes = json.loads((data / "Données" / "notes_scenarios.json").read_text(encoding="utf-8"))
    j = notes["equipes"]["T"]["joueurs"]["Jean"]
    assert j["profil"] == "Profil." and list(j["notes"]) == ["s1", "s2"] and j["autre"] == 1
    assert "vieux" not in p.read_text(encoding="utf-8") and "| s2 | = | moyen |" in p.read_text(encoding="utf-8")


def test_fusion_notes_invalides(tmp_path):
    data = _data(tmp_path)
    p = _analyse(tmp_path, "# T\n")
    assign = tmp_path / "assign.json"
    assign.write_text(json.dumps({"T": {"Jean": {"analyse": str(p), "scenarios": ["s1", "s2"]}}}), encoding="utf-8")
    lot = tmp_path / "lot.json"
    lot.write_text(json.dumps({"T": {"Jean": {"profil": "x", "notes": {"s1": ["??", "c"]}}}}), encoding="utf-8")
    errs = notes_fusion.fusion(assign, [lot], data)
    assert len(errs) == 1 and "manquants ['s2']" in errs[0]
    assert p.read_text(encoding="utf-8") == "# T\n"

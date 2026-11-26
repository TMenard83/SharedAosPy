"""Cascade des couches : une couche périmée bloque toutes celles du dessus."""

from __future__ import annotations

import pytest

from aospy.analysis.layers import cascade
from aospy.persistence import db, repository


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(cascade, "_layer1_fingerprint", lambda data_dir=None: "v1|0")
    c = db.connect(tmp_path / "t.duckdb")
    yield c
    c.close()


def _build(con, layer):
    repository.mark_layer_built(con, layer, cascade._fingerprint(con, layer, repository.layer_builds(con)))


def test_empty_db_everything_stale(con):
    assert [s.fresh for s in cascade.status(con)] == [False, False, False]
    with pytest.raises(ValueError, match="couche 1"):
        cascade.require_fresh(con, 2)
    with pytest.raises(ValueError, match="aospy cascade"):
        cascade.require_fresh(con, 4)


def test_built_in_order_is_fresh(con):
    for layer in (1, 2, 3):
        _build(con, layer)
    assert all(s.fresh for s in cascade.status(con))
    cascade.require_fresh(con, 4)


def test_rebuilding_layer1_invalidates_above(con):
    for layer in (1, 2, 3):
        _build(con, layer)
    con.execute("UPDATE layer_build SET built_at = built_at + INTERVAL 1 SECOND WHERE layer = 1")
    st = cascade.status(con)
    assert [s.fresh for s in st] == [True, False, False]
    with pytest.raises(ValueError, match="couche 2"):
        cascade.require_fresh(con, 3)
    cascade.require_fresh(con, 2)


def test_analyzer_version_change(con, monkeypatch):
    for layer in (1, 2, 3):
        _build(con, layer)
    monkeypatch.setattr(cascade, "_layer1_fingerprint", lambda data_dir=None: "v2|0")
    st = cascade.status(con)
    assert not st[0].fresh and "v1" in st[0].reason and "v2" in st[0].reason
    assert not st[2].fresh


def test_layer3_refuses_on_stale_layer2(con):
    _build(con, 1)
    with pytest.raises(ValueError, match="couche 2"):
        cascade.build_layer3(con)

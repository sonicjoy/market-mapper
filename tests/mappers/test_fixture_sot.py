"""Tests for the offline SoT fixture store."""

from __future__ import annotations

from mappers.seed.fixture_store import fixture_path, load_fixture, write_fixture
from mappers.seed.sot import SotSnapshot, load_snapshot, reset_sot_cache


def test_fixture_loads_without_bigquery():
    reset_sot_cache()
    snap = load_snapshot()
    assert snap.rule_set_id
    assert snap.leagues
    assert snap.entities


def test_fixture_path_round_trip(tmp_path):
    snap = load_fixture()
    out = tmp_path / "tip.json"
    write_fixture(snap, out)
    again = load_fixture(out)
    assert again.rule_set_id == snap.rule_set_id
    assert len(again.entities) == len(snap.entities)


def test_fixture_path_none_unless_env_set(monkeypatch):
    monkeypatch.delenv("MAPPING_SOT_FIXTURE", raising=False)
    assert fixture_path() is None


def test_load_snapshot_uses_live_bq_without_fixture_env(monkeypatch):
    monkeypatch.delenv("MAPPING_SOT_FIXTURE", raising=False)
    sentinel = SotSnapshot(
        rule_set_id="P_live", entities=[], market_rules=[], leagues=[],
    )
    monkeypatch.setattr(
        "mappers.seed.sot.load_live_snapshot", lambda: sentinel,
    )
    reset_sot_cache()
    assert load_snapshot().rule_set_id == "P_live"

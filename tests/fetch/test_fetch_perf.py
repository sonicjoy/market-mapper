"""Tests for main-pipeline fetch performance helpers."""

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import fetch.__main__ as orch
from fetch import optic
from fetch.__main__ import _fetcher_cmd


def test_fetch_fixtures_parallel_collects_without_shared_mutation():
    fixtures = [{"id": f"fx{i}", "source_ids": {}} for i in range(5)]

    def fake_fetch(_headers, fixture):
        return {"id": fixture["id"], "odds": []}

    with (
        patch("fetch.optic.fetch_processed_fixture", side_effect=fake_fetch),
        patch("fetch.optic.sleep"),
    ):
        results, skipped = optic.fetch_fixtures_parallel(
            {}, fixtures, workers=3)
    assert skipped == 0
    assert {r["id"] for r in results} == {f["id"] for f in fixtures}


def test_fetch_fixtures_parallel_counts_skips():
    fixtures = [{"id": "a"}, {"id": "b"}]

    def fake_fetch(_headers, fixture):
        return None if fixture["id"] == "a" else {"id": "b"}

    with (
        patch("fetch.optic.fetch_processed_fixture", side_effect=fake_fetch),
        patch("fetch.optic.sleep"),
    ):
        results, skipped = optic.fetch_fixtures_parallel(
            {}, fixtures, workers=2)
    assert skipped == 1
    assert [r["id"] for r in results] == ["b"]


def test_fetcher_cmd_forwards_horizon_only_to_optic(tmp_path):
    leagues = ["nba"]
    optic_cmd = _fetcher_cmd(
        "fetch.optic", leagues, tmp_path,
        minimal=True, horizon_hours=12.0,
    )
    assert "--horizon-hours" in optic_cmd
    assert "12.0" in optic_cmd
    assert "--max-items" in optic_cmd

    kalshi_cmd = _fetcher_cmd(
        "fetch.kalshi", leagues, tmp_path,
        minimal=False, horizon_hours=12.0,
    )
    assert "--horizon-hours" not in kalshi_cmd


def test_orchestrator_runs_optic_then_optional_in_parallel(tmp_path, monkeypatch):
    """Optic is serial-first; remaining fetchers share a pool."""
    calls: list[str] = []

    def fake_run(cmd):
        # cmd: python -m fetch.X --league ...
        mod = cmd[cmd.index("-m") + 1]
        calls.append(mod)
        return MagicMock(returncode=0)

    monkeypatch.setattr(orch.subprocess, "run", fake_run)

    class _DT:
        @staticmethod
        def now(_tz):
            return datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(orch, "datetime", _DT)

    out_root = tmp_path / "data"
    monkeypatch.setattr(
        sys, "argv",
        ["fetch", "--league", "nba", "--out-dir", str(out_root)],
    )
    orch.main()
    assert calls[0] == "fetch.optic"
    assert set(calls[1:]) == {
        "fetch.kalshi", "fetch.px", "fetch.crypto_com", "fetch.polymarket",
        "fetch.novig", "fetch.dkex_bq", "fetch.sxbet", "fetch.underdog", "fetch.stx",
    }


def test_orchestrator_appends_runshop_when_tip_flag_set(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_run(cmd):
        mod = cmd[cmd.index("-m") + 1]
        calls.append(mod)
        return MagicMock(returncode=0)

    monkeypatch.setattr(orch.subprocess, "run", fake_run)

    class _DT:
        @staticmethod
        def now(_tz):
            return datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(orch, "datetime", _DT)

    out_root = tmp_path / "data"
    monkeypatch.setattr(
        sys, "argv",
        ["fetch", "--league", "world_cup", "--out-dir", str(out_root)],
    )
    orch.main()
    assert "fetch.runshop" in calls

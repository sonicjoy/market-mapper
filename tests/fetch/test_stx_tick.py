"""STX in the 15-minute tick: off unless STX_ENV is set, only for STX leagues, key from Secret Manager."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from fetch import stx
from fetch.tip import stx_requested


def _run(monkeypatch, tmp_path, *extra, env=None):
    monkeypatch.setattr(sys, "argv", ["fetch.stx", "--out-dir", str(tmp_path), *extra])
    for k in (stx.TICK_ENV, stx.TICK_REGION_ENV):
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    stx.main()


def test_stx_requested_follows_the_run_set_leagues():
    assert stx_requested(["nfl", "epl"]) and stx_requested(["italy_serie_a"])
    assert not stx_requested(["epl", "wnba"])  # ISL / AFC / cricket have no run-set slug


def test_tick_without_stx_env_fetches_nothing(monkeypatch, tmp_path, capsys):
    called = []
    monkeypatch.setattr(stx, "_fetch_live", lambda *a, **k: called.append(a))
    _run(monkeypatch, tmp_path, "--league", "nfl", env={"GCP_PROJECT": "marketmaking-test"})
    assert not called and not (tmp_path / stx.OUT_FILE).exists()
    assert "skipping" in capsys.readouterr().out


def test_tick_skips_when_no_requested_league_is_stx(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(stx, "_fetch_live", lambda *a, **k: called.append(a))
    _run(monkeypatch, tmp_path, "--league", "epl", env={stx.TICK_ENV: "demo", "GCP_PROJECT": "marketmaking-test"})
    assert not called


def test_tick_fetches_live_with_the_gsm_project_and_writes_both_files(monkeypatch, tmp_path):
    seen = {}

    async def fake(region, env, with_players, gsm_project=None):
        seen.update(region=region, env=env, players=with_players, project=gsm_project)
        return [{"market_id": "m1", "event_id": "e1"}], [{"event_id": "e1", "teams": []}]

    monkeypatch.setattr(stx, "_fetch_live", fake)
    _run(
        monkeypatch, tmp_path, "--league", "nfl", "nba", env={stx.TICK_ENV: "demo", "GCP_PROJECT": "marketmaking-test"}
    )
    assert seen == {"region": "ontario", "env": "demo", "players": True, "project": "marketmaking-test"}
    assert json.loads((tmp_path / stx.OUT_FILE).read_text())["market_id"] == "m1"
    assert (tmp_path / stx.PLAYERS_FILE).exists()


def test_tick_max_items_truncates(monkeypatch, tmp_path):
    async def fake(*a, **k):
        return [{"market_id": str(i)} for i in range(5)], []

    monkeypatch.setattr(stx, "_fetch_live", fake)
    _run(monkeypatch, tmp_path, "--league", "nfl", "--max-items", "3", env={stx.TICK_ENV: "demo", "GCP_PROJECT": "p"})
    assert len((tmp_path / stx.OUT_FILE).read_text().splitlines()) == 3


def test_credentials_read_secret_manager_names_without_printing(monkeypatch, capsys):
    got = []
    monkeypatch.setattr(stx, "_gsm", lambda name, project: got.append((name, project)) or f"<{name}>")
    assert stx._credentials("marketmaking-test") == ("<stx-api-key-id>", "<stx-private-key>")
    assert got == [("stx-api-key-id", "marketmaking-test"), ("stx-private-key", "marketmaking-test")]
    assert capsys.readouterr().out == ""


def test_dev_live_still_needs_the_env_key(monkeypatch):
    monkeypatch.delenv(stx.KEY_ID_ENV, raising=False)
    with pytest.raises(SystemExit):
        asyncio.run(stx._fetch_live("ontario", "demo", False))


def test_a_roster_404_skips_that_event_and_keeps_the_catalogue(monkeypatch, capsys):
    """Ontario demo 2026-10-29: ``event not found`` on one event's roster aborted the whole fetch."""
    import types

    class SdkError(Exception):
        pass

    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def iter_markets(self, status):
            for eid in ("e1", "e2"):
                yield {"market_id": f"m-{eid}", "event_id": eid, "rules": "player_stat_line"}

        async def event_players(self, event_id):
            if event_id == "e1":
                raise SdkError("event not found")
            return {"teams": []}

    monkeypatch.setenv(stx.KEY_ID_ENV, "k")
    monkeypatch.setenv(stx.KEY_PATH_ENV, "/dev/null")
    fake = types.SimpleNamespace(AsyncSTX=Client, STXException=SdkError)
    monkeypatch.setattr(stx.importlib, "import_module", lambda name: fake)
    markets, players = asyncio.run(stx._fetch_live("ontario", "demo", True, None))
    assert {m["market_id"] for m in markets} == {"m-e1", "m-e2"}
    assert [p["event_id"] for p in players] == ["e2"]
    assert "1/2 events have no roster" in capsys.readouterr().err


def _capture_client(monkeypatch):
    """Patch the SDK with a client that records its kwargs; returns the dict they land in."""
    import types

    seen: dict = {}

    class Client:
        def __init__(self, **kw):
            seen.update(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def iter_markets(self, status):
            if False:
                yield {}

    monkeypatch.setenv(stx.KEY_ID_ENV, "k")
    monkeypatch.setenv(stx.KEY_PATH_ENV, "/dev/null")
    fake = types.SimpleNamespace(AsyncSTX=Client, STXException=Exception)
    monkeypatch.setattr(stx.importlib, "import_module", lambda n: fake)
    return seen


def test_unset_proxy_leaves_the_sdk_direct(monkeypatch):
    monkeypatch.delenv(stx.PROXY_ENV, raising=False)
    seen = _capture_client(monkeypatch)
    asyncio.run(stx._fetch_live("ontario", "demo", False, None))
    assert "transport" not in seen


def test_stx_https_proxy_goes_to_the_sdk_transport_only(monkeypatch):
    import os

    import httpx

    monkeypatch.setenv(stx.PROXY_ENV, "http://10.15.0.2:3128")
    seen = _capture_client(monkeypatch)
    asyncio.run(stx._fetch_live("ontario", "prod", False, None))
    assert isinstance(seen["transport"], httpx.AsyncHTTPTransport)
    assert "HTTPS_PROXY" not in os.environ and "https_proxy" not in os.environ  # nothing process-wide

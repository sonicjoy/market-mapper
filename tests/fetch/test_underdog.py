"""fetch.underdog: pager, retries, row shape the Underdog pass reads, orchestrator wiring."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import fetch.__main__ as orch
from fetch import tip
from fetch import underdog as udx
from mappers.exchanges import underdog_pass
from mappers.exchanges.underdog import UnderdogConfig
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

BASE = "https://udx.example"

GAMEWIN = {
    "ticker": "UDXNFLGAMEWIN_BALDAL26SEP271625_BAL",
    "description": (
        "Resolves Yes if the Baltimore Ravens win the National Football League game between the "
        "Baltimore Ravens and the Dallas Cowboys originally scheduled for 4:25pm ET on September 27, 2026."
    ),
    "status": "open",
    "external_ids": {"optic_odds": {"fixture_id": "FIX-BAL-DAL", "market_id": "moneyline"}},
    "expires_at": "2026-09-30T20:25:00.000000Z",
    "tick_size": "0.001",
    "minimum_price": "0.001",
    "maximum_price": "0.999",
}
TENNIS = {**GAMEWIN, "ticker": "UDXATPCHLMATCHWIN_GORBOY26SEP241400_SGORZNY"}
COMBO = {**GAMEWIN, "ticker": "UDX-MULTI", "legs": [{"ticker": "A", "outcome": "yes"}]}


def _resp(status: int, body: dict | None = None, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


def _session(*responses) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


def test_pager_follows_next_page_url_and_sends_filters_once() -> None:
    session = _session(
        _resp(200, {"markets": [GAMEWIN], "next_page_url": "/markets?limit=100&page=p2&status=open"}),
        _resp(200, {"markets": [TENNIS], "next_page_url": None}),
    )
    rows = list(udx.iter_markets(session, BASE, sleep=lambda _s: None))
    assert [r["ticker"] for r in rows] == [GAMEWIN["ticker"], TENNIS["ticker"]]
    first, second = session.get.call_args_list
    assert first.args[0] == f"{BASE}/markets"
    assert first.kwargs["params"] == {"type": "single_leg", "status": "open", "limit": 100}
    assert second.args[0] == f"{BASE}/markets?limit=100&page=p2&status=open"
    assert second.kwargs["params"] is None


def test_pager_refuses_absolute_next_page_url() -> None:
    session = _session(_resp(200, {"markets": [], "next_page_url": "https://evil.example/markets"}))
    with pytest.raises(udx.UdxFetchError, match="root-relative"):
        list(udx.iter_markets(session, BASE, sleep=lambda _s: None))


def test_pager_stops_on_repeating_cursor() -> None:
    page = {"markets": [GAMEWIN], "next_page_url": "/markets?page=same"}
    session = _session(_resp(200, page), _resp(200, page))
    with pytest.raises(udx.UdxFetchError, match="repeats"):
        list(udx.iter_markets(session, BASE, sleep=lambda _s: None))


def test_pager_page_cap() -> None:
    session = MagicMock()
    counter = iter(range(10))
    session.get.side_effect = lambda *_a, **_k: _resp(
        200, {"markets": [], "next_page_url": f"/markets?page={next(counter)}"}
    )
    with pytest.raises(udx.UdxFetchError, match="more than 3 pages"):
        list(udx.iter_markets(session, BASE, sleep=lambda _s: None, max_pages=3))


def test_retry_on_429_honours_retry_after_then_succeeds() -> None:
    sleeps: list[float] = []
    session = _session(
        _resp(429, {}, {"Retry-After": "2"}),
        _resp(503),
        _resp(200, {"markets": [], "next_page_url": None}),
    )
    body = udx.get_json(session, f"{BASE}/markets", sleep=sleeps.append)
    assert body == {"markets": [], "next_page_url": None}
    assert sleeps == [2.0, 2.0]  # Retry-After, then doubled backoff (1 -> 2)


def test_retry_on_transport_error() -> None:
    sleeps: list[float] = []
    session = _session(requests.ConnectionError("reset"), _resp(200, {"markets": []}))
    assert udx.get_json(session, f"{BASE}/markets", sleep=sleeps.append) == {"markets": []}
    assert sleeps == [1.0]


def test_retries_exhausted_raise() -> None:
    session = _session(*[_resp(500) for _ in range(udx.MAX_TRIES)])
    with pytest.raises(udx.UdxFetchError, match="HTTP 500"):
        udx.get_json(session, f"{BASE}/markets", sleep=lambda _s: None)
    assert session.get.call_count == udx.MAX_TRIES


def test_unauthenticated_403_names_signed_mode() -> None:
    session = _session(_resp(403))
    with pytest.raises(udx.UdxFetchError, match="UDX_AUTH=signed"):
        udx.get_json(session, f"{BASE}/markets", sleep=lambda _s: None)


def test_empty_bucket_waits_out_the_window() -> None:
    sleeps: list[float] = []
    session = _session(_resp(200, {"markets": []}, {"RateLimit": '"read";r=0;t=1'}))
    udx.get_json(session, f"{BASE}/markets", sleep=sleeps.append)
    assert sleeps == [1.0]


def test_signed_headers_sign_path_without_query() -> None:
    signed: list[tuple[str, str]] = []

    def sign(method: str, path: str) -> dict[str, str]:
        signed.append((method, path))
        return {"UDX-Access-Key": "k"}

    session = _session(_resp(200, {"markets": []}))
    udx.get_json(session, f"{BASE}/markets?page=abc", sign=sign, sleep=lambda _s: None)
    assert signed == [("GET", "/markets")]
    assert session.get.call_args.kwargs["headers"] == {"UDX-Access-Key": "k"}


def test_keep_rows_drops_legs_and_caps_without_reading_tickers() -> None:
    rows = [GAMEWIN, TENNIS, COMBO, {**GAMEWIN, "ticker": "opaque-id"}]
    assert [r["ticker"] for r in udx.keep_rows(rows)] == [
        GAMEWIN["ticker"], TENNIS["ticker"], "opaque-id",
    ]  # combo dropped, nothing filtered by prefix
    assert len(udx.keep_rows(rows, max_items=1)) == 1


def test_tip_underdog_league_map_and_requested(monkeypatch) -> None:
    monkeypatch.setattr(
        tip,
        "resolved_leagues",
        lambda: {
            "nfl": SimpleNamespace(UNDERDOG=SimpleNamespace(league="NFL")),
            "nba": SimpleNamespace(UNDERDOG=None),
        },
    )
    assert tip.underdog_league_map() == {"nfl": "NFL"}
    assert tip.underdog_requested(["nba", "nfl"])
    assert not tip.underdog_requested(["nba"])


def test_main_writes_rows_the_underdog_pass_stamps(tmp_path, monkeypatch) -> None:
    """End to end on the file: fetcher output -> read_catalogue -> run_pass stamps both sides."""
    monkeypatch.setattr(tip, "underdog_requested", lambda _l: True)
    monkeypatch.setattr(udx, "iter_markets", lambda *_a, **_k: iter([GAMEWIN, COMBO]))
    assert udx.main(["--league", "nfl", "--out-dir", str(tmp_path)]) == 0

    catalogue = underdog_pass.read_catalogue(tmp_path / udx.OUT_FILE)
    assert [r["ticker"] for r in catalogue] == [GAMEWIN["ticker"]]
    assert not (tmp_path / "underdog_markets.jsonl.tmp").exists()

    fixture = SimpleNamespace(
        fixture_id="FIX-BAL-DAL",
        away_name="Baltimore Ravens",
        home_name="Dallas Cowboys",
        start_et="2026-09-27T16:25:00-04:00",
        away="BAL",
        home="DAL",
        start_date="2026-09-27T20:25:00Z",
    )
    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(league="NFL", market_types=market_types_for_sport(Sport.FOOTBALL))
    tally = underdog_pass.run_pass(
        catalogue,
        cfg,
        [SimpleNamespace(fixture=fixture)],
        league="nfl",
        attach=attach,
        row_index={},
        all_rows=[],
    )
    assert tally["stamped"] == 2
    assert {(r.side, r.underdog_side) for r in stamped} == {("BAL", "yes"), ("DAL", "no")}
    assert {r.underdog_ticker for r in stamped} == {GAMEWIN["ticker"]}


def test_main_skips_without_underdog_leagues(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tip, "underdog_requested", lambda _l: False)
    called = MagicMock()
    monkeypatch.setattr(udx, "iter_markets", called)
    assert udx.main(["--league", "nba", "--out-dir", str(tmp_path)]) == 0
    called.assert_not_called()
    assert not (tmp_path / udx.OUT_FILE).exists()


def test_main_failure_leaves_no_file(tmp_path, monkeypatch) -> None:
    def boom(*_a, **_k):
        yield GAMEWIN
        raise udx.UdxFetchError("HTTP 500")

    monkeypatch.setattr(udx, "iter_markets", boom)
    assert udx.main(["--all-leagues", "--out-dir", str(tmp_path)]) == 1
    assert not (tmp_path / udx.OUT_FILE).exists()


def _run_orchestrator(tmp_path, monkeypatch, *, requested: bool, codes: dict[str, int]) -> list[str]:
    calls: list[str] = []

    def fake_run(cmd):
        mod = cmd[cmd.index("-m") + 1]
        calls.append(mod)
        return MagicMock(returncode=codes.get(mod, 0))

    class _DT:
        @staticmethod
        def now(_tz):
            return datetime(2026, 9, 24, 16, 0, tzinfo=UTC)

    monkeypatch.setattr(orch.subprocess, "run", fake_run)
    monkeypatch.setattr(orch, "datetime", _DT)
    monkeypatch.setattr(orch, "underdog_requested", lambda _l: requested)
    monkeypatch.setattr(orch, "runshop_requested", lambda _l: False)
    monkeypatch.setattr(orch, "huddle_requested", lambda _l: False)
    monkeypatch.setattr(sys, "argv", ["fetch", "--league", "nfl", "--out-dir", str(tmp_path / "data")])
    orch.main()
    return calls


def test_orchestrator_runs_underdog_when_requested(tmp_path, monkeypatch) -> None:
    calls = _run_orchestrator(tmp_path, monkeypatch, requested=True, codes={})
    assert calls[0] == "fetch.optic"
    assert "fetch.underdog" in calls[1:]


def test_orchestrator_skips_underdog_when_not_requested(tmp_path, monkeypatch) -> None:
    assert "fetch.underdog" not in _run_orchestrator(tmp_path, monkeypatch, requested=False, codes={})


def test_orchestrator_underdog_failure_is_not_fatal(tmp_path, monkeypatch, capsys) -> None:
    calls = _run_orchestrator(tmp_path, monkeypatch, requested=True, codes={"fetch.underdog": 1})
    assert "fetch.underdog" in calls
    out = capsys.readouterr()
    assert "FAILED: fetch.underdog" in out.err
    assert "Continuing with partial data" in out.out

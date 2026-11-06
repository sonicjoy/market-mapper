"""Kalshi mapping fetch: one open-events sweep, kept by sport tag and typed scope."""

import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch import kalshi  # noqa: E402
from mappers.exchanges.kalshi import (  # noqa: E402
    KalshiConfig,
    parse_market_line,
    scoped_market_type,
)
from mappers.sport import Sport  # noqa: E402

CATALOG = {
    "KXNFLGAME": {"ticker": "KXNFLGAME", "tags": ["Football"], "product_metadata": {"scope": "Game"}},
    "KXNFLPASS": {"ticker": "KXNFLPASS", "tags": ["Football"], "product_metadata": {"scope": "Passing"}},
    "KXGOLF": {"ticker": "KXGOLF", "tags": ["Golf"], "product_metadata": {"scope": "Game"}},
}
MILESTONE = {"id": "m1", "home_id": "chi", "away_id": "phi"}


def _raw_market(ticker: str, status: str = "active", **over) -> dict:
    row = {k: k for k in kalshi.STRUCTURAL_KEYS}
    row.update(event_ticker="E", ticker=ticker, status=status)
    row.update(over)
    return row


def _event(series: str, scope: str | None, markets: list[dict], et: str = "E") -> dict:
    pm = {"competition": "Pro Football"}
    if scope:
        pm["competition_scope"] = scope
    return {"event_ticker": et, "series_ticker": series, "product_metadata": pm, "markets": markets}


def test_strip_market_keeps_typed_strike_when_present():
    raw = _raw_market("T", strike_type="greater", floor_strike=2.5, custom_strike={"soccer_team": "abc"}, yes_bid=40)
    row = kalshi.strip_market(raw)
    assert row["strike_type"] == "greater"
    assert row["floor_strike"] == 2.5
    assert row["custom_strike"] == {"soccer_team": "abc"}
    assert "cap_strike" not in row and "yes_bid" not in row


def test_event_rows_carry_typed_identity_and_only_active_markets():
    event = _event(
        "KXNFLGAME",
        "Game",
        [
            _raw_market("T-1", custom_strike={"football_team": "chi"}),
            _raw_market("T-2", status="finalized"),
        ],
    )
    rows = kalshi.event_rows(event, CATALOG, {Sport.FOOTBALL}, {"E": MILESTONE})
    assert [r["ticker"] for r in rows] == ["T-1"]
    row = rows[0]
    assert (row["sport"], row["series_scope"], row["competition_scope"]) == ("football", "Game", "Game")
    assert row["milestone"] == MILESTONE


def test_event_rows_need_a_requested_sport_and_a_mapped_scope():
    game = _event("KXNFLGAME", "Game", [_raw_market("T-1")])
    assert kalshi.event_rows(game, CATALOG, {Sport.SOCCER}, {}) == []
    golf = _event("KXGOLF", "Game", [_raw_market("T-1")])
    assert kalshi.event_rows(golf, CATALOG, set(Sport), {}) == []
    # A "Future" event inside a "Game" series is not a game.
    future = _event("KXNFLGAME", "Future", [_raw_market("T-1")])
    assert kalshi.event_rows(future, CATALOG, {Sport.FOOTBALL}, {}) == []
    # A finer event scope types a broader series.
    passing = _event("KXNFLPASS", "Passing Yards", [_raw_market("T-1")])
    assert len(kalshi.event_rows(passing, CATALOG, {Sport.FOOTBALL}, {})) == 1
    # No event scope: the series scope decides.
    bare = _event("KXNFLGAME", None, [_raw_market("T-1")])
    assert len(kalshi.event_rows(bare, CATALOG, {Sport.FOOTBALL}, {})) == 1


def test_sweep_pages_open_events_with_nested_markets():
    pages = [
        {"events": [{"event_ticker": "A"}], "cursor": "c1"},
        {"events": [{"event_ticker": "B"}], "cursor": ""},
    ]
    seen: list[dict] = []
    with patch("fetch.kalshi.kalshi_get", side_effect=pages) as get:
        kalshi.sweep_events("key", object(), seen.append)
    assert [e["event_ticker"] for e in seen] == ["A", "B"]
    first = get.call_args_list[0].args[1]
    assert first["status"] == "open" and first["with_nested_markets"] == "true"
    assert get.call_args_list[1].args[1]["cursor"] == "c1"


def test_sweep_refuses_a_truncated_book():
    with (
        patch("fetch.kalshi.kalshi_get", return_value={"events": [], "cursor": "x"}),
        pytest.raises(RuntimeError, match="max_pages"),
    ):
        kalshi.sweep_events("key", object(), lambda _e: None, max_pages=2)


def test_fetch_milestones_indexes_every_related_event():
    ms = {
        "id": "m1",
        "type": "football_game",
        "start_date": "2026-09-29T00:15:00Z",
        "source_ids": {"source_2_id": "20260929A204B7F8", "source_3_id": "35b0eb86"},
        "details": {"home_team_id": "chi", "away_team_id": "phi"},
        "related_event_tickers": ["KXNFLGAME-26SEP28PHICHI", "KXNFLSPREAD-26SEP28PHICHI"],
    }

    def fake_get(path, params, *_a):
        if path.endswith("/structured_targets"):
            if params["type"] == "football_team":
                return {"structured_targets": [{"id": "chi", "source_ids": {"source_2_id": "OPTCHI"}}]}
            return {"structured_targets": []}
        return {"milestones": [ms], "cursor": ""}

    with patch("fetch.kalshi.kalshi_get", side_effect=fake_get):
        by_event = kalshi.fetch_milestones("key", object())
    got = by_event["KXNFLSPREAD-26SEP28PHICHI"]
    assert got is by_event["KXNFLGAME-26SEP28PHICHI"]
    assert got["optic_fixture_id"] == "20260929A204B7F8"
    assert got["sportradar_id"] is None  # not an sr: id
    assert (got["home_optic_id"], got["away_optic_id"]) == ("OPTCHI", None)


def test_fetch_book_writes_kept_rows():
    event = _event("KXNFLGAME", "Game", [_raw_market("T-1")])

    def fake_sweep(_k, _p, sink):
        sink(event)
        sink(_event("KXGOLF", "Game", [_raw_market("G-1")]))

    out: list[dict] = []
    with (
        patch("fetch.kalshi.load_series_catalog", return_value=CATALOG),
        patch("fetch.kalshi.fetch_milestones", return_value={"E": MILESTONE}),
        patch("fetch.kalshi.sweep_events", side_effect=fake_sweep),
    ):
        n = kalshi.fetch_book({Sport.FOOTBALL}, "key", object(), out.append)
    assert n == 1 and [r["ticker"] for r in out] == ["T-1"]


def test_failed_fetch_leaves_no_output_file(tmp_path):
    with (
        patch("fetch.kalshi.fetch_book", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        kalshi._write_book({Sport.FOOTBALL}, "key", object(), str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_write_book_renames_on_success(tmp_path):
    def fake_book(_s, _k, _p, out):
        out({"ticker": "T-1"})
        return 1

    with patch("fetch.kalshi.fetch_book", side_effect=fake_book):
        assert kalshi._write_book({Sport.FOOTBALL}, "key", object(), str(tmp_path)) == 1
    lines = (tmp_path / "kalshi_markets.jsonl").read_text().splitlines()
    assert [json.loads(line)["ticker"] for line in lines] == ["T-1"]


TEAM_FIRST_TD = {
    "KXNFLTEAMFIRSTTD": {
        "ticker": "KXNFLTEAMFIRSTTD",
        "tags": ["Football"],
        "product_metadata": {"scope": "Touchdowns"},
    }
}


def _team_first_td_market(player: str) -> dict:
    return _raw_market(
        f"T-{player}",
        title=f"{player}: 1st Chicago Touchdown",
        yes_sub_title=player,
        no_sub_title=player,
        strike_type="structured",
        custom_strike={"football_player": "p-id", "football_team": "t-id"},
    )


def test_team_first_td_events_pass_the_fetch_filter_and_reach_the_parser():
    """Kalshi's real shape: series scope "Touchdowns", event scope "First Chicago TD" (names the team)."""
    event = _event("KXNFLTEAMFIRSTTD", "First Chicago TD", [_team_first_td_market("D'Andre Swift")])
    rows = kalshi.event_rows(event, {**CATALOG, **TEAM_FIRST_TD}, {Sport.FOOTBALL}, {"E": MILESTONE})
    assert [r["ticker"] for r in rows] == ["T-D'Andre Swift"]
    assert (rows[0]["series_scope"], rows[0]["competition_scope"]) == ("Touchdowns", "First Chicago TD")
    market = parse_market_line(json.dumps(rows[0]))
    assert market is not None
    typed = scoped_market_type(market, KalshiConfig(sport=Sport.FOOTBALL))
    assert typed is not None and typed.value == "team_first_touchdown_scorer"


def test_the_fetch_filter_for_team_first_td_is_as_strict_as_the_parser():
    markets = [_team_first_td_market("D'Andre Swift")]
    catalog = {**CATALOG, **TEAM_FIRST_TD}
    assert kalshi.event_rows(_event("KXNFLTEAMFIRSTTD", "First Chicago TD", markets), catalog, {Sport.SOCCER}, {}) == []
    assert kalshi.event_rows(_event("KXNFLTEAMFIRSTTD", "Future", markets), catalog, {Sport.FOOTBALL}, {}) == []
    assert kalshi.event_rows(_event("KXNFLTEAMFIRSTTD", None, markets), catalog, {Sport.FOOTBALL}, {}) == []
    assert (
        kalshi.event_rows(_event("KXNFLTEAMFIRSTTD", "First Chicago Touchdown", markets), catalog, {Sport.FOOTBALL}, {})
        == []
    )
    wrong_series = {**CATALOG, "KXNFLGAME": {**CATALOG["KXNFLGAME"], "product_metadata": {"scope": "Game"}}}
    assert kalshi.event_rows(_event("KXNFLGAME", "First Chicago TD", markets), wrong_series, {Sport.FOOTBALL}, {}) == []

"""Explore -> Gap leaderboard: SQL shape, row resolution, ranking, filters (no BQ)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mappers.control_plane import console_gap_leaderboard_sql as lb_sql
from mappers.control_plane.console_gap_leaderboard import build_leaderboard, list_gap_leaderboard
from mappers.control_plane.console_gap_leaderboard_rows import (
    build_indexes,
    fix_link,
    fixture_kickoff,
    fixture_name,
    resolve_league,
)
from mappers.control_plane.console_gap_leaderboard_sql import (
    _UDX_FIXTURE,
    NON_SPORT_KALSHI_SERIES,
    UDX_LEAGUE_TOKENS,
    gap_leaderboard_sql,
)
from mappers.control_plane.http_console_gap_leaderboard import register_gap_leaderboard_routes
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.store import InMemoryStore

if TYPE_CHECKING:
    from mappers.control_plane.service import ProposalService


def _league(slug: str, exchanges: list[dict[str, Any]], sport: str = "hockey") -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=slug,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=exchanges,
    )


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    leagues = [
        _league("nhl", []),
        _league("ncaaf", [{"sportsbook": "dkex", "enabled": True, "source_league_id": "CFB"}], "football"),
        _league("mlb", [{"sportsbook": "polymarket_usa", "enabled": True, "source_league_id": "mlb"}], "baseball"),
        _league(
            "nfl",
            [{"sportsbook": "crypto.com", "enabled": True, "settings": {"league": "NFL"}}],
            "football",
        ),
    ]
    store.seed_rule_set(rule_set_id="S_gl", entities=[], leagues=leagues, market_rules=[], activate=True)
    return store


def _row(
    book: str, hint: str | None, fx: str | None, market: str | None, demand: int, legs: int, **kw: Any
) -> dict[str, Any]:
    level_fx = 1 if fx is None else 0
    level_mk = 1 if market is None else 0
    return {
        "book": book,
        "league_hint": hint,
        "fixture_key": fx,
        "market": market,
        "g_fixture": level_fx,
        "g_market": level_mk,
        "fixture_name": kw.get("name"),
        "start_at": kw.get("start"),
        "demand": demand,
        "legs": legs,
        "last_seen": None,
        "catalogue_total": kw.get("cat_total"),
        "catalogue_unmapped": kw.get("cat_unmapped"),
    }


def _rows() -> list[dict[str, Any]]:
    soon = datetime.now(UTC) + timedelta(hours=3)
    return [
        _row("kalshi", "", None, None, 120, 9),
        _row("kalshi", "KXNHLGAME", "30JAN15ANALA", None, 100, 4),
        _row("kalshi", "KXNHLGAME", "30JAN15ANALA", "KXNHLGAME", 100, 4),
        _row("kalshi", "KXNHLSPREAD", "30JAN15ANALA", None, 30, 5),
        _row("kalshi", "KXNHLSPREAD", "30JAN15ANALA", "KXNHLSPREAD", 30, 5),
        _row("polymarket_usa", "", None, None, 50, 2),
        _row("polymarket_usa", "mlb", "mlb-tb-phi-2026-09-25", None, 50, 2),
        _row("polymarket_usa", "mlb", "mlb-tb-phi-2026-09-25", "astatc yrfi", 50, 2),
        _row("crypto", None, None, None, 10, 3, cat_total=900, cat_unmapped=400),
        _row("crypto", "NFL", "NX.F.OPT.NFL-1-260927", None, 10, 3, name="A @ B", start=soon, cat_unmapped=400),
        _row("crypto", "NFL", "NX.F.OPT.NFL-1-260927", "Passing Yards", 10, 3, start=soon, cat_unmapped=300),
        _row("crypto", "NFL", "NX.F.OPT.NFL-1-260927", "Moneyline", 0, 0, start=soon, cat_unmapped=100),
    ]


def test_sql_rejects_unknown_window_and_formats_cleanly() -> None:
    with pytest.raises(ValueError):
        gap_leaderboard_sql(7)
    sql = gap_leaderboard_sql(24).format(project="p")
    assert "interval 24 hour" in sql and "interval 30 hour" in sql
    assert NON_SPORT_KALSHI_SERIES in sql
    assert "[0-9]{6}" in sql and "{project}" not in sql


def test_sql_reads_each_venue_where_it_reports_the_miss() -> None:
    sql = gap_leaderboard_sql(6).format(project="p")
    assert "__" not in sql.replace("__TABLES__", "")
    # DraftKings: the venue's platform name, skipped + MAPPING_FAILED, ticker AND side.
    assert "r.platform in ('draftkings', 'draftkings-inplay') then 'dkex'" in sql
    assert "r.status = 'skipped'\n    and r.reason = 'MAPPING_FAILED'" in sql
    assert "concat('dkex|F|', market_ticker, '|', side)" in sql
    # Underdog: no-mmmapper-row legs, plus UNMAPPED tickers from metadata.
    assert "r.reason = 'UNMAPPED_OPTIC'" in sql
    assert "json_value_array(r.metadata, '$.unmapped')" in sql
    assert "concat('underdog|M|', market_ticker)" in sql
    # SX: Optic's selection_id names the maker's outcome.
    assert "concat('sx bet|S|', market_hash, '|', if(sx_outcome_one = 'true', 'two', 'one'))" in sql
    assert "'dkex', 'underdog', 'sx bet')" in sql


def test_udx_ticker_grouping_regexes() -> None:
    """The SQL regexes, run here with ``re`` (same semantics as BigQuery RE2 for these)."""
    fixture = re.compile(_UDX_FIXTURE.replace("{{", "{").replace("}}", "}"))
    league = re.compile(rf"^UDX({UDX_LEAGUE_TOKENS})")
    ticker = "UDXNFLRUSHYDS_CHIATL26OCT181300BIJANROBINSO_149.5"
    m = fixture.match(ticker.split("_")[1])
    assert m is not None and m.group(1) == "CHIATL26OCT18"
    m = fixture.match("CHIATL26OCT18DANSWIFT")
    assert m is not None and m.group(1) == "CHIATL26OCT18"
    assert (league.match(ticker) or [None, None])[1] == "NFL"
    # Longest token wins: ATPCHL is not ATP.
    assert (league.match("UDXATPCHLMATCHWIN_X") or [None, None])[1] == "ATPCHL"


def test_new_venues_resolve_league_kickoff_name_and_fix() -> None:
    idx = build_indexes(_store())
    dk = resolve_league("dkex", "CFB", idx)
    assert (dk["tip_league"], dk["sport"], dk["in_tip"]) == ("ncaaf", "football", True)
    assert resolve_league("dkex", "LALIGA", idx)["in_tip"] is False
    ud = resolve_league("underdog", "NFL", idx)
    assert (ud["tip_league"], ud["sport"], ud["in_tip"]) == ("nfl", "football", True)
    start, date_only = fixture_kickoff("underdog", {"fixture_key": "CHIATL26OCT18"})
    assert start is not None and start.date().isoformat() == "2026-10-18" and date_only
    assert fixture_kickoff("dkex", {"fixture_key": "01O0FOA9VSSH3VO"}) == (None, False)
    assert fixture_name("dkex", {"fixture_key": "01O0FOA9VSSH3VO"}) == "DraftKings event 01O0FOA9VSSH3VO"
    assert fixture_name("sxbet", {"fixture_key": "0x49326133" + "a" * 54}) == "SX market 0x49326133"
    assert fix_link("sxbet", "0xabc", None) == "/unmapped?platform=sxbet&q=0xabc&phase=pre"
    # No console page inventories Underdog or DraftKings legs yet.
    assert fix_link("underdog", "CHIATL26OCT18", 3.0) is None
    assert fix_link("dkex", "01O0FOA9VSSH3VO", 3.0) is None


def test_new_venues_get_platform_tiles() -> None:
    rows = [
        _row("dkex", "", None, None, 40, 6),
        _row("dkex", "CFB", "01O0FOA9VSSH3VO", None, 40, 6),
        _row("dkex", "CFB", "01O0FOA9VSSH3VO", "PPAY-FG", 40, 6),
        _row("underdog", "", None, None, 20, 2),
        _row("underdog", "NFL", "CHIATL26OCT18", None, 20, 2),
        _row("underdog", "NFL", "CHIATL26OCT18", "NFLTD", 20, 2),
        _row("sxbet", "", None, None, 1, 1),
        _row("sxbet", "", "0xabc", None, 1, 1),
        _row("sxbet", "", "0xabc", "", 1, 1),
    ]
    out = build_leaderboard(rows, _store())
    assert [(p["id"], p["label"], p["demand"]) for p in out["platforms"]] == [
        ("dkex", "DraftKings Exchange", 40),
        ("underdog", "Underdog", 20),
        ("sxbet", "SX Bet", 1),
    ]
    assert out["platforms"][0]["leagues"][0]["tip_league"] == "ncaaf"
    assert out["platforms"][1]["leagues"][0]["fixtures"][0]["kickoff_date_only"] is True


def test_platforms_ranked_by_demand_with_exact_sql_counts() -> None:
    out = build_leaderboard(_rows(), _store())
    assert [p["id"] for p in out["platforms"]] == ["kalshi", "polymarket_usa", "crypto"]
    kalshi = out["platforms"][0]
    # Platform demand is the SQL distinct count (120), not the fixture sum (130).
    assert (kalshi["demand"], kalshi["demand_is_sum"]) == (120, False)
    assert out["platforms"][2]["unmapped"] == 400


def test_kalshi_series_stay_unresolved_per_series() -> None:
    """The tip carries no Kalshi series, so each series stays its own off-tip group."""
    out = build_leaderboard(_rows(), _store())
    leagues = out["platforms"][0]["leagues"]
    assert [(lg["key"], lg["tip_league"]) for lg in leagues] == [
        ("kalshi:~KXNHLGAME", None),
        ("kalshi:~KXNHLSPREAD", None),
    ]
    assert [lg["demand"] for lg in leagues] == [100, 30]


def test_sort_by_unmapped_uses_catalogue_for_crypto() -> None:
    out = build_leaderboard(_rows(), _store(), sort="unmapped")
    assert out["platforms"][0]["id"] == "crypto"
    markets = out["platforms"][0]["leagues"][0]["fixtures"][0]["markets"]
    assert [m["market"] for m in markets] == ["Passing Yards", "Moneyline"]


def test_market_filter_sums_picked_markets_and_flags_it() -> None:
    out = build_leaderboard(_rows(), _store(), markets=["passing yards"])
    # Re-ranked on the picked market only: crypto is the only venue with demand left.
    assert out["platforms"][0]["id"] == "crypto"
    crypto = next(p for p in out["platforms"] if p["id"] == "crypto")
    fx = crypto["leagues"][0]["fixtures"][0]
    assert (fx["unmapped"], fx["demand_is_sum"]) == (300, True)
    assert crypto["demand_is_sum"] is True
    assert next(p for p in out["platforms"] if p["id"] == "kalshi")["leagues"] == []
    # The facet ignores its own pick.
    assert {o["name"] for o in out["market_options"]} >= {"Passing Yards", "Moneyline", "KXNHLGAME"}


def test_window_and_platform_filters() -> None:
    now = datetime.now(UTC)
    out = build_leaderboard(_rows(), _store(), kickoff_from=now, kickoff_to=now + timedelta(hours=6))
    kept = {p["id"]: sum(len(lg["fixtures"]) for lg in p["leagues"]) for p in out["platforms"]}
    assert kept == {"kalshi": 0, "polymarket_usa": 0, "crypto": 1}
    only = build_leaderboard(_rows(), _store(), platforms=["polymarket_usa"])
    assert [p["id"] for p in only["platforms"]] == ["polymarket_usa"]
    assert only["platforms"][0]["leagues"][0]["tip_league"] == "mlb"


def test_resolution_helpers() -> None:
    idx = build_indexes(_store())
    assert resolve_league("crypto", "NFL", idx)["tip_league"] == "nfl"
    miss = resolve_league("novig", "", idx)
    assert (miss["in_tip"], miss["label"]) == (False, "(unresolved)")
    start, date_only = fixture_kickoff("polymarket_usa", {"fixture_key": "mlb-tb-phi-2026-09-25"})
    assert start is not None and start.date().isoformat() == "2026-09-25" and date_only
    assert fix_link("px", "10765", 3.0) is None
    assert fix_link("crypto", "NX.F.OPT.NFL-1", -1.0, "Moneyline") == (
        "/venue-gaps?q=NX.F.OPT.NFL-1&phase=live&market=Moneyline"
    )


def test_list_errors_are_surfaced_not_raised() -> None:
    bad = list_gap_leaderboard(hours=5, query_fn=lambda _s, _p: _rows())
    assert "window" in (bad["error"] or "")
    bound = list_gap_leaderboard(kickoff_from="tomorrow", query_fn=lambda _s, _p: _rows())
    assert "kickoff_from" in (bound["error"] or "")

    def boom(_sql: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("bq down")

    assert list_gap_leaderboard(query_fn=boom)["error"] == "bq down"


def test_route_forwards_repeated_params(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("mappers.control_plane.http_console_gap_leaderboard.list_gap_leaderboard", fake)
    app = FastAPI()
    register_gap_leaderboard_routes(app, service=lambda: cast("ProposalService", object()), call=lambda fn: fn())
    res = TestClient(app).get(
        "/console/gap-leaderboard",
        params=[("platform", "kalshi"), ("platform", "crypto"), ("market", "Moneyline"), ("hours", "6")],
    )
    assert res.status_code == 200
    assert seen["platforms"] == ["kalshi", "crypto"]
    assert seen["markets"] == ["Moneyline"]
    assert seen["hours"] == 6


def test_leaderboard_query_memoises_for_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(lb_sql, "run_venue_gap_query", lambda sql, _p: calls.append(sql) or [])
    lb_sql.clear_leaderboard_cache()
    assert lb_sql.LEADERBOARD_CACHE_TTL_SECONDS == 3600.0
    assert lb_sql.leaderboard_cached_at("q1") is None
    lb_sql.leaderboard_query("q1", {})
    lb_sql.leaderboard_query("q1", {})
    lb_sql.leaderboard_query("q24", {})
    assert calls == ["q1", "q24"]
    assert lb_sql.leaderboard_cached_at("q1") is not None
    lb_sql.clear_leaderboard_cache()
    assert lb_sql.leaderboard_cached_at("q1") is None

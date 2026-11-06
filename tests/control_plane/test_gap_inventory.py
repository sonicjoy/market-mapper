"""RFQ inventory ranking + tip Polymarket prefixes (Kalshi is never harvested)."""

from __future__ import annotations

from datetime import date
from typing import Any

from mappers.control_plane.gap_inventory import (
    CLOSE_MAX_DAYS,
    MAX_EVENTS,
    RfqGapItem,
    _is_close,
    _kickoff_date,
    diversify_probe_items,
    drop_dead_buckets,
    fetch_rfq_inventory,
    note_unproductive,
    poly_skip_reason,
    rank_rfq_gaps,
    series_bucket,
    tip_poly_prefixes,
    tip_poly_us_prefixes,
)
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL
from mappers.control_plane.rows import LeagueRow
from tests.control_plane.gap_store_helpers import _soccer_store, _store


def test_rank_keeps_every_harvest_book() -> None:
    rows = [
        ("kalshi", "KXNFLGAME-1", 1),
        ("crypto", "NX.F.OPT.NFL-1", 1),
        ("polymarket", "nfl", 1),
        ("novig", "uuid-1", 1),
        ("prophetx", "evt:line", 1),
        ("underdog", "UDXNFLGAMEWIN_X_Y", 1),
        ("dkex", "NFL-ML-FG-ABC", 1),
        ("huddle", "selection-1", 1),
        ("some_new_book", "x", 1),
    ]
    ranked = rank_rfq_gaps(rows, limit=MAX_EVENTS)
    assert {r.book for r in ranked} == {
        "crypto", "polymarket", "novig", "prophetx", "underdog", "dkex", "huddle",
    }


def test_rank_caps_at_max_events() -> None:
    rows = [("polymarket", f"pfx{i}", i) for i in range(MAX_EVENTS + 10)]
    ranked = rank_rfq_gaps(rows, limit=MAX_EVENTS)
    assert len(ranked) == MAX_EVENTS
    assert ranked[0].demand == MAX_EVENTS + 9


def test_rank_close_first_high_demand_inside_window() -> None:
    """All close games before far demanding; inside 3 days, high demand first."""
    today = date(2026, 9, 1)
    rows = [
        ("crypto", "NX.F.OPT.TENNIS-0001-260903-M.O.1.1", 9_000),
        ("crypto", "NX.F.OPT.TENNIS-0027-260901-M.O.1.2", 50),
        ("crypto", "NX.F.OPT.TENNIS-0002-260831-M.O.1.1", 7_000),
    ]
    ranked = rank_rfq_gaps(rows, limit=MAX_EVENTS, today=today)
    crypto = [item.key for item in ranked if item.book == "crypto"]
    # close 9k then close 50, then past demanding 7k
    assert crypto == [
        "NX.F.OPT.TENNIS-0001-260903-M.O.1.1",
        "NX.F.OPT.TENNIS-0027-260901-M.O.1.2",
        "NX.F.OPT.TENNIS-0002-260831-M.O.1.1",
    ]


def test_close_window_is_three_days() -> None:
    assert CLOSE_MAX_DAYS == 3
    today = date(2026, 9, 1)
    on_window = _kickoff_date("crypto", "NX.F.OPT.UFC-00013-260904-M.O.1.1")
    off_window = _kickoff_date("crypto", "NX.F.OPT.UFC-00013-260905-M.O.1.1")
    assert _is_close(on_window, today) is True
    assert _is_close(off_window, today) is False


def test_close_low_demand_beats_far_demanding() -> None:
    today = date(2026, 9, 1)
    ranked = rank_rfq_gaps(
        [
            ("crypto", "NX.F.OPT.TENNIS-0001-260908-M.O.1.1", 8_000),
            ("crypto", "NX.F.OPT.TENNIS-0002-260831-M.O.1.1", 8_000),
            ("crypto", "NX.F.OPT.TENNIS-0003-260901-M.O.1.1", 100),
        ],
        limit=MAX_EVENTS,
        today=today,
    )
    assert [item.key for item in ranked] == [
        "NX.F.OPT.TENNIS-0003-260901-M.O.1.1",
        "NX.F.OPT.TENNIS-0001-260908-M.O.1.1",
        "NX.F.OPT.TENNIS-0002-260831-M.O.1.1",
    ]


def test_poly_never_crowds_out_probe_books() -> None:
    """Poly demand is per slug_prefix; it keeps its own page, same size as other books."""
    rows: list[tuple[str, str, int]] = [
        ("polymarket", f"pfx{i}", 100_000 - i) for i in range(80)
    ]
    rows += [("crypto", f"NX.F.OPT.FIFA-{i}", 5) for i in range(MAX_EVENTS)]
    ranked = rank_rfq_gaps(rows, limit=MAX_EVENTS)
    crypto = [r for r in ranked if r.book == "crypto"]
    poly = [r for r in ranked if r.book == "polymarket"]
    assert len(crypto) == MAX_EVENTS
    assert len(poly) == 80
    assert poly[0].key == "pfx0"


def test_fetch_rfq_inventory_renders_sql_and_splits_books() -> None:
    captured: list[str] = []

    class _Row:
        def __init__(self, book: str, key: str, demand: int) -> None:
            self.book = book
            self.key = key
            self.demand = demand

    def query_fn(sql: str) -> list[_Row]:
        captured.append(sql)
        return [
            _Row("polymarket", "efl", 152_000),
            _Row("kalshi", "KXLALIGAGAME-26AUG25VCFRBB", 12),
        ]

    items = fetch_rfq_inventory(
        _soccer_store(), project="marketmaking-test", query_fn=query_fn,
    )
    sql = captured[0]
    assert "{project}" not in sql
    assert "{limit}" not in sql
    assert "{poly_limit}" not in sql
    assert "{per_bucket}" not in sql
    assert "{close_days}" not in sql
    assert "current_date('UTC')" in sql
    assert "union distinct" in sql
    assert "kalshi_probe" in sql
    assert "crypto_probe" in sql
    assert "UNMAPPED" in sql
    assert "probe_true" not in sql
    assert "`marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge`" in sql
    assert "'Polymarket (USA)'" in sql
    # Kalshi rows from the SQL are dropped: Kalshi is not a harvest book.
    assert [item.book for item in items] == ["polymarket"]
    assert "novig_probe" in sql
    assert "px_probe" in sql
    assert "cryptocom-inplay" in sql


def _poly_league(slug: str, prefix: str) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport="soccer",
        optic_league_id=f"optic_{slug}",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "polymarket",
                "enabled": True,
                "parser_profile": "polymarket_soccer_v1",
                "settings": {"slug_prefix": prefix},
            }
        ],
    )


def test_tip_poly_prefixes() -> None:
    store = _store([], [_poly_league("efl_cup", "efl"), _poly_league("korea_k1", "kor")])
    assert tip_poly_prefixes(store) == frozenset({"efl", "kor"})


def test_tip_poly_us_prefixes() -> None:
    row = _poly_league("lec", "lec")
    row.exchanges.append(
        {
            "sportsbook": "polymarket_usa",
            "enabled": True,
            "parser_profile": "poly_usa_generic_v1",
            "source_league_id": "lgscup",
        },
    )
    store = _store([], [row])
    assert tip_poly_us_prefixes(store) == frozenset({"lgscup"})


def test_tip_poly_us_prefixes_skips_disabled_pin() -> None:
    row = _poly_league("lec", "lec")
    row.exchanges.append(
        {
            "sportsbook": "polymarket_usa",
            "enabled": False,
            "parser_profile": "poly_usa_generic_v1",
            "source_league_id": "lgscup",
        },
    )
    assert tip_poly_us_prefixes(_store([], [row])) == frozenset()


def test_series_bucket_crypto_sport_and_tour() -> None:
    assert series_bucket("polymarket", "efl") == "polymarket:OTHER"
    assert series_bucket("crypto", "NX.F.OPT.TENNIS-0001-260901-M.O.1.1") == "crypto:TENNIS"
    assert (
        series_bucket("crypto", "NX.F.OPT.TENNIS-0001-260901-M.O.1.1", meta="ATP")
        == "crypto:TENNIS:ATP"
    )
    assert (
        series_bucket("crypto", "NX.F.OPT.TENNIS-0001-260901-M.O.1.1", meta="WTA")
        == "crypto:TENNIS:WTA"
    )


def test_diversify_caps_one_series_then_keeps_other() -> None:
    tennis = [RfqGapItem("crypto", f"NX.F.OPT.TENNIS-{i}", 100 - i) for i in range(20)]
    fifa = [RfqGapItem("crypto", f"NX.F.OPT.FIFA-{i}", 50 - i) for i in range(4)]
    mixed = diversify_probe_items(tennis + fifa, probe_limit=8, per_bucket=3)
    tennis_kept = [item for item in mixed if "TENNIS" in item.key]
    fifa_kept = [item for item in mixed if "FIFA" in item.key]
    assert len(tennis_kept) == 5
    assert len(fifa_kept) == 3


def test_note_unproductive_skips_bucket_after_miss_streak() -> None:
    dead: set[str] = set()
    streaks: dict[str, int] = {}
    note_unproductive(dead, streaks, "crypto:TENNIS", "missing_optic")
    note_unproductive(dead, streaks, "crypto:TENNIS", "missing_optic")
    assert "crypto:TENNIS" not in dead
    note_unproductive(dead, streaks, "crypto:TENNIS", "missing_optic")
    assert "crypto:TENNIS" in dead
    keys = ["NX.F.OPT.TENNIS-1", "NX.F.OPT.FIFA-1"]
    live = drop_dead_buckets(keys, "crypto", dead)
    assert live == ["NX.F.OPT.FIFA-1"]


def test_poly_skip_reason() -> None:
    wired: frozenset[str] = frozenset({"kor", "bun"})
    wired_us: frozenset[str] = frozenset({"lgscup"})
    assert poly_skip_reason("efl", wired) == "needs_league_card"
    assert poly_skip_reason("kor", wired) == "wired_optic_or_stamp"
    assert poly_skip_reason("lgscup", wired, wired_us=wired_us) == "wired_optic_or_stamp"
    assert poly_skip_reason("(null)", wired) == "poly_null_prefix"
    assert poly_skip_reason("", wired) == "poly_null_prefix"


def test_rank_includes_prophetx_rfq_keys() -> None:
    rows = [
        ("prophetx", "ev:line", 99),
        ("polymarket", "efl", 10),
        ("crypto", "NX.F.OPT.FIFA-1", 5),
    ]
    ranked = rank_rfq_gaps(rows, limit=MAX_EVENTS)
    assert {item.book for item in ranked} == {"prophetx", "polymarket", "crypto"}
    assert ranked[-1].book == "prophetx"


def test_inventory_sql_includes_px_and_novig_probes() -> None:
    assert "px_probe" in RFQ_INVENTORY_SQL
    assert "novig_probe" in RFQ_INVENTORY_SQL
    assert "underdog_probe" in RFQ_INVENTORY_SQL
    assert "dkex_probe" in RFQ_INVENTORY_SQL
    assert "huddle_probe" in RFQ_INVENTORY_SQL
    assert "json_value_array(r.metadata, '$.unmapped')" in RFQ_INVENTORY_SQL
    assert "{px_limit}" not in RFQ_INVENTORY_SQL


def test_inventory_reads_draftkings_where_it_reports_the_miss() -> None:
    """DraftKings: ``draftkings`` platform, skipped + MAPPING_FAILED, ticker on the leg."""
    dk = RFQ_INVENTORY_SQL.split("dkex_syms as (", 1)[1].split("dkex_mapped as (", 1)[0]
    assert "r.platform in ('draftkings', 'draftkings-inplay')" in dk
    assert "r.status = 'skipped'" in dk and "r.reason = 'MAPPING_FAILED'" in dk
    assert "json_value(l.platform_mapping, '$.market_ticker')" in dk
    assert "metadata" not in dk


def test_inventory_sql_reads_crypto_quote_details() -> None:
    assert "quote_details" in RFQ_INVENTORY_SQL
    assert "no mapping for symbol" in RFQ_INVENTORY_SQL
    assert "COMBOS" in RFQ_INVENTORY_SQL
    assert "partition by symbol, coalesce(external_rfq_id, '')" in RFQ_INVENTORY_SQL


def test_poly_skip_disabled_exchange_ignored() -> None:
    row = _poly_league("efl_cup", "efl")
    disabled: dict[str, Any] = {
        **row.exchanges[0],
        "enabled": False,
    }
    store = _store(
        [],
        [
            LeagueRow(
                league=row.league,
                sport=row.sport,
                optic_league_id=row.optic_league_id,
                extra_optic_league_ids=[],
                fixture_source=row.fixture_source,
                fixture_horizon_hours=row.fixture_horizon_hours,
                enabled=True,
                output_order=[],
                exchanges=[disabled],
            )
        ],
    )
    assert tip_poly_prefixes(store) == frozenset()


def test_nhl_underdog_ticker_seats_on_the_tip_league() -> None:
    from mappers.control_plane.pipeline_gap_batch import league_resolver

    item = RfqGapItem("underdog", "UDXNHLTOTAL_BOSMIN26OCT032000_6.5", 12)
    store = _store([], [_nhl_underdog_league()])
    assert league_resolver(store)(item) == "nhl"


def _nhl_underdog_league() -> LeagueRow:
    return LeagueRow(
        league="nhl",
        sport="hockey",
        optic_league_id="nhl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "underdog",
                "enabled": True,
                "parser_profile": "underdog_generic_v1",
                "settings": {"league": "NHL"},
                "source_league_id": "NHL",
            },
        ],
    )



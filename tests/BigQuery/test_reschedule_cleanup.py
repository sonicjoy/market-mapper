"""Tests for RescheduleCleanup — pure logic, no BQ connection."""

from datetime import UTC, datetime
from types import SimpleNamespace

from BigQuery.load_mappings import (
    _DETECT_BY_POLY_TOKEN,
    INPLAY_SYMBOL_HOLD_HOURS,
    INPLAY_SYMBOL_PRESTART_MINUTES,
    RescheduleCleanup,
    _build_merge_sql,
    _not_optic_live,
    _optic_live_game_ids,
    _row_merge_key,
    _stale_crypto_symbol_delete_sql,
    _stale_crypto_symbol_detect_sql,
    _stale_orientation_delete_sql,
    _stale_started_delete_sql,
)


def _kalshi_doubles_row(ticker: str, selection_id: str, side: str) -> dict:
    """A synthetic ITF-doubles market_mapping row (no crypto symbol)."""
    return {
        "sport": "tennis",
        "league": "itf_men_doubles",
        "start_date": "2026-08-14T00:01:00Z",
        "home": "Bilardo / Cristian Dumitru",
        "away": "Ferrari / Valle",
        "market_type": "moneyline",
        "entity": None,
        "line": None,
        "side": side,
        "group_key": None,
        "sportsbook": "Kalshi",
        "source_ids": {"market_id": ticker, "selection_id": selection_id},
    }


def test_row_merge_key_distinguishes_twin_kalshi_side_tickers():
    """ticker A "yes" and ticker B "no" both resolve to the same canonical side;
    the Kalshi ticker+selection fallback keeps them as distinct merge keys."""
    a_yes = _kalshi_doubles_row(
        "KXITFDOUBLES-26AUG14BILCRIFERVAL-BILCRI", "yes",
        "Bilardo / Cristian Dumitru")
    b_no = _kalshi_doubles_row(
        "KXITFDOUBLES-26AUG14BILCRIFERVAL-FERVAL", "no",
        "Bilardo / Cristian Dumitru")
    assert _row_merge_key(a_yes) != _row_merge_key(b_no)


def test_row_merge_key_distinguishes_twin_underdog_gamewin_tickers():
    """2026-09-24 test load abort: UDX lists …_KAN yes and …_CWS no, both
    "KAN wins"; without the ticker in the key they collided and the whole
    market_mapping load (every sportsbook) stopped."""
    base = {
        "sport": "baseball", "league": "mlb",
        "start_date": "2026-09-24T18:10:00Z", "home": "KAN", "away": "CWS",
        "market_type": "moneyline", "entity": None, "line": None,
        "side": "KAN", "group_key": None, "sportsbook": "Underdog",
    }
    kan_yes = {**base, "source_ids": {
        "market_id": "UDXMLBGAMEWIN_CWSKAN26SEP241410_KAN", "selection_id": "yes"}}
    cws_no = {**base, "source_ids": {
        "market_id": "UDXMLBGAMEWIN_CWSKAN26SEP241410_CWS", "selection_id": "no"}}
    assert _row_merge_key(kan_yes) != _row_merge_key(cws_no)
    assert _row_merge_key(kan_yes)[-1] == "UDXMLBGAMEWIN_CWSKAN26SEP241410_KAN|yes"


def test_row_merge_key_books_match_source_identity_sql():
    """Every ticker-keyed book in the SQL identity is in the Python mirror."""
    from BigQuery.load_mappings import _TICKER_KEYED_BOOKS, _source_identity_sql
    sql = _source_identity_sql()
    for book in _TICKER_KEYED_BOOKS:
        assert f"sportsbook = '{book}'" in sql
    assert sql.count("sportsbook = '") == len(_TICKER_KEYED_BOOKS)


def test_row_merge_key_crypto_symbol_still_primary():
    """A crypto row's identity is its FIX Symbol, not the Kalshi fallback."""
    row = {"sportsbook": "crypto.com",
           "source_ids": {"symbol": "M.O.1.2", "market_id": "ignored"}}
    assert _row_merge_key(row)[-1] == "M.O.1.2"


def test_row_merge_key_non_kalshi_identity_unchanged():
    """Optic-mapped rows keep NULL source identity (market_id not folded in)."""
    row = {"sportsbook": "FanDuel",
           "source_ids": {"market_id": "abc", "selection_id": "def"}}
    assert _row_merge_key(row)[-1] is None


def _row(old_game_id, old_start, new_start, stale_rows, new_game_id=None):
    """Build a fake detection-query result row."""
    ns = SimpleNamespace(
        old_game_id=old_game_id,
        old_start_date=datetime.fromisoformat(old_start).replace(
            tzinfo=UTC),
        new_start_date=datetime.fromisoformat(new_start).replace(
            tzinfo=UTC),
        stale_rows=stale_rows,
    )
    if new_game_id is not None:
        ns.new_game_id = new_game_id
    return ns


def test_empty():
    cleanup = RescheduleCleanup([])
    assert cleanup.delete_sql is None
    assert cleanup.total == 0
    assert cleanup.game_count == 0
    assert cleanup.report == []


def test_single_reschedule():
    rows = [_row("21072-22202-2026-03-17",
                  "2026-03-17T11:00:00", "2026-03-18T01:15:00", 38)]
    cleanup = RescheduleCleanup(rows)

    assert cleanup.total == 38
    assert cleanup.game_count == 1
    assert len(cleanup.report) == 1
    assert "21072-22202-2026-03-17" in cleanup.report[0]

    assert cleanup.delete_sql is not None
    assert "DELETE FROM" in cleanup.delete_sql
    assert "21072-22202-2026-03-17" in cleanup.delete_sql
    assert "2026-03-17" in cleanup.delete_sql
    # New time should NOT appear in the delete — we're deleting the old rows.
    assert "2026-03-18T01:15:00" not in cleanup.delete_sql


def test_multiple_games():
    rows = [
        _row("18275-13323-2026-03-14",
             "2026-03-14T22:00:00", "2026-03-14T22:10:00", 83),
        _row("21072-22202-2026-03-17",
             "2026-03-17T11:00:00", "2026-03-18T01:15:00", 38),
    ]
    cleanup = RescheduleCleanup(rows)

    assert cleanup.total == 121
    assert cleanup.game_count == 2
    assert len(cleanup.report) == 2

    assert cleanup.delete_sql is not None
    assert "18275-13323-2026-03-14" in cleanup.delete_sql
    assert "21072-22202-2026-03-17" in cleanup.delete_sql


def test_same_game_multiple_old_times():
    """A game rescheduled twice — two stale start_dates for one game_id."""
    rows = [
        _row("21072-22202-2026-03-17",
             "2026-03-17T04:00:00", "2026-03-18T01:15:00", 10),
        _row("21072-22202-2026-03-17",
             "2026-03-17T11:00:00", "2026-03-18T01:15:00", 28),
    ]
    cleanup = RescheduleCleanup(rows)

    assert cleanup.total == 38
    assert cleanup.game_count == 1
    assert len(cleanup.report) == 2

    assert cleanup.delete_sql is not None
    assert "2026-03-17T04:00:00" in cleanup.delete_sql
    assert "2026-03-17T11:00:00" in cleanup.delete_sql


def test_cross_date_reschedule():
    """Game_id changed (cross-midnight reschedule detected via Kalshi ticker)."""
    rows = [_row("21072-22202-2026-03-16",
                  "2026-03-17T11:00:00", "2026-03-18T01:15:00", 38,
                  new_game_id="21072-22202-2026-03-17")]
    cleanup = RescheduleCleanup(rows)

    assert cleanup.total == 38
    assert cleanup.game_count == 1
    assert len(cleanup.report) == 1
    # Report should mention the game_id change.
    assert "21072-22202-2026-03-16" in cleanup.report[0]
    assert "21072-22202-2026-03-17" in cleanup.report[0]
    assert "game_id changed" in cleanup.report[0]

    # Delete targets the OLD game_id, not the new one.
    assert cleanup.delete_sql is not None
    assert "21072-22202-2026-03-16" in cleanup.delete_sql
    assert "21072-22202-2026-03-17" not in cleanup.delete_sql


def test_detect_by_poly_token_joins_on_clob_token_not_kalshi_ticker():
    """Pass 3 reaches the rows passes 1 and 2 cannot: optic re-issued the
    fixture under a new id (esports roster rename -> new team -> new
    game_id) and the book has no Kalshi ticker to join on."""
    sql = _DETECT_BY_POLY_TOKEN.format(
        cutoff="2026-06-22", live_pred=_not_optic_live("s", set()))
    # Identity is the clob token alone — Polymarket source_ids carry no
    # market_id, so folding one in (as the Kalshi pass does) would make
    # the join match nothing.
    assert ("STRING(t.source_ids.selection_id) = "
            "STRING(s.source_ids.selection_id)") in sql
    assert "source_ids.market_id" not in sql
    # Polymarket only, and never Kalshi's rows.
    # US selection_id is the venue side, shared across games: never a join key.
    assert "t.sportsbook = 'Polymarket'" in sql
    assert "Polymarket (USA)" not in sql
    assert "'Kalshi'" not in sql
    # Per-book join: the US-restricted catalogue must not reap the main
    # book's rows off its own staged evidence.
    assert "t.sportsbook = s.sportsbook" in sql
    # A game_id change is the whole point of this pass, so it must be
    # detected alongside a plain time shift.
    assert "t.game_id != s.game_id" in sql
    assert "t.start_date != s.start_date" in sql
    assert "TIMESTAMP('2026-06-22')" in sql
    # Live fixtures stay insert-only, as in passes 1 and 2.
    assert _not_optic_live("s", set()) in sql


def test_detect_by_poly_token_excludes_optic_live_games():
    sql = _DETECT_BY_POLY_TOKEN.format(
        cutoff="2026-06-22",
        live_pred=_not_optic_live("s", {"13008-25460-2026-08-23-01"}))
    assert "s.game_id NOT IN ('13008-25460-2026-08-23-01')" in sql


def test_poly_token_reschedule_row_deletes_only_the_stale_fixture():
    """The 2026-08-21 prod case: one clob token on EACE v SNG and
    EACE v ESA3, both @08-23 08:00.  The staged fixture is truth, so the
    delete targets the superseded game_id and leaves the new one."""
    stale = SimpleNamespace(
        old_game_id="13008-24566-2026-08-23-01",
        new_game_id="13008-25460-2026-08-23-01",
        old_start_date=datetime(2026, 8, 23, 8, 0, tzinfo=UTC),
        new_start_date=datetime(2026, 8, 23, 8, 0, tzinfo=UTC),
        stale_rows=3,
    )
    cleanup = RescheduleCleanup([stale])
    assert cleanup.delete_sql is not None
    assert "13008-24566-2026-08-23-01" in cleanup.delete_sql
    assert "13008-25460-2026-08-23-01" not in cleanup.delete_sql
    # A re-issued fixture keeps its start time, so the report must name the
    # game_id change — otherwise the log reads as a no-op reschedule.
    assert any("game_id changed" in line for line in cleanup.report)


def test_stale_started_delete_sql_empty_leagues():
    assert _stale_started_delete_sql("2026-05-01", []) is None


def test_stale_started_delete_sql_partition_and_predicate():
    sql = _stale_started_delete_sql("2026-05-01", ["mlb", "nba"])
    assert sql is not None
    assert "DELETE FROM markets_us.market_mapping" in sql
    assert "DATE(start_date) >= DATE('2026-05-01')" in sql
    assert "INTERVAL 24 HOUR" in sql
    assert "'mlb'" in sql
    assert "'nba'" in sql


def test_stale_orientation_delete_sql_scopes_to_staged_fixtures():
    sql = _stale_orientation_delete_sql("'2026-07-30', '2026-07-31'")
    assert "DELETE FROM markets_us.market_mapping t" in sql
    assert "DATE(t.start_date) IN ('2026-07-30', '2026-07-31')" in sql
    assert "market_mapping_stage" in sql
    # EXISTS scopes to fixtures this batch refreshed; NOT EXISTS finds the
    # ones whose home/away no longer matches.
    assert "s.home = t.home" in sql
    assert "s.away = t.away" in sql
    assert "NOT EXISTS" in sql
    assert _not_optic_live("t", set()) in sql
    # Must not be sportsbook-scoped: a code change orphans every book's
    # rows for the fixture, not just the one that triggered it.
    assert "sportsbook" not in sql


def test_stale_crypto_symbol_delete_sql_scopes_to_staged_fixtures():
    sql = _stale_crypto_symbol_delete_sql("'2026-07-30', '2026-07-31'")
    assert "DELETE FROM markets_us.market_mapping t" in sql
    assert "sportsbook = 'crypto.com'" in sql
    assert "DATE(t.start_date) IN ('2026-07-30', '2026-07-31')" in sql
    assert _not_optic_live("t", set()) in sql
    assert "JSON_VALUE(s.source_ids, '$.symbol')" in sql
    assert "JSON_VALUE(t.source_ids, '$.symbol')" in sql
    assert "IS NOT DISTINCT FROM" in sql
    assert "market_mapping_stage" in sql
    assert "t.source_symbol" not in sql
    assert "s.source_symbol" not in sql


def test_stale_crypto_symbol_delete_sql_skips_optic_live_games():
    sql = _stale_crypto_symbol_delete_sql(
        "'2026-07-31'", {"68310-10747-2026-06-12"},
    )
    assert "t.game_id NOT IN ('68310-10747-2026-06-12')" in sql


def test_stale_crypto_symbol_delete_sql_holds_inplay_window():
    sql = _stale_crypto_symbol_delete_sql("'2026-09-26'")
    detect = _stale_crypto_symbol_detect_sql("'2026-09-26'")
    hold = (
        f"t.start_date NOT BETWEEN "
        f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {INPLAY_SYMBOL_HOLD_HOURS} HOUR) "
        f"AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), "
        f"INTERVAL {INPLAY_SYMBOL_PRESTART_MINUTES} MINUTE)"
    )
    assert hold in sql
    assert hold in detect
    assert INPLAY_SYMBOL_HOLD_HOURS == 4
    assert INPLAY_SYMBOL_PRESTART_MINUTES == 30


def test_merge_sql_keys_on_source_identity_not_column():
    sql = _build_merge_sql("'2026-07-31'")
    # Crypto symbol stays the primary source identity...
    assert "JSON_VALUE(t.source_ids, '$.symbol')" in sql
    assert "JSON_VALUE(s.source_ids, '$.symbol')" in sql
    assert "IS NOT DISTINCT FROM" in sql
    # ...with a Kalshi ticker+selection fallback for twin side-tickers.
    assert "IF(t.sportsbook = 'Kalshi'" in sql
    assert "JSON_VALUE(t.source_ids, '$.market_id')" in sql
    assert "JSON_VALUE(t.source_ids, '$.selection_id')" in sql
    assert "COALESCE(" in sql
    assert "t.source_symbol" not in sql
    assert "s.source_symbol" not in sql
    assert "source_symbol" not in sql.split("INSERT")[0]


def test_merge_sql_upserts_when_no_optic_live_games():
    sql = _build_merge_sql("'2026-07-31'")
    assert "WHEN MATCHED THEN UPDATE SET" in sql
    assert "WHEN MATCHED AND" not in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "CURRENT_TIMESTAMP()" not in sql


def test_merge_sql_insert_only_for_optic_live_games():
    sql = _build_merge_sql(
        "'2026-07-31'", live_game_ids={"g-live-1", "g-live-2"},
    )
    assert "WHEN MATCHED AND s.game_id NOT IN" in sql
    assert "'g-live-1'" in sql
    assert "'g-live-2'" in sql
    assert "WHEN MATCHED THEN UPDATE" not in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "WHEN NOT MATCHED BY SOURCE" not in sql
    assert "CURRENT_TIMESTAMP()" not in sql


def test_optic_live_game_ids_from_mapping_records():
    recs = [
        {"optic_is_live": True, "optic_odds": {"game_id": "g-live"}},
        {"optic_is_live": False, "optic_odds": {"game_id": "g-pre"}},
        {"optic_is_live": True, "optic_odds": None},
    ]
    assert _optic_live_game_ids(recs) == {"g-live"}

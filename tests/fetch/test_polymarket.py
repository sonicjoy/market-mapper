from fetch.polymarket import build_market_lines


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_build_market_lines_groups_by_condition_id():
    rows = [
        _Row(condition_id="0xA", slug="mlb-az-stl-2026-07-21", question="AZ vs. STL",
             clob_token_id="cA0", position_id="pA0", outcome_label="Arizona Diamondbacks", outcome_index=0),
        _Row(condition_id="0xA", slug="mlb-az-stl-2026-07-21", question="AZ vs. STL",
             clob_token_id="cA1", position_id="pA1", outcome_label="St. Louis Cardinals", outcome_index=1),
        _Row(condition_id="0xB", slug="mlb-bos-nyy-2026-07-21", question="BOS vs. NYY: O/U 8.5",
             clob_token_id="cB0", position_id="pB0", outcome_label="Over", outcome_index=0),
    ]
    out = build_market_lines(rows)
    by_cid = {m["condition_id"]: m for m in out}
    assert set(by_cid) == {"0xA", "0xB"}
    assert by_cid["0xA"]["question"] == "AZ vs. STL"
    assert len(by_cid["0xA"]["outcomes"]) == 2
    # outcomes ordered by outcome_index
    assert [o["outcome_index"] for o in by_cid["0xA"]["outcomes"]] == [0, 1]
    assert by_cid["0xA"]["outcomes"][0]["clob_token_id"] == "cA0"


def test_build_market_lines_sorts_out_of_order_outcomes():
    # Rows arrive with outcome_index 1 before 0 -- build_market_lines must
    # re-sort, not just preserve arrival order.
    rows = [
        _Row(condition_id="0xC", slug="mlb-lad-sf-2026-07-21", question="LAD vs. SF",
             clob_token_id="cC1", position_id="pC1", outcome_label="San Francisco Giants", outcome_index=1),
        _Row(condition_id="0xC", slug="mlb-lad-sf-2026-07-21", question="LAD vs. SF",
             clob_token_id="cC0", position_id="pC0", outcome_label="Los Angeles Dodgers", outcome_index=0),
    ]
    out = build_market_lines(rows)
    by_cid = {m["condition_id"]: m for m in out}
    assert [o["outcome_index"] for o in by_cid["0xC"]["outcomes"]] == [0, 1]
    assert by_cid["0xC"]["outcomes"][0]["clob_token_id"] == "cC0"
    assert by_cid["0xC"]["outcomes"][1]["clob_token_id"] == "cC1"


def test_build_market_lines_drops_null_condition_id():
    # A null condition_id must be dropped, not str()-ed into a bogus "None"
    # market that groups unrelated rows together.
    rows = [
        _Row(condition_id=None, slug="mlb-mystery-2026-07-21", question="AAA vs. BBB",
             clob_token_id="cN0", position_id="pN0", outcome_label="AAA", outcome_index=0),
        _Row(condition_id="0xD", slug="mlb-cle-min-2026-07-21", question="CLE vs. MIN",
             clob_token_id="cD0", position_id="pD0", outcome_label="Cleveland Guardians", outcome_index=0),
    ]
    out = build_market_lines(rows)
    by_cid = {m["condition_id"]: m for m in out}
    assert set(by_cid) == {"0xD"}
    assert "None" not in by_cid


# --- bridge window: keyed on the slug's fixture date, never on last_updated ---
#
# Regression guard for a silent, months-long coverage outage. The bridge loader
# deliberately never re-enriches an already-bridged condition_id, so a row's
# last_updated is "first discovered", not "still valid". This fetcher used to
# filter `last_updated >= now - 2 days`, which made every market invisible to
# the mapper 48h after discovery even with its fixture days away. Measured
# 2026-08-06: Leagues Cup, Conference League and MLS all fetched ZERO markets.


def test_bridge_window_never_keys_off_row_freshness():
    """The original guard: window on the GAME, never on when we discovered the row.

    The timestamp comparison is now against the market's own kickoff
    (`game_start_time`), so CURRENT_TIMESTAMP appears — but `last_updated` must
    still never gate the window.
    """
    from fetch.polymarket import bridge_window_sql

    sql = bridge_window_sql()
    assert "game_start_time" in sql, sql
    assert "slug" in sql and "PARSE_DATE" in sql, sql
    assert "last_updated" not in sql, sql


def test_bridge_window_fails_open_on_unclassifiable_row():
    """A row with neither an instant nor a parseable slug date must be KEPT."""
    from fetch.polymarket import bridge_window_sql

    sql = bridge_window_sql()
    assert "ELSE TRUE" in sql, sql


def test_bridge_window_case_is_tokenised():
    """Guard the concatenation itself: adjacent string literals silently glued
    'TRUE' to 'END' once ('ELSE TRUEEND'), which BigQuery rejected only at run time."""
    import re

    from fetch.polymarket import bridge_window_sql

    sql = bridge_window_sql()
    assert re.search(r"\bEND\b", sql), sql
    assert "TRUEEND" not in sql, sql
    assert sql.count("WHEN") == 2 and sql.count("THEN") == 2, sql


def test_bridge_window_drops_a_market_whose_game_is_over():
    """A settled market must not reach the matcher.

    Canonical rows key on the FIXTURE's start_date and carry no token, so a settled
    market that resolves onto the next game of the same matchup overwrites that game's
    own row — the live fixture then points at the settled market's token. Both gates
    have to close: the instant gate for enriched rows, and the slug-date gate for
    legacy NULL-instant rows (which is what mis-mapped on 2026-08-06, because Gamma
    will not re-enrich a closed market so its instant stays NULL).
    """
    from fetch.polymarket import STALE_AFTER_KICKOFF_HOURS, bridge_window_sql

    sql = bridge_window_sql()
    # enriched rows: kept only while the game could still be running
    assert STALE_AFTER_KICKOFF_HOURS <= 24, "must not outlive load_mappings' 24h cutoff"
    assert f"INTERVAL {STALE_AFTER_KICKOFF_HOURS} HOUR" in sql, sql
    # legacy rows: a past-dated slug can only be an already-played game
    assert ">= CURRENT_DATE()" in sql, sql


def test_bridge_query_never_filters_rows_by_recency():
    """last_updated may only order the QUALIFY dedup, never gate the WHERE."""
    from fetch.polymarket import bridge_query

    q = bridge_query("proj.raw_ingestion_us.polymarket_position_token_bridge")
    where = q.split("WHERE", 1)[1].split("QUALIFY", 1)[0]
    assert "last_updated" not in where, where
    # ...but the dedup still takes the newest row per token.
    assert "ORDER BY last_updated DESC" in q

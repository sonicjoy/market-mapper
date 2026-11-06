"""Release 068 G5 — shared oom winner query builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from BigQuery.oom_winner_query import build_rfq_key_lookup_sql, build_winner_query

_REPO = Path(__file__).resolve().parents[2]
_WINNER_SQL = _REPO / "BigQuery" / "sql" / "oom_winner_query.sql"
_MMUTILS_WINNER_SQL = (
    Path(__file__).resolve().parents[3]
    / "MMutils"
    / "handlers"
    / "sql"
    / "oom_winner_query.sql"
)


def test_winner_sql_matches_mmutils_template() -> None:
    assert _WINNER_SQL.is_file()
    if _MMUTILS_WINNER_SQL.is_file():
        assert _WINNER_SQL.read_text(encoding="utf-8") == _MMUTILS_WINNER_SQL.read_text(encoding="utf-8")


def test_build_winner_query_strips_header_and_substitutes() -> None:
    sql = build_winner_query("marketmaking-test", "kalshi")
    assert sql.lstrip().casefold().startswith("with ")
    assert "`marketmaking-test.opticodds_us.opticodds_mapping`" in sql
    assert "lower(o.sportsbook) = 'kalshi'" in sql
    assert "{project}" not in sql
    assert "{sportsbook_lower}" not in sql


def test_build_rfq_key_lookup_sql_is_parameterized() -> None:
    sql = build_rfq_key_lookup_sql("marketmaking-test")
    assert sql.lstrip().casefold().startswith("with ")
    assert "@sportsbook_lower" in sql
    assert "@src_market_id" in sql
    assert "@src_selection_id" in sql
    assert "lower(coalesce(json_value(o.source_ids, '$.market_id'), ''))" in sql.lower()
    assert "lower(coalesce(json_value(o.source_ids, '$.selection_id'), ''))" in sql.lower()
    assert "as in_rank_window" in sql
    assert "coalesce(" in sql.lower()


def test_build_rfq_key_lookup_sql_supports_recency_filter() -> None:
    sql = build_rfq_key_lookup_sql("marketmaking-test", min_last_updated_days=60)
    assert "interval 60 day" in sql
    assert "o.last_updated is null" in sql
    stale_sql = build_rfq_key_lookup_sql("marketmaking-test", min_last_updated_days=365)
    assert "interval 365 day" in stale_sql


def test_build_rfq_key_lookup_sql_exposes_rank_window_without_filtering() -> None:
    sql = build_rfq_key_lookup_sql("marketmaking-test")
    where_block = sql.lower().split(
        "from `marketmaking-test.opticodds_us.opticodds_mapping`", 1
    )[1]
    where_block = where_block.split(")\nselect", 1)[0]
    assert "start_date >=" not in where_block
    assert "start_date <=" not in where_block
    assert "last_updated >=" not in where_block
    assert "coalesce(" in sql.lower()


def test_build_winner_query_rejects_bad_project() -> None:
    with pytest.raises(ValueError, match="invalid project_id"):
        build_winner_query("bad project", "kalshi")

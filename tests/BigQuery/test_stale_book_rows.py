"""Stale Kalshi / Polymarket reaps that MERGE's pure upsert leaves behind."""

from __future__ import annotations

from types import SimpleNamespace

import BigQuery.stale_book_rows as reap
from BigQuery.load_mappings import KEY_COLUMNS, NULLABLE_KEYS, STAGE_TABLE, TABLE

_SAME_KEY = reap.same_key_sql(KEY_COLUMNS, NULLABLE_KEYS)


def test_same_key_matches_the_merge_key():
    assert "s.line IS NOT DISTINCT FROM t.line" in _SAME_KEY
    assert "s.entity IS NOT DISTINCT FROM t.entity" in _SAME_KEY
    assert "s.side = t.side" in _SAME_KEY
    assert "s.sportsbook = t.sportsbook" in _SAME_KEY
    assert _SAME_KEY.count(" AND ") == len(KEY_COLUMNS) - 1


def test_relabeled_kalshi_needs_ticker_staged_elsewhere_and_not_here():
    where = reap.relabeled_kalshi_where(STAGE_TABLE, "'2026-09-29'", _SAME_KEY)
    assert "DATE(t.start_date) IN ('2026-09-29')" in where
    assert "t.sportsbook = 'Kalshi'" in where
    exists, not_exists = where.split("AND NOT EXISTS")
    assert "JSON_VALUE(s.source_ids, '$.market_id')" in exists
    assert "JSON_VALUE(s.source_ids, '$.selection_id')" in exists
    assert _SAME_KEY not in exists
    assert _SAME_KEY in not_exists
    # Positive evidence (the ticker is staged under another line), so
    # Optic-live fixtures are not exempt.
    assert "NOT IN" not in where


def test_dropped_polymarket_is_scoped_to_staged_poly_fixtures():
    guard = "t.game_id NOT IN ('live-1') AND TRUE"
    where = reap.dropped_polymarket_where(STAGE_TABLE, "'2026-09-27'", _SAME_KEY, guard)
    assert guard in where
    assert "t.sportsbook = 'Polymarket'" in where
    exists, not_exists = where.split("AND NOT EXISTS")
    assert "s.game_id = t.game_id AND s.start_date = t.start_date" in exists
    assert _SAME_KEY in not_exists
    assert "s.sportsbook = 'Polymarket'" in not_exists


class _Client:
    def __init__(self, detect_rows):
        self.detect_rows = list(detect_rows)
        self.queries: list[str] = []

    def query(self, sql):
        self.queries.append(sql)
        rows = self.detect_rows.pop(0) if self.detect_rows else []
        return SimpleNamespace(result=lambda: rows)


def test_clean_deletes_only_when_detect_finds_rows(monkeypatch, capsys):
    deletes: list[str] = []
    monkeypatch.setattr(reap, "sandbox_query", lambda _c, sql: deletes.append(sql))
    nhl = SimpleNamespace(league="nhl", game_id="32620-69549-2026-09-29",
                          market_type="point_spread", n=4)
    client = _Client([[nhl], []])
    total = reap.clean_stale_book_rows(
        client, TABLE, STAGE_TABLE, "'2026-09-29'",
        same_key=_SAME_KEY, polymarket_guard="TRUE",
    )
    assert total == 4
    assert len(deletes) == 1
    assert deletes[0].startswith(f"DELETE FROM {TABLE} t WHERE")
    assert "t.sportsbook = 'Kalshi'" in deletes[0]
    out = capsys.readouterr().out
    assert "Deleted 4 stale relabeled Kalshi rows." in out
    assert "No stale Polymarket rows." in out


def test_relabeled_stx_is_reaped_like_kalshi_on_market_id_and_side():
    where = reap.relabeled_ticker_where(STAGE_TABLE, "'2026-10-29'", _SAME_KEY, "STX")
    assert "t.sportsbook = 'STX'" in where and "s.sportsbook = 'STX'" in where
    assert "JSON_VALUE(s.source_ids, '$.selection_id')" in where
    assert reap.relabeled_kalshi_where(STAGE_TABLE, "'d'", _SAME_KEY) == reap.relabeled_ticker_where(
        STAGE_TABLE, "'d'", _SAME_KEY, "Kalshi"
    )

"""Moved Polymarket (USA) tickers: only that book's rows on the old game go."""

from __future__ import annotations

from types import SimpleNamespace

from BigQuery import usa_ticker_moves as mv

T, S = "markets_us.market_mapping", "markets_us.market_mapping_stage"


def test_delete_is_scoped_to_the_us_book_and_ticker():
    sql = mv.moved_usa_ticker_delete_sql(T, S, "2026-07-27")
    assert sql.strip().startswith(f"DELETE FROM {T} t")
    assert "t.sportsbook = 'Polymarket (USA)'" in sql
    assert "s.game_id != t.game_id" in sql       # staged on another game
    assert "s.game_id = t.game_id" in sql        # ...and not still on this one
    assert "STRING(t.source_ids.market_id)" in sql
    assert "TIMESTAMP('2026-07-27')" in sql       # partition bound


def test_detect_and_delete_share_one_predicate():
    where = mv.moved_usa_ticker_where(T, S, "2026-07-27")
    assert where in mv.moved_usa_ticker_detect_sql(T, S, "2026-07-27")
    assert where in mv.moved_usa_ticker_delete_sql(T, S, "2026-07-27")


class _Client:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def query(self, sql, **_):
        self.sql.append(sql)
        return SimpleNamespace(result=lambda: self.rows)


def test_clean_skips_delete_when_nothing_moved(monkeypatch):
    calls = []
    monkeypatch.setattr(mv, "sandbox_query", lambda c, q: calls.append(q))
    assert mv.clean_moved_usa_tickers(_Client([]), T, S, "2026-07-27") == 0
    assert calls == []


def test_clean_deletes_and_counts(monkeypatch):
    calls = []
    monkeypatch.setattr(mv, "sandbox_query", lambda c, q: calls.append(q))
    rows = [SimpleNamespace(ticker="astatc-mlb-bal-nyy-2026-09-26-hr-x-gte1",
                            game_id="15260-54558-2026-09-25-16",
                            start_date="2026-09-25 23:25:00", n=112)]
    assert mv.clean_moved_usa_tickers(_Client(rows), T, S, "2026-07-27") == 112
    assert len(calls) == 1 and calls[0].strip().startswith("DELETE")

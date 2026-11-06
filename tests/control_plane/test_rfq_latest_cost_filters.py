"""rfq_latest readers stay partition-bounded and cluster-pruned (BigQuery cost)."""

from __future__ import annotations

import pytest

from mappers.control_plane import bq_ttl_cache
from mappers.control_plane.console_rfq_demand import _SQL as DEMAND_SQL
from mappers.control_plane.console_unmapped import _CONSOLE_UNMAPPED_SQL
from mappers.control_plane.crypto_rfq_symbols_sql import crypto_rfq_symbol_rows_sql
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL
from mappers.control_plane.rfq_latest_sql import recent_window, render_rfq_filters

_READERS = {
    "console_rfq_demand": DEMAND_SQL,
    "console_unmapped": _CONSOLE_UNMAPPED_SQL,
    "gap_inventory": RFQ_INVENTORY_SQL,
}

_BOUND = "first_publish_time > timestamp_sub(current_timestamp(), interval 6 hour)"


@pytest.mark.parametrize("name", sorted(_READERS))
def test_every_rfq_latest_read_is_bounded_and_pruned(name: str) -> None:
    sql = _READERS[name]
    assert "__RECENT_3H__" not in sql and "__UNMAPPED_FAILED__" not in sql
    assert "__KALSHI__" not in sql and "__POLY__" not in sql
    assert "48 hour" not in sql, "first_publish_time must follow the last_updated window"
    assert "like 'polymarket%'" not in sql, "platform like defeats clustering"
    reads = sql.count("reporting_us.rfq_latest")
    assert reads > 0
    assert sql.count(_BOUND) == reads, "every rfq_latest read needs the tight partition bound"
    # DraftKings mapping failures are ``skipped`` (rfq_latest_sql.dkex_mapping_failed).
    statuses = sql.count("r.status = 'failed'") + sql.count("r.status = 'skipped'")
    assert statuses == reads, "every read filters the clustered status"


def test_recent_window_adds_publish_lag() -> None:
    assert "interval 3 hour" in recent_window(3)
    assert _BOUND in recent_window(3)
    assert "interval 51 hour" in recent_window(48)


def test_render_fills_every_token() -> None:
    out = render_rfq_filters("__RECENT_3H__ __KALSHI__ __POLY__ __UNMAPPED_FAILED__")
    assert "__" not in out
    assert "r.status = 'failed'" in out
    assert "'polymarketus-inplay'" in out and "'kalshi-inplay'" in out


def test_crypto_symbol_rows_are_pruned() -> None:
    sql = crypto_rfq_symbol_rows_sql(hours=3)
    assert sql.count("r.status = 'failed'") == 3
    assert sql.count("r.platform in ('cryptocom', 'cryptocom-inplay')") == 3


def test_ttl_cache_memoises_and_clears() -> None:
    bq_ttl_cache.clear_ttl_cache()
    calls: list[int] = []

    def fetch() -> int:
        calls.append(1)
        return len(calls)

    assert bq_ttl_cache.ttl_cached("ns", "k", fetch) == 1
    assert bq_ttl_cache.ttl_cached("ns", "k", fetch) == 1
    assert bq_ttl_cache.ttl_cached("ns", "other", fetch) == 2
    bq_ttl_cache.clear_ttl_cache("ns")
    assert bq_ttl_cache.ttl_cached("ns", "k", fetch) == 3
    assert bq_ttl_cache.ttl_cached("ns", "k", fetch, ttl=0.0) == 4
    bq_ttl_cache.clear_ttl_cache()


def test_ttl_cache_never_caches_errors() -> None:
    bq_ttl_cache.clear_ttl_cache()

    def boom() -> int:
        raise RuntimeError("bq down")

    with pytest.raises(RuntimeError):
        bq_ttl_cache.ttl_cached("ns", "k", boom)
    assert bq_ttl_cache.ttl_cached("ns", "k", lambda: 7) == 7
    bq_ttl_cache.clear_ttl_cache()

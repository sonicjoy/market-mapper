"""Card-wide market_mapping read used by the harvest walk."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from mappers.control_plane.gap_mapping_batch import lookup_mappings_batch, mapping_batch_sql

_KX = "KXEPLGAME-26AUG25ARSCHE"
_KX_OTHER = "KXEPLGAME-26AUG25LIVMUN"
_NX = "NX.F.OPT.UFC-00011-260822-M.O.1.1.20260822"
_NX_BASE = "NX.F.OPT.UFC-00011-260822-M.O.1.1"


def test_sql_matches_every_source_field_and_event_prefix() -> None:
    sql = mapping_batch_sql("marketmaking-test")
    assert "markets_us.market_mapping" in sql
    assert "start_date > timestamp_sub" in sql
    for field in ("market_id", "symbol", "selection_id", "event_id"):
        assert f"'$.{field}') in unnest(@ids)" in sql
    assert "in unnest(@events)" in sql
    assert "exists" not in sql
    assert "__ROW_LIMIT__" not in sql


def test_one_query_groups_rows_back_to_each_key() -> None:
    calls: list[dict[str, list[str]]] = []

    def query_fn(_sql: str, params: dict[str, list[str]]) -> list[dict[str, Any]]:
        calls.append(params)
        return [
            {"market_ticker": f"{_KX}-ARS", "sportsbook": "Kalshi", "league": "epl", "side": "ARS"},
            {"symbol": _NX_BASE, "sportsbook": "crypto.com", "league": "ufc"},
            {"market_ticker": "KXNBAGAME-26AUG25LALBOS-LAL", "sportsbook": "Kalshi"},
        ]

    out = lookup_mappings_batch([_KX, _KX_OTHER, _NX, _KX], query_fn=query_fn)

    assert len(calls) == 1
    assert _KX in calls[0]["events"]
    assert _NX_BASE in calls[0]["ids"]
    assert [r["side"] for r in out[_KX]] == ["ARS"]
    assert out[_KX_OTHER] == []
    assert [r["league"] for r in out[_NX]] == ["ufc"]


def test_failed_read_logs_and_leaves_keys_unmapped(caplog: pytest.LogCaptureFixture) -> None:
    def query_fn(_sql: str, _params: dict[str, list[str]]) -> list[Any]:
        raise RuntimeError("bq down")

    with caplog.at_level(logging.WARNING, logger="mappers.control_plane.gap_mapping_batch"):
        out = lookup_mappings_batch([_KX], query_fn=query_fn)
    assert out == {_KX: []}
    assert "gap mapping batch read failed" in caplog.text


def test_empty_key_list_skips_the_query() -> None:
    def query_fn(_sql: str, _params: dict[str, list[str]]) -> list[Any]:
        raise AssertionError("should not query")

    assert lookup_mappings_batch(["", "  "], query_fn=query_fn) == {}

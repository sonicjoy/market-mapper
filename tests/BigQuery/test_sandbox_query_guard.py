"""Tests for the sandbox_query writable-dataset guard.

The guard scans SQL text for `dataset.table` references, so anything
dotted inside a string literal used to look like a dataset: the stale
crypto cleanup DELETE filters on `sportsbook = 'crypto.com'` and was
refused in production as touching dataset `crypto`.
"""

import pytest

from BigQuery.client import sandbox_query
from BigQuery.load_mappings import _stale_crypto_symbol_delete_sql
from BigQuery.usa_ticker_moves import moved_usa_ticker_delete_sql


class _FakeClient:
    """Records the SQL that reaches BigQuery."""

    def __init__(self):
        self.queries = []

    def query(self, sql, **kwargs):
        self.queries.append(sql)
        return self

    def result(self):
        return []


def test_stale_crypto_delete_passes_the_guard():
    client = _FakeClient()
    sandbox_query(client, _stale_crypto_symbol_delete_sql("'2026-07-31'"))
    assert len(client.queries) == 1


def test_dotted_string_literal_is_not_a_dataset():
    client = _FakeClient()
    sandbox_query(
        client,
        "DELETE FROM markets_us.market_mapping "
        "WHERE sportsbook = 'crypto.com' AND league = 'ncaa.fb'",
    )
    assert len(client.queries) == 1


def test_real_non_writable_dataset_is_still_refused():
    with pytest.raises(ValueError, match="non-writable datasets: raw_ingestion_us"):
        sandbox_query(_FakeClient(), "DELETE FROM raw_ingestion_us.foo WHERE x = 1")


def test_usa_ticker_struct_path_passes_the_guard():
    """t.source_ids.market_id is a STRUCT field, not dataset source_ids."""
    client = _FakeClient()
    sandbox_query(
        client,
        moved_usa_ticker_delete_sql(
            "markets_us.market_mapping",
            "markets_us.market_mapping_stage",
            "2026-07-27",
        ),
    )
    assert len(client.queries) == 1


def test_project_qualified_source_ids_is_still_refused():
    with pytest.raises(ValueError, match="non-writable datasets: source_ids"):
        sandbox_query(
            _FakeClient(),
            "DELETE FROM `rs-marketmaking.source_ids.foo` WHERE x = 1",
        )


def test_bare_source_ids_dataset_is_still_refused():
    with pytest.raises(ValueError, match="non-writable datasets: source_ids"):
        sandbox_query(_FakeClient(), "DELETE FROM source_ids.foo WHERE x = 1")

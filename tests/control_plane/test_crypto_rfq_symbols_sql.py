"""Crypto RFQ symbol SQL reads quote_details, not only reason_detail."""

from __future__ import annotations

from mappers.control_plane.crypto_rfq_symbols_sql import (
    crypto_rfq_mf_cte,
    crypto_rfq_symbol_rows_sql,
)
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL


def test_inventory_sql_reads_quote_details() -> None:
    assert "quote_details" in RFQ_INVENTORY_SQL
    assert "no mapping for symbol" in RFQ_INVENTORY_SQL
    assert "COMBOS" in RFQ_INVENTORY_SQL


def test_crypto_mf_cte_includes_legacy_and_structured_paths() -> None:
    body = crypto_rfq_mf_cte(hours=3)
    assert "crypto_mf as (" in body
    assert "quote_details" in body
    assert "platform_mapping" in body
    assert "partition by symbol, coalesce(external_rfq_id, '')" in body
    assert body.rstrip().endswith(",")


def test_inventory_sql_chains_crypto_mf_into_mapped() -> None:
    assert "crypto_mf as (" in RFQ_INVENTORY_SQL
    assert "),\n\ncrypto_mapped" in RFQ_INVENTORY_SQL or "),\ncrypto_mapped" in RFQ_INVENTORY_SQL


def test_symbol_rows_sql_has_three_sources() -> None:
    sql = crypto_rfq_symbol_rows_sql(hours=1)
    assert "union all" in sql.lower()
    assert sql.count("union all") >= 2


def test_symbol_rows_sql_includes_cryptocom_inplay() -> None:
    sql = crypto_rfq_symbol_rows_sql(hours=1)
    assert "cryptocom-inplay" in sql

"""Underdog catalogue snapshots -> raw_ingestion_us.underdog_fetch_raw (never auto-created)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, cast

from google.cloud import bigquery

from BigQuery import load_exchange_fetch as lef
from BigQuery.exchange_fetch_extract import underdog_keys
from BigQuery.exchange_fetch_tables import LOAD_SCHEMAS, TABLES
from tests.BigQuery.test_sxbet_fetch_raw import _Client

ROW = {
    "ticker": "UDXMLSTEAMTOTAL_ATLNYC26OCT28_ATL0.5",
    "event_ticker": "UDXMLSTEAMTOTAL_ATLNYC26OCT28",
    "series_ticker": "UDXMLSTEAMTOTAL",
    "external_ids": {"optic_odds": {"fixture_id": "202610288B09321E", "market_id": "team_total"}},
}


def test_underdog_keys() -> None:
    assert underdog_keys(json.dumps(ROW)) == (
        "UDXMLSTEAMTOTAL",
        "UDXMLSTEAMTOTAL_ATLNYC26OCT28",
        "UDXMLSTEAMTOTAL_ATLNYC26OCT28_ATL0.5",
    )
    assert underdog_keys("not json") == (None, None, None)
    assert underdog_keys("{}") == (None, None, None)


def test_wrap_and_schema_agree() -> None:
    buf = io.BytesIO()
    lef._wrap_underdog(buf, json.dumps(ROW), "2026-10-28T12:00", "2026-10-28T12:00:00Z")
    row = json.loads(buf.getvalue())
    assert set(row) == {f.name for f in LOAD_SCHEMAS["underdog"]}
    assert json.loads(row["data"]) == ROW  # verbatim: the gate replays this line
    assert TABLES["underdog"] == "raw_ingestion_us.underdog_fetch_raw"


def test_the_underdog_file_is_picked_up(tmp_path: Path) -> None:
    (tmp_path / "underdog_markets.jsonl").write_text(json.dumps(ROW) + "\n", encoding="utf-8")
    buffers = lef._build_buffers_fixed(tmp_path, "2026-10-28T12:00", "2026-10-28T12:00:00Z")
    assert buffers["underdog"][1] == 1


def test_underdog_loads_with_create_never_and_a_missing_table_is_skipped() -> None:
    client = _Client(missing=True)
    lef._load_buffer(cast(Any, client), "underdog", io.BytesIO(b"{}\n"), 1)  # no raise
    assert client.configs[0].create_disposition == bigquery.CreateDisposition.CREATE_NEVER

"""SX catalogue snapshots -> raw_ingestion_us.sxbet_fetch_raw (never auto-created)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, cast

import pytest
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from BigQuery import load_exchange_fetch as lef
from BigQuery.exchange_fetch_extract import sxbet_keys
from BigQuery.exchange_fetch_tables import LOAD_SCHEMAS, TABLES

ROW = {"marketHash": "0xABC", "sportXeventId": "L20254403", "leagueId": 244, "type": 3}


def test_sxbet_keys() -> None:
    assert sxbet_keys(json.dumps(ROW)) == ("244", "L20254403", "0xabc")
    assert sxbet_keys("not json") == (None, None, None)


def test_wrap_and_schema_agree() -> None:
    buf = io.BytesIO()
    lef._wrap_sxbet(buf, json.dumps(ROW), "2026-10-13T17:00", "2026-10-13T17:00:00Z")
    row = json.loads(buf.getvalue())
    assert set(row) == {f.name for f in LOAD_SCHEMAS["sxbet"]}
    assert (row["league_id"], row["event_id"], row["market_hash"]) == ("244", "L20254403", "0xabc")
    assert TABLES["sxbet"] == "raw_ingestion_us.sxbet_fetch_raw"


def test_the_sxbet_file_is_picked_up(tmp_path: Path) -> None:
    (tmp_path / "sxbet_markets.jsonl").write_text(json.dumps(ROW) + "\n", encoding="utf-8")
    buffers = lef._build_buffers_fixed(tmp_path, "2026-10-13T17:00", "2026-10-13T17:00:00Z")
    assert buffers["sxbet"][1] == 1


class _Job:
    errors = None

    def result(self) -> None:
        return None


class _Client:
    def __init__(self, missing: bool) -> None:
        self.missing, self.configs = missing, []

    def load_table_from_file(self, buf, table, job_config):
        self.configs.append(job_config)
        if self.missing:
            raise NotFound("table not found")
        return _Job()


def test_sxbet_loads_with_create_never_and_a_missing_table_is_skipped() -> None:
    client = _Client(missing=True)
    lef._load_buffer(cast(Any, client), "sxbet", io.BytesIO(b"{}\n"), 1)   # no raise
    assert client.configs[0].create_disposition == bigquery.CreateDisposition.CREATE_NEVER


def test_other_tables_keep_their_create_disposition_and_still_raise() -> None:
    client = _Client(missing=True)
    with pytest.raises(NotFound):
        lef._load_buffer(cast(Any, client), "optic", io.BytesIO(b"{}\n"), 1)
    assert client.configs[0].create_disposition is None

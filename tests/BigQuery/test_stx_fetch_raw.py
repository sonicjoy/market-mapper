"""STX catalogue + rosters -> raw_ingestion_us.stx_fetch_raw / stx_players_fetch_raw (never auto-created)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, cast

from google.cloud import bigquery

from BigQuery import load_exchange_fetch as lef
from BigQuery.exchange_fetch_extract import stx_keys
from BigQuery.exchange_fetch_tables import LOAD_SCHEMAS, TABLES
from tests.BigQuery.test_sxbet_fetch_raw import _Client

MARKET = {"market_id": "0a0b4f52", "event_id": "63c2c44a", "rules": "home_winner"}
ROSTER = {"event_id": "63c2c44a", "teams": []}


def test_keys():
    assert stx_keys(json.dumps(MARKET)) == ("63c2c44a", "0a0b4f52")
    assert stx_keys(json.dumps(ROSTER)) == ("63c2c44a", None)
    assert stx_keys("not json") == (None, None)


def test_wrap_and_schema_agree():
    for key, wrap, line in (("stx", lef._wrap_stx, MARKET), ("stx_players", lef._wrap_stx_players, ROSTER)):
        buf = io.BytesIO()
        wrap(buf, json.dumps(line), "2026-10-29T12:00", "2026-10-29T12:00:00Z")
        row = json.loads(buf.getvalue())
        assert set(row) == {f.name for f in LOAD_SCHEMAS[key]}
        assert json.loads(row["data"]) == line  # verbatim: the gate replays this line
    assert TABLES["stx"] == "raw_ingestion_us.stx_fetch_raw"
    assert TABLES["stx_players"] == "raw_ingestion_us.stx_players_fetch_raw"


def test_the_stx_files_are_picked_up(tmp_path: Path):
    (tmp_path / "stx_markets.jsonl").write_text(json.dumps(MARKET) + "\n", encoding="utf-8")
    (tmp_path / "stx_event_players.jsonl").write_text(json.dumps(ROSTER) + "\n", encoding="utf-8")
    buffers = lef._build_buffers_fixed(tmp_path, "2026-10-29T12:00", "2026-10-29T12:00:00Z")
    assert buffers["stx"][1] == 1 and buffers["stx_players"][1] == 1


def test_stx_loads_with_create_never_and_a_missing_table_is_skipped():
    for key in ("stx", "stx_players"):
        client = _Client(missing=True)
        lef._load_buffer(cast(Any, client), key, io.BytesIO(b"{}\n"), 1)  # no raise
        assert client.configs[0].create_disposition == bigquery.CreateDisposition.CREATE_NEVER

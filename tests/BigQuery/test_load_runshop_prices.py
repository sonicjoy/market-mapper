"""Tests for BigQuery/load_runshop_prices.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import NotFound

from BigQuery import load_runshop_prices as loader


def _sample_record(
    *,
    row_id: int = 2655276840,
    fixture_id: int = 905827989,
    update_ts: str = "2026-07-03T10:43:08.099056Z",
) -> dict:
    return {
        "id": row_id,
        "txOddsFixtureID": fixture_id,
        "updateTimeStamp": update_ts,
        "marketIds": [3, 629],
        "modelId": 224,
        "price": 8.213923470122,
        "metadataId": 51189316,
    }


def test_update_timestamp_micros_parses_z_suffix():
    micros = loader.update_timestamp_micros("2026-07-03T10:43:08.099056Z")
    expected = int(
        datetime(2026, 7, 3, 10, 43, 8, 99056, tzinfo=UTC).timestamp()
        * 1_000_000,
    )
    assert micros == expected


def test_dedupe_key_uses_id_and_update_micros():
    rec = _sample_record()
    assert loader.dedupe_key(rec) == (
        2655276840,
        loader.update_timestamp_micros("2026-07-03T10:43:08.099056Z"),
    )


def test_filter_new_records_drops_existing_pairs():
    existing = {
        (2655276840, loader.update_timestamp_micros("2026-07-03T10:43:08.099056Z")),
    }
    records = [
        _sample_record(),
        _sample_record(row_id=2655276841, update_ts="2026-07-03T11:00:00.000000Z"),
    ]
    new_records = loader.filter_new_records(records, existing)
    assert len(new_records) == 1
    assert new_records[0]["id"] == 2655276841


def test_stamp_insert_time_uses_single_value():
    insert_time = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    stamped = loader.stamp_insert_time([_sample_record()], insert_time)
    assert stamped[0]["insert_time"] == "2026-07-07T12:00:00+00:00"
    assert stamped[0]["id"] == 2655276840


def test_load_missing_file_exits_zero(tmp_path: Path, capsys):
    path = tmp_path / "missing.jsonl"
    assert loader.load(str(path)) == 0
    assert "skipping" in capsys.readouterr().out


def test_load_empty_file_exits_zero(tmp_path: Path, capsys):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert loader.load(str(path)) == 0
    assert "No rows" in capsys.readouterr().out


def test_load_skips_when_all_rows_exist(tmp_path: Path, capsys):
    path = tmp_path / "prices.jsonl"
    rec = _sample_record()
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_client.get_table.return_value = MagicMock()
    mock_client.query.return_value.result.return_value = [
        MagicMock(
            id=rec["id"],
            update_micros=loader.update_timestamp_micros(rec["updateTimeStamp"]),
        ),
    ]

    with patch.object(loader.bigquery, "Client", return_value=mock_client), patch.dict(
        "os.environ", {"GCP_PROJECT": "test-project"},
    ):
        assert loader.load(str(path)) == 0

    out = capsys.readouterr().out
    assert "0 new rows" in out
    mock_client.load_table_from_json.assert_not_called()


def test_load_creates_table_and_appends_new_rows(tmp_path: Path, capsys):
    path = tmp_path / "prices.jsonl"
    rec = _sample_record()
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_client.get_table.side_effect = NotFound("missing")
    mock_job = MagicMock()
    mock_job.errors = None
    mock_job.output_rows = 1
    mock_client.load_table_from_json.return_value = mock_job

    with patch.object(loader.bigquery, "Client", return_value=mock_client), patch.dict(
        "os.environ", {"GCP_PROJECT": "test-project"},
    ):
        assert loader.load(str(path)) == 1

    mock_client.create_table.assert_called_once()
    table = mock_client.create_table.call_args[0][0]
    assert table.time_partitioning.field == "insert_time"
    mock_client.query.assert_not_called()

    rows = mock_client.load_table_from_json.call_args[0][0]
    assert len(rows) == 1
    assert rows[0]["id"] == rec["id"]
    assert "insert_time" in rows[0]
    assert "Appended 1 rows" in capsys.readouterr().out


def test_load_dedupes_then_appends_only_new(tmp_path: Path):
    path = tmp_path / "prices.jsonl"
    existing = _sample_record()
    new_rec = _sample_record(row_id=999, update_ts="2026-07-04T10:00:00.000000Z")
    path.write_text(
        json.dumps(existing) + "\n" + json.dumps(new_rec) + "\n",
        encoding="utf-8",
    )

    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_client.get_table.return_value = MagicMock()
    mock_client.query.return_value.result.return_value = [
        MagicMock(
            id=existing["id"],
            update_micros=loader.update_timestamp_micros(existing["updateTimeStamp"]),
        ),
    ]
    mock_job = MagicMock()
    mock_job.errors = None
    mock_job.output_rows = 1
    mock_client.load_table_from_json.return_value = mock_job

    with patch.object(loader.bigquery, "Client", return_value=mock_client), patch.dict(
        "os.environ", {"GCP_PROJECT": "test-project"},
    ):
        assert loader.load(str(path)) == 1

    rows = mock_client.load_table_from_json.call_args[0][0]
    assert len(rows) == 1
    assert rows[0]["id"] == 999

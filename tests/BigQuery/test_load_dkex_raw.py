"""load_dkex_raw appends into the existing table and never asks to create it."""

from __future__ import annotations

import json
from unittest import mock

from google.cloud import bigquery

from BigQuery import load_dkex_raw


def test_load_appends_without_create_permission(tmp_path, monkeypatch):
    path = tmp_path / "dkex_markets.jsonl"
    path.write_text(json.dumps({"source": "api", "id": "m1"}) + "\n")
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    client = mock.MagicMock()
    client.load_table_from_file.return_value.errors = None
    client.load_table_from_file.return_value.output_rows = 1
    with mock.patch.object(load_dkex_raw.bigquery, "Client", return_value=client):
        load_dkex_raw.load(str(path))

    buf, table = client.load_table_from_file.call_args.args
    config = client.load_table_from_file.call_args.kwargs["job_config"]
    assert table == load_dkex_raw.TABLE
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    # CREATE_IF_NEEDED needs bigquery.tables.create on the dataset; the
    # CronJob's GSA has dataEditor on dkex_raw only.
    assert config.create_disposition == bigquery.CreateDisposition.CREATE_NEVER
    buf.seek(0)
    assert json.loads(buf.read().decode()) == {
        "kind": "api", "data": json.dumps({"source": "api", "id": "m1"}),
    }

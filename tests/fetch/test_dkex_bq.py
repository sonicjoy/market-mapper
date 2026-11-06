"""fetch.dkex_bq: the latest dkex_raw api snapshot -> dkex_markets.jsonl."""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fetch import dkex_bq


def _client(datas: Sequence[str | None]) -> MagicMock:
    client = MagicMock()
    client.query.return_value.result.return_value = [
        SimpleNamespace(data=d) for d in datas
    ]
    return client


def test_read_snapshot_reads_only_the_latest_api_load() -> None:
    client = _client(['{"symbol": "A"}', None, '{"symbol": "B"}'])
    lines = dkex_bq.read_snapshot(client, "proj", None)
    assert lines == ['{"symbol": "A"}', '{"symbol": "B"}']
    sql = client.query.call_args.args[0]
    assert "`proj.raw_ingestion_us.dkex_raw`" in sql
    assert "kind = 'api'" in sql
    assert "r.insert_time = snap.s" in sql
    assert "limit" not in sql


def test_snapshot_read_repeats_the_freshness_bound_so_it_prunes() -> None:
    client = _client([])
    dkex_bq.read_snapshot(client, "proj", None)
    sql = client.query.call_args.args[0]
    bound = "insert_time > timestamp_sub(current_timestamp(), interval @max_age_s second)"
    assert sql.count(bound) == 2
    assert f"and r.{bound}" in sql


def test_read_snapshot_caps_rows_for_smoke_runs() -> None:
    client = _client([])
    dkex_bq.read_snapshot(client, "proj", 3)
    assert client.query.call_args.args[0].rstrip().endswith("limit 3")


def test_main_writes_the_catalogue_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    rows = [json.dumps({"symbol": "A", "stat_achievement": "WIN"})]
    with patch.object(dkex_bq.bigquery, "Client", return_value=_client(rows)):
        assert dkex_bq.main(["--league", "nfl", "--out-dir", str(tmp_path)]) == 0
    out = (tmp_path / "dkex_markets.jsonl").read_text().splitlines()
    assert [json.loads(line) for line in out] == [{"symbol": "A", "stat_achievement": "WIN"}]


def test_main_writes_nothing_when_the_snapshot_is_stale(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "proj")
    with patch.object(dkex_bq.bigquery, "Client", return_value=_client([])):
        assert dkex_bq.main(["--out-dir", str(tmp_path)]) == 1
    assert not (tmp_path / "dkex_markets.jsonl").exists()

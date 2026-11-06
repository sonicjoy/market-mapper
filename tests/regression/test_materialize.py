"""Materializer: BQ fetch snapshot -> replayable tick dir, never half-built."""

import json
from types import SimpleNamespace

import pytest

from regression import materialize


class FakeClient:
    """Answers each table's query with canned rows."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        table = sql.split("`")[1].rsplit(".", 1)[1]
        return SimpleNamespace(result=lambda: self.rows.get(table, []))


def _rows(**tables):
    return {t: [SimpleNamespace(**r) for r in rs] for t, rs in tables.items()}


FULL = _rows(
    optic_fetch_raw=[{"data": '{"id": "FX1"}'}],
    kalshi_fetch_raw=[{"data": '{"ticker": "B"}'}, {"data": '{"ticker": "A"}'}],
    crypto_fetch_raw=[{"data": '{"Symbol": "S1"}'}],
    novig_fetch_raw=[{"kind": "events", "data": '{"e": 1}'}, {"kind": "markets", "data": '{"m": 1}'}],
)


def _patch(monkeypatch):
    monkeypatch.setattr(materialize, "_params", lambda snap: None)


def test_writes_prod_file_layout(tmp_path, monkeypatch):
    _patch(monkeypatch)
    out = materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=FakeClient(FULL))
    assert out == tmp_path / "2026-09-30" / "15_00"
    assert (out / "kalshi_markets.jsonl").read_text().splitlines() == [
        '{"ticker": "A"}',
        '{"ticker": "B"}',
    ]  # sorted, deterministic
    assert (out / "novig_events.jsonl").read_text() == '{"e": 1}\n'
    assert (out / "prophetx_events.jsonl").read_text() == ""
    meta = json.loads((out / "materialized.json").read_text())
    assert meta["rows"]["crypto_com_markets.jsonl"] == 1
    assert "runshop" in meta["not_covered"]


def test_incomplete_snapshot_is_refused_and_not_marked(tmp_path, monkeypatch):
    _patch(monkeypatch)
    rows = dict(FULL)
    rows.pop("crypto_fetch_raw")
    with pytest.raises(RuntimeError, match="crypto_com_markets.jsonl empty"):
        materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=FakeClient(rows))
    assert not (tmp_path / "2026-09-30" / "15_00" / "materialized.json").exists()


def test_cached_tick_is_not_requeried(tmp_path, monkeypatch):
    _patch(monkeypatch)
    materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=FakeClient(FULL))
    again = FakeClient(FULL)
    materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=again)
    assert again.queries == []


def test_every_query_prunes_to_the_snapshot_partition():
    for sql in (materialize._ROWS_SQL, materialize._NOVIG_SQL):
        assert "fetch_time BETWEEN @lo AND @hi" in sql
        assert "snapshot_id = @snap" in sql


def test_latest_snapshots_aligned_to_the_hour_boundary():
    ids = ["2026-10-16T06:30", "2026-10-16T06:00", "2026-10-16T05:30", "2026-10-16T05:00", "2026-10-16T04:00"]
    client = FakeClient({"crypto_fetch_raw": [SimpleNamespace(snapshot_id=i) for i in ids]})
    assert materialize.latest_snapshots("p", 2, client=client) == ids[:2]
    aligned = materialize.latest_snapshots("p", 2, client=client, every_hours=2)
    assert aligned == ["2026-10-16T06:00", "2026-10-16T04:00"]


class _Result(list):
    """A BigQuery RowIterator stand-in: iterable, with the result table's row count and schema."""

    schema = ("data",)

    @property
    def total_rows(self):
        return len(self)


class RangedClient(FakeClient):
    """A client whose results come back through row ranges of the job's result table, like BigQuery's."""

    def __init__(self, rows):
        super().__init__(rows)
        self.spans = {}

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        table = sql.split("`")[1].rsplit(".", 1)[1]
        result = _Result(self.rows.get(table, []))
        return SimpleNamespace(result=lambda: result, destination=table)

    def list_rows(self, table, selected_fields=None, start_index=0, max_results=0, page_size=None):
        self.spans.setdefault(table, []).append((start_index, max_results))
        rows = self.rows.get(table, [])
        if page_size is None:  # google-cloud-bigquery 3.46.1 without page_size: every page restarts at start
            return (rows[start_index : start_index + 2] * max_results)[:max_results]
        return rows[start_index : start_index + max_results]


def test_ranged_read_writes_the_same_files_as_one_stream(tmp_path, monkeypatch):
    _patch(monkeypatch)
    rows = dict(FULL)
    rows["optic_fetch_raw"] = [SimpleNamespace(data=f'{{"id": "FX{i:03d}"}}') for i in range(37)]
    one = materialize.materialize("2026-09-30T15:00", tmp_path / "one", "proj", client=FakeClient(rows))
    ranged_client = RangedClient(rows)
    ranged = materialize.materialize("2026-09-30T15:00", tmp_path / "ranged", "proj", client=ranged_client)
    for f in sorted(p.name for p in one.iterdir()):
        assert (ranged / f).read_bytes() == (one / f).read_bytes(), f
    spans = ranged_client.spans["optic_fetch_raw"]
    assert len(spans) == materialize.RANGES  # a few big rows still split 16 ways
    assert sorted(i for s, n in spans for i in range(s, s + n)) == list(range(37))  # each row exactly once


def test_ranges_cover_every_row_once():
    for total in (1, 15, 16, 17, 1853, 189009):
        spans = materialize._ranges(total)
        assert len(spans) == min(materialize.RANGES, total)
        assert sum(n for _s, n in spans) == total
        assert all(s2 == s1 + n1 for (s1, n1), (s2, _n2) in zip(spans, spans[1:], strict=False))


def test_a_read_that_repeats_rows_is_refused_not_written(tmp_path, monkeypatch):
    """A DISTINCT query never returns a line twice: a repeat means the read went wrong (CI, 2026-10-19)."""
    _patch(monkeypatch)
    rows = dict(FULL)
    rows["kalshi_fetch_raw"] = [SimpleNamespace(data='{"ticker": "A"}')] * 2
    with pytest.raises(RuntimeError, match="1 repeated lines from a DISTINCT query"):
        materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=FakeClient(rows))
    assert not (tmp_path / "2026-09-30" / "15_00" / "materialized.json").exists()


class MissingTableClient(FakeClient):
    """BigQuery answering NotFound for tables Terraform has not created."""

    def __init__(self, rows, missing):
        super().__init__(rows)
        self.missing = missing

    def query(self, sql, job_config=None):
        from google.api_core.exceptions import NotFound

        table = sql.split("`")[1].rsplit(".", 1)[1]
        if table in self.missing:
            raise NotFound(f"Not found: Table {table}")
        return super().query(sql, job_config)


def test_sx_and_underdog_files_are_written(tmp_path, monkeypatch):
    _patch(monkeypatch)
    rows = dict(
        FULL,
        **_rows(
            sxbet_fetch_raw=[{"data": '{"marketHash": "0xa"}'}], underdog_fetch_raw=[{"data": '{"ticker": "UDXX_Y_Z"}'}]
        ),
    )
    out = materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=FakeClient(rows))
    assert (out / "sxbet_markets.jsonl").read_text() == '{"marketHash": "0xa"}\n'
    assert (out / "underdog_markets.jsonl").read_text() == '{"ticker": "UDXX_Y_Z"}\n'
    assert json.loads((out / "materialized.json").read_text())["not_covered"] == ["runshop", "dkex", "huddle"]


def test_an_optional_table_not_created_yet_reads_empty_and_is_named(tmp_path, monkeypatch):
    _patch(monkeypatch)
    client = MissingTableClient(FULL, {"underdog_fetch_raw"})
    out = materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=client)
    assert (out / "underdog_markets.jsonl").read_text() == ""
    assert json.loads((out / "materialized.json").read_text())["not_covered"][-1] == "underdog"


def test_any_other_missing_table_still_fails(tmp_path, monkeypatch):
    from google.api_core.exceptions import NotFound

    _patch(monkeypatch)
    with pytest.raises(NotFound):
        materialize.materialize(
            "2026-09-30T15:00", tmp_path, "proj", client=MissingTableClient(FULL, {"sxbet_fetch_raw"})
        )
    assert not (tmp_path / "2026-09-30" / "15_00" / "materialized.json").exists()


def test_stx_files_are_written_and_a_missing_stx_table_is_named(tmp_path, monkeypatch):
    _patch(monkeypatch)
    rows = dict(FULL, **_rows(stx_fetch_raw=[{"data": '{"market_id": "m"}'}], stx_players_fetch_raw=[{"data": '{"event_id": "e"}'}]))
    out = materialize.materialize("2026-09-30T15:00", tmp_path, "proj", client=FakeClient(rows))
    assert (out / "stx_markets.jsonl").read_text() == '{"market_id": "m"}\n'
    assert (out / "stx_event_players.jsonl").read_text() == '{"event_id": "e"}\n'
    out2 = materialize.materialize(
        "2026-09-30T16:00", tmp_path, "proj", client=MissingTableClient(FULL, {"stx_fetch_raw", "stx_players_fetch_raw"})
    )
    assert json.loads((out2 / "materialized.json").read_text())["not_covered"][-2:] == ["stx", "stx_players"]

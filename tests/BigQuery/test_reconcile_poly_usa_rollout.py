"""Reconcile tolerates polymarket_usa before the fetch_raw table is populated."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from BigQuery.reconcile_fetch_snapshot import reconcile


def test_reconcile_skips_empty_poly_usa_slice(tmp_path: Path):
    data_dir = tmp_path / "2026-09-10" / "10_00"
    data_dir.mkdir(parents=True)
    (data_dir / "polymarket_usa_markets.jsonl").write_text(
        '{"inner":"nfl","slug":"aec-nfl-bal-kc-2026-09-10"}\n',
        encoding="utf-8",
    )
    client = MagicMock()
    client.query.return_value.result.return_value = []
    with patch(
        "BigQuery.reconcile_fetch_snapshot.bigquery.Client",
        return_value=client,
    ):
        assert reconcile(data_dir) == []

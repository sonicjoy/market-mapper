"""Local JSONL snapshot for Missing dev."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from mappers.control_plane.console_missing import _cache, list_missing_symbols
from mappers.control_plane.console_missing_local import (
    load_missing_local_jsonl,
    write_missing_local_jsonl,
)


def test_roundtrip_jsonl(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "missing.jsonl"
    row = {
        "symbol": "NX.F.OPT.MLB-1",
        "symbol_base": "NX.F.OPT.MLB-1",
        "fixture_prefix": "NX.F.OPT.MLB-1-260925",
        "crypto_prefix": "MLB",
        "market_group": "Game Line",
        "contract_type": "Moneyline",
        "period_type": "Full-Game",
        "meta_name": "A @ B",
        "meta_league": "MLB",
        "kickoff": datetime(2026, 9, 26, 18, 0, tzinfo=UTC),
        "scope": "untouched",
    }
    write_missing_local_jsonl([row], path)
    loaded = load_missing_local_jsonl(path)
    assert loaded[0]["symbol"] == "NX.F.OPT.MLB-1"
    assert isinstance(loaded[0]["kickoff"], datetime)


def test_list_missing_reads_local_file(tmp_path: Path, monkeypatch) -> None:
    _cache.clear()
    path = tmp_path / "missing.jsonl"
    path.write_text(
        json.dumps(
            {
                "symbol": "NX.F.OPT.MLB-1",
                "symbol_base": "NX.F.OPT.MLB-1",
                "fixture_prefix": "p",
                "crypto_prefix": "MLB",
                "market_group": "Game Line",
                "contract_type": "Moneyline",
                "period_type": "Full-Game",
                "meta_name": "A @ B",
                "meta_league": "MLB",
                "kickoff": "2026-09-26T18:00:00+00:00",
                "scope": "untouched",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAPPING_MISSING_BQ_PROJECT", "local")
    monkeypatch.setenv("MAPPING_MISSING_LOCAL_PATH", str(path))
    view = list_missing_symbols(limit=10)
    assert view["count"] == 1
    assert view["bq_project"] == "local"
    assert view["rows"][0]["symbol"] == "NX.F.OPT.MLB-1"

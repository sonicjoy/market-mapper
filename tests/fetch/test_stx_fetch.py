"""STX catalogue loader: file formats, the kept fields, the CLI, and the live path's key handling."""

from __future__ import annotations

import asyncio
import gzip
import json
import sys
from pathlib import Path

import pytest

from fetch import stx

CAPTURE = "tests/fixtures/stx/stx_open_markets_identity_2026-10-28.json.gz"
PLAYERS = "tests/fixtures/stx/stx_event_players_2026-10-28.json"
ROW = {
    "market_id": "m1",
    "event_id": "e1",
    "rules": "spread",
    "specifier": "-2.5",
    "question": "Will ...?",
    "description": "long text",
    "symbol": "NFL-GB-CAR-...",
    "event_start": "2026-10-30T00:15:00.000000Z",
}


def test_normalize_keeps_identity_fields_and_drops_text_and_symbol():
    out = stx.normalize(ROW)
    assert set(out) == set(stx.KEEP)
    assert (out["market_id"], out["specifier"], out["grouping_id"]) == ("m1", "-2.5", None)
    assert "question" not in out and "symbol" not in out and "description" not in out


@pytest.mark.parametrize("shape", ["list", "wrapped", "jsonl", "gz"])
def test_load_markets_list_reads_every_export_shape(tmp_path, shape):
    path = tmp_path / ("m.json.gz" if shape == "gz" else "m.json")
    body = {
        "list": json.dumps([ROW]),
        "wrapped": json.dumps({"markets": [ROW]}),
        "jsonl": json.dumps(ROW) + "\n\n",
        "gz": json.dumps({"markets": [ROW]}),
    }[shape]
    if shape == "gz":
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(body)
    else:
        path.write_text(body, encoding="utf-8")
    assert stx.load_markets_list(path) == [ROW]


def test_capture_loads_6443_markets():
    assert len(stx.load_markets_list(Path(CAPTURE))) == 6443


def test_cli_from_file_writes_markets_and_rosters(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["fetch.stx", "--from-file", CAPTURE, "--players-file", PLAYERS, "--out-dir", str(tmp_path)]
    )
    stx.main()
    lines = (tmp_path / stx.OUT_FILE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6443 and set(json.loads(lines[0])) == set(stx.KEEP)
    rosters = [json.loads(x) for x in (tmp_path / stx.PLAYERS_FILE).read_text(encoding="utf-8").splitlines()]
    assert len(rosters) == 4 and all(r["event_id"] for r in rosters)


def test_live_without_key_env_stops_before_importing_the_sdk(monkeypatch):
    monkeypatch.delenv(stx.KEY_ID_ENV, raising=False)
    monkeypatch.delenv(stx.KEY_PATH_ENV, raising=False)
    with pytest.raises(SystemExit, match=stx.KEY_PATH_ENV):
        asyncio.run(stx._fetch_live("ontario", "demo", False))

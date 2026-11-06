"""JSONL file reads vs SnapshotIndex.from_jsonl produce identical mappings."""

import hashlib
import json
from pathlib import Path

from mappers import pipeline
from mappers.run import LEAGUES
from mappers.snapshot_index import SnapshotIndex


def _setup(tmp_path, monkeypatch, league_key: str, league_id: str, league_cfg) -> Path:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config" / league_key
    config_dir.mkdir(parents=True)
    (config_dir / "team_aliases.toml").write_text("[ALP]\n[BET]\n")

    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    game = {
        "id": "fx1",
        "game_id": "g1",
        "start_date": "2026-07-30T01:00:00Z",
        "status": "unplayed",
        "is_live": False,
        "home_competitors": [
            {"id": "h1", "abbreviation": "ALP", "name": "Alpha"},
        ],
        "away_competitors": [
            {"id": "a1", "abbreviation": "BET", "name": "Beta"},
        ],
        "league": {"id": league_id},
        "odds": [],
    }
    data_dir.mkdir(parents=True)
    (data_dir / "optic_fixtures_odds.jsonl").write_text(
        json.dumps(game) + "\n")
    return data_dir


def _rows_hash(result) -> str:
    payload = json.dumps(
        [r.model_dump() for r in result.rows],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_jsonl_and_snapshot_index_parity_lol(tmp_path, monkeypatch):
    data_dir = _setup(
        tmp_path, monkeypatch, "lol", LEAGUES['lol'].OPTIC.league_id, LEAGUES['lol'],
    )
    file_result = pipeline.run(data_dir, LEAGUES['lol'])
    index = SnapshotIndex.from_jsonl(data_dir)
    snap_result = pipeline.run(data_dir, LEAGUES['lol'], snapshot=index)
    assert _rows_hash(file_result) == _rows_hash(snap_result)


def test_jsonl_and_snapshot_index_parity_soccer(tmp_path, monkeypatch):
    data_dir = _setup(
        tmp_path, monkeypatch, "argentina_primera",
        LEAGUES['argentina_primera'].OPTIC.league_id, LEAGUES['argentina_primera'],
    )
    file_result = pipeline.run(data_dir, LEAGUES['argentina_primera'])
    index = SnapshotIndex.from_jsonl(data_dir)
    snap_result = pipeline.run(
        data_dir, LEAGUES['argentina_primera'], snapshot=index,
    )
    assert _rows_hash(file_result) == _rows_hash(snap_result)

"""Novig league strings compare case-insensitively (prod tip: "nfl" vs feed "NFL")."""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch.novig import select_events
from mappers.exchanges.novig import NovigConfig, novig_league_key
from mappers.market_types import MarketType
from mappers.pipeline import run
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.snapshot_index import SnapshotIndex
from tests.mappers.test_doubleheader import _optic_game

_FIXTURE_ID = "fix1"


def _event(league: str, event_id: str = "e1") -> dict:
    start = datetime.now(UTC) + timedelta(hours=2)
    return {
        "id": event_id, "league": league, "status": "OPEN_PREGAME", "type": "Game",
        "opticOddsId": _FIXTURE_ID,
        "scheduledStart": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_league_key_trims_and_casefolds():
    assert novig_league_key(" NFL ") == novig_league_key("nfl") == "nfl"
    assert novig_league_key("Champions League") == "champions league"


def test_select_events_keeps_upper_feed_event_for_lower_config():
    kept = select_events(
        [_event("NFL"), _event("MLB", "e2")], {"nfl"}, horizon_hours=24)
    assert [e["id"] for e in kept] == ["e1"]


def test_select_events_matches_mixed_case_league():
    kept = select_events([_event("Champions League")], {" champions league"}, 24)
    assert len(kept) == 1


def test_snapshot_lookups_are_case_insensitive(tmp_path: Path):
    tmp_path = tmp_path / "2026-07-29" / "12_00"
    tmp_path.mkdir(parents=True)
    (tmp_path / "novig_events.jsonl").write_text(
        json.dumps({"id": "e1", "league": "NFL"}) + "\n")
    (tmp_path / "novig_markets.jsonl").write_text(
        json.dumps({"id": "m1", "league": "NFL"}) + "\n")
    idx = SnapshotIndex.from_jsonl(tmp_path)
    for spelling in ("nfl", "NFL", " Nfl "):
        assert len(idx.novig_event_lines(spelling)) == 1
        assert len(idx.novig_market_lines(spelling)) == 1
    assert idx.novig_event_lines("mlb") == []


def _outcome(oid: str, kind: str, index: int, team_id: str, name: str) -> dict:
    return {
        "id": oid, "description": name, "type": kind, "index": index,
        "competitor": {"id": "c-" + oid, "name": name, "shortName": name,
                       "opticOddsId": team_id},
    }


def _novig_files(data: Path, feed_league: str) -> None:
    (data / "novig_events.jsonl").write_text(
        json.dumps(_event(feed_league)) + "\n", encoding="utf-8")
    market = {
        "id": "m1", "type": "MONEY", "description": "ML", "status": "OPEN",
        "strike": None, "league": feed_league, "eventId": "e1",
        "outcomes": [
            _outcome("o-home", "Home", 0, f"{_FIXTURE_ID}-home", "BOS"),
            _outcome("o-away", "Away", 1, f"{_FIXTURE_ID}-away", "TB"),
        ],
    }
    (data / "novig_markets.jsonl").write_text(
        json.dumps(market) + "\n", encoding="utf-8")


def _run_pass(tmp_path: Path, capsys, cfg_league: str, feed_league: str) -> str:
    tmp_path = tmp_path / "2026-09-07" / "09_00"
    tmp_path.mkdir(parents=True)
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == "mlb")
    cfg = dataclasses.replace(
        build_tip_league(row),
        NOVIG=NovigConfig(
            league=cfg_league, market_types={"MONEY": MarketType.MONEYLINE}),
    )
    game = _optic_game(
        game_id="g1", fixture_id=_FIXTURE_ID, start_date="2026-09-07T18:00:00Z")
    (tmp_path / "optic_fixtures_odds.jsonl").write_text(
        json.dumps(game) + "\n", encoding="utf-8")
    for name in ("prophetx_events", "prophetx_markets", "kalshi_markets"):
        (tmp_path / f"{name}.jsonl").write_text("", encoding="utf-8")
    _novig_files(tmp_path, feed_league)
    capsys.readouterr()
    run(tmp_path, cfg)
    return capsys.readouterr().err


def test_pipeline_novig_pass_keeps_events_and_markets_across_case(
        tmp_path: Path, capsys):
    err = _run_pass(tmp_path, capsys, cfg_league="mlb", feed_league="MLB")
    assert "novig [mlb]: 2 stamped" in err


def test_pipeline_novig_pass_still_drops_other_league(tmp_path: Path, capsys):
    err = _run_pass(tmp_path, capsys, cfg_league="mlb", feed_league="NFL")
    assert "novig [mlb]: 0 stamped, 0 dropped (optic didn't price), 0 no fixture" in err

"""SnapshotIndex: JSONL ingest and league-keyed slices."""

import json
from types import SimpleNamespace

from mappers.snapshot_index import (
    SnapshotIndex,
    filter_empty_optic,
    resolve_snapshot,
    snapshot_source_mode,
)


def _optic_game(league_id: str, game_id: str) -> str:
    return json.dumps({
        "id": game_id,
        "league": {"id": league_id},
        "home_competitors": [{"id": "h", "abbreviation": "H", "name": "Home"}],
        "away_competitors": [{"id": "a", "abbreviation": "A", "name": "Away"}],
        "start_date": "2026-07-30T01:00:00Z",
        "odds": [],
    })


def test_from_jsonl_groups_optic_by_league(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    nba = _optic_game("nba", "g1")
    nhl = _optic_game("nhl", "g2")
    (data_dir / "optic_fixtures_odds.jsonl").write_text(f"{nba}\n{nhl}\n")

    idx = SnapshotIndex.from_jsonl(data_dir)
    assert idx.snapshot_id == "2026-07-29T12:00"
    assert len(idx.optic_lines("nba")) == 1
    assert len(idx.optic_lines("nhl")) == 1
    assert nba in idx.optic_lines("nba")


def test_kalshi_lines_by_typed_sport(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    k1 = json.dumps({"event_ticker": "E1", "ticker": "T1", "sport": "basketball"})
    k1h = json.dumps({"event_ticker": "E2", "ticker": "T1H", "sport": "basketball"})
    k2 = json.dumps({"event_ticker": "E3", "ticker": "T2", "sport": "hockey"})
    untyped = json.dumps({"event_ticker": "KXNBA-26FEB26LALBOS", "ticker": "T3"})
    (data_dir / "kalshi_markets.jsonl").write_text(f"{k1}\n{k1h}\n{k2}\n{untyped}\n")

    idx = SnapshotIndex.from_jsonl(data_dir)
    assert idx.kalshi_lines_for_sport("basketball") == [k1, k1h]
    assert idx.kalshi_lines_for_sport("hockey") == [k2]
    assert idx.kalshi_lines_for_sport("soccer") == []


def test_polymarket_usa_league_filter(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    # The gateway league id comes from the typed field, not the symbol.
    nfl = json.dumps({
        "league_id": 1, "slug": "tsc-nfl-sea-kc-2026-09-09-tt-sea-10pt5",
        "sports_market_type": "football_team_points_full_game_total",
        "line": 10.5,
    })
    mlb = json.dumps({"league_id": 5, "slug": "asc-nfl-looks-like-nfl"})
    (data_dir / "polymarket_usa_markets.jsonl").write_text(f"{nfl}\n{mlb}\n")
    idx = SnapshotIndex.from_jsonl(data_dir)
    assert idx.polymarket_usa_markets_for_leagues(frozenset({1})) == [nfl]
    assert idx.polymarket_usa_markets_for_leagues(frozenset({5})) == [mlb]
    assert idx.polymarket_usa_markets_for_leagues(frozenset({1, 5})) == [nfl, mlb]


def test_polymarket_prefix_filter(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    nba = json.dumps({"slug": "nba-lakers-celtics", "condition_id": "0x1"})
    epl = json.dumps({"slug": "epl-arsenal-chelsea", "condition_id": "0x2"})
    (data_dir / "polymarket_markets.jsonl").write_text(f"{nba}\n{epl}\n")

    idx = SnapshotIndex.from_jsonl(data_dir)
    assert idx.polymarket_lines_for_prefix("nba") == [nba]
    assert epl not in idx.polymarket_lines_for_prefix("nba")


def test_snapshot_source_mode_default_jsonl(monkeypatch):
    monkeypatch.delenv("MAP_SNAPSHOT_SOURCE", raising=False)
    assert snapshot_source_mode() == "jsonl"


def test_resolve_snapshot_indexes_jsonl(tmp_path, monkeypatch):
    monkeypatch.delenv("MAP_SNAPSHOT_SOURCE", raising=False)
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    (data_dir / "optic_fixtures_odds.jsonl").write_text(
        _optic_game("nba", "g1") + "\n")
    idx = resolve_snapshot(data_dir)
    assert idx is not None
    assert idx.optic_lines("nba")


def test_filter_empty_optic_skips_idle_leagues(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    (data_dir / "optic_fixtures_odds.jsonl").write_text(
        _optic_game("nba", "g1") + "\n")
    idx = SnapshotIndex.from_jsonl(data_dir)
    leagues = {
        "nba": SimpleNamespace(OPTIC=SimpleNamespace(
            league_id="nba", extra_league_ids=())),
        "nhl": SimpleNamespace(OPTIC=SimpleNamespace(
            league_id="nhl", extra_league_ids=())),
    }
    kept = filter_empty_optic(idx, ["nba", "nhl"], leagues)
    assert kept == ["nba"]


def test_filter_empty_optic_keeps_single_league(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    (data_dir / "optic_fixtures_odds.jsonl").write_text(
        _optic_game("nba", "g1") + "\n")
    idx = SnapshotIndex.from_jsonl(data_dir)
    leagues = {
        "nhl": SimpleNamespace(OPTIC=SimpleNamespace(
            league_id="nhl", extra_league_ids=())),
    }
    assert filter_empty_optic(idx, ["nhl"], leagues) == ["nhl"]


def test_crypto_index_uses_event_meta_league(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    raw = json.dumps({"Symbol": "NX.F.OPT.NBA-1", "eventMetaLEAGUE": "NBA"})
    parsed = json.dumps({"league": "NBA", "symbol": "x"})
    (data_dir / "crypto_com_markets.jsonl").write_text(f"{raw}\n{parsed}\n")
    idx = SnapshotIndex.from_jsonl(data_dir)
    assert len(idx.crypto_lines("NBA")) == 2


def test_px_markets_join_event_tournament(tmp_path):
    data_dir = tmp_path / "data" / "2026-07-29" / "12_00"
    data_dir.mkdir(parents=True)
    (data_dir / "prophetx_events.jsonl").write_text(
        json.dumps({"event_id": 9, "tournament_id": 132}) + "\n")
    (data_dir / "prophetx_markets.jsonl").write_text(
        json.dumps({"id": 1, "sport_event_id": 9, "name": "Moneyline"}) + "\n")
    idx = SnapshotIndex.from_jsonl(data_dir)
    assert len(idx.px_event_lines("132")) == 1
    assert len(idx.px_market_lines("132")) == 1

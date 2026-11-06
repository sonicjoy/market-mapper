"""A doubles side is one pair, so the league can map it."""

import json
from pathlib import Path

from mappers.exchanges.optic import OpticConfig, load_fixtures
from mappers.team_bootstrap import bootstrap_empty_abbrs

_ROJER = "Jean-Julien Rojer"
_WINEGAR = "Theodore Winegar"


def _write(tmp_path) -> Path:
    path = tmp_path / "optic.jsonl"
    path.write_text(json.dumps({
        "id": "dbl",
        "game_id": "dbl",
        "start_date": "2026-09-22T18:00:00Z",
        "status": "unplayed",
        "is_live": False,
        "home_competitors": [
            {"id": "d2", "name": _WINEGAR, "abbreviation": ""},
            {"id": "d1", "name": _ROJER, "abbreviation": ""},
        ],
        "away_competitors": [
            {"id": "a1", "name": "Other Side", "abbreviation": "OTH"},
        ],
        "league": {"id": "atp_doubles"},
        "odds": [{
            "id": "odd-rojer",
            "market_id": "moneyline",
            "selection": _ROJER,
            "team_id": "other-rojer-record",
            "grouping_key": "default",
        }],
        "source_ids": {},
    }) + "\n", encoding="utf-8")
    return path


def test_doubles_side_maps_as_one_pair(tmp_path):
    path = _write(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "optic_fixtures_odds.jsonl").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8",
    )
    overrides = bootstrap_empty_abbrs(data, "atp_doubles", Path())
    cfg = OpticConfig(
        league_id="atp_doubles", table_types={}, abbr_overrides=overrides,
    )
    index = load_fixtures(path, cfg)
    fixture = next(iter(index.values()))[0]
    assert fixture.home_name == f"{_WINEGAR} / {_ROJER}"
    assert fixture.home == overrides["d1+d2"]
    assert fixture.team_map["d1"] == fixture.home
    assert fixture.team_map["d2"] == fixture.home
    assert fixture.team_map["d1+d2"] == fixture.home
    assert fixture.team_map["other-rojer-record"] == fixture.home
    assert fixture.team_map["a1"] == "OTH"

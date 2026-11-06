"""Polymarket US gateway market harvest (typed fields; symbols never split)."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import requests

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch import polymarket_usa as harvest  # noqa: E402


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    if status >= 400 and status != 404:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    else:
        resp.raise_for_status = MagicMock()
    return resp


_MLB = harvest.GatewayLeague(league_id=5, name="MLB", url_key="mlb")


def test_catalogue_is_keyed_on_the_typed_league_id():
    payload = {"sports": [
        {"slug": "soccer", "leagues": [
            {"id": 306, "slug": "serca", "name": "Serie C Girone A"},
            {"id": 307, "slug": "sercb", "name": "Serie C Girone B"},
            {"id": "bad", "slug": "x"}, {"id": 9},
        ]},
        {"slug": "baseball", "leagues": [{"id": 5, "slug": "mlb", "name": "MLB"}]},
    ]}
    cat = harvest.parse_catalogue(payload)
    assert set(cat) == {306, 307, 5}
    assert cat[306] == harvest.GatewayLeague(306, "Serie C Girone A", "serca")


def test_wanted_ids_missing_from_the_catalogue_are_reported():
    cat = {5: _MLB}
    assert harvest.wanted_leagues(cat, frozenset({5, 4})) == ([_MLB], [4])


def test_every_code_league_id_is_an_int():
    from mappers.exchanges.polymarket_usa_leagues import all_us_league_ids
    ids = all_us_league_ids()
    assert ids and all(isinstance(i, int) for i in ids)


def test_get_league_events_keeps_vm_harvest_fields() -> None:
    """The league walk keeps startTime/id/teams/markets for records and gap events."""
    event = {
        "id": 99,
        "ticker": "nfl-sea-kc-2026-09-09",
        "slug": "nfl-sea-kc-2026-09-09",
        "title": "Seattle Seahawks at Kansas City Chiefs",
        "startTime": "2026-09-10T00:20:00Z",
        "sportradarGameId": "uuid-1",
        "teams": [{"abbreviation": "sea", "name": "Seattle Seahawks"}],
        "markets": [{"slug": "nested-market"}],
    }
    page = _resp(200, {"events": [event]})
    with patch("fetch.polymarket_usa.requests.get", return_value=page):
        rows = harvest.league_events("nfl")
    assert rows == [event]


def test_league_events_skips_404():
    with patch("fetch.polymarket_usa.requests.get", return_value=_resp(404)):
        assert harvest.league_events("nope") == []


# === Structured Path 2 records (polymarket_usa_markets.jsonl) ===

_PIT_TEAM = {
    "id": 3021, "name": "Pittsburgh Pirates", "abbreviation": "pit",
    "safeName": "Pirates", "league": "mlb", "logo": "https://x/pit.png",
    "providerIds": [
        {"provider": "PROVIDER_SPORTRADAR", "providerId": "481dfe7e"},
        {"provider": "PROVIDER_SPORTSDATAIO", "providerId": "4"},
    ],
}
_DET_TEAM = {"id": 3010, "name": "Detroit Tigers", "abbreviation": "det"}



def _spread_market() -> dict[str, Any]:
    return {
        "id": "1014120",
        "slug": "asc-mlb-pit-det-2026-09-26-pos-2pt5",
        "sportsMarketType": "baseball_team_full_game_spread",
        "marketType": "spreads",
        "line": 2.5,
        "title": "Detroit Tigers wins by over 2.5 runs",
        "marketSides": [
            {"id": "2027724", "long": True, "description": "+2.50",
             "teamId": 3021, "team": _PIT_TEAM, "price": "0.75"},
            {"id": "2027725", "long": False, "description": "-2.50",
             "teamId": 3010, "team": _DET_TEAM},
        ],
    }


def _mlb_event(**extra: Any) -> dict[str, Any]:
    return {
        "id": 123158, "ticker": "mlb-pit-det-2026-09-26",
        "startTime": "2026-09-26T17:10:00Z",
        "sportradarGameId": "4d3fd422", "teams": [_PIT_TEAM, _DET_TEAM],
        **extra,
    }


def test_market_record_keeps_typed_fields_and_drops_display():
    rec = harvest.market_record(_spread_market(), _mlb_event(), 5)
    assert rec is not None
    assert rec["league_id"] == 5
    assert rec["market_id"] == "1014120"
    assert rec["event_id"] == "123158"
    assert rec["event_start"] == "2026-09-26T17:10:00Z"
    assert rec["sports_market_type"] == "baseball_team_full_game_spread"
    assert rec["line"] == 2.5
    assert rec["teams"][0] == {
        "id": "3021", "abbreviation": "pit", "name": "Pittsburgh Pirates",
        "safe_name": "Pirates", "league": "mlb", "sportradar_id": "481dfe7e",
    }
    assert rec["sides"] == [
        {"id": "2027724", "long": True, "description": "+2.50", "team_id": "3021"},
        {"id": "2027725", "long": False, "description": "-2.50", "team_id": "3010"},
    ]


def test_market_record_keeps_player_metadata():
    market = {
        "id": "1060707", "slug": "astatc-mlb-pit-det-2026-09-26-hits-nicgon-gte1",
        "sportsMarketType": "baseball_player_hits", "line": 1,
        "metadata": {"playerName": "Nick Gonzales", "lineLabel": "1+",
                     "playerId": 515, "statLabel": "H"},
        "marketSides": [{"id": "1", "long": True, "description": "Yes", "teamId": 3021}],
    }
    rec = harvest.market_record(market, _mlb_event(), 5)
    assert rec is not None
    assert rec["metadata"] == {"playerName": "Nick Gonzales", "lineLabel": "1+", "playerId": 515}
    assert rec["sides"][0]["team_id"] == "3021"


def test_harvest_records_from_page_and_detail(tmp_path):
    page = _resp(200, {"events": [_mlb_event(markets=[_spread_market()])]})
    total = {
        "id": "1", "slug": "tsc-mlb-pit-det-2026-09-26-7pt5",
        "sportsMarketType": "baseball_team_full_game_total", "line": 7.5,
        "marketSides": [{"id": "9", "long": True, "description": "Over"},
                        {"id": "10", "long": False, "description": "Under"}],
    }
    # Live detail omits nothing, but the page's event fields must back-fill it.
    detail = _resp(200, {"event": {"markets": [_spread_market(), total]}})

    def _get(url: str, **_kwargs: Any) -> MagicMock:
        return detail if "/v1/events/" in url else page

    with patch("fetch.polymarket_usa.requests.get", side_effect=_get):
        records = harvest.harvest_records([_MLB])
    # Keyed on the gateway market id, not the symbol.
    assert sorted(records) == ["1", "1014120"]
    assert {r["event_id"] for r in records.values()} == {"123158"}
    assert {r["league_id"] for r in records.values()} == {5}
    assert {r["inner"] for r in records.values()} == {"mlb"}
    path = harvest.write_markets(tmp_path, records)
    lines = path.read_text().splitlines()
    assert [json.loads(line)["market_id"] for line in lines] == sorted(records)


def test_absorb_records_drops_market_seen_on_two_events():
    out: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    harvest._absorb_records(_mlb_event(markets=[_spread_market()]), _MLB, out, conflicts)
    harvest._absorb_records(
        _mlb_event(id=999, markets=[_spread_market()]), _MLB, out, conflicts,
    )
    assert out == {}
    assert conflicts == {"1014120"}

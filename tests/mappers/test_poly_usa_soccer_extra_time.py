"""Polymarket US soccer player props count extra time, so they map only where it cannot be played.

Venue text on every soccer player prop (gateway, 2026-10-21): "Extra time is included if
played. Penalty shootouts are not included if played." Optic's player_goals is a 90-minute
market. Stage labels are Optic's /fixtures/active ``season_type`` values seen on 2026-10-21.
"""

from __future__ import annotations

import json

import pytest

from mappers.exchanges import optic
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_extra_time import (
    blocks_player_prop,
    extra_time_possible,
    held_fixture_keys,
)
from mappers.exchanges.polymarket_usa_players import build_player_index
from mappers.pipeline import (
    _build_optic_usa_index,
    _strip_unverified_usa_passthrough,
    _usa_bind_events,
    _usa_market_rows,
    _usa_slug_fixtures,
    _usa_stamp_rows,
    row_key,
)
from mappers.shared import CanonicalRow

_EVENT = {
    "league_id": 16,
    "event_id": "172233",
    "event_ticker": "lal-lev-ath-2026-10-21",
    "event_start": "2026-10-21T18:00:00Z",
    "sportradar_game_id": "sr:sport_event:74801144",
    "teams": [
        {"id": "3447", "abbreviation": "lev", "name": "Levante UD", "league": "lal"},
        {"id": "3445", "abbreviation": "ath", "name": "Athletic Club", "league": "lal"},
    ],
}
# fetch.polymarket_usa.market_record of two live markets on that event (ids kept, extras trimmed).
_PROP_SLUG = "astatc-lal-lev-ath-2026-10-21-g-lalbrugui-gte3"
_PROP = {
    **_EVENT,
    "market_id": "1628064",
    "slug": _PROP_SLUG,
    "sports_market_type": "soccer_player_goals",
    "market_type": "props",
    "line": 3,
    "metadata": {"playerName": "Brugui", "playerId": 8038, "lineLabel": "3+", "teamId": 3447},
    "sides": [
        {"id": "3255602", "long": True, "description": "Yes", "team_id": "3447"},
        {"id": "3255603", "long": False, "description": "No", "team_id": "3447"},
    ],
}
_WIN_SLUG = "atc-lal-lev-ath-2026-10-21-lev"
_WIN = {
    **_EVENT,
    "market_id": "1601336",
    "slug": _WIN_SLUG,
    "sports_market_type": "soccer_team_full_time_winner",
    "market_type": "drawable_outcome",
    "line": None,
    "metadata": {},
    "sides": [
        {"id": "3202146", "long": True, "description": "Yes", "team_id": "3447"},
        {"id": "3202147", "long": False, "description": "No", "team_id": "3447"},
    ],
}
# Optic 202610212DF4375B as the league phase it is, and the same game labelled as a cup tie.
_LEAGUE = optic.Fixture(
    fixture_id="202610212DF4375B",
    game_id="G",
    sportradar_id="74801144",
    start_et="2026-10-21T14:00:00",
    start_date="2026-10-21T18:00:00Z",
    home="LEV",
    away="ATH",
    home_name="Levante UD",
    away_name="Athletic Club Bilbao",
    team_map={},
    odds=[],
    is_live=False,
    league_id="spain_-_la_liga",
    season_type="Regular Season",
)
_TIE = _LEAGUE._replace(league_id="spain_-_copa_del_rey", season_type="Round of 32")


def _odd(oid: str, market_id: str, slug: str | None = None) -> optic.Odd:
    src = {"Polymarket (USA)": {"market_id": slug}} if slug else {}
    return optic.Odd(id=oid, market_id=market_id, grouping_key="default", source_ids=src)


def _row(fx: optic.Fixture, market_type: str, entity: str | None, line: float | None, side: str, oid: str):
    return CanonicalRow(
        league="laliga",
        start_date=fx.start_date,
        home=fx.home,
        away=fx.away,
        market_type=market_type,
        entity=entity,
        line=line,
        side=side,
        optic_id=oid,
    )


def _rows(fx: optic.Fixture) -> list[CanonicalRow]:
    return [_row(fx, "player_goals", "brugui", 2.5, "over", "g"), _row(fx, "moneyline_3way", None, None, "LEV", "w")]


def _market(record: dict) -> pus.UsMarket:
    market = pus.parse_market(json.loads(json.dumps(record)))
    assert market is not None
    return market


def _run(
    fx: optic.Fixture, odds: dict[str, optic.Odd], records: tuple[dict, ...] = (_PROP, _WIN)
) -> tuple[dict[tuple, CanonicalRow], dict[str, int]]:
    """Bind → derive → strip → stamp, as _run_polymarket_usa_pass does for a soccer league."""
    markets = [_market(r) for r in records]
    row_index = {row_key(r): r for r in _rows(fx)}
    stats = {"stamped": 0, "dropped_no_optic": 0, "no_bets": 0, "agree": 0, "conflict": 0, "stripped": 0}
    binds = _usa_bind_events(
        markets,
        [fx],
        pus.TeamAliases(usa={}, kalshi={}),
        _usa_slug_fixtures(_build_optic_usa_index(row_index, odds), [fx]),
        person=False,
        stats=stats,
    )
    computed = _usa_market_rows(markets, binds, build_player_index(row_index, "laliga"), "laliga", stats)
    held = held_fixture_keys([fx])
    stats["stripped"] = _strip_unverified_usa_passthrough(row_index, odds, markets, binds, computed, None, held)
    _usa_stamp_rows(computed, _build_optic_usa_index(row_index, odds), row_index, stats, odds, None)
    return row_index, stats


def _stamped(row_index: dict[tuple, CanonicalRow]) -> dict[str, tuple[str, str | None]]:
    return {
        r.market_type: (r.polymarket_usa_market_id, r.polymarket_usa_side)
        for r in row_index.values()
        if r.polymarket_usa_market_id
    }


@pytest.mark.parametrize(
    "league_id, stage",
    [
        ("spain_-_la_liga", "Regular Season"),
        ("usa_-_major_league_soccer", "Regular Season"),
        ("mexico_-_liga_mx", "Apertura"),
        ("uefa_-_champions_league", "Group Stage"),
        ("uefa_-_nations_league", "Group A"),
    ],
)
def test_league_phase_cannot_reach_extra_time(league_id: str, stage: str) -> None:
    assert not extra_time_possible(_LEAGUE._replace(league_id=league_id, season_type=stage))


@pytest.mark.parametrize(
    "league_id, stage",
    [
        ("germany_-_dfb_pokal", "Round 2"),
        ("england_-_efl_cup", "Round of 16"),
        ("brazil_-_copa_do_brasil", "Semifinals"),
        ("uefa_-_champions_league", "Playoffs"),
        ("uefa_-_champions_league", "Round of 16"),
        ("mexico_-_liga_mx", "Quarterfinals"),
        ("international_-_friendlies", "N/A"),
        ("spain_-_la_liga", ""),  # a fixture fetched without the stage
    ],
)
def test_knockout_unlisted_or_missing_stage_counts_as_extra_time_possible(league_id: str, stage: str) -> None:
    assert extra_time_possible(_LEAGUE._replace(league_id=league_id, season_type=stage))


@pytest.mark.parametrize("market_id", ["to_advance", "player_goals_incl_et", "extra_time_moneyline"])
def test_a_quoted_tie_market_overrides_a_league_phase_label(market_id: str) -> None:
    assert extra_time_possible(_LEAGUE._replace(odds=[_odd("x", market_id)]))


def test_only_soccer_player_props_are_held() -> None:
    assert blocks_player_prop("soccer_player_goals", _TIE)
    assert blocks_player_prop("soccer_player_goalkeeper_saves", _TIE)
    assert not blocks_player_prop("soccer_player_goals", _LEAGUE)
    assert not blocks_player_prop("soccer_team_full_time_winner", _TIE)
    assert not blocks_player_prop("basketball_player_points", _TIE)


def test_fixture_carries_optic_league_and_stage() -> None:
    record = {
        "id": "202610212DF4375B",
        "game_id": "G",
        "start_date": "2026-10-21T18:00:00Z",
        "status": "unplayed",
        "is_live": False,
        "season_type": "Regular Season",
        "league": {"id": "spain_-_la_liga"},
        "home_competitors": [{"id": "H", "name": "Levante UD", "abbreviation": "LEV"}],
        "away_competitors": [{"id": "A", "name": "Athletic Club Bilbao", "abbreviation": "ATH"}],
    }
    cfg = optic.OpticConfig(league_id="spain_-_la_liga", table_types={})
    fx = optic._fixture_from_game(optic.Game(**record), cfg)
    assert fx is not None and (fx.league_id, fx.season_type) == ("spain_-_la_liga", "Regular Season")
    bare = optic._fixture_from_game(optic.Game(**{k: v for k, v in record.items() if k != "season_type"}), cfg)
    assert bare is not None and bare.season_type == ""


def test_league_phase_prop_maps_onto_optic_player_goals() -> None:
    row_index, stats = _run(_LEAGUE, {})
    assert _stamped(row_index) == {"player_goals": (_PROP_SLUG, "yes"), "moneyline_3way": (_WIN_SLUG, "yes")}
    assert stats.get("extra_time", 0) == 0


def test_tie_holds_the_prop_and_still_maps_the_team_market() -> None:
    row_index, stats = _run(_TIE, {})
    assert _stamped(row_index) == {"moneyline_3way": (_WIN_SLUG, "yes")}
    assert stats["extra_time"] == 1


def test_optic_passthrough_onto_the_90_minute_market_is_stripped_on_a_tie() -> None:
    odds = {"g": _odd("g", "player_goals", _PROP_SLUG)}
    row_index, stats = _run(_TIE, odds)
    assert stats["stripped"] == 1 and "Polymarket (USA)" not in odds["g"].source_ids
    assert "player_goals" not in _stamped(row_index)


def test_optic_passthrough_onto_the_90_minute_market_is_kept_in_the_league_phase() -> None:
    odds = {"g": _odd("g", "player_goals", _PROP_SLUG)}
    _row_index, stats = _run(_LEAGUE, odds)
    assert stats["stripped"] == 0 and stats["agree"] == 1
    assert "Polymarket (USA)" in odds["g"].source_ids


@pytest.mark.parametrize("records", [(_WIN,), ()], ids=["prop-missing-from-snapshot", "empty-snapshot"])
def test_passthrough_of_a_symbol_the_snapshot_lacks_is_stripped_on_a_tie(records: tuple[dict, ...]) -> None:
    """An event whose detail fetch failed has no props in the snapshot; Optic's hang still goes."""
    odds = {"g": _odd("g", "player_goals", _PROP_SLUG)}
    _row_index, stats = _run(_TIE, odds, records)
    assert stats["stripped"] == 1 and "Polymarket (USA)" not in odds["g"].source_ids


def test_passthrough_of_a_symbol_the_snapshot_lacks_is_kept_in_the_league_phase() -> None:
    odds = {"g": _odd("g", "player_goals", _PROP_SLUG)}
    _row_index, stats = _run(_LEAGUE, odds, (_WIN,))
    assert stats["stripped"] == 0 and "Polymarket (USA)" in odds["g"].source_ids

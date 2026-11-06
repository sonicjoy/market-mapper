"""Kalshi NFL team first touchdown scorer (KXNFLTEAMFIRSTTD): one Yes per player, the No leg never maps.

Real shape (Kalshi API, 2026-10-22 NE v CHI): series scope "Touchdowns" (KXNFLFIRSTTD shares it), one event per
team whose scope names the team ("First Chicago TD" / "First New England TD"), title "<Player>: 1st Chicago
Touchdown", custom_strike carries football_player and football_team ids. A "No Touchdown" contract per event
carries a player id of its own. Optic labels the same contracts "<team> :: <player>" and matches on the player.
"""

from __future__ import annotations

import pytest

from mappers.exchanges.kalshi import (
    KalshiConfig,
    Market,
    YesNoMarket,
    build_rows,
    parse_typed_market,
    scoped_market_type,
)
from mappers.shared import normalize_player_name
from mappers.sport import Sport
from mappers.vocab.kalshi_scopes import team_first_td_type

FOOTBALL = KalshiConfig(sport=Sport.FOOTBALL)


def _leg(player: str, team: str = "Chicago", **over) -> Market:
    fields = {
        "event_ticker": "E",
        "ticker": f"T-{player}",
        "title": f"{player}: 1st {team} Touchdown",
        "yes_sub_title": player,
        "strike_type": "structured",
        "custom_strike": {"football_player": "p-id", "football_team": "t-id"},
        "competition_scope": f"First {team} TD",
        "series_scope": "Touchdowns",
    }
    return Market(**{**fields, **over})


@pytest.mark.parametrize("team", ["Chicago", "New England", "Las Vegas"])
def test_the_team_named_event_scope_types_the_market(team):
    parsed = parse_typed_market(_leg("D'Andre Swift", team), FOOTBALL)
    assert isinstance(parsed, YesNoMarket)
    assert parsed.market_type.value == "team_first_touchdown_scorer"
    assert (parsed.player_name, parsed.yes_only) == ("D'Andre Swift", True)


def test_only_the_yes_leg_maps():
    rows = build_rows(
        "2026-10-22", "CHI", "NE", [_leg("D'Andre Swift"), _leg("Hunter Henry", "New England")], FOOTBALL, league="nfl"
    )
    assert {r.market_type for r in rows} == {"team_first_touchdown_scorer"}
    assert [(r.side, r.kalshi_side) for r in rows] == [("yes", "yes")] * 2


def test_the_entity_is_the_one_optic_derives_from_its_team_prefixed_selection():
    optic_selection = "Chicago Bears :: D'Andre Swift"
    optic_entity = normalize_player_name(optic_selection.rsplit(" :: ", 1)[-1])
    rows = build_rows("2026-10-22", "CHI", "NE", [_leg("D'Andre Swift")], FOOTBALL, league="nfl")
    assert [r.entity for r in rows] == [optic_entity]


def test_a_ticker_optic_stamps_keeps_the_player_only_entity():
    leg = _leg("Max Bredeson", "Minnesota")
    stamped = {leg.ticker: "Minnesota Vikings :: Max Bredeson"}
    rows = build_rows("2026-10-25", "MIN", "IND", [leg], FOOTBALL, league="nfl", optic_player_names=stamped)
    assert [r.entity for r in rows] == ["max_bredeson"]


def test_the_prefix_is_kept_for_every_other_market():
    leg = _leg("Jaxon Smith-Njigba", competition_scope="First TD", title="Jaxon Smith-Njigba: 1st Touchdown")
    stamped = {leg.ticker: "Seattle Seahawks :: Jaxon Smith-Njigba"}
    rows = build_rows("2026-10-25", "SEA", "KC", [leg], FOOTBALL, league="nfl", optic_player_names=stamped)
    assert [r.entity for r in rows] == [normalize_player_name("Seattle Seahawks :: Jaxon Smith-Njigba")]


def test_the_no_touchdown_contract_is_a_player_row_named_for_it_that_no_optic_odd_matches():
    parsed = parse_typed_market(_leg("No Touchdown"), FOOTBALL)
    assert isinstance(parsed, YesNoMarket) and parsed.player_name == "No Touchdown"


def test_the_per_player_first_td_series_is_unchanged():
    leg = _leg(
        "Jaxon Smith-Njigba",
        competition_scope="First TD",
        series_scope="Touchdowns",
        title="Jaxon Smith-Njigba: 1st Touchdown",
    )
    typed = scoped_market_type(leg, FOOTBALL)
    assert typed is not None and typed.value == "first_touchdown_scorer"


def test_the_first_team_to_score_series_keeps_its_literal_type_under_the_same_series_scope():
    leg = _leg("Chicago", competition_scope="First Team to Score a TD", series_scope="Touchdowns")
    typed = scoped_market_type(leg, FOOTBALL)
    assert typed is not None and typed.value == "first_team_touchdown"


@pytest.mark.parametrize(
    "over",
    [
        {"series_scope": "First TD"},
        {"series_scope": None},
        {"competition_scope": "First Chicago Touchdown"},
        {"competition_scope": "Chicago TD"},
        {"competition_scope": None},
        {"custom_strike": {"football_team": "t-id"}},
        {"custom_strike": {"football_player": "p-id"}},
        {"custom_strike": {"football_player": "", "football_team": "t-id"}},
        {"custom_strike": None},
    ],
)
def test_anything_short_of_the_typed_shape_stays_unmapped(over):
    assert scoped_market_type(_leg("D'Andre Swift", **over), FOOTBALL) is None


def test_the_helper_alone_needs_every_part_of_the_shape():
    strike = {"football_player": "p", "football_team": "t"}
    typed = team_first_td_type(Sport.FOOTBALL, "Touchdowns", "First Chicago TD", strike)
    assert typed is not None and typed.value == "team_first_touchdown_scorer"
    assert team_first_td_type(Sport.FOOTBALL, " Touchdowns ", " First Chicago TD ", strike) is not None
    assert team_first_td_type(Sport.FOOTBALL, "Touchdowns", "First Chicago TD", [strike]) is None


@pytest.mark.parametrize("sport", [Sport.HOCKEY, Sport.BASKETBALL, Sport.SOCCER])
def test_other_sports_never_map_it(sport):
    assert scoped_market_type(_leg("D'Andre Swift"), KalshiConfig(sport=sport)) is None


def test_other_player_yes_no_still_maps_both_legs():
    leg = _leg(
        "Cale Makar",
        competition_scope="1st Goalscorer",
        series_scope="1st Goalscorer",
        custom_strike={"hockey_player": "p"},
    )
    rows = build_rows("2026-10-22", "COL", "VGK", [leg], KalshiConfig(sport=Sport.HOCKEY), league="nhl")
    assert sorted(r.side for r in rows) == ["no", "yes"]

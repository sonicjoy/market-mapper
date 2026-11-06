"""Football NFL/NCAAF BQ market-rule pin payload."""

from mappers.control_plane.rows import MarketRuleRow
from mappers.market_types import MarketType
from mappers.seed.football_nfl_ncaaf_rules import (
    build_football_nfl_ncaaf_payload,
    desired_market_rule_pins,
    missing_market_rule_pins,
)


def _row(
    league: str,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    canonical: str,
) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"mr_{league}_{sportsbook}_{source_key}",
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action="map",
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="id_verified",
    )


def test_desired_pins_include_new_football_extras():
    nfl = desired_market_rule_pins("nfl")
    keys = {
        (pin.sportsbook, pin.source_key, pin.canonical_market_type)
        for pin in nfl
    }
    assert ("optic", "moneyline", "moneyline") in keys
    assert ("optic", "player_passing_attempts", "player_passing_attempts") in keys
    assert ("optic", "team_total_touchdowns", "team_total_touchdowns") in keys
    assert ("optic", "1st_half_team_total", "1h_team_total") in keys
    # Polymarket US maps from its own enum table, never tip rules.
    assert not any(book == "polymarket_usa" for book, _key, _mt in keys)
    assert ("optic", "player_rushing_+_receiving_yards", "player_rushing_+_receiving_yards") in keys
    assert ("optic", "total_touchdowns", "total_touchdowns") in keys
    assert ("optic", "will_there_be_overtime", "will_there_be_overtime") in keys
    assert ("optic", "race_to_14_points", "race_to_points") in keys
    assert ("optic", "race_to_10_points", "race_to_points") in keys
    assert ("crypto.com", "Total Rushing + Receiving Yards", "player_rushing_+_receiving_yards") in keys
    assert ("polymarket", "spread", "point_spread") in keys
    # Kalshi maps from its typed scopes, never tip rules.
    assert not any(book == "kalshi" for book, _key, _mt in keys)
    assert ("px", "Moneyline", "moneyline") in keys
    assert ("novig", "MONEY", "moneyline") in keys
    assert ("novig", "PASSING_YARDS", "player_passing_yards") in keys
    assert ("novig", "RECEIVING_YARDS", "player_receiving_yards") in keys
    assert ("novig", "TOUCHDOWNS", "player_touchdowns") in keys
    assert ("optic", "player_tackles_+_assists", "player_tackles_+_assists") in keys
    assert ("optic", "player_kicking_points", "player_kicking_points") in keys
    assert ("novig", "RUSHING_AND_RECEIVING_YARDS", "player_rushing_+_receiving_yards") in keys
    assert ("novig", "PASSING_AND_RUSHING_YARDS", "player_passing_+_rushing_yards") in keys
    assert ("novig", "LONGEST_COMPLETION", "player_longest_passing_completion") in keys
    assert ("novig", "TACKLES_ASSISTS", "player_tackles_+_assists") in keys
    assert ("novig", "KICKING_POINTS", "player_kicking_points") in keys
    assert ("novig", "FIRST_TOUCHDOWN_SCORER", "first_touchdown_scorer") in keys
    assert ("huddle", "RESULT", "moneyline") in keys
    assert ("huddle", "PLAYER_PASSING_YARDS_OVER_UNDER", "player_passing_yards") in keys
    huddle_ignores = {
        pin.source_key for pin in nfl
        if pin.sportsbook == "huddle" and pin.action == "ignore"
    }
    assert "POINT_OVER_UNDER_EXC_OT" in huddle_ignores
    assert ("novig", "MONEY_1H", "1h_winner_3way") in keys
    assert ("novig", "SPREAD_1H", "1h_point_spread") in keys
    assert ("crypto.com", "Moneyline", "moneyline") in keys
    assert ("crypto.com", "To Score a Touchdown", "player_touchdowns") in keys
    touchdown = next(
        pin for pin in nfl
        if pin.sportsbook == "crypto.com" and pin.source_key == "To Score a Touchdown"
    )
    assert touchdown.source_key_type == "player_prop_contract_type"
    assert "player_prop" not in (touchdown.notes or "")
    assert ("crypto.com", "Interceptions Thrown", "player_interceptions") in keys
    crypto_team = next(
        pin for pin in nfl
        if pin.sportsbook == "crypto.com"
        and pin.source_key_type == "team_prop_contract_type"
        and pin.source_key == "Total Points"
    )
    assert crypto_team.canonical_market_type == "team_total"


def test_ncaaf_pins_no_kalshi_or_huddle():
    ncaaf = desired_market_rule_pins("ncaaf")
    assert not any(pin.sportsbook == "kalshi" for pin in ncaaf)
    huddle = {pin.source_key for pin in ncaaf if pin.sportsbook == "huddle"}
    assert huddle == set()


def test_missing_pins_skip_existing_tip_rows():
    tip = [
        _row("nfl", "optic", "market_id", "player_passing_attempts", "player_passing_attempts"),
    ]
    miss = missing_market_rule_pins("nfl", tip)
    miss_keys = {(p.sportsbook, p.source_key) for p in miss}
    assert ("optic", "player_passing_attempts") not in miss_keys
    assert ("optic", "team_total_touchdowns") in miss_keys


def test_build_payload_groups_by_league():
    payload = build_football_nfl_ncaaf_payload([])
    assert len(payload.market_rules) == 2
    leagues = {group.league for group in payload.market_rules}
    assert leagues == {"nfl", "ncaaf"}
    nfl_group = next(g for g in payload.market_rules if g.league == "nfl")
    assert any(
        pin.canonical_market_type == MarketType.TEAM_TOTAL_FIELD_GOALS.value
        for pin in nfl_group.rules
    )

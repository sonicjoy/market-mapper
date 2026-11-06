"""DKEX market rule seed."""

from __future__ import annotations

from mappers.seed.dkex_market_rules import (
    desired_market_rule_pins,
    format_market_period_key,
)


def test_format_market_period_key() -> None:
    assert format_market_period_key("win", "fg") == "WIN:FG"


def test_nfl_pins_include_game_lines() -> None:
    keys = {pin.source_key for pin in desired_market_rule_pins("nfl")}
    assert "WIN:FG" in keys
    assert "MOVY:FG" in keys
    assert not any(key.startswith("WCHP") for key in keys)


def test_soccer_pins_cover_the_soccer_crosswalk() -> None:
    keys = {pin.source_key for pin in desired_market_rule_pins("epl")}
    assert keys == {"DWIN:FG", "MOVY:FG", "TGLS:FG", "BTMSC:FG", "SGL1:FG"}


def test_soccer_venue_tokens() -> None:
    from mappers.control_plane.gap_fix_dkex_leagues import venue_token_for_slug

    assert venue_token_for_slug("epl") == "EPL"
    assert venue_token_for_slug("brazil_serie_a") == "BSA"
    assert venue_token_for_slug("argentina_primera") == "LPA"
    assert venue_token_for_slug("england_championship") == "EFLC"
    assert venue_token_for_slug("italy_coppa_italia") == "COPPAIT"
    # The League Cup is its own competition, not the Championship.
    assert venue_token_for_slug("efl_cup") == "ELC"

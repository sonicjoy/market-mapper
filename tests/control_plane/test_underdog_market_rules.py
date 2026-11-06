"""Underdog market-rule seed pins."""

from __future__ import annotations

from mappers.seed.underdog_market_rules import (
    SOURCE_KEY_TYPE,
    desired_market_rule_pins,
    format_product_period_key,
    parse_product_period_key,
)


def test_product_period_key_roundtrip() -> None:
    assert format_product_period_key("GAMEWIN", "") == "GAMEWIN"
    assert format_product_period_key("SPREAD", "1H") == "SPREAD:1H"
    assert parse_product_period_key("TOTAL:1Q") == ("TOTAL", "1Q")


def test_nfl_includes_game_lines_and_props() -> None:
    pins = desired_market_rule_pins("nfl")
    keys = {(p.source_key_type, p.source_key) for p in pins}
    assert SOURCE_KEY_TYPE == "product_period"
    assert ("product_period", "GAMEWIN") in keys
    assert ("product_period", "PASSYDS") in keys


def test_mlb_game_lines_team_total_rfi_and_player_props() -> None:
    pins = desired_market_rule_pins("mlb")
    keys = {p.source_key for p in pins}
    assert keys == {
        "GAMEWIN", "SPREAD", "TOTAL", "TEAMTOTAL", "RFI",
        "HITS", "KS", "HRR", "HR", "TB", "RBI",
    }


def test_nhl_takes_the_three_game_lines_only() -> None:
    """Team goals has no Optic hockey row, so it gets no rule (it stays unmapped)."""
    assert {p.source_key for p in desired_market_rule_pins("nhl")} == {"GAMEWIN", "SPREAD", "TOTAL"}


def test_new_soccer_leagues_take_the_soccer_crosswalk() -> None:
    for league in ("international_friendlies", "brazil_serie_a", "saudi_pro_league", "argentina_primera_nacional"):
        pins = desired_market_rule_pins(league)
        assert {p.source_key for p in pins} == {
            "GAMEWIN", "SPREAD", "TOTAL", "BTTS", "GAMEWIN:1H", "SPREAD:1H", "TOTAL:1H",
        }, league
        assert {p.canonical_market_type for p in pins if p.source_key == "GAMEWIN"} == {"moneyline_3way"}

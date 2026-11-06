"""Emit DKEX market-rule pins from the Python crosswalk."""

from __future__ import annotations

from mappers.control_plane.console_mapping_clone import rule_row_key
from mappers.control_plane.models import (
    BatchChangesPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import MarketRuleRow
from mappers.market_types import MarketType
from mappers.vocab import dkex_markets

SOURCE_KEY_TYPE = "market_period"
_NOTE = (
    "DKEX: mirror mappers/vocab/dkex_markets.py (market, period) "
    "on the BQ tip for Coverage and classify overlay."
)

_LEAGUE_TABLE: dict[str, dict[tuple[str, str], MarketType]] = {
    "nfl": dkex_markets.FOOTBALL,
    "ncaaf": dkex_markets.FOOTBALL,
    "mlb": dkex_markets.BASEBALL,
    "wnba": dkex_markets.BASKETBALL,
    "nba": dkex_markets.BASKETBALL,
    "nhl": dkex_markets.HOCKEY,
    "ufc": dkex_markets.UFC,
    "atp": dkex_markets.TENNIS,
    "wta": dkex_markets.TENNIS,
    **dict.fromkeys((
        "epl", "england_championship", "la_liga", "ucl", "europa_league",
        "europa_conference_league", "italy_serie_a", "italy_coppa_italia",
        "germany_bundesliga", "france_ligue_1", "brazil_serie_a",
        "argentina_primera", "mls", "liga_mx", "international_club_friendlies",
    ), dkex_markets.SOCCER),
}

_GAME_LINE_LEAGUES = tuple(_LEAGUE_TABLE.keys())


def format_market_period_key(market: str, period: str) -> str:
    """Serialize ``(market, period)`` for ``mapping_market_rules.source_key``."""
    mkt = market.strip().upper()
    per = period.strip().upper()
    return f"{mkt}:{per}" if per else mkt


def _pin(league: str, source_key: str, canonical: MarketType) -> MarketRulePin:
    return MarketRulePin(
        league=league,
        sportsbook="dkex",
        rule_kind="taxonomy",
        source_key_type=SOURCE_KEY_TYPE,
        source_key=source_key,
        action="map",
        canonical_market_type=canonical.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        match_operator="exact",
        notes=_NOTE,
    )


def desired_market_rule_pins(league: str) -> list[MarketRulePin]:
    """DKEX pins for one tip league slug."""
    table = _LEAGUE_TABLE.get(league.strip().casefold())
    if table is None:
        return []
    return [
        _pin(league, format_market_period_key(market, period), mt)
        for (market, period), mt in sorted(table.items())
    ]


def missing_market_rule_pins(
    league: str,
    tip_rules: list[MarketRuleRow],
) -> list[MarketRulePin]:
    """Pins absent from the live tip."""
    have = {
        f"rule:{row.league}:{row.sportsbook}:{row.source_key_type}:{row.source_key}"
        for row in tip_rules
        if row.league == league
        and row.enabled
        and not row.tombstone
    }
    return [
        pin
        for pin in desired_market_rule_pins(league)
        if rule_row_key(league, pin) not in have
    ]


def build_dkex_game_line_payload(
    tip_rules: list[MarketRuleRow],
    *,
    leagues: tuple[str, ...] = _GAME_LINE_LEAGUES,
) -> BatchChangesPayload:
    """Batch payload for every missing DKEX market pin."""
    pins: list[MarketRulePin] = []
    for league in leagues:
        pins.extend(missing_market_rule_pins(league, tip_rules))
    if not pins:
        return BatchChangesPayload()
    groups = [
        MappingMarketRulesPayload(
            league=league,
            rules=[pin for pin in pins if pin.league == league],
            evidence_refs=[
                f"gap:dkex:market:{league}",
                "docs/adding-dkex.md",
            ],
        )
        for league in leagues
        if any(pin.league == league for pin in pins)
    ]
    return BatchChangesPayload(market_rules=groups)

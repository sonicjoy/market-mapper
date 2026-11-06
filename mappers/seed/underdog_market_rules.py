"""Emit Underdog UDX game-line market-rule pins from the Python crosswalk."""

from __future__ import annotations

from mappers.control_plane.console_mapping_clone import rule_row_key
from mappers.control_plane.models import (
    BatchChangesPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import MarketRuleRow
from mappers.control_plane.underdog_legacy_vocab import BY_VENUE_LEAGUE, VENUE_TOKEN_TO_LEAGUE_SLUG
from mappers.market_types import MarketType

SOURCE_KEY_TYPE = "product_period"
_NOTE = (
    "Underdog UDX: mirror mappers/vocab/underdog_markets.py (product, period) "
    "on the BQ tip for Coverage and classify overlay."
)

_LEAGUE_VENUE: dict[str, str] = {
    slug: venue
    for venue, slug in VENUE_TOKEN_TO_LEAGUE_SLUG.items()
}

_GAME_LINE_LEAGUES = tuple(_LEAGUE_VENUE.keys())


def format_product_period_key(product: str, period: str) -> str:
    """Serialize ``(product, period)`` for ``mapping_market_rules.source_key``."""
    prod = product.strip().upper()
    per = period.strip().upper()
    return f"{prod}:{per}" if per else prod


def parse_product_period_key(key: str) -> tuple[str, str]:
    """Inverse of :func:`format_product_period_key`."""
    raw = key.strip().upper()
    if ":" in raw:
        product, period = raw.split(":", 1)
        return product, period
    return raw, ""


def _pin(league: str, source_key: str, canonical: MarketType) -> MarketRulePin:
    return MarketRulePin(
        league=league,
        sportsbook="underdog",
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
    """Underdog pins for one tip league slug."""
    venue = _LEAGUE_VENUE.get(league.strip().casefold())
    if venue is None:
        return []
    table = BY_VENUE_LEAGUE.get(venue)
    if table is None:
        return []
    return [
        _pin(league, format_product_period_key(product, period), mt)
        for (product, period), mt in sorted(table.items())
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


def build_underdog_game_line_payload(
    tip_rules: list[MarketRuleRow],
    *,
    leagues: tuple[str, ...] = _GAME_LINE_LEAGUES,
) -> BatchChangesPayload:
    """Batch payload for every missing Underdog game-line pin."""
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
                f"gap:underdog:market:{league}",
                "docs/adding-underdog.md",
            ],
        )
        for league in leagues
        if any(pin.league == league for pin in pins)
    ]
    return BatchChangesPayload(market_rules=groups)

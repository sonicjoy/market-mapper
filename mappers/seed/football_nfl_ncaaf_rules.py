"""Emit NFL/NCAAF market-rule pins from the Python Path 2 tables.

Maps Optic, Polymarket, ProphetX, Novig, crypto.com, and Huddle
rows (Polymarket US maps from its own enum table, not tip rules) onto the activated BQ tip so classify matches
the in-code registry.
"""

from __future__ import annotations

from mappers.control_plane.console_mapping_clone import rule_row_key
from mappers.control_plane.models import (
    BatchChangesPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import MarketRuleRow
from mappers.market_types import MarketType
from mappers.vocab import novig_markets
from mappers.vocab.football_huddle import EXC_OT_CODES, GAME_TYPES
from mappers.vocab.football_markets import (
    FOOTBALL_MARKET_TYPES,
    FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS,
    FOOTBALL_OPTIC_TABLE_TYPES,
    NCAAF_CRYPTO,
    NFL_CRYPTO,
    NFL_NCAAF_LEAGUES,
    NFL_PX,
)

_NOTE = (
    "NFL/NCAAF Path 2: mirror Python Optic / Polymarket / PX / "
    "Novig / crypto.com / Huddle tables on the BQ tip."
)


def _pin(
    *,
    league: str,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    action: str,
    canonical: MarketType | None,
    match_operator: str = "exact",
    notes: str = _NOTE,
) -> MarketRulePin:
    return MarketRulePin(
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action=action,
        canonical_market_type=canonical.value if canonical else None,
        priority=100,
        enabled=True,
        confidence="id_verified",
        match_operator=match_operator,
        notes=notes,
    )


def desired_market_rule_pins(league: str) -> list[MarketRulePin]:
    """Full NFL/NCAAF football taxonomy the Python registry wires."""
    if league not in NFL_NCAAF_LEAGUES:
        return []
    pins = [
        _pin(
            league=league,
            sportsbook="optic",
            source_key_type="market_id",
            source_key=optic_id,
            action="map",
            canonical=mt,
        )
        for optic_id, mt in {
            **FOOTBALL_OPTIC_TABLE_TYPES,
            **FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS,
        }.items()
    ]
    pins.extend(_poly_pins(league))
    pins.extend(_px_pins(league))
    pins.extend(_novig_pins(league))
    pins.extend(_crypto_football_pins(league))
    pins.extend(_huddle_pins(league))
    return pins


def _poly_pins(league: str) -> list[MarketRulePin]:
    return [
        _pin(
            league=league,
            sportsbook="polymarket",
            source_key_type="kind",
            source_key=kind,
            action="map",
            canonical=mt,
        )
        for kind, mt in FOOTBALL_MARKET_TYPES.items()
    ]


def _px_pins(league: str) -> list[MarketRulePin]:
    if league != "nfl":
        return []
    pins = [
        _pin(
            league=league,
            sportsbook="px",
            source_key_type="market_name",
            source_key=name,
            action="map",
            canonical=mt,
        )
        for name, mt in NFL_PX.exact.items()
    ]
    pins.extend(
        _pin(
            league=league,
            sportsbook="px",
            source_key_type="market_name",
            source_key=suffix,
            action="map",
            canonical=mt,
            match_operator="suffix",
        )
        for suffix, mt in NFL_PX.suffix
    )
    return pins


def _novig_pins(league: str) -> list[MarketRulePin]:
    return [
        _pin(
            league=league,
            sportsbook="novig",
            source_key_type="market_type",
            source_key=market_type,
            action="map",
            canonical=mt,
        )
        for market_type, mt in novig_markets.FOOTBALL.items()
    ]


def _huddle_pins(league: str) -> list[MarketRulePin]:
    """NFL-only: Huddle game-level 1-1 maps plus EXC_OT ignores."""
    if league != "nfl":
        return []
    pins = [
        _pin(
            league=league,
            sportsbook="huddle",
            source_key_type="market_code",
            source_key=code,
            action="map",
            canonical=mt,
        )
        for code, mt in GAME_TYPES.items()
    ]
    pins.extend(
        _pin(
            league=league,
            sportsbook="huddle",
            source_key_type="market_code",
            source_key=code,
            action="ignore",
            canonical=None,
        )
        for code in sorted(EXC_OT_CODES)
    )
    return pins


def _crypto_football_pins(league: str) -> list[MarketRulePin]:
    crypto = NFL_CRYPTO if league == "nfl" else NCAAF_CRYPTO
    if crypto is None:
        return []
    pins = [
        _pin(
            league=league,
            sportsbook="crypto.com",
            source_key_type="contract_type",
            source_key=key,
            action="map",
            canonical=mt,
            notes=_NOTE,
        )
        for key, mt in crypto.contract_types.items()
    ]
    pins.extend(
        _pin(
            league=league,
            sportsbook="crypto.com",
            source_key_type="player_prop_contract_type",
            source_key=key,
            action="map",
            canonical=mt,
            notes=_NOTE,
        )
        for key, mt in crypto.prop_contract_types.items()
    )
    pins.extend(
        _pin(
            league=league,
            sportsbook="crypto.com",
            source_key_type="team_prop_contract_type",
            source_key=key,
            action="map",
            canonical=mt,
            notes=_NOTE,
        )
        for key, mt in crypto.team_prop_contract_types.items()
    )
    return pins


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
        pin for pin in desired_market_rule_pins(league)
        if rule_row_key(league, pin) not in have
    ]


def build_football_nfl_ncaaf_payload(
    tip_rules: list[MarketRuleRow],
) -> BatchChangesPayload:
    """Batch payload for every missing NFL/NCAAF football pin."""
    pins: list[MarketRulePin] = []
    for league in sorted(NFL_NCAAF_LEAGUES):
        pins.extend(missing_market_rule_pins(league, tip_rules))
    if not pins:
        return BatchChangesPayload()
    groups = [
        MappingMarketRulesPayload(
            league=league,
            rules=[pin for pin in pins if pin.league == league],
        )
        for league in sorted(NFL_NCAAF_LEAGUES)
        if any(pin.league == league for pin in pins)
    ]
    return BatchChangesPayload(market_rules=groups)

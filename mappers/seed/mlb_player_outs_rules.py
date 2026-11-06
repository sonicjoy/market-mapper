"""Emit MLB player-prop market-rule pins for the BQ tip.

Optic pins mirror the Python baseball tables. Crypto.com
player props use ``player_prop_contract_type`` rows on the tip (no vocab).
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

MLB_LEAGUE = "mlb"
_NOTE = (
    "MLB player props: Optic pins from Python baseball tables "
    "(outs, RBIs, stolen bases)."
)
_PROP_PINS: tuple[tuple[MarketType, str], ...] = (
    (MarketType.PLAYER_OUTS, "player_outs"),
    (MarketType.PLAYER_RBIS, "player_rbis"),
    (MarketType.PLAYER_STOLEN_BASES, "player_stolen_bases"),
)
_CRYPTO_PROP_PINS: tuple[tuple[MarketType, str], ...] = (
    (MarketType.PLAYER_RBIS, "Total RBIs"),
)


def _pin(
    *,
    canonical: MarketType,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    notes: str = _NOTE,
) -> MarketRulePin:
    return MarketRulePin(
        league=MLB_LEAGUE,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action="map",
        canonical_market_type=canonical.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        match_operator="exact",
        notes=notes,
    )


def desired_market_rule_pins() -> list[MarketRulePin]:
    """MLB player-prop pins the Python registry wires."""
    pins: list[MarketRulePin] = []
    for canonical, optic_id in _PROP_PINS:
        pins.append(
            _pin(
                canonical=canonical,
                sportsbook="optic",
                source_key_type="market_id",
                source_key=optic_id,
            )
        )
    for canonical, crypto_contract in _CRYPTO_PROP_PINS:
        pins.append(
            _pin(
                canonical=canonical,
                sportsbook="crypto.com",
                source_key_type="player_prop_contract_type",
                source_key=crypto_contract,
            )
        )
    return pins


def missing_market_rule_pins(tip_rules: list[MarketRuleRow]) -> list[MarketRulePin]:
    """Pins absent from the live tip (map rows only)."""
    have = {
        f"rule:{row.league}:{row.sportsbook}:{row.source_key_type}:{row.source_key}"
        for row in tip_rules
        if row.league == MLB_LEAGUE
        and row.enabled
        and not row.tombstone
        and row.action == "map"
    }
    return [
        pin
        for pin in desired_market_rule_pins()
        if rule_row_key(MLB_LEAGUE, pin) not in have
    ]


def build_mlb_player_outs_payload(tip_rules: list[MarketRuleRow]) -> BatchChangesPayload:
    """Batch payload for every missing MLB player-prop pin."""
    pins = missing_market_rule_pins(tip_rules)
    if not pins:
        return BatchChangesPayload()
    return BatchChangesPayload(
        market_rules=[
            MappingMarketRulesPayload(league=MLB_LEAGUE, rules=pins),
        ],
    )

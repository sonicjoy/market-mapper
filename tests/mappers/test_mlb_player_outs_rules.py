"""MLB player-prop BQ market-rule pin payload."""

from mappers.control_plane.rows import MarketRuleRow
from mappers.market_types import MarketType
from mappers.seed.mlb_player_outs_rules import (
    build_mlb_player_outs_payload,
    desired_market_rule_pins,
    missing_market_rule_pins,
)

_ALL_PINS = (
    ("optic", "market_id", "player_outs", MarketType.PLAYER_OUTS),
    ("optic", "market_id", "player_rbis", MarketType.PLAYER_RBIS),
    ("crypto.com", "player_prop_contract_type", "Total RBIs", MarketType.PLAYER_RBIS),
    ("optic", "market_id", "player_stolen_bases", MarketType.PLAYER_STOLEN_BASES),
)


def _row(
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    canonical: MarketType,
    *,
    action: str = "map",
) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"mr_mlb_{sportsbook}_{source_key}",
        league="mlb",
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action=action,
        canonical_market_type=canonical.value if action == "map" else None,
        priority=100,
        enabled=True,
        confidence="id_verified",
    )


def test_desired_pins_cover_optic_and_no_kalshi() -> None:
    pins = desired_market_rule_pins()
    assert len(pins) == 4
    assert not [p for p in pins if p.sportsbook == "kalshi"]
    for book, key_type, key, canonical in _ALL_PINS:
        match = [
            p for p in pins
            if p.sportsbook == book
            and p.source_key_type == key_type
            and p.source_key == key
        ]
        assert len(match) == 1
        assert match[0].canonical_market_type == canonical.value


def test_missing_skips_existing_map_rows() -> None:
    tip = [
        _row(book, key_type, key, canonical)
        for book, key_type, key, canonical in _ALL_PINS
    ]
    assert missing_market_rule_pins(tip) == []


def test_build_payload_only_emits_missing() -> None:
    tip = [
        _row("optic", "market_id", "player_outs", MarketType.PLAYER_OUTS),
    ]
    payload = build_mlb_player_outs_payload(tip)
    assert len(payload.market_rules) == 1
    assert payload.market_rules[0].league == "mlb"
    assert len(payload.market_rules[0].rules) == 3
    keys = {
        (p.sportsbook, p.source_key_type, p.source_key)
        for p in payload.market_rules[0].rules
    }
    assert ("optic", "market_id", "player_rbis") in keys
    assert ("crypto.com", "player_prop_contract_type", "Total RBIs") in keys
    assert ("optic", "market_id", "player_stolen_bases") in keys

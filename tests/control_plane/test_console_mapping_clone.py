"""Clone-from market-rule pins copy the analogue league's rules, never Kalshi's."""

from mappers.control_plane.console_mapping_clone import clone_rule_pins
from mappers.control_plane.rows import MarketRuleRow


def _rule(league: str, sportsbook: str, source_key_type: str, source_key: str) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"{league}-{sportsbook}-{source_key}",
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action="map",
        canonical_market_type="moneyline",
        priority=100,
        enabled=True,
        confidence="manual",
    )


def test_clone_copies_book_rules_verbatim() -> None:
    pins = clone_rule_pins([_rule("boxing_matches", "px", "market_name", "")], "boxing_matches")
    assert [(p.sportsbook, p.source_key) for p in pins] == [("px", "")]


def test_clone_skips_kalshi_tip_rows() -> None:
    """Kalshi maps from its own typed fields; an old tip row is not copied onto a new league."""
    tip = [
        _rule("caribbean_premier_league", "kalshi", "ticker_type", ""),
        _rule("caribbean_premier_league", "optic", "market_id", "moneyline"),
    ]
    pins = clone_rule_pins(tip, "caribbean_premier_league")
    assert [p.sportsbook for p in pins] == ["optic"]

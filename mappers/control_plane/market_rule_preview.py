"""Verify-preview cards. Presentation only; the bands live on market_rule_card."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.market_rule_card import market_rule_card


def rule_cards(
    league: str,
    rules: list[Any],
    evidence: list[str] | None = None,
) -> list[dict[str, str]]:
    """One card per pin, for Editor and Cart verify previews."""
    refs = [str(ref) for ref in (evidence or []) if str(ref).strip()]
    return [market_rule_card(pin, league=league, evidence_refs=refs) for pin in rules]


def batch_rule_cards(payload: Any) -> list[dict[str, str]]:
    """Cards for every market-rule pin in a cart batch."""
    cards: list[dict[str, str]] = []
    for group in getattr(payload, "market_rules", []) or []:
        cards.extend(rule_cards(
            str(group.league), list(group.rules), list(group.evidence_refs or []),
        ))
    for league in getattr(payload, "leagues", []) or []:
        cards.extend(rule_cards(
            str(league.league),
            list(league.market_rules),
            list(getattr(league, "evidence_refs", None) or []),
        ))
    return cards

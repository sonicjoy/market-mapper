"""Copy venue official text onto a market-rule pin.

Both the venue's text and an http(s) citation whose host matches the book
must already be on the rule. Otherwise both fields stay null. Confidence
drops to ``low`` only on the book pin of a map. Optic companions and
ignores keep the confidence they were given. Nothing here is read off the
market id, the market name, or a sentence blocklist.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from mappers.control_plane.models import (
    BatchChangesPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)

UNCITED_CONFIDENCE = "low"
CITED_CONFIDENCE = "manual"
OFFICIAL_ABSENT = "No official description or citation URL."
_BOOK_HOSTS: dict[str, tuple[str, ...]] = {
    "polymarket": ("polymarket.com",),
    "polymarket_usa": ("polymarket.com", "polymarket.us"),
    "crypto.com": ("crypto.com",),
}


def stamp_official_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Keep a host-matched pair, or clear both."""
    stamped = dict(rule)
    pair = _cited_pair(stamped)
    if pair is None:
        stamped["official_description"] = None
        stamped["citation_url"] = None
        if _lowers_confidence(stamped):
            stamped["confidence"] = UNCITED_CONFIDENCE
        return stamped
    text, link = pair
    stamped["official_description"] = text
    stamped["citation_url"] = link
    if str(stamped.get("confidence") or "") in {"", UNCITED_CONFIDENCE}:
        stamped["confidence"] = CITED_CONFIDENCE
    return stamped


def stamp_market_pin(pin: dict[str, Any]) -> dict[str, Any]:
    """Stamp every rule on a harvest or cart pin."""
    rules = pin.get("rules")
    if not isinstance(rules, list):
        return pin
    out = dict(pin)
    out["rules"] = [
        stamp_official_rule(dict(row)) if isinstance(row, dict) else row
        for row in rules
    ]
    return out


def stamp_rule_models(rules: list[MarketRulePin]) -> list[MarketRulePin]:
    """Same stamp as the draft kernel, for Editor and Cart payloads."""
    return [
        MarketRulePin.model_validate(stamp_official_rule(pin.model_dump(mode="json")))
        for pin in rules
    ]


def stamp_market_payload(
    league: str,
    rules: list[MarketRulePin],
) -> MappingMarketRulesPayload:
    """Editor verify payload after the official-text stamp."""
    return MappingMarketRulesPayload(league=league, rules=stamp_rule_models(rules))


def stamp_batch_official(payload: BatchChangesPayload) -> BatchChangesPayload:
    """Cart batch: market-rule groups and league-embedded rules share the stamp."""
    groups = [
        group.model_copy(update={"rules": stamp_rule_models(group.rules)})
        for group in payload.market_rules
    ]
    leagues = [
        row.model_copy(update={"market_rules": stamp_rule_models(row.market_rules)})
        for row in payload.leagues
    ]
    return payload.model_copy(update={"market_rules": groups, "leagues": leagues})


def absence_warnings(rules: list[MarketRulePin]) -> list[str]:
    """One line when a drafted rule has no official text."""
    if any(rule.confidence == UNCITED_CONFIDENCE for rule in rules):
        return [OFFICIAL_ABSENT]
    return []


def batch_absence_warnings(payload: BatchChangesPayload) -> list[str]:
    """Cart batch: say so once when any stamped rule has no official text."""
    rules = [rule for group in payload.market_rules for rule in group.rules]
    rules.extend(rule for row in payload.leagues for rule in row.market_rules)
    return absence_warnings(rules)


def _lowers_confidence(rule: dict[str, Any]) -> bool:
    """Only the book pin of a map is marked low when it has no citation."""
    action = str(rule.get("action") or "").strip().lower()
    book = str(rule.get("sportsbook") or "").strip().lower()
    return action == "map" and book not in {"", "optic"}


def _cited_pair(rule: dict[str, Any]) -> tuple[str, str] | None:
    """Venue text plus an http(s) URL on that book's host, or nothing."""
    text = str(rule.get("official_description") or "").strip()
    link = str(rule.get("citation_url") or "").strip()
    book = str(rule.get("sportsbook") or "").strip().lower()
    if text and link.startswith(("https://", "http://")) and _host_matches(book, link):
        return text, link
    return None


def _host_matches(book: str, link: str) -> bool:
    host = (urlsplit(link).hostname or "").lower().removeprefix("www.")
    names = _BOOK_HOSTS.get(book)
    if not names or not host:
        return False
    return any(host == name or host.endswith("." + name) for name in names)

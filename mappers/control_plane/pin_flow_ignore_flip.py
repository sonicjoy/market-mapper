"""Ignore→map cart lines. The draft kernel is the only matcher."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix import _cart_item
from mappers.control_plane.pin_flow_markets import draft_and_verify_market_rules
from mappers.control_plane.rof_before_rule import MarketRuleObservation


def ignore_flip_cart_items(
    store: Any,
    league: str,
    rows: list[dict[str, Any]],
    market: str,
    live: set[str],
) -> list[dict[str, Any]]:
    """Flips the kernel accepts. A source key is never used as the canonical."""
    observations = [_flip_obs(league, row, live) for row in rows if _matches(row, market)]
    if not observations:
        return []
    pins, _skipped = draft_and_verify_market_rules(store, observations)
    return [_cart_item(pin) for pin in pins]


def _flip_obs(league: str, row: dict[str, Any], live: set[str]) -> MarketRuleObservation:
    key = str(row.get("source_key") or "")
    return {
        "league": league,
        "sportsbook": str(row.get("sportsbook") or ""),
        "source_key": key,
        "source_key_type": str(row.get("source_key_type") or ""),
        "action": "map",
        "flip_ignore": True,
        "live_optic_market_ids": set(live),
        "evidence_refs": [f"chat:ignore_flip:{key}"],
    }


def _matches(row: dict[str, Any], market: str) -> bool:
    if not market:
        return True
    blob = f"{row.get('source_key')} {row.get('canonical_market_type')}".lower()
    return market in blob

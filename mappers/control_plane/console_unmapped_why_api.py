"""Why / stage cart helpers for console unmapped (and Missing) inventory rows."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap
from mappers.control_plane.console_unmapped import (
    build_unmapped_tip_index,
    enrich_unmapped_row,
)
from mappers.control_plane.console_unmapped_fixes import (
    stage_unmapped_cart,
    why_unmapped_leg,
)


def inventory_context_row(
    platform: str,
    key: str,
    *,
    description: str | None = None,
    league: str | None = None,
    fixture: str | None = None,
    sport: str | None = None,
    market_group: str | None = None,
    contract_type: str | None = None,
    crypto_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal inventory dict for Why / stage (RFQ or catalogue row)."""
    raw: dict[str, Any] = {"platform": platform, "key": key}
    if description:
        raw["platform_leg_description"] = description
    if league:
        raw["league"] = league
    if fixture:
        raw["fixture"] = fixture
    if sport:
        raw["sport"] = sport
    if market_group:
        raw["market_group"] = market_group
    if contract_type:
        raw["contract_type"] = contract_type
    if crypto_ids:
        raw["crypto_ids"] = list(crypto_ids)
    return raw


def why_unmapped_console_leg(
    store: Any,
    platform: str,
    key: str,
    *,
    description: str | None = None,
    league: str | None = None,
    fixture: str | None = None,
    sport: str | None = None,
    market_group: str | None = None,
    contract_type: str | None = None,
    crypto_ids: list[str] | None = None,
) -> dict[str, Any]:
    """On-demand mapping breakdown for one inventory key."""
    index = build_unmapped_tip_index(store)
    raw = inventory_context_row(
        platform,
        key,
        description=description,
        league=league,
        fixture=fixture,
        sport=sport,
        market_group=market_group,
        contract_type=contract_type,
        crypto_ids=crypto_ids,
    )
    out = why_unmapped_leg(enrich_unmapped_row(raw, index), store)
    return {"platform": platform, "key": key, **out}


def _unmapped_probe_fn(store: Any) -> Any:
    """Return the crypto probe callback for unmapped cart staging."""

    def probe_fn(book: str, leg_key: str, leg_league: str) -> dict[str, Any]:
        """Run gap probe for one sportsbook leg key."""
        if book == "crypto":
            return run_probe_crypto_gap(
                store,
                {"symbol": leg_key, "league": leg_league or None},
            )
        return {"results": []}

    return probe_fn


unmapped_probe_fn = _unmapped_probe_fn


def stage_unmapped_console_leg(
    store: Any,
    platform: str,
    key: str,
    item_ids: list[str],
    *,
    description: str | None = None,
    league: str | None = None,
    fixture: str | None = None,
    sport: str | None = None,
    market_group: str | None = None,
    contract_type: str | None = None,
    crypto_ids: list[str] | None = None,
    evidence_fn: Any | None = None,
) -> dict[str, Any]:
    """Draft cart items for selected Why badges on one inventory key."""
    index = build_unmapped_tip_index(store)
    raw = inventory_context_row(
        platform,
        key,
        description=description,
        league=league,
        fixture=fixture,
        sport=sport,
        market_group=market_group,
        contract_type=contract_type,
        crypto_ids=crypto_ids,
    )
    row = enrich_unmapped_row(raw, index)
    return stage_unmapped_cart(
        row,
        store,
        item_ids,
        probe_fn=_unmapped_probe_fn(store),
        evidence_fn=evidence_fn,
    )

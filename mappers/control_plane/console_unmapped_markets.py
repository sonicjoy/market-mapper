"""Market-rule badge for Unmapped Why, drafted by the pin_flow_markets kernel."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_market_bind import (
    is_name_match_book,
    live_optic_census,
    tip_league_row,
)
from mappers.control_plane.pin_flow_markets import (
    MarketRuleObservation,
    draft_and_verify_market_rules,
)
from mappers.exchanges.crypto_com import crypto_market_rule_source_key_type


def market_rule_badge(
    row: dict[str, Any],
    store: Any | None,
    league: str,
    book: str,
) -> dict[str, Any] | None:
    """``{canonical, mapped, pin}`` for one unmapped leg, or None for no badge.

    ``pin`` is the staged market-rule pin when Why can fix it. The kernel is
    the only gate: anything it will not draft (needs_code, no live Optic
    canonical, overlay would not apply) shows no badge at all.
    """
    if store is None or not league or not is_name_match_book(book):
        return None
    obs = market_observation(row, store, league, book)
    if obs is None:
        return None
    pins, skipped = draft_and_verify_market_rules(store, [obs])
    if pins:
        rules = pins[0].get("rules") or []
        book_rule = next(
            (r for r in rules if str(r.get("sportsbook") or "") != "optic"), None,
        )
        if book_rule is None:
            return None
        canonical = str(book_rule.get("canonical_market_type") or "")
        return {"canonical": canonical, "mapped": False, "pin": pins[0]}
    mapped = next(
        (s for s in skipped if str(s.get("reason") or "") == "already_mapped"), None,
    )
    if mapped is None:
        return None
    return {"canonical": str(mapped.get("detail") or ""), "mapped": True, "pin": None}


def market_observation(
    row: dict[str, Any],
    store: Any,
    league: str,
    book: str,
) -> MarketRuleObservation | None:
    """Kernel input for one unmapped leg, or None when the book key is absent."""
    if tip_league_row(store, league) is None:
        return None
    live = live_optic_census(store, league)
    if book == "crypto.com":
        return _crypto_obs(row, league, live)
    if book in {"polymarket", "polymarket_usa"}:
        return _poly_obs(row, league, live)
    if book == "px":
        return _px_obs(row, league, live)
    return None


def _crypto_obs(
    row: dict[str, Any], league: str, live: set[str],
) -> MarketRuleObservation | None:
    contract_type = str(row.get("contract_type") or "").strip()
    if not contract_type:
        return None
    market_group = str(row.get("market_group") or row.get("market_type") or "").strip()
    return {
        "league": league,
        "sportsbook": "crypto.com",
        "source_key": contract_type,
        "source_key_type": crypto_market_rule_source_key_type(market_group),
        "demand": 1,
        "market_group": market_group,
        "evidence_refs": [f"gap:{row.get('key') or ''}"],
        "live_optic_market_ids": live,
    }


def _poly_obs(
    row: dict[str, Any], league: str, live: set[str],
) -> MarketRuleObservation | None:
    kind = str(row.get("kind") or "").strip()
    if not kind:
        return None
    platform = str(row.get("platform") or "").lower()
    return {
        "league": league,
        "sportsbook": "polymarket_usa" if "us" in platform else "polymarket",
        "source_key": kind,
        "source_key_type": "kind",
        "demand": 1,
        "evidence_refs": [f"gap:{row.get('key') or ''}"],
        "live_optic_market_ids": live,
    }


def _px_obs(
    row: dict[str, Any], league: str, live: set[str],
) -> MarketRuleObservation | None:
    market_name = str(row.get("market_name") or "").strip()
    if not market_name:
        return None
    return {
        "league": league,
        "sportsbook": "px",
        "source_key": market_name,
        "source_key_type": "market_name",
        "demand": 1,
        "evidence_refs": [f"gap:{row.get('key') or ''}"],
        "live_optic_market_ids": live,
    }


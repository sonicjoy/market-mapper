"""Polymarket US symbol classify + gateway anatomy for Mapper Chat."""

from __future__ import annotations

from typing import Any

from fetch.polymarket_usa_gateway import lookup_market


def classify_us_symbol(text: str) -> dict[str, str] | None:
    """Return classify_source_id fields when the gateway knows ``text``."""
    if lookup_market(text) is None:
        return None
    return {
        "id": text, "norm_id": text.lower(),
        "sportsbook": "polymarket_usa", "id_kind": "us_symbol",
    }


def us_symbol_fields(source_id: str) -> dict[str, Any]:
    """Polymarket US anatomy from the gateway's typed fields (symbol not split)."""
    market = lookup_market(source_id)
    if market is None:
        return {}
    teams = market["teams"]
    by_order = {t.get("ordering"): t for t in teams if t.get("ordering")}
    home = by_order.get("home") or (teams[0] if teams else {})
    away = by_order.get("away") or (teams[1] if len(teams) > 1 else {})
    names = [t.get("name") or t.get("abbreviation") or "" for t in (home, away) if t]
    return {
        "seen": True,
        "sportsbook": "polymarket_usa",
        "id_kind": "us_symbol",
        "title": " vs ".join(names) if len(names) == 2 else market["question"],
        "league": market["league"],
        "kickoff": market["game_start"],
        "scheduled": market["game_start"],
        "home": home.get("abbreviation", ""),
        "away": away.get("abbreviation", ""),
        "sports_market_type": market["sports_market_type"],
    }

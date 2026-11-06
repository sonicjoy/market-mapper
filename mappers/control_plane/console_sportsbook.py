"""Sportsbook normalisation for console catalog + override publish."""

from __future__ import annotations

_CANONICAL_BY_LOWER = {
    "kalshi": "Kalshi",
    "polymarket": "Polymarket",
    "polymarket (usa)": "Polymarket (USA)",
    "crypto.com": "crypto.com",
    "novig": "Novig",
    "underdog": "Underdog",
    "dkex": "DKEX",
    "prophet x": "Prophet X",
    "prophet_x": "Prophet X",
    "sxbet": "SX Bet",
    "sx bet": "SX Bet",
}


def canonical_sportsbook(value: str) -> str:
    """Map operator input to the casing stored on opticodds_mapping rows."""
    text = (value or "").strip()
    if not text:
        raise ValueError("sportsbook is required")
    return _CANONICAL_BY_LOWER.get(text.lower(), text)


def sportsbook_lower(value: str) -> str:
    """RFQ key partition uses lower(sportsbook)."""
    return canonical_sportsbook(value).lower()

"""Shared cricket Optic + Polymarket taxonomy (moneyline only)."""

from mappers.market_types import MarketType

# Optic cricket books confirmed moneyline-only (cricket_odi.py, 2026-08-04).
CRICKET_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
}

CRICKET_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
}

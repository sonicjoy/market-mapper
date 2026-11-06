"""Shared crypto.com tennis moneyline config (ATP / WTA / ITF meta leagues)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.market_types import MarketType


# crypto.com lists Challenger events under their own meta_league, not "ATP"
# (86 Moneyline symbols on 2026-11-05 vs 14 for "ATP"). Optic serves
# atp_challenger fixtures and 7 books map them (e.g. James Trotter vs Andres
# Andrade, Masamichi Imamura vs Yosuke Watanuki on 2026-11-05).
TENNIS_META_LEAGUE_BY_SLUG: dict[str, str] = {"atp_challenger": "ATP Challenger"}
# Challenger events the feed still files under plain "ATP".
TENNIS_ALSO_LEAGUES: dict[str, tuple[str, ...]] = {"atp_challenger": ("ATP",)}


def tennis_crypto_config(
    league: str,
    settings: Mapping[str, Any] | None = None,
    also_leagues: tuple[str, ...] = (),
) -> CryptoConfig:
    """Build a CryptoConfig for a tennis meta_league (ATP, WTA, ITF)."""
    period = "Full Game"
    if settings and settings.get("period_type"):
        period = str(settings["period_type"])
    return CryptoConfig(
        sport_grouping="TENNIS",
        league=league,
        symbol_prefix="TENNIS",
        also_leagues=also_leagues,
        period_type=period,
        contract_types={"Moneyline": MarketType.MONEYLINE},
    )

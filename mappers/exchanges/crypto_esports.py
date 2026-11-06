"""Shared crypto.com esports moneyline config (LoL / CS2 / Dota 2)."""

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.market_types import MarketType


def esports_crypto_config(league: str) -> CryptoConfig:
    """Build a CryptoConfig for a crypto meta_league (LOL, CS2, DOTA2).

    Catalogue (2026-08-12, 21d): moneyline only, period ``Full-Game``,
    ``meta_sports_grouping=ESPORT``.
    """
    return CryptoConfig(
        sport_grouping="ESPORT",
        league=league,
        period_type="Full-Game",
        contract_types={"Moneyline": MarketType.MONEYLINE},
    )

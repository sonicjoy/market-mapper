"""Parser-profile protocol and league build context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.dkex import DkexConfig
from mappers.exchanges.huddle import HuddleConfig
from mappers.exchanges.kalshi import KalshiConfig
from mappers.exchanges.novig import NovigConfig
from mappers.exchanges.optic import OpticConfig
from mappers.exchanges.polymarket import PolymarketConfig
from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
from mappers.exchanges.px import PxConfig
from mappers.exchanges.runshop import RunshopConfig
from mappers.exchanges.underdog import UnderdogConfig
from mappers.sport import Sport

ExchangeConfig = (
    KalshiConfig
    | PxConfig
    | CryptoConfig
    | PolymarketConfig
    | PolyUsaConfig
    | OpticConfig
    | NovigConfig
    | RunshopConfig
    | DkexConfig
    | UnderdogConfig
    | HuddleConfig
)


@dataclass(frozen=True)
class LeagueBuildContext:
    """League-row values shared across parser profiles for one build."""

    league: str
    sport: Sport
    optic_league_id: str
    fixture_horizon_hours: float
    extra_optic_league_ids: tuple[str, ...]


class ParserProfile(Protocol):
    """Build one exchange config from tip settings and league context."""

    @property
    def profile_id(self) -> str: ...

    @property
    def sportsbook(self) -> str: ...

    @property
    def sport(self) -> Sport: ...

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> ExchangeConfig | None:
        """Return exchange config, or None when settings are insufficient."""

"""dkex_generic_v1: the DKEX parser profile (split from ``_builders``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mappers.exchanges.dkex import DkexConfig
from mappers.market_types import MarketType
from mappers.profiles.types import LeagueBuildContext
from mappers.sport import Sport


@dataclass(frozen=True)
class DkexGenericProfile:
    """dkex_generic_v1: shared DKEX market vocabulary for one sport."""

    profile_id: str
    sportsbook: str
    sport: Sport
    market_types: Mapping[tuple[str, str], MarketType]
    implied_lines: Mapping[str, float] = field(default_factory=dict)
    ignored_markets: frozenset[str] = frozenset()
    club_short_names: bool = False
    person_names: bool = False
    any_league: bool = False
    min_strikes: Mapping[tuple[str, str], float] = field(default_factory=dict)

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> DkexConfig | None:
        """Build DKEX config when the venue league token is present."""
        _ = ctx
        # DKEX league tokens are compared against league_token(subTopic)
        # (mappers/exchanges/dkex.py), which is upper case ("NFL",
        # "CFB"); a tip carrying "cfb" would silently
        # match nothing, so normalize rather than trust the control plane.
        league = str(settings.get("league") or "").strip().upper()
        if not league:
            return None
        return DkexConfig(
            league=league,
            market_types=dict(self.market_types),
            implied_lines=dict(self.implied_lines),
            ignored_markets=self.ignored_markets,
            club_short_names=self.club_short_names,
            person_names=self.person_names,
            any_league=self.any_league,
            min_strikes=dict(self.min_strikes),
        )

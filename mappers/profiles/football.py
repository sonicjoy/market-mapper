"""Parser profiles for football tip-only leagues."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from mappers.exchanges.huddle import HuddleConfig
from mappers.exchanges.px import PxConfig
from mappers.market_types import MarketType
from mappers.profiles._builders import (
    CryptoGenericProfile,
    NovigGenericProfile,
    OpticStandardProfile,
    PolyGenericProfile,
    PxGenericProfile,
    UnderdogGenericProfile,
)
from mappers.profiles._dkex_builder import DkexGenericProfile
from mappers.profiles.types import LeagueBuildContext, ParserProfile
from mappers.sport import Sport
from mappers.vocab import dkex_markets, novig_markets
from mappers.vocab.football_huddle import EXC_OT_CODES, GAME_TYPES
from mappers.vocab.football_markets import (
    FOOTBALL_MARKET_TYPES,
    FOOTBALL_OPTIC_TABLE_TYPES,
    FOOTBALL_POLY_TEAM_NAME_ALIASES,
    NFL_PX,
    football_market_rules,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_DKEX_ID = "dkex_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"
_HUDDLE_ID = "huddle_nfl_v1"


@dataclass(frozen=True)
class NflPxProfile(PxGenericProfile):
    """px_generic_v1 with the code-owned NFL market vocab as the base.

    The tip overlay merges onto this, so NFL props PX ships by name suffix
    ("<Player> To Score a Touchdown") map without a tip rule.
    """

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> PxConfig | None:
        """Generic PX config, seeded with NFL_PX's exact and suffix maps."""
        cfg = super().build(settings, ctx)
        if cfg is None or ctx.league != "nfl":
            return cfg
        return replace(cfg, exact=dict(NFL_PX.exact), suffix=list(NFL_PX.suffix))


@dataclass(frozen=True)
class HuddleNflProfile:
    """huddle_nfl_v1: NFL Huddle marketCode grammar."""

    profile_id: str
    sportsbook: str
    sport: Sport
    table_types: Mapping[str, MarketType]
    ignored_codes: frozenset[str] = frozenset()

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> HuddleConfig | None:
        """Build when the tip pin carries a Huddle competition id."""
        _ = ctx
        cid = str(settings.get("competition_id") or "").strip()
        if not cid:
            return None
        return HuddleConfig(
            competition_ids=(cid,),
            table_types=dict(self.table_types),
            ignored_codes=self.ignored_codes,
        )


FOOTBALL_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.FOOTBALL,
        table_types=FOOTBALL_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.FOOTBALL,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.FOOTBALL,
        market_types=FOOTBALL_MARKET_TYPES,
        market_rules=football_market_rules,
        team_name_aliases=FOOTBALL_POLY_TEAM_NAME_ALIASES,
        aliases_leagues=frozenset({"cfl"}),
    ),
    NflPxProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.FOOTBALL,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.FOOTBALL,
        market_types=novig_markets.FOOTBALL,
        ignored_types=novig_markets.FOOTBALL_IGNORED,
    ),
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.FOOTBALL,
        market_types=dkex_markets.FOOTBALL,
        implied_lines=dkex_markets.FOOTBALL_IMPLIED_LINES,
        ignored_markets=dkex_markets.FOOTBALL_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.FOOTBALL,
    ),
    HuddleNflProfile(
        profile_id=_HUDDLE_ID,
        sportsbook="huddle",
        sport=Sport.FOOTBALL,
        table_types=GAME_TYPES,
        ignored_codes=EXC_OT_CODES,
    ),
)

"""Parser profiles for basketball tip-only leagues."""

from __future__ import annotations

from mappers.profiles._builders import (
    CryptoGenericProfile,
    NovigGenericProfile,
    OpticStandardProfile,
    PolyGenericProfile,
    PxGenericProfile,
    UnderdogGenericProfile,
)
from mappers.profiles._dkex_builder import DkexGenericProfile
from mappers.profiles.types import ParserProfile
from mappers.sport import Sport
from mappers.vocab import dkex_markets, novig_markets
from mappers.vocab.basketball_markets import (
    BASKETBALL_MARKET_TYPES,
    BASKETBALL_OPTIC_TABLE_TYPES,
    BASKETBALL_POLY_TEAM_NAME_ALIASES,
    basketball_market_rules,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_DKEX_ID = "dkex_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"

BASKETBALL_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.BASKETBALL,
        table_types=BASKETBALL_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.BASKETBALL,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.BASKETBALL,
        market_types=BASKETBALL_MARKET_TYPES,
        market_rules=basketball_market_rules,
        team_name_aliases=BASKETBALL_POLY_TEAM_NAME_ALIASES,
        aliases_leagues=frozenset({"wnba"}),
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.BASKETBALL,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.BASKETBALL,
        market_types=novig_markets.BASKETBALL,
        ignored_types=novig_markets.BASKETBALL_IGNORED,
    ),
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.BASKETBALL,
        market_types=dkex_markets.BASKETBALL,
        ignored_markets=dkex_markets.BASKETBALL_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.BASKETBALL,
    ),
)

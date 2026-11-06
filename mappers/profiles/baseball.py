"""Parser profiles for baseball tip-only leagues."""

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
from mappers.vocab.baseball_markets import (
    BASEBALL_MARKET_TYPES,
    BASEBALL_OPTIC_TABLE_TYPES,
    baseball_market_rules,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_DKEX_ID = "dkex_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"

BASEBALL_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.BASEBALL,
        table_types=BASEBALL_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.BASEBALL,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.BASEBALL,
        market_types=BASEBALL_MARKET_TYPES,
        market_rules=baseball_market_rules,
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.BASEBALL,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.BASEBALL,
        market_types=novig_markets.BASEBALL,
        ignored_types=novig_markets.BASEBALL_IGNORED,
    ),
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.BASEBALL,
        market_types=dkex_markets.BASEBALL,
        ignored_markets=dkex_markets.BASEBALL_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.BASEBALL,
    ),
)

"""Parser profiles for soccer tip-only leagues."""

from __future__ import annotations

from mappers.profiles._builders import (
    CryptoGenericProfile,
    NovigGenericProfile,
    OpticStandardProfile,
    PolyGenericProfile,
    PxGenericProfile,
    RunshopGenericProfile,
    UnderdogGenericProfile,
)
from mappers.profiles._dkex_builder import DkexGenericProfile
from mappers.profiles.types import ParserProfile
from mappers.sport import Sport
from mappers.vocab import dkex_markets, novig_markets
from mappers.vocab.soccer_markets import (
    SOCCER_MARKET_TYPES,
    SOCCER_OPTIC_TABLE_TYPES,
    soccer_market_rules,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"
_RUNSHOP_ID = "runshop_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"
_DKEX_ID = "dkex_generic_v1"

SOCCER_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.SOCCER,
        table_types=SOCCER_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.SOCCER,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.SOCCER,
        market_types=SOCCER_MARKET_TYPES,
        market_rules=soccer_market_rules,
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.SOCCER,
    ),
    RunshopGenericProfile(
        profile_id=_RUNSHOP_ID,
        sportsbook="runshop",
        sport=Sport.SOCCER,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.SOCCER,
        market_types=novig_markets.SOCCER,
        ignored_types=novig_markets.SOCCER_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.SOCCER,
    ),
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.SOCCER,
        market_types=dkex_markets.SOCCER,
        ignored_markets=dkex_markets.SOCCER_IGNORED,
        club_short_names=True,
    ),
)

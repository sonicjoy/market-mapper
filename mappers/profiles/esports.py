"""Parser profiles for esports tip-only leagues."""

from __future__ import annotations

from mappers.profiles._builders import (
    CryptoGenericProfile,
    NovigGenericProfile,
    OpticStandardProfile,
    PolyGenericProfile,
    PxGenericProfile,
    UnderdogGenericProfile,
)
from mappers.profiles.types import ParserProfile
from mappers.sport import Sport
from mappers.vocab import novig_markets
from mappers.vocab.esports_markets import (
    ESPORTS_MARKET_TYPES,
    ESPORTS_OPTIC_TABLE_TYPES,
    esports_market_rules,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"

ESPORTS_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.ESPORTS,
        table_types=ESPORTS_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.ESPORTS,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.ESPORTS,
        market_types=ESPORTS_MARKET_TYPES,
        market_rules=esports_market_rules,
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.ESPORTS,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.ESPORTS,
        market_types=novig_markets.ESPORTS,
        ignored_types=novig_markets.ESPORTS_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.ESPORTS,
    ),
)

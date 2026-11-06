"""Parser profiles for cricket tip-only leagues."""

from __future__ import annotations

from mappers.exchanges.polymarket import (
    cricket_market_rules,
)
from mappers.profiles._builders import (
    CryptoGenericProfile,
    OpticStandardProfile,
    PolyGenericProfile,
    PxGenericProfile,
)
from mappers.profiles.types import ParserProfile
from mappers.sport import Sport
from mappers.vocab.cricket_markets import (
    CRICKET_MARKET_TYPES,
    CRICKET_OPTIC_TABLE_TYPES,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"

CRICKET_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.CRICKET,
        table_types=CRICKET_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.CRICKET,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.CRICKET,
        market_types=CRICKET_MARKET_TYPES,
        market_rules=cricket_market_rules,
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.CRICKET,
    ),
)

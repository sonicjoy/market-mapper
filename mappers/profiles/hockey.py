"""Parser profiles for hockey tip-only leagues."""

from __future__ import annotations

from mappers.profiles._builders import (
    CryptoGenericProfile,
    NovigGenericProfile,
    OpticStandardProfile,
    PxGenericProfile,
    UnderdogGenericProfile,
)
from mappers.profiles._dkex_builder import DkexGenericProfile
from mappers.profiles.types import ParserProfile
from mappers.sport import Sport
from mappers.vocab import dkex_markets, novig_markets
from mappers.vocab.hockey_markets import HOCKEY_OPTIC_TABLE_TYPES

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_PX_ID = "px_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_DKEX_ID = "dkex_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"

HOCKEY_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.HOCKEY,
        table_types=HOCKEY_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.HOCKEY,
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.HOCKEY,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.HOCKEY,
        market_types=novig_markets.HOCKEY,
        ignored_types=novig_markets.HOCKEY_IGNORED,
    ),
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.HOCKEY,
        market_types=dkex_markets.HOCKEY,
        ignored_markets=dkex_markets.HOCKEY_IGNORED,
        min_strikes=dkex_markets.HOCKEY_MIN_STRIKES,
    ),
    # The tip pins underdog_generic_v1 on nhl. Unregistered, tip_only_ok
    # drops the whole league (every venue) from the mapper run set.
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.HOCKEY,
    ),
)

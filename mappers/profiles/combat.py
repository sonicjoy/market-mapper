"""Parser profiles for MMA and boxing tip-only leagues."""

from __future__ import annotations

from mappers.profiles._builders import (
    CryptoMmaProfile,
    NovigGenericProfile,
    OpticStandardProfile,
    PolyUfcProfile,
    UnderdogGenericProfile,
)
from mappers.profiles._dkex_builder import DkexGenericProfile
from mappers.profiles.types import ParserProfile
from mappers.sport import Sport
from mappers.vocab import dkex_markets, novig_markets
from mappers.vocab.combat_markets import (
    BOXING_OPTIC_TABLE_TYPES,
    UFC_MARKET_TYPES,
    UFC_OPTIC_TABLE_TYPES,
    UFC_POLY_TEAM_NAME_ALIASES,
    ufc_market_rules,
)

_OPTIC_ID = "optic_standard_v1"
_CRYPTO_MMA_ID = "crypto_mma_v1"
_POLY_UFC_ID = "poly_ufc_v1"
_NOVIG_ID = "novig_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"
_DKEX_ID = "dkex_generic_v1"

MMA_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_OPTIC_ID,
        sportsbook="optic",
        sport=Sport.MMA,
        table_types=UFC_OPTIC_TABLE_TYPES,
    ),
    CryptoMmaProfile(
        profile_id=_CRYPTO_MMA_ID,
        sportsbook="crypto.com",
        sport=Sport.MMA,
    ),
    PolyUfcProfile(
        profile_id=_POLY_UFC_ID,
        sportsbook="polymarket",
        sport=Sport.MMA,
        market_types=UFC_MARKET_TYPES,
        market_rules=ufc_market_rules,
        team_name_aliases=UFC_POLY_TEAM_NAME_ALIASES,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.MMA,
        market_types=novig_markets.MMA,
        ignored_types=novig_markets.MMA_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.MMA,
    ),
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.MMA,
        market_types=dkex_markets.UFC,
        ignored_markets=dkex_markets.UFC_IGNORED,
        person_names=True,
    ),
)

BOXING_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_OPTIC_ID,
        sportsbook="optic",
        sport=Sport.BOXING,
        table_types=BOXING_OPTIC_TABLE_TYPES,
    ),
    # The tip pins crypto.com on boxing_matches with this id; unregistered, it
    # failed tip_only_ok and dropped the whole league (every venue). It builds
    # nothing for the BOXING grouping (MMA only), so crypto.com stays unmapped.
    CryptoMmaProfile(
        profile_id=_CRYPTO_MMA_ID,
        sportsbook="crypto.com",
        sport=Sport.BOXING,
    ),
)

COMBAT_PROFILES: tuple[ParserProfile, ...] = (*MMA_PROFILES, *BOXING_PROFILES)

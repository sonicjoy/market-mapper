"""Parser profiles for tennis tip-only leagues."""

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
from mappers.vocab import dkex_markets
from mappers.vocab.novig_markets import TENNIS as NOVIG_TENNIS
from mappers.vocab.novig_markets import TENNIS_IGNORED
from mappers.vocab.tennis_aliases import TENNIS_TEAM_NAME_ALIASES
from mappers.vocab.tennis_markets import (
    TENNIS_MARKET_TYPES,
    TENNIS_OPTIC_TABLE_TYPES,
    tennis_market_rules,
)

_PROFILE_ID = "optic_standard_v1"
_CRYPTO_ID = "crypto_generic_v1"
_POLY_ID = "poly_generic_v1"
_PX_ID = "px_generic_v1"
_NOVIG_ID = "novig_generic_v1"
_UNDERDOG_ID = "underdog_generic_v1"
_DKEX_ID = "dkex_generic_v1"

TENNIS_PROFILES: tuple[ParserProfile, ...] = (
    OpticStandardProfile(
        profile_id=_PROFILE_ID,
        sportsbook="optic",
        sport=Sport.TENNIS,
        table_types=TENNIS_OPTIC_TABLE_TYPES,
    ),
    CryptoGenericProfile(
        profile_id=_CRYPTO_ID,
        sportsbook="crypto.com",
        sport=Sport.TENNIS,
    ),
    PolyGenericProfile(
        profile_id=_POLY_ID,
        sportsbook="polymarket",
        sport=Sport.TENNIS,
        market_types=TENNIS_MARKET_TYPES,
        market_rules=tennis_market_rules,
        team_name_aliases=TENNIS_TEAM_NAME_ALIASES,
    ),
    PxGenericProfile(
        profile_id=_PX_ID,
        sportsbook="px",
        sport=Sport.TENNIS,
    ),
    NovigGenericProfile(
        profile_id=_NOVIG_ID,
        sportsbook="novig",
        sport=Sport.TENNIS,
        market_types=NOVIG_TENNIS,
        ignored_types=TENNIS_IGNORED,
    ),
    UnderdogGenericProfile(
        profile_id=_UNDERDOG_ID,
        sportsbook="underdog",
        sport=Sport.TENNIS,
    ),
    # Tennis subTopic is the tournament or the tour, inconsistently, so
    # the pass reads every WIN/MTH event and the two-player fixture match
    # decides the league (atp / wta / challenger / itf).
    DkexGenericProfile(
        profile_id=_DKEX_ID,
        sportsbook="dkex",
        sport=Sport.TENNIS,
        market_types=dkex_markets.TENNIS,
        ignored_markets=dkex_markets.TENNIS_IGNORED,
        person_names=True,
        any_league=True,
    ),
)

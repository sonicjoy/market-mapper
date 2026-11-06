"""Parser profile registry keyed by (profile_id, sport)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
from mappers.profiles.baseball import BASEBALL_PROFILES
from mappers.profiles.basketball import BASKETBALL_PROFILES
from mappers.profiles.combat import COMBAT_PROFILES
from mappers.profiles.cricket import CRICKET_PROFILES
from mappers.profiles.esports import ESPORTS_PROFILES
from mappers.profiles.football import FOOTBALL_PROFILES
from mappers.profiles.hockey import HOCKEY_PROFILES
from mappers.profiles.soccer import SOCCER_PROFILES
from mappers.profiles.tennis import TENNIS_PROFILES
from mappers.profiles.types import LeagueBuildContext, ParserProfile
from mappers.sport import Sport

POLY_USA_PROFILE_ID = "poly_usa_generic_v1"

_ALL_PROFILES: tuple[ParserProfile, ...] = (
    *SOCCER_PROFILES,
    *ESPORTS_PROFILES,
    *CRICKET_PROFILES,
    *COMBAT_PROFILES,
    *TENNIS_PROFILES,
    *FOOTBALL_PROFILES,
    *BASKETBALL_PROFILES,
    *BASEBALL_PROFILES,
    *HOCKEY_PROFILES,
)


@dataclass(frozen=True)
class PolyUsaProfile:
    """poly_usa_generic_v1: a tip Polymarket US pin, which builds nothing.

    Which gateway leagues a league reads is code
    (``mappers.exchanges.polymarket_usa_leagues``, applied by
    ``with_code_poly_usa``); the profile stays registered only so an old tip
    pin resolves to no config instead of an unknown profile.
    """

    sport: Sport
    profile_id: str = POLY_USA_PROFILE_ID
    sportsbook: str = "polymarket_usa"

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> PolyUsaConfig | None:
        """Always None: the tip pin is ignored."""
        _ = settings, ctx
        return None


_POLY_USA_PROFILES: tuple[ParserProfile, ...] = tuple(
    PolyUsaProfile(sport=sport) for sport in Sport
)


PROFILES: dict[tuple[str, Sport], ParserProfile] = {
    (profile.profile_id, profile.sport): profile
    for profile in (*_ALL_PROFILES, *_POLY_USA_PROFILES)
}


def profile_registered(profile_id: str, sport: Sport) -> bool:
    """True when the profile id is registered for the given sport."""
    return (profile_id, sport) in PROFILES


def lookup_profile(profile_id: str, sport: Sport) -> ParserProfile | None:
    """Return the registered profile, or None when absent."""
    return PROFILES.get((profile_id, sport))

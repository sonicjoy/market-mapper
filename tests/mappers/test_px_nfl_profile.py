"""NFL ProphetX config carries the code-owned vocab, not just the tip's rules."""

from mappers.market_types import MarketType
from mappers.profiles.football import NflPxProfile
from mappers.profiles.types import LeagueBuildContext
from mappers.sport import Sport


def _ctx(league: str) -> LeagueBuildContext:
    return LeagueBuildContext(
        league=league, sport=Sport.FOOTBALL, optic_league_id="x",
        fixture_horizon_hours=48.0, extra_optic_league_ids=(),
    )


def _profile() -> NflPxProfile:
    return NflPxProfile(profile_id="px_generic_v1", sportsbook="px", sport=Sport.FOOTBALL)


def test_nfl_px_maps_anytime_touchdown_suffix():
    cfg = _profile().build({"tournament_id": 31}, _ctx("nfl"))
    assert cfg is not None
    assert (" To Score a Touchdown", MarketType.PLAYER_TOUCHDOWNS) in cfg.suffix
    assert cfg.tournament_id == 31


def test_other_football_leagues_stay_generic():
    cfg = _profile().build({"tournament_id": 99}, _ctx("ncaaf"))
    assert cfg is not None and cfg.suffix == [] and cfg.exact == {}


def test_no_tournament_no_config():
    assert _profile().build({}, _ctx("nfl")) is None

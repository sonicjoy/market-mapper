"""Tests for per-league crypto.com CryptoConfig wiring."""

from mappers.control_plane.rows import LeagueRow
from mappers.crypto_meta import (
    crypto_meta_code,
    crypto_sport_grouping,
    harvest_name_exceptions,
    narrow_crypto_leagues,
)
from mappers.exchanges.crypto_soccer import soccer_crypto_config
from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.vocab.baseball_markets import MLB_CRYPTO
from mappers.vocab.basketball_markets import NBA_CRYPTO, WNBA_CRYPTO
from mappers.vocab.football_markets import NCAAF_CRYPTO, NFL_CRYPTO
from mappers.vocab.hockey_markets import NHL_CRYPTO
from tests.mappers._require import require


def _tip_optic_league_ids() -> dict[str, str]:
    snap = load_fixture()
    return {row.league: row.optic_league_id for row in snap.leagues}


def _tip_crypto_meta(league: str) -> str:
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == league)
    return crypto_meta_code(row)


def _crypto_row(league: str, meta: str, grouping: str) -> LeagueRow:
    return LeagueRow(
        league=league,
        sport="tennis" if grouping == "TENNIS" else "soccer",
        optic_league_id=league,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "crypto.com",
                "enabled": True,
                "parser_profile": "crypto_generic_v1",
                "source_league_id": meta,
                "settings": {"league": meta, "sport_grouping": grouping},
            }
        ],
    )


def _tennis_crypto(league: str):
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == league)
    cfg = build_tip_league(row)
    assert cfg.CRYPTO is not None
    return cfg.CRYPTO


def test_all_repo_leagues_have_crypto_config():
    """Tip-only ball leagues expose crypto via build_tip_league; wired soccer via LEAGUES."""
    tip_crypto = {
        "nba": NBA_CRYPTO,
        "mlb": MLB_CRYPTO,
        "nfl": NFL_CRYPTO,
        "nhl": NHL_CRYPTO,
        "ncaab": build_tip_league(
            next(r for r in load_fixture().leagues if r.league == "ncaab")
        ).CRYPTO,
        "ncaaf": NCAAF_CRYPTO,
        "wnba": WNBA_CRYPTO,
    }
    for key, crypto in tip_crypto.items():
        assert crypto is not None, key
        assert crypto.league
    expected_with_crypto = {
        "world_cup", "epl", "ucl",
        "liga_mx", "la_liga",
        "europa_league", "europa_conference_league", "brazil_serie_a",
        "mls", "argentina_primera", "efl_cup",
        "france_ligue_1", "germany_bundesliga", "italy_serie_a",
        "lol", "cs2", "dota_2",
    }
    for key, cfg in LEAGUES.items():
        if key in expected_with_crypto:
            assert cfg.CRYPTO is not None, key
            assert cfg.CRYPTO.league


def test_mlb_crypto_vocabulary():
    c = MLB_CRYPTO
    assert c is not None
    assert c.league == "MLB"
    assert c.period_type == "Full-Game"
    assert c.contract_types["Total Runs"] == MarketType.GAME_TOTAL
    assert c.prop_period_type == "Full-Game"
    assert c.prop_contract_types["To Get A Hit"] == MarketType.PLAYER_HITS
    assert c.prop_contract_types["To Hit A Home Run"] == MarketType.PLAYER_HOME_RUNS
    assert (
        c.prop_contract_types["Total Pitching Strikeouts"]
        == MarketType.PLAYER_STRIKEOUTS
    )
    assert c.prop_contract_types["Total Outs Recorded"] == MarketType.PLAYER_OUTS
    assert (
        c.prop_contract_types["Total Hits Milestones"] == MarketType.PLAYER_HITS
    )
    assert (
        c.prop_contract_types["Total Hits, Runs, & RBIs"]
        == MarketType.PLAYER_HITS_RUNS_RBIS
    )
    assert c.game_prop_period_type == "1st Inning"
    assert c.game_prop_contract_types["To Score A Run"] == MarketType.FIRST_INNING_TOTAL
    f5 = c.period_contract_types["1st-5th Inning"]
    assert f5["Moneyline"] == MarketType.FIRST_FIVE_MONEYLINE_3WAY
    assert f5["Moneyline (3-Way)"] == MarketType.FIRST_FIVE_MONEYLINE_3WAY
    f3 = c.period_contract_types["1st-3rd Inning"]
    assert f3 == {"Moneyline (3-Way)": MarketType.FIRST_THREE_MONEYLINE_3WAY}
    assert "Spread" not in f3
    assert "Total Runs" not in f3
    # Deferred: no Optic counterpart.
    assert "Total RBIs" not in c.prop_contract_types
    assert "To Score A Run" not in c.prop_contract_types


def test_soccer_leagues_share_prop_vocabulary():
    for cfg in (
        LEAGUES["epl"].CRYPTO,
        LEAGUES["ucl"].CRYPTO,
        LEAGUES["world_cup"].CRYPTO,
        LEAGUES["liga_mx"].CRYPTO,
        LEAGUES["la_liga"].CRYPTO,
        LEAGUES["europa_league"].CRYPTO,
        LEAGUES["europa_conference_league"].CRYPTO,
        LEAGUES["brazil_serie_a"].CRYPTO,
        LEAGUES["mls"].CRYPTO,
        LEAGUES["efl_cup"].CRYPTO,
    ):
        assert cfg is not None
        assert "Both Teams To Score" in cfg.game_prop_contract_types
        assert "Anytime Goal Scorer" in cfg.prop_contract_types


def test_esports_crypto_moneyline_only():
    for cfg, league in (
        (LEAGUES['lol'].CRYPTO, "LOL"),
        (LEAGUES['cs2'].CRYPTO, "CS2"),
        (LEAGUES['dota_2'].CRYPTO, "DOTA2"),
    ):
        assert cfg is not None
        assert cfg.league == league
        assert cfg.sport_grouping == "ESPORT"
        assert cfg.period_type == "Full-Game"
        assert cfg.contract_types == {"Moneyline": MarketType.MONEYLINE}


def test_tennis_leagues_split_by_meta_league():
    assert _tennis_crypto("atp").league == "ATP"
    assert _tennis_crypto("atp_challenger").league == "ATP Challenger"
    assert _tennis_crypto("wta").league == "WTA"
    assert _tennis_crypto("itf_men").league == "ITF"
    assert _tennis_crypto("itf_women").league == "ITF"
    assert _tennis_crypto("atp").sport_grouping == "TENNIS"


def test_narrow_crypto_leagues_keeps_atp_tours_for_atp_meta():
    rows = [
        _crypto_row("wta", "WTA", "TENNIS"),
        _crypto_row("atp", "ATP", "TENNIS"),
        _crypto_row("atp_challenger", "ATP", "TENNIS"),
        _crypto_row("itf_men", "ITF", "TENNIS"),
        _crypto_row("england_championship", "ELC", "SOCCER"),
    ]
    inferred = ["wta", "atp", "atp_challenger", "itf_men"]
    assert narrow_crypto_leagues(inferred, "ATP", rows) == ["atp", "atp_challenger"]
    assert narrow_crypto_leagues(inferred, "WTA", rows) == ["wta"]
    assert narrow_crypto_leagues(inferred, "", rows) == inferred
    assert narrow_crypto_leagues(["england_championship"], "ELC", rows) == [
        "england_championship"
    ]
    snap = load_fixture()
    tennis = {
        row.league for row in snap.leagues if crypto_sport_grouping(row) == "TENNIS"
    }
    assert tennis == {"atp", "atp_challenger", "itf_men", "itf_women", "wta"}


def test_mlb_harvest_name_exceptions_are_not_a_league_map():
    assert harvest_name_exceptions("MLB") is not None
    assert harvest_name_exceptions("ELC") is None
    assert harvest_name_exceptions("UFC") == {"Tina Black": "VMA5"}


def test_world_cup_maps_knockout_novelty_lines_to_advance():
    assert LEAGUES['world_cup'].CRYPTO is not None
    assert LEAGUES['world_cup'].CRYPTO.contract_types["To Lift The Cup"] == MarketType.TO_ADVANCE
    assert LEAGUES['world_cup'].CRYPTO.contract_types["To Win Bronze"] == MarketType.TO_ADVANCE
    assert LEAGUES['world_cup'].CRYPTO.contract_period_types["To Lift The Cup"] == "Full Game"
    assert LEAGUES['world_cup'].CRYPTO.contract_period_types["To Win Bronze"] == "Full Game"
    assert "To Lift The Cup" not in LEAGUES['world_cup'].CRYPTO.game_line_ignored
    assert "To Win Bronze" not in LEAGUES['world_cup'].CRYPTO.game_line_ignored


def test_tennis_symbol_prefix_follows_sport_grouping():
    # All tennis leagues emit NX.F.OPT.TENNIS symbols (split by meta_league).
    for league in ("atp", "atp_challenger", "wta", "itf_men", "itf_women"):
        assert _tennis_crypto(league).symbol_prefix == "TENNIS"

def test_symbol_prefix_defaults_to_league_for_non_tennis():
    assert MLB_CRYPTO is not None and MLB_CRYPTO.symbol_prefix is None
    assert LEAGUES['ucl'].CRYPTO is not None and LEAGUES['ucl'].CRYPTO.symbol_prefix is None


def test_soccer_factory_matches_world_cup_shared_vocab():
    # FIFA adds to_advance aliases on top of the shared soccer factory.
    crypto = require(LEAGUES['world_cup'].CRYPTO)
    shared = soccer_crypto_config("FIFA").contract_types
    assert shared.items() <= crypto.contract_types.items()
    assert "To Lift The Cup" not in shared
    assert "To Win Bronze" not in shared
    assert crypto.contract_types["To Advance"] == MarketType.TO_ADVANCE


def test_nba_props_use_hyphen_period_gate():
    assert NBA_CRYPTO is not None
    assert NBA_CRYPTO.prop_period_type == "Full-Game"


def test_wnba_crypto_uses_hyphen_period_for_game_lines():
    assert WNBA_CRYPTO is not None
    assert WNBA_CRYPTO.league == "WNBA"
    assert WNBA_CRYPTO.period_type == "Full-Game"
    cfg = build_tip_league(next(r for r in load_fixture().leagues if r.league == "wnba"))
    assert cfg.PX is not None
    assert cfg.PX.tournament_id == 1600000176


def test_wnba_crypto_maps_over_under_props():
    """Basketball props are true Over/Under stat lines (Full-Game gate)."""
    assert WNBA_CRYPTO is not None
    assert WNBA_CRYPTO.prop_period_type == "Full-Game"
    assert WNBA_CRYPTO.prop_contract_types == {
        "Total Points": MarketType.PLAYER_POINTS,
        "Total Points Milestones": MarketType.PLAYER_POINTS,
        "Total Rebounds": MarketType.PLAYER_REBOUNDS,
        "Total Rebounds Milestones": MarketType.PLAYER_REBOUNDS,
        "Total Assists": MarketType.PLAYER_ASSISTS,
        "Total Assists Milestones": MarketType.PLAYER_ASSISTS,
        "Total 3-Pointers Made": MarketType.PLAYER_THREES,
        "Total 3-Pointers Made Milestones": MarketType.PLAYER_THREES,
    }


def test_nfl_crypto_maps_player_props():
    """NFL props are Over/Under stat lines + anytime-TD (Full-Game gate).

    Plain "Total X" and its "... Milestones" ladder share one MarketType; the
    anytime "To Score a Touchdown" resolves to player_touchdowns over 0.5 via
    _FIXED_OVER_HALF.  Feed strings verified against crypto_underlying_securities.
    """
    c = NFL_CRYPTO
    assert c is not None
    assert c.prop_period_type == "Full-Game"
    p = c.prop_contract_types
    assert p["Total Receiving Yards"] == MarketType.PLAYER_RECEIVING_YARDS
    assert p["Total Receiving Yards Milestones"] == MarketType.PLAYER_RECEIVING_YARDS
    assert p["Total Rushing Yards Milestones"] == MarketType.PLAYER_RUSHING_YARDS
    assert p["Total Receptions Milestones"] == MarketType.PLAYER_RECEPTIONS
    assert p["Total Passing Yards Milestones"] == MarketType.PLAYER_PASSING_YARDS
    assert p["Total Passing Touchdowns Milestones"] == MarketType.PLAYER_PASSING_TOUCHDOWNS
    assert p["Total Pass Completions Milestones"] == MarketType.PLAYER_PASSING_COMPLETIONS
    assert p["Total Rushing Attempts"] == MarketType.PLAYER_RUSHING_ATTEMPTS
    assert p["Longest Reception"] == MarketType.PLAYER_LONGEST_RECEPTION
    assert p["To Score a Touchdown"] == MarketType.PLAYER_TOUCHDOWNS
    assert p["To Score 2+ Touchdowns"] == MarketType.PLAYER_TOUCHDOWNS
    assert p["To Score 3+ Touchdowns"] == MarketType.PLAYER_TOUCHDOWNS
    assert p["To Score First Touchdown"] == MarketType.FIRST_TOUCHDOWN_SCORER
    assert p["Interceptions Thrown"] == MarketType.PLAYER_INTERCEPTIONS
    assert p["Interceptions Thrown Milestones"] == MarketType.PLAYER_INTERCEPTIONS
    assert c.team_prop_period_type == "Full-Game"
    assert c.team_prop_contract_types["Total Points"] == MarketType.TEAM_TOTAL
    # NCAAF shares the football prop vocabulary (same builder).
    assert NCAAF_CRYPTO is not None
    assert NCAAF_CRYPTO.prop_contract_types == c.prop_contract_types
    assert NCAAF_CRYPTO.team_prop_contract_types == c.team_prop_contract_types
    assert p["Total Rushing + Receiving Yards"] == MarketType.PLAYER_RUSHING_RECEIVING_YARDS
    assert p["Total Passing + Rushing Yards"] == MarketType.PLAYER_PASSING_RUSHING_YARDS


def test_offseason_leagues_use_best_guess_periods():
    assert NFL_CRYPTO is not None and NFL_CRYPTO.period_type == "Full Game"
    assert NCAAF_CRYPTO is not None and NCAAF_CRYPTO.period_type == "Full-Game"
    assert NHL_CRYPTO is not None
    ncaab = build_tip_league(next(r for r in load_fixture().leagues if r.league == "ncaab"))
    assert ncaab.CRYPTO is not None and ncaab.CRYPTO.period_type == "Full-Game"


def test_soccer_crypto_leagues_are_in_from_fix_harvest_registry():
    """CRYPTO-wired soccer must be harvestable from the tip exchange."""
    optic_ids = _tip_optic_league_ids()
    soccer = {
        "epl": "EPL",
        "france_ligue_1": "FRL1",
        "germany_bundesliga": "DEB",
        "italy_serie_a": "ITSA",
        "mls": "MLS",
        "la_liga": "ESP",
        "liga_mx": "LMX",
        "ucl": "UCL",
        "europa_league": "UEL",
        "europa_conference_league": "UCOL",
        "argentina_primera": "ARP",
        "brazil_serie_a": "BRSA",
        "world_cup": "FIFA",
    }
    for key, meta in soccer.items():
        assert _tip_crypto_meta(key) == meta, key
        assert optic_ids[key], key


def test_ncaaf_crypto_is_in_from_fix_harvest_registry():
    optic_ids = _tip_optic_league_ids()
    assert _tip_crypto_meta("ncaaf") == "CFB"
    assert optic_ids["ncaaf"] == "ncaaf"


def test_esports_crypto_leagues_are_in_from_fix_harvest_registry():
    """CS2/LoL/Dota 2 need tip crypto meta or fixtures drop as no identity."""
    optic_ids = _tip_optic_league_ids()
    for key, meta in (("cs2", "CS2"), ("lol", "LOL"), ("dota_2", "DOTA2")):
        assert _tip_crypto_meta(key) == meta, key
        assert optic_ids[key], key

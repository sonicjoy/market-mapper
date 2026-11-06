"""Tests for the crypto.com mapper — crypto_com.parse_selection() and
crypto_com.build_rows().

Records inline rather than fixture-sourced, matching the repo's other
mapper unit tests.  The strings are real selections carved from the
live FIX feed (NBA OKC@NYK, 2026-06-03), the same shapes that live in
scratch/crypto_com_markets.sample.jsonl.
"""

import json

import pytest

from mappers.exchanges.crypto_com import (
    build_rows,
    dedupe_superseded,
    normalize_period_type,
    parse_selection,
    periods_match,
)
from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.shared import TIE_SIDE, CollisionEntry
from mappers.vocab.baseball_markets import MLB_CRYPTO
from mappers.vocab.basketball_markets import NBA_CRYPTO, WNBA_CRYPTO
from mappers.vocab.football_markets import NCAAF_CRYPTO, NFL_CRYPTO
from mappers.vocab.hockey_markets import NHL_CRYPTO
from tests.mappers._require import require

SOCCER_CRYPTO = require(LEAGUES["world_cup"].CRYPTO)

# Shared event context (full on-disk keys, as the fetcher writes them).
_NBA_GAME = {
    "eventMetaLEAGUE": "NBA", "eventMetaSPORTS_GROUPING": "BASKETBALL",
    "eventMetaEVENT_DATE": "2026-06-02T23:00:00+00:00",
    "eventMetaHOME_PARTICIPANT": "New York Knicks",
    "eventMetaAWAY_PARTICIPANT": "Oklahoma City Thunder",
    "eventMetaEXTERNAL_HOME_ID": "20000006",
    "eventMetaEXTERNAL_AWAY_ID": "20000018",
    "eventMetaEXTERNAL_GAME_ID": "90012345",
    "eventMetaPREDICT_MARKET_TYPE": "Game Line",
    "eventMetaPREDICT_PERIOD_TYPE": "Full Game",
}

# One real selection per game-line shape: moneyline (no value),
# total (Over/Under with threshold), spread (signed value).
MONEYLINE = json.dumps({
    **_NBA_GAME,
    "SecurityID": "ML-NYK-001", "Symbol": "NX.F.OPT.NBA-ML.H",
    "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline",
    "eventMetaPREDICT_OUTCOME_TYPE": "Home",
    "eventName": "New York Knicks to win",
    "eventMetaPREDICT_MARKET_ID": "MKT-1",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-1",
})
TOTAL_OVER = json.dumps({
    **_NBA_GAME,
    "SecurityID": "TO-001", "Symbol": "NX.F.OPT.NBA-TP.O",
    "eventMetaPREDICT_CONTRACT_TYPE": "Total Points",
    "eventMetaPREDICT_OUTCOME_TYPE": "Over",
    "eventMetaPREDICT_VALUE": "201.5",
    "eventName": "Over 201.5 to win",
    "eventMetaPREDICT_MARKET_ID": "MKT-2",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-2",
})
SPREAD_HOME = json.dumps({
    **_NBA_GAME,
    "SecurityID": "SP-001", "Symbol": "NX.F.OPT.NBA-SP.H",
    "eventMetaPREDICT_CONTRACT_TYPE": "Spread",
    "eventMetaPREDICT_OUTCOME_TYPE": "Home",
    "eventMetaPREDICT_VALUE": "-1.5",
    "eventName": "New York Knicks -1.5 to win",
    "eventMetaPREDICT_MARKET_ID": "MKT-3",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-3",
})


def test_parse_moneyline_has_no_line():
    sel = parse_selection(MONEYLINE)
    assert sel is not None
    assert sel.contract_type == "Moneyline"
    assert sel.outcome_type == "Home"
    assert sel.value is None
    assert sel.security_id == "ML-NYK-001"


def test_parse_allows_null_selection_name():
    record = json.loads(MONEYLINE)
    record["eventName"] = None

    sel = parse_selection(json.dumps(record))

    assert sel is not None
    assert sel.selection_name is None


def test_parse_total_carries_threshold():
    sel = parse_selection(TOTAL_OVER)
    assert sel is not None
    assert sel.contract_type == "Total Points"
    assert sel.outcome_type == "Over"
    assert sel.value == 201.5


def test_parse_spread_carries_signed_line():
    sel = parse_selection(SPREAD_HOME)
    assert sel is not None
    assert sel.contract_type == "Spread"
    assert sel.outcome_type == "Home"
    assert sel.value == -1.5


# === build_rows: canonical translation (home="NYK", away="OKC") ===

# Side resolution is identity-based: it resolves the selection's own
# external_home_id / external_away_id, so build_rows needs the alias map.
ALIASES = {
    "20000006": "NYK",   # New York Knicks
    "20000018": "OKC",   # Oklahoma City Thunder
    "20000009": "BOS",   # Boston Celtics
}


def _build(*lines, home="NYK", away="OKC", skipped=None):
    # parse_selection returns None for non-game-lines (skipped on read);
    # the walrus filter mirrors what the pipeline's load loop does.
    kw: dict = {}
    if skipped is not None:
        kw["skipped_unmapped_game_lines"] = skipped
    return build_rows(
        "2026-06-02T23:00:00+00:00", home, away,
        [s for ln in lines if (s := parse_selection(ln)) is not None],
        NBA_CRYPTO, aliases=ALIASES, league="nba", **kw)


def test_period_normalization_collapses_hyphen_and_space():
    assert normalize_period_type("Full-Game") == normalize_period_type("Full Game")
    assert periods_match("Full-Game", "Full Game")


def test_moneyline_side_is_team_no_line():
    (row,) = _build(MONEYLINE)
    assert row.market_type == "moneyline"
    assert row.side == "NYK"          # Home → home abbrev
    assert row.line is None
    assert row.entity is None
    assert row.crypto_security_id == "ML-NYK-001"
    assert row.crypto_selection_name == "New York Knicks to win"


def test_total_side_is_over_under_with_threshold():
    (row,) = _build(TOTAL_OVER)
    assert row.market_type == "game_total"
    assert row.side == "over"
    assert row.line == 201.5
    assert row.entity is None


def test_spread_side_is_team_with_signed_line():
    (row,) = _build(SPREAD_HOME)
    assert row.market_type == "point_spread"
    assert row.side == "NYK"
    assert row.line == -1.5


# A crypto.com glitch seen in the live feed: a Spread contract with an
# empty PREDICT_VALUE.  It has no usable threshold and a line-less spread
# also breaks the downstream sort key (spreads pair by signed line), so it
# must be dropped, not emitted.
SPREAD_NO_LINE = json.dumps({
    **_NBA_GAME,
    "SecurityID": "SP-NOLINE", "Symbol": "NX.F.OPT.NBA-SP.H",
    "eventMetaPREDICT_CONTRACT_TYPE": "Spread",
    "eventMetaPREDICT_OUTCOME_TYPE": "Home",
    "eventMetaPREDICT_VALUE": "",
    "eventName": "New York Knicks to win",
    "eventMetaPREDICT_MARKET_ID": "MKT-3",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-3",
})


def test_lineless_spread_is_skipped_by_default():
    """A Spread with an empty PREDICT_VALUE is dropped in production rather
    than emitted as a line-less point_spread row."""
    assert parse_selection(SPREAD_NO_LINE) is not None
    assert _build(SPREAD_NO_LINE) == []


def test_lineless_spread_raises_in_strict_mode():
    with pytest.raises(ValueError, match="no PREDICT_VALUE line"):
        build_rows(
            "2026-06-02T23:00:00+00:00", "NYK", "OKC",
            [s for ln in (SPREAD_NO_LINE,)
             if (s := parse_selection(ln)) is not None],
            NBA_CRYPTO, aliases=ALIASES, league="nba",
            strict_game_lines=True,
        )


# === Basketball player props (true Over/Under stat lines) ===

# NBA/WNBA props are Over/Under-shaped: the line is in the event name and
# the side in PREDICT_OUTCOME_TYPE.  security_def rows carry the outcome
# type; underlying-catalogue rows leave it blank (side comes from the name).
_NBA_PROP = {
    **_NBA_GAME,
    "eventMetaPREDICT_MARKET_TYPE": "Player Prop",
    "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
}

PROP_POINTS_OVER = json.dumps({
    **_NBA_PROP,
    "SecurityID": "PROP-PTS-1", "Symbol": "NX.F.OPT.NBA-PTS.O",
    "eventMetaPREDICT_CONTRACT_TYPE": "Total Points",
    "eventMetaPREDICT_OUTCOME_TYPE": "Over",
    "eventMetaPARTICIPANT": "Jalen Brunson",
    "eventMetaPLAYER_ID": "20100001",
    "eventName": "Jalen Brunson Over 24.5 Total Points",
    "eventMetaPREDICT_MARKET_ID": "MKT-PTS",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-PTS",
})

# Underlying-catalogue shape: blank outcome type, no value — both side
# and line are recovered from the event name.
PROP_REB_UNDER_NAME_ONLY = json.dumps({
    **_NBA_PROP,
    "SecurityID": "PROP-REB-1", "Symbol": "NX.F.OPT.NBA-REB.U",
    "eventMetaPREDICT_CONTRACT_TYPE": "Total Rebounds",
    "eventMetaPARTICIPANT": "Jalen Brunson",
    "eventMetaPLAYER_ID": "20100001",
    "eventName": "Jalen Brunson Under 3.5 Total Rebounds",
    "eventMetaPREDICT_MARKET_ID": "MKT-REB",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-REB",
})


def test_basketball_prop_over_from_outcome_and_name():
    """Over/Under stat line: side from outcome_type, line from event name."""
    (row,) = _build(PROP_POINTS_OVER)
    assert row.market_type == "player_points"
    assert row.entity == "jalen_brunson"
    assert row.side == "over"
    assert row.line == 24.5
    assert row.crypto_security_id == "PROP-PTS-1"


def test_basketball_prop_blank_outcome_reads_side_from_name():
    """Underlying rows leave outcome_type blank — the name gives both."""
    (row,) = _build(PROP_REB_UNDER_NAME_ONLY)
    assert row.market_type == "player_rebounds"
    assert row.entity == "jalen_brunson"
    assert row.side == "under"
    assert row.line == 3.5


def _build_wnba(*lines, home="ATL", away="LAS"):
    return build_rows(
        "2026-08-20T02:00:00+00:00", home, away,
        [s for ln in lines if (s := parse_selection(ln)) is not None],
        WNBA_CRYPTO, aliases=ALIASES, league="wnba")


def test_wnba_points_milestone_n_plus_maps_to_player_points():
    """Milestone N+ is over N-0.5 — same fetch infer as MLB hits 1+."""
    payload = json.dumps({
        "eventMetaLEAGUE": "WNBA",
        "eventMetaSPORTS_GROUPING": "WNBA",
        "eventMetaEVENT_DATE": "2026-08-20T02:00:00+00:00",
        "eventMetaHOME_PARTICIPANT": "Atlanta Dream",
        "eventMetaAWAY_PARTICIPANT": "Los Angeles Sparks",
        "eventMetaEXTERNAL_HOME_ID": "20000006",
        "eventMetaEXTERNAL_AWAY_ID": "20000018",
        "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.WNBA-00001-260820",
        "eventMetaPREDICT_MARKET_TYPE": "Player Prop",
        "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
        "eventMetaPREDICT_CONTRACT_TYPE": "Total Points Milestones",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "19.5",
        "eventMetaPARTICIPANT": "Allisha Gray",
        "SecurityID": "WNBA-PTS-MS-1",
        "Symbol": "NX.F.OPT.WNBA-00001-260820-M.O.1.200",
        "eventName": "Allisha Gray Total Points Milestone 20+",
        "eventMetaPREDICT_MARKET_ID": "MKT-WNBA-PTS-MS",
        "eventMetaPREDICT_OUTCOME_ID": "OUT-WNBA-PTS-MS",
    })
    (row,) = _build_wnba(payload)
    assert row.market_type == "player_points"
    assert row.entity == "allisha_gray"
    assert row.side == "over"
    assert row.line == 19.5


# === NFL build_rows (player props → Optic-wired MarketTypes) ===

_NFL_PROP_BASE = {
    "eventMetaLEAGUE": "NFL",
    "eventMetaSPORTS_GROUPING": "NFL",
    "eventMetaEVENT_DATE": "2026-09-11T00:15:00+00:00",
    "eventMetaHOME_PARTICIPANT": "Los Angeles Rams",
    "eventMetaAWAY_PARTICIPANT": "San Francisco 49ers",
    "eventMetaEXTERNAL_HOME_ID": "30000001",
    "eventMetaEXTERNAL_AWAY_ID": "30000002",
    "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.NFL-00001-260910",
    "eventMetaPREDICT_MARKET_TYPE": "Player Prop",
    "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
    "eventMetaPREDICT_MARKET_ID": "MKT-NFL",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-NFL",
}


def _build_nfl(*lines, home="LAR", away="SF", aliases=None):
    # Props are player-scoped: build_rows passes home/away straight through
    # (no team-side resolution), so ALIASES is unused here.  Team props pass
    # crypto_id aliases for EXTERNAL_* / TEAM_ID.
    return build_rows(
        "2026-09-11T00:15:00+00:00", home, away,
        [s for ln in lines if (s := parse_selection(ln)) is not None],
        NFL_CRYPTO, aliases=aliases if aliases is not None else ALIASES,
        league="nfl")


_TT_ALIASES = {**ALIASES, "dal-id": "DAL", "nyg-id": "NYG", "nyj-id": "NYJ"}
_NFL_TT_BASE = {
    **_NFL_PROP_BASE,
    "eventMetaPREDICT_MARKET_TYPE": "Team Prop",
    "eventMetaHOME_PARTICIPANT": "Dallas Cowboys",
    "eventMetaAWAY_PARTICIPANT": "New York Giants",
    "eventMetaEXTERNAL_HOME_ID": "dal-id",
    "eventMetaEXTERNAL_AWAY_ID": "nyg-id",
    "eventMetaPREDICT_CONTRACT_TYPE": "Total Points",
}


_NFL_ALIASES = {**ALIASES, "30000001": "LAR", "30000002": "SF"}


def test_nfl_1st_half_moneyline_maps():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_MARKET_TYPE": "Game Line",
        "eventMetaPREDICT_PERIOD_TYPE": "1st Half",
        "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline (3-Way)",
        "eventMetaPREDICT_OUTCOME_TYPE": "Home",
        "SecurityID": "NFL-1HML-H",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.10",
        "eventName": "Los Angeles Rams 1st Half Moneyline",
    })
    (row,) = _build_nfl(payload, aliases=_NFL_ALIASES)
    assert row.market_type == "1h_winner_3way"
    assert row.side == "LAR"


_NFL_PERIOD_LINE = {
    **_NFL_PROP_BASE,
    "eventMetaPREDICT_MARKET_TYPE": "Game Line",
    "SecurityID": "NFL-PERIOD",
    "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.20",
}


@pytest.mark.parametrize(("period", "contract", "outcome", "value", "market_type", "side", "line"), [
    ("2nd Half", "Spread", "Away", "-3.5", "2h_point_spread", "SF", -3.5),
    ("2nd Half", "Total Points", "Over", "20.5", "2h_total", "over", 20.5),
    ("2nd Quarter", "Spread", "Home", "2.5", "2q_point_spread", "LAR", 2.5),
    ("2nd Quarter", "Total Points", "Under", "13.5", "2q_total", "under", 13.5),
    ("3rd Quarter", "Moneyline (3-Way)", "Draw", "", "3q_winner_3way", TIE_SIDE, None),
    ("4th Quarter", "Spread", "Away", "-0.5", "4q_point_spread", "SF", -0.5),
])
def test_football_period_game_lines_map(period, contract, outcome, value, market_type, side, line):
    """crypto.com lists every half/quarter as Game Line + period type (CFB/NFL)."""
    payload = json.dumps({
        **_NFL_PERIOD_LINE,
        "eventMetaPREDICT_PERIOD_TYPE": period,
        "eventMetaPREDICT_CONTRACT_TYPE": contract,
        "eventMetaPREDICT_OUTCOME_TYPE": outcome,
        "eventMetaPREDICT_VALUE": value,
    })
    (row,) = _build_nfl(payload, aliases=_NFL_ALIASES)
    assert (row.market_type, row.side, row.line) == (market_type, side, line)


_NHL_PROP_BASE = {
    **_NFL_PROP_BASE,
    "eventMetaLEAGUE": "NHL",
    "eventMetaSPORTS_GROUPING": "NHL",
    "eventMetaHOME_PARTICIPANT": "Washington Capitals",
    "eventMetaAWAY_PARTICIPANT": "New York Rangers",
    "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.NHL-00001-261009",
    "eventMetaPARTICIPANT": "Alex Ovechkin",
    "eventMetaPLAYER_ID": "nhl-ovi",
    "SecurityID": "NHL-PROP",
    "Symbol": "NX.F.OPT.NHL-00001-261009-M.O.1.40",
}


@pytest.mark.parametrize(("contract", "outcome", "value", "market_type", "side", "line"), [
    ("To Score a Goal", "Yes", "", "player_goals", "over", 0.5),
    ("Total Goals", "Under", "0.5", "player_goals", "under", 0.5),
    ("Total Points Milestones", "Over", "1.5", "player_points", "over", 1.5),
    ("Total Shots on Goal", "Over", "2.5", "player_shots_on_goal", "over", 2.5),
    ("Total Assists", "Over", "0.5", "player_assists", "over", 0.5),
    ("Total Saves", "Over", "21.5", "player_saves", "over", 21.5),
    ("First Goal Scorer", "Yes", "", "first_goal_scorer", "yes", None),
])
def test_nhl_player_props_map(contract, outcome, value, market_type, side, line):
    payload = json.dumps({
        **_NHL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": contract,
        "eventMetaPREDICT_OUTCOME_TYPE": outcome,
        "eventMetaPREDICT_VALUE": value,
    })
    (row,) = build_rows(
        "2026-10-09T23:00:00+00:00", "WSH", "NYR",
        [s for s in (parse_selection(payload),) if s is not None],
        NHL_CRYPTO, aliases=ALIASES, league="nhl")
    assert (row.market_type, row.entity, row.side, row.line) == (
        market_type, "alex_ovechkin", side, line)


def test_football_two_way_period_moneyline_is_not_the_3way_market():
    """A period "Moneyline" without a Draw outcome must not stamp *_winner_3way."""
    payload = json.dumps({
        **_NFL_PERIOD_LINE,
        "eventMetaPREDICT_PERIOD_TYPE": "1st Quarter",
        "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline",
        "eventMetaPREDICT_OUTCOME_TYPE": "Home",
    })
    assert _build_nfl(payload, aliases=_NFL_ALIASES) == []


def test_nfl_receiving_yards_milestone_maps_over_under():
    """"Milestone 60+" → player_receiving_yards over 59.5 (same infer as WNBA)."""
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "Total Receiving Yards Milestones",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "59.5",
        "eventMetaPARTICIPANT": "Puka Nacua",
        "SecurityID": "NFL-RECYDS-MS-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.198",
        "eventName": "Puka Nacua Total Receiving Yards Milestone 60+",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "player_receiving_yards"
    assert row.entity == "puka_nacua"
    assert row.side == "over"
    assert row.line == 59.5


def test_nfl_to_score_a_touchdown_maps_anytime_over_half():
    """"To Score a Touchdown" (Yes leg) → player_touchdowns over 0.5."""
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score a Touchdown",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "eventMetaPARTICIPANT": "Christian McCaffrey",
        "SecurityID": "NFL-ANYTD-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.112",
        "eventName": "Christian McCaffrey To Score a Touchdown",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "player_touchdowns"
    assert row.entity == "christian_mccaffrey"
    assert row.side == "over"
    assert row.line == 0.5


def test_nfl_first_touchdown_scorer_is_yes_no():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score First Touchdown",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "eventMetaPARTICIPANT": "Puka Nacua",
        "SecurityID": "NFL-FIRSTTD-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.120",
        "eventName": "Puka Nacua To Score First Touchdown",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "first_touchdown_scorer"
    assert row.entity == "puka_nacua"
    assert row.side == "yes"
    assert row.line is None


def test_nfl_to_score_two_plus_touchdowns_is_over_one_point_five():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score 2+ Touchdowns",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "eventMetaPARTICIPANT": "Christian McCaffrey",
        "SecurityID": "NFL-2TD-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.130",
        "eventName": "Christian McCaffrey To Score 2+ Touchdowns",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "player_touchdowns"
    assert row.side == "over"
    assert row.line == 1.5


def test_nfl_interceptions_thrown_maps_over_under():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "Interceptions Thrown",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "0.5",
        "eventMetaPARTICIPANT": "Matthew Stafford",
        "SecurityID": "NFL-INT-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.140",
        "eventName": "Matthew Stafford Over 0.5 Interceptions Thrown",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "player_interceptions"
    assert row.entity == "matthew_stafford"
    assert row.side == "over"
    assert row.line == 0.5


def test_nfl_team_prop_total_points_uses_short_participant():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "SecurityID": "NFL-TT-NYG",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.222",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    (row,) = _build_nfl(payload, home="DAL", away="NYG", aliases=_TT_ALIASES)
    assert row.market_type == "team_total"
    assert row.entity == "NYG"
    assert row.side == "over"
    assert row.line == 22.5


def test_nfl_team_prop_total_points_uses_team_id_alias():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "eventMetaTEAM_ID": "nyg-feed-id",
        "SecurityID": "NFL-TT-NYG-ID",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.223",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    aliases = {**_TT_ALIASES, "nyg-feed-id": "NYG"}
    (row,) = _build_nfl(payload, home="DAL", away="NYG", aliases=aliases)
    assert row.entity == "NYG"
    assert row.market_type == "team_total"


def test_nfl_team_prop_falls_back_to_nickname_when_team_id_alias_missing():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "eventMetaTEAM_ID": "nyg-feed-id",
        "SecurityID": "NFL-TT-NYG-FB",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.224",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    (row,) = _build_nfl(payload, home="DAL", away="NYG", aliases=_TT_ALIASES)
    assert row.entity == "NYG"


def test_nfl_team_prop_nickname_uses_crypto_slot_id_when_orientation_flipped():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaHOME_PARTICIPANT": "New York Giants",
        "eventMetaAWAY_PARTICIPANT": "Dallas Cowboys",
        "eventMetaEXTERNAL_HOME_ID": "nyg-id",
        "eventMetaEXTERNAL_AWAY_ID": "dal-id",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "SecurityID": "NFL-TT-FLIP",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.227",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    (row,) = _build_nfl(payload, home="DAL", away="NYG", aliases=_TT_ALIASES)
    assert row.entity == "NYG"


def test_nfl_team_prop_skips_collision_team_id_without_raising():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "eventMetaTEAM_ID": "collide-id",
        "SecurityID": "NFL-TT-COLLIDE",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.228",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    aliases = {
        **_TT_ALIASES,
        "collide-id": [
            CollisionEntry(canonical="NYG", id=1, name="New York Giants"),
            CollisionEntry(canonical="NYJ", id=2, name="New York Jets"),
        ],
    }
    (row,) = _build_nfl(payload, home="DAL", away="NYG", aliases=aliases)
    assert row.entity == "NYG"


def test_nfl_team_prop_skips_ambiguous_nickname():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaHOME_PARTICIPANT": "New York Jets",
        "eventMetaAWAY_PARTICIPANT": "New York Giants",
        "eventMetaEXTERNAL_HOME_ID": "nyj-id",
        "eventMetaEXTERNAL_AWAY_ID": "nyg-id",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "New York",
        "SecurityID": "NFL-TT-AMB",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.225",
        "eventName": "New York Over 22.5 Total Points",
    })
    assert _build_nfl(payload, home="NYJ", away="NYG", aliases=_TT_ALIASES) == []


def test_nfl_team_prop_collision_external_ids_do_not_abort():
    """Colliding EXTERNAL_* aliases must not zero the league on team props."""
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "eventMetaTEAM_ID": "nyg-feed-id",
        "SecurityID": "NFL-TT-COLLIDE-EXT",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.230",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    aliases = {
        **_TT_ALIASES,
        "nyg-feed-id": "NYG",
        "dal-id": [
            CollisionEntry(canonical="DAL", id=1, name="Dallas Cowboys"),
            CollisionEntry(canonical="NYG", id=2, name="New York Giants"),
        ],
        "nyg-id": [
            CollisionEntry(canonical="NYG", id=2, name="New York Giants"),
            CollisionEntry(canonical="NYJ", id=3, name="New York Jets"),
        ],
    }
    (row,) = _build_nfl(payload, home="DAL", away="NYG", aliases=aliases)
    assert row.entity == "NYG"
    assert row.market_type == "team_total"


def test_nfl_team_prop_skips_crossed_crypto_ids():
    """Swapped crypto_id aliases must not stamp a team total on the wrong side."""
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "22.5",
        "eventMetaPARTICIPANT": "Giants",
        "SecurityID": "NFL-TT-CROSSED",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.229",
        "eventName": "New York Giants Over 22.5 Total Points",
    })
    aliases = {**_TT_ALIASES, "dal-id": "NYG", "nyg-id": "DAL"}
    names = {"DAL": "Dallas Cowboys", "NYG": "New York Giants"}
    skipped: list[str] = []
    rows = build_rows(
        "2026-09-11T00:15:00+00:00", "DAL", "NYG",
        [s for ln in [payload] if (s := parse_selection(ln)) is not None],
        NFL_CRYPTO, aliases=aliases, league="nfl",
        entity_names=names, skipped_name_mismatch=skipped,
    )
    assert rows == []
    assert skipped


def test_nfl_team_prop_skips_when_over_under_has_no_line():
    payload = json.dumps({
        **_NFL_TT_BASE,
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPARTICIPANT": "Giants",
        "SecurityID": "NFL-TT-NOLINE",
        "Symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.226",
        "eventName": "New York Giants Total Points",
    })
    assert _build_nfl(payload, home="DAL", away="NYG", aliases=_TT_ALIASES) == []


def test_nfl_to_score_three_plus_touchdowns_is_over_two_point_five():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score 3+ Touchdowns",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "eventMetaPARTICIPANT": "Christian McCaffrey",
        "SecurityID": "NFL-3TD-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.131",
        "eventName": "Christian McCaffrey To Score 3+ Touchdowns",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "player_touchdowns"
    assert row.side == "over"
    assert row.line == 2.5


def test_nfl_to_score_touchdown_no_is_skipped():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score a Touchdown",
        "eventMetaPREDICT_OUTCOME_TYPE": "No",
        "eventMetaPARTICIPANT": "Christian McCaffrey",
        "SecurityID": "NFL-ANYTD-NO",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.113",
        "eventName": "Christian McCaffrey Not To Score a Touchdown",
    })
    assert _build_nfl(payload) == []


def test_nfl_two_plus_touchdowns_ignores_over_in_event_name():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score 2+ Touchdowns",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "eventMetaPARTICIPANT": "Christian McCaffrey",
        "SecurityID": "NFL-2TD-OVER-NAME",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.132",
        "eventName": "Christian McCaffrey Over 4.5 To Score 2+ Touchdowns",
    })
    (row,) = _build_nfl(payload)
    assert row.line == 1.5
    assert row.side == "over"


def test_ncaaf_team_prop_total_points():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaLEAGUE": "NCAAF",
        "eventMetaSPORTS_GROUPING": "NCAAF",
        "eventMetaPREDICT_MARKET_TYPE": "Team Prop",
        "eventMetaHOME_PARTICIPANT": "Cal Poly Mustangs",
        "eventMetaAWAY_PARTICIPANT": "San Jose State Spartans",
        "eventMetaEXTERNAL_HOME_ID": "cp-id",
        "eventMetaEXTERNAL_AWAY_ID": "sjs-id",
        "eventMetaPREDICT_CONTRACT_TYPE": "Total Points",
        "eventMetaPREDICT_OUTCOME_TYPE": "Under",
        "eventMetaPREDICT_VALUE": "27.5",
        "eventMetaPARTICIPANT": "San Jose State",
        "SecurityID": "NCAAF-TT-SJS",
        "Symbol": "NX.F.OPT.NCAAF-00001-260914-M.O.1.1",
        "eventName": "San Jose State Under 27.5 Total Points",
    })
    aliases = {**ALIASES, "cp-id": "CP", "sjs-id": "SJS"}
    (row,) = build_rows(
        "2026-09-11T00:15:00+00:00", "CP", "SJS",
        [s for ln in [payload] if (s := parse_selection(ln)) is not None],
        NCAAF_CRYPTO, aliases=aliases, league="ncaaf",
    )
    assert row.market_type == "team_total"
    assert row.entity == "SJS"
    assert row.side == "under"
    assert row.line == 27.5


def test_ncaaf_team_prop_skips_bare_state_nickname():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaLEAGUE": "NCAAF",
        "eventMetaSPORTS_GROUPING": "NCAAF",
        "eventMetaPREDICT_MARKET_TYPE": "Team Prop",
        "eventMetaHOME_PARTICIPANT": "Ohio State Buckeyes",
        "eventMetaAWAY_PARTICIPANT": "Penn State Nittany Lions",
        "eventMetaEXTERNAL_HOME_ID": "osu-id",
        "eventMetaEXTERNAL_AWAY_ID": "psu-id",
        "eventMetaPREDICT_CONTRACT_TYPE": "Total Points",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "48.5",
        "eventMetaPARTICIPANT": "State",
        "SecurityID": "NCAAF-TT-STATE",
        "Symbol": "NX.F.OPT.NCAAF-00002-260914-M.O.1.1",
        "eventName": "State Over 48.5 Total Points",
    })
    aliases = {**ALIASES, "osu-id": "OSU", "psu-id": "PSU"}
    rows = build_rows(
        "2026-09-11T00:15:00+00:00", "OSU", "PSU",
        [s for ln in [payload] if (s := parse_selection(ln)) is not None],
        NCAAF_CRYPTO, aliases=aliases, league="ncaaf",
    )
    assert rows == []


def test_nfl_combined_yards_prop_maps():
    payload = json.dumps({
        **_NFL_PROP_BASE,
        "eventMetaPREDICT_CONTRACT_TYPE": "Total Rushing + Receiving Yards",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": "89.5",
        "eventMetaPARTICIPANT": "Puka Nacua",
        "SecurityID": "NFL-COMBO-1",
        "Symbol": "NX.F.OPT.NFL-00001-260910-M.O.1.199",
        "eventName": "Puka Nacua Over 89.5 Total Rushing + Receiving Yards",
    })
    (row,) = _build_nfl(payload)
    assert row.market_type == "player_rushing_+_receiving_yards"
    assert row.entity == "puka_nacua"
    assert row.side == "over"
    assert row.line == 89.5


# === MLB build_rows (FIX-confirmed ids, underlying-shaped game lines) ===

_MLB_GAME = {
    "eventMetaLEAGUE": "MLB",
    "eventMetaSPORTS_GROUPING": "MLB",
    "eventMetaEVENT_DATE": "2026-07-06T23:10:00+00:00",
    "eventMetaHOME_PARTICIPANT": "Kansas City Royals",
    "eventMetaAWAY_PARTICIPANT": "Philadelphia Phillies",
    "eventMetaEXTERNAL_HOME_ID": "10000005",
    "eventMetaEXTERNAL_AWAY_ID": "10000012",
    "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.MLB-00001-260706",
    "eventMetaPREDICT_MARKET_TYPE": "Game Line",
    "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
}

_MLB_MONEYLINE = json.dumps({
    **_MLB_GAME,
    "SecurityID": "MLB-ML-H",
    "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.1",
    "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline",
    "eventMetaPREDICT_OUTCOME_TYPE": "Home",
    "eventMetaPREDICT_MARKET_ID": "MKT-MLB-ML",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-ML",
    "eventName": "Kansas City Royals to win",
})

_MLB_TOTAL = json.dumps({
    **_MLB_GAME,
    "SecurityID": "MLB-TR-O",
    "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.42",
    "eventMetaPREDICT_CONTRACT_TYPE": "Total Runs",
    "eventMetaPREDICT_OUTCOME_TYPE": "Under",
    "eventMetaPREDICT_VALUE": "12.5",
    "eventMetaPREDICT_MARKET_ID": "MKT-MLB-TR",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-TR",
    "eventName": "Under 12.5",
})

_MLB_SPREAD = json.dumps({
    **_MLB_GAME,
    "SecurityID": "MLB-SP-H",
    "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.21",
    "eventMetaPREDICT_CONTRACT_TYPE": "Spread",
    "eventMetaPREDICT_OUTCOME_TYPE": "Home",
    "eventMetaPREDICT_VALUE": "2.5",
    "eventMetaPREDICT_MARKET_ID": "MKT-MLB-SP",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-SP",
    "eventName": "Kansas City Royals +2.5",
})

_MLB_ALIASES = {
    "10000005": "KAN",
    "10000012": "PHI",
}


def _build_mlb(*lines, home="KAN", away="PHI"):
    return build_rows(
        "2026-07-06T23:10:00+00:00", home, away,
        [s for ln in lines if (s := parse_selection(ln)) is not None],
        MLB_CRYPTO, aliases=_MLB_ALIASES, league="mlb")


def test_mlb_moneyline_and_game_lines_build():
    rows = _build_mlb(_MLB_MONEYLINE, _MLB_TOTAL, _MLB_SPREAD)
    by_type = {r.market_type: r for r in rows}
    assert by_type["moneyline"].side == "KAN"
    assert by_type["game_total"].side == "under" and by_type["game_total"].line == 12.5
    assert by_type["point_spread"].side == "KAN" and by_type["point_spread"].line == 2.5


def _mlb_f5(line: str) -> str:
    """Clone an MLB Full-Game fixture onto the 1st-5th Inning period."""
    rec = json.loads(line)
    rec["eventMetaPREDICT_PERIOD_TYPE"] = "1st-5th Inning"
    return json.dumps(rec)


def test_mlb_f5_game_lines_build():
    rows = _build_mlb(
        _mlb_f5(_MLB_MONEYLINE), _mlb_f5(_MLB_TOTAL), _mlb_f5(_MLB_SPREAD))
    by_type = {r.market_type: r for r in rows}
    assert by_type["f5_moneyline_3way"].side == "KAN"
    assert by_type["f5_total"].side == "under" and by_type["f5_total"].line == 12.5
    assert by_type["f5_point_spread"].side == "KAN"
    assert by_type["f5_point_spread"].line == 2.5


def _mlb_3way(period: str, outcome: str, suffix: str) -> str:
    rec = json.loads(_MLB_MONEYLINE)
    rec["eventMetaPREDICT_PERIOD_TYPE"] = period
    rec["eventMetaPREDICT_CONTRACT_TYPE"] = "Moneyline (3-Way)"
    rec["eventMetaPREDICT_OUTCOME_TYPE"] = outcome
    rec["SecurityID"] = f"MLB-3W-{suffix}"
    rec["Symbol"] = f"NX.F.OPT.MLB-00001-260706-M.O.1.{suffix}"
    rec["eventMetaPREDICT_OUTCOME_ID"] = f"OUT-MLB-3W-{suffix}"
    return json.dumps(rec)


def test_mlb_f5_moneyline_3way_home_away_draw():
    rows = _build_mlb(
        _mlb_3way("1st-5th Inning", "Home", "48"),
        _mlb_3way("1st-5th Inning", "Away", "47"),
        _mlb_3way("1st-5th Inning", "Draw", "49"),
    )
    by_side = {r.side: r for r in rows}
    assert set(by_side) == {"KAN", "PHI", TIE_SIDE}
    assert all(r.market_type == "f5_moneyline_3way" and r.line is None for r in rows)
    assert (by_side["KAN"].crypto_symbol or "").endswith(".48")
    assert (by_side["PHI"].crypto_symbol or "").endswith(".47")
    assert (by_side[TIE_SIDE].crypto_symbol or "").endswith(".49")


def test_mlb_f3_moneyline_3way_home_away_draw():
    rows = _build_mlb(
        _mlb_3way("1st-3rd Inning", "Home", "55"),
        _mlb_3way("1st-3rd Inning", "Away", "54"),
        _mlb_3way("1st-3rd Inning", "Draw", "56"),
    )
    by_side = {r.side: r for r in rows}
    assert set(by_side) == {"KAN", "PHI", TIE_SIDE}
    assert all(r.market_type == "f3_moneyline_3way" and r.line is None for r in rows)
    assert (by_side["KAN"].crypto_symbol or "").endswith(".55")
    assert (by_side["PHI"].crypto_symbol or "").endswith(".54")
    assert (by_side[TIE_SIDE].crypto_symbol or "").endswith(".56")


def test_mlb_f3_spread_and_total_are_skipped():
    """Crypto lists F3 spread/total; Optic has no 1st_3_innings counterpart."""
    rec_spread = json.loads(_MLB_SPREAD)
    rec_spread["eventMetaPREDICT_PERIOD_TYPE"] = "1st-3rd Inning"
    rec_total = json.loads(_MLB_TOTAL)
    rec_total["eventMetaPREDICT_PERIOD_TYPE"] = "1st-3rd Inning"
    assert _build_mlb(json.dumps(rec_spread)) == []
    assert _build_mlb(json.dumps(rec_total)) == []


def test_mlb_to_score_a_run_is_first_inning_total_over_half() -> None:
    """Yes @ 1st Inning = Optic first_inning_total over 0.5 (will a run score)."""
    payload = json.dumps({
        **_MLB_GAME,
        "eventMetaPREDICT_MARKET_TYPE": "Game Prop",
        "eventMetaPREDICT_PERIOD_TYPE": "1st Inning",
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score A Run",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "SecurityID": "MLB-TSAR-Y",
        "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.53",
        "eventMetaPREDICT_MARKET_ID": "MKT-MLB-TSAR",
        "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-TSAR",
        "eventName": "To Score A Run",
    })
    (row,) = _build_mlb(payload)
    assert row.market_type == "first_inning_total"
    assert row.side == "over"
    assert row.line == 0.5
    assert row.entity is None
    assert row.home == "KAN" and row.away == "PHI"


def test_mlb_to_score_a_run_no_is_first_inning_total_under_half() -> None:
    payload = json.dumps({
        **_MLB_GAME,
        "eventMetaPREDICT_MARKET_TYPE": "Game Prop",
        "eventMetaPREDICT_PERIOD_TYPE": "1st Inning",
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score A Run",
        "eventMetaPREDICT_OUTCOME_TYPE": "No",
        "SecurityID": "MLB-TSAR-N",
        "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.54",
        "eventMetaPREDICT_MARKET_ID": "MKT-MLB-TSAR-N",
        "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-TSAR-N",
        "eventName": "To Score A Run",
    })
    (row,) = _build_mlb(payload)
    assert row.market_type == "first_inning_total"
    assert row.side == "under"
    assert row.line == 0.5


def test_mlb_to_score_a_run_wrong_period_is_skipped() -> None:
    payload = json.dumps({
        **_MLB_GAME,
        "eventMetaPREDICT_MARKET_TYPE": "Game Prop",
        "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
        "eventMetaPREDICT_CONTRACT_TYPE": "To Score A Run",
        "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
        "SecurityID": "MLB-TSAR-FG",
        "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.99",
        "eventMetaPREDICT_MARKET_ID": "MKT-MLB-TSAR-FG",
        "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-TSAR-FG",
        "eventName": "To Score A Run",
    })
    assert _build_mlb(payload) == []


def test_non_game_line_is_skipped_on_read():
    # The full on-disk file carries everything; non-game-lines are
    # dropped at parse time, before build_rows ever sees them.
    future = json.dumps({**json.loads(MONEYLINE),
                         "eventMetaPREDICT_MARKET_TYPE": "Team Future"})
    assert parse_selection(future) is None
    assert _build(future) == []


def test_wrong_period_is_skipped():
    half = json.dumps({**json.loads(MONEYLINE),
                       "eventMetaPREDICT_PERIOD_TYPE": "1st Half"})
    assert _build(half) == []


def test_period_gate_accepts_hyphen_vs_space():
    """Full-Game vs Full Game must not drop rows at season start."""
    spaced = json.dumps({**json.loads(MONEYLINE),
                         "eventMetaPREDICT_PERIOD_TYPE": "Full-Game"})
    (row,) = _build(spaced)
    assert row.market_type == "moneyline"


def test_unmapped_game_line_contract_type_raises_in_strict_mode():
    novel = json.dumps({**json.loads(MONEYLINE),
                        "eventMetaPREDICT_CONTRACT_TYPE": "Odd/Even"})
    with pytest.raises(ValueError, match="unmapped crypto.com game-line"):
        build_rows(
            "2026-06-02T23:00:00+00:00", "NYK", "OKC",
            [s for ln in (novel,) if (s := parse_selection(ln)) is not None],
            NBA_CRYPTO, aliases=ALIASES, league="nba",
            strict_game_lines=True,
        )


def test_unmapped_game_line_contract_type_skipped_by_default():
    novel = json.dumps({**json.loads(MONEYLINE),
                        "eventMetaPREDICT_CONTRACT_TYPE": "Odd/Even"})
    skipped: list[str] = []
    assert _build(novel, skipped=skipped) == []
    assert skipped == ["Odd/Even"]


# === Identity-based side resolution (flip safety) ===

def test_flipped_orientation_keeps_sides_identity_based():
    """When the fixture's home/away is the opposite of the crypto feed's
    (neutral-site flip), the side must still follow the selection's own
    team — not the fixture position — while the row keeps the fixture's
    orientation for the merge key.

    The crypto MONEYLINE selection is "Home" with external_home_id
    20000006 (New York Knicks).  With the fixture flipped (home=OKC,
    away=NYK), the side must be NYK, not OKC.  Positional resolution
    would (wrongly) return OKC.
    """
    (row,) = _build(MONEYLINE, home="OKC", away="NYK")
    assert row.side == "NYK"            # selection's home team, not fixture's
    assert row.home == "OKC" and row.away == "NYK"   # row keeps fixture orientation
    # Totals carry no team, so a flip leaves over/under untouched.
    (tot,) = _build(TOTAL_OVER, home="OKC", away="NYK")
    assert tot.side == "over"


def test_selection_team_mismatch_is_skipped_with_alert(capsys):
    """A selection whose participants aren't this game's two teams is
    dropped with an ALERT line — never cross-wired onto the fixture, and
    never raised (a raise aborted the whole league's rows)."""
    wrong_game = json.dumps({**json.loads(MONEYLINE),
                             "eventMetaEXTERNAL_HOME_ID": "20000009"})  # Boston
    assert _build(wrong_game) == []   # {BOS, OKC} != {NYK, OKC}
    assert "ALERT: crypto [" in capsys.readouterr().err


def test_selection_team_mismatch_one_alert_per_game(capsys):
    """cron forwards only 40 ALERT lines: a bad game prints one, not one
    per selection."""
    bad = [json.dumps({**json.loads(ln), "eventMetaEXTERNAL_HOME_ID": "20000009"})
           for ln in (MONEYLINE, TOTAL_OVER)]
    assert len(_build(MONEYLINE.replace("NX.F.OPT.NBA-ML.H", "X"), *bad)) == 1
    alerts = [ln for ln in capsys.readouterr().err.splitlines()
              if ln.startswith("ALERT:")]
    assert len(alerts) == 1 and "skipped 2 selection(s)" in alerts[0]


def test_selection_team_mismatch_keeps_other_selections():
    """One bad selection must not cost the game's good ones."""
    wrong_game = json.dumps({**json.loads(MONEYLINE),
                             "eventMetaEXTERNAL_HOME_ID": "20000009"})
    (row,) = _build(wrong_game, TOTAL_OVER)
    assert row.crypto_symbol == json.loads(TOTAL_OVER)["Symbol"]


# === Soccer 3-way moneyline (World Cup) — the THREE_WAY/Draw branch ===

# Real selections from the live feed: England (90000858) v Croatia
# (90000944), all three legs of the 3-way.  SOCCER_CRYPTO is imported
# from LEAGUES['world_cup'].py so the prop / DNB vocabulary stays in sync.
_WC_GAME = {
    "eventMetaLEAGUE": "FIFA", "eventMetaSPORTS_GROUPING": "SOCCER",
    "eventMetaEVENT_DATE": "2026-06-13T19:00:00+00:00",
    "eventMetaHOME_PARTICIPANT": "England",
    "eventMetaAWAY_PARTICIPANT": "Croatia",
    "eventMetaEXTERNAL_HOME_ID": "90000858",
    "eventMetaEXTERNAL_AWAY_ID": "90000944",
    "eventMetaEXTERNAL_GAME_ID": "90086930",
    "eventMetaPREDICT_MARKET_TYPE": "Game Line",
    "eventMetaPREDICT_PERIOD_TYPE": "90 Minutes and Stoppage Time",
    "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline (3-Way)",
    "eventMetaPREDICT_MARKET_ID": "WC-MKT-1",  # one market, three legs
}
WC_HOME = json.dumps({**_WC_GAME, "SecurityID": "WC-ENG-H",
                      "Symbol": "NX.F.OPT.FIFA-ML3.H",
                      "eventMetaPREDICT_OUTCOME_TYPE": "Home",
                      "eventMetaPREDICT_OUTCOME_ID": "WC-OUT-H",
                      "eventName": "England to win"})
WC_AWAY = json.dumps({**_WC_GAME, "SecurityID": "WC-CRO-A",
                      "Symbol": "NX.F.OPT.FIFA-ML3.A",
                      "eventMetaPREDICT_OUTCOME_TYPE": "Away",
                      "eventMetaPREDICT_OUTCOME_ID": "WC-OUT-A",
                      "eventName": "Croatia to win"})
WC_DRAW = json.dumps({**_WC_GAME, "SecurityID": "WC-DRAW",
                      "Symbol": "NX.F.OPT.FIFA-ML3.D",
                      "eventMetaPREDICT_OUTCOME_TYPE": "Draw",
                      "eventMetaPREDICT_OUTCOME_ID": "WC-OUT-D",
                      "eventName": "Draw"})

_WC_ALIASES = {"90000858": "ENG", "90000944": "CRO"}


def _build_wc(*lines, home="ENG", away="CRO"):
    return build_rows(
        "2026-06-13T19:00:00+00:00", home, away,
        [s for ln in lines if (s := parse_selection(ln)) is not None],
        SOCCER_CRYPTO, aliases=_WC_ALIASES, league="world_cup")


def test_3way_home_away_are_team_no_line():
    home_row, away_row = _build_wc(WC_HOME, WC_AWAY)
    assert home_row.market_type == "moneyline_3way"
    assert home_row.side == "ENG"
    assert home_row.line is None         # 3-way moneyline has no line
    assert away_row.side == "CRO"
    assert away_row.line is None


def test_3way_draw_is_tie_side():
    """Draw maps to TIE_SIDE so it merges onto Optic/Kalshi draw rows."""
    (row,) = _build_wc(WC_DRAW)
    assert row.market_type == "moneyline_3way"
    assert row.side == TIE_SIDE          # "_TIE"
    assert row.line is None
    assert row.entity is None


def test_3way_sides_are_identity_based_under_flip():
    """Neutral-site flip (real for World Cup): the fixture orientation is
    the opposite of the feed's, but each leg follows its own team."""
    home_row, away_row, draw_row = _build_wc(
        WC_HOME, WC_AWAY, WC_DRAW, home="CRO", away="ENG")
    assert home_row.side == "ENG"        # the "Home" leg is still England
    assert away_row.side == "CRO"
    assert draw_row.side == TIE_SIDE     # draw is orientation-free
    assert home_row.home == "CRO" and home_row.away == "ENG"  # keeps fixture


def test_draw_on_two_way_moneyline_raises():
    """A Draw outcome on a 2-way MONEYLINE (e.g. NBA) is a feed error —
    basketball can't draw — so it must raise, not silently map."""
    nba_draw = json.dumps({**json.loads(MONEYLINE),
                           "eventMetaPREDICT_OUTCOME_TYPE": "Draw"})
    with pytest.raises(ValueError, match="unexpected"):
        _build(nba_draw)


# === Soccer to advance (World Cup), confirmed live 2026-06-26 ===

# Real selections from the live feed: Brazil (90000861) v Japan
# (90001208).  outcome_type is Home/Away (not Yes/No); TEAM_ID names
# the advancing team.
_WC_ADVANCE = {
    **_WC_GAME,
    "eventMetaHOME_PARTICIPANT": "Brazil",
    "eventMetaAWAY_PARTICIPANT": "Japan",
    "eventMetaEXTERNAL_HOME_ID": "90000861",
    "eventMetaEXTERNAL_AWAY_ID": "90001208",
    "eventMetaEXTERNAL_GAME_ID": "90086982",
    "eventMetaPREDICT_CONTRACT_TYPE": "To Advance",
    "eventMetaPREDICT_PERIOD_TYPE": "Full Game",
}
WC_ADV_HOME = json.dumps({**_WC_ADVANCE, "SecurityID": "WC-ADV-BRA",
                          "Symbol": "NX.F.OPT.FIFA-ADV-BRA",
                          "eventMetaPREDICT_OUTCOME_TYPE": "Home",
                          "eventMetaPREDICT_OUTCOME_ID": "WC-ADV-OUT-BRA",
                          "eventMetaPARTICIPANT": "Brazil",
                          "eventMetaTEAM_ID": "90000861",
                          "eventName": "Brazil to advance"})
WC_ADV_AWAY = json.dumps({**_WC_ADVANCE, "SecurityID": "WC-ADV-JPN",
                          "Symbol": "NX.F.OPT.FIFA-ADV-JPN",
                          "eventMetaPREDICT_OUTCOME_TYPE": "Away",
                          "eventMetaPREDICT_OUTCOME_ID": "WC-ADV-OUT-JPN",
                          "eventMetaPARTICIPANT": "Japan",
                          "eventMetaTEAM_ID": "90001208",
                          "eventName": "Japan to advance"})
_WC_ADV_ALIASES = {"90000861": "BRA", "90001208": "JPN"}


def _build_wc_advance(*lines, home="BRA", away="JPN"):
    return build_rows(
        "2026-06-29T17:00:00+00:00", home, away,
        [s for ln in lines if (s := parse_selection(ln)) is not None],
        SOCCER_CRYPTO, aliases=_WC_ADV_ALIASES, league="world_cup")


def test_to_advance_is_team_scoped_yes():
    home_row, away_row = _build_wc_advance(WC_ADV_HOME, WC_ADV_AWAY)
    assert home_row.market_type == "to_advance"
    assert home_row.entity == "BRA"
    assert home_row.side == "yes"
    assert home_row.line is None
    assert away_row.entity == "JPN"
    assert away_row.side == "yes"


def test_to_advance_entity_follows_team_id_under_flip():
    """Fixture orientation may differ from the feed; TEAM_ID is stable."""
    home_row, away_row = _build_wc_advance(
        WC_ADV_HOME, WC_ADV_AWAY, home="JPN", away="BRA")
    assert home_row.entity == "BRA"
    assert away_row.entity == "JPN"
    assert home_row.home == "JPN" and home_row.away == "BRA"


def test_to_advance_wrong_period_is_skipped():
    """Regular-time period label must not map onto the ET-inclusive advance leg."""
    wrong_period = json.dumps({**json.loads(WC_ADV_HOME),
                               "eventMetaPREDICT_PERIOD_TYPE":
                               "90 Minutes and Stoppage Time"})
    assert _build_wc_advance(wrong_period) == []


# === Soccer totals / spread (World Cup), confirmed live 2026-06-09 ===

# Both carry the real line verbatim in PREDICT_VALUE: totals as N.5
# Over/Under, spread as the signed goal handicap (Home -2.5 = home
# favoured by 2.5).  No line_offset — the value is the line.
def _wc_line(contract_type, outcome, value, sec):
    return json.dumps({**_WC_GAME, "SecurityID": sec,
                       "Symbol": f"NX.F.OPT.FIFA-{sec}",
                       "eventMetaPREDICT_CONTRACT_TYPE": contract_type,
                       "eventMetaPREDICT_OUTCOME_TYPE": outcome,
                       "eventMetaPREDICT_VALUE": value,
                       "eventMetaPREDICT_OUTCOME_ID": f"OUT-{sec}",
                       "eventName": f"{contract_type} {outcome} {value}"})


def test_total_goals_is_over_under_with_line():
    over, under = _build_wc(
        _wc_line("Total Goals", "Over", "2.5", "WC-TOT-O"),
        _wc_line("Total Goals", "Under", "2.5", "WC-TOT-U"))
    assert over.market_type == "game_total"
    assert over.side == "over" and over.line == 2.5
    assert over.entity is None           # game-scoped
    assert under.side == "under" and under.line == 2.5


def test_soccer_spread_side_is_team_with_signed_line():
    """The goal handicap keeps its sign and team identity: the Home leg
    at -2.5 is the home team giving 2.5, the Away leg its +2.5 mirror."""
    home, away = _build_wc(
        _wc_line("Spread", "Home", "-2.5", "WC-SPR-H"),
        _wc_line("Spread", "Away", "2.5", "WC-SPR-A"))
    assert home.market_type == "point_spread"
    assert home.side == "ENG" and home.line == -2.5
    assert away.side == "CRO" and away.line == 2.5


def test_two_way_moneyline_maps_to_dnb():
    """Draw-no-bet is Home/Away only — maps to moneyline_dnb."""
    home_row, away_row = _build_wc(
        _wc_line("Moneyline (2-Way)", "Home", "", "WC-2W-H"),
        _wc_line("Moneyline (2-Way)", "Away", "", "WC-2W-A"))
    assert home_row.market_type == "moneyline_dnb"
    assert home_row.side == "ENG" and home_row.line is None
    assert away_row.market_type == "moneyline_dnb"
    assert away_row.side == "CRO" and away_row.line is None


def test_semifinal_3way_and_totals_map_with_world_cup_crypto():
    """Regression: Jul 2026 semifinal catalogue rows map on 90' period gate."""
    wc_crypto = SOCCER_CRYPTO

    base = {
        **_WC_GAME,
        "eventMetaHOME_PARTICIPANT": "Spain",
        "eventMetaAWAY_PARTICIPANT": "Argentina",
        "eventMetaEXTERNAL_HOME_ID": "90000958",
        "eventMetaEXTERNAL_AWAY_ID": "90000859",
        "eventMetaEXTERNAL_GAME_ID": "90087010",
        "eventMetaEVENT_DATE": "2026-07-19T19:00:00+00:00",
    }
    aliases = {"90000958": "ESP", "90000859": "ARG"}
    home = json.dumps({**base, "SecurityID": "WC-ESP-H",
                       "Symbol": "NX.F.OPT.FIFA-00001-260719-M.O.1.1.20260830",
                       "eventMetaPREDICT_OUTCOME_ID": "OUT-ESP",
                       "eventMetaPREDICT_OUTCOME_TYPE": "Home",
                       "eventName": "Spain to win"})
    away = json.dumps({**base, "SecurityID": "WC-ARG-A",
                       "Symbol": "NX.F.OPT.FIFA-00001-260719-M.O.1.2.20260830",
                       "eventMetaPREDICT_OUTCOME_ID": "OUT-ARG",
                       "eventMetaPREDICT_OUTCOME_TYPE": "Away",
                       "eventName": "Argentina to win"})
    draw = json.dumps({**base, "SecurityID": "WC-DRAW",
                       "Symbol": "NX.F.OPT.FIFA-00001-260719-M.O.1.3.20260830",
                       "eventMetaPREDICT_OUTCOME_ID": "OUT-DRAW",
                       "eventMetaPREDICT_OUTCOME_TYPE": "Draw",
                       "eventMetaPARTICIPANT": None,
                       "eventName": "Draw"})
    over = json.dumps({**base, "SecurityID": "WC-TOT-O",
                       "Symbol": "NX.F.OPT.FIFA-00001-260719-M.O.1.38.20260830",
                       "eventMetaPREDICT_CONTRACT_TYPE": "Total Goals",
                       "eventMetaPREDICT_OUTCOME_ID": "OUT-OVER",
                       "eventMetaPREDICT_OUTCOME_TYPE": "Over",
                       "eventMetaPREDICT_VALUE": 2.5,
                       "eventName": "Over 2.5"})
    rows = build_rows(
        "2026-07-19T19:00:00+00:00", "ESP", "ARG",
        [s for ln in (home, away, draw, over)
         if (s := parse_selection(ln)) is not None],
        wc_crypto, aliases=aliases, league="world_cup",
    )
    assert {r.market_type for r in rows} == {"moneyline_3way", "game_total"}
    assert sum(r.market_type == "moneyline_3way" for r in rows) == 3
    assert any(r.side == "over" and r.line == 2.5 for r in rows)


# === Soccer player props (World Cup) — Anytime Goal Scorer ===

# A real prop shape from the live feed: a Yes/No threshold contract, no
# PREDICT_VALUE (the "1+" lives in the contract_type string), carrying
# the player name + id.  Player Prop is a separate market group from the
# game lines above; it shares the soccer event context (England v Croatia).
_WC_PROP = {
    "eventMetaLEAGUE": "FIFA", "eventMetaSPORTS_GROUPING": "SOCCER",
    "eventMetaEVENT_DATE": "2026-06-13T19:00:00+00:00",
    "eventMetaHOME_PARTICIPANT": "England",
    "eventMetaAWAY_PARTICIPANT": "Croatia",
    "eventMetaEXTERNAL_HOME_ID": "90000858",
    "eventMetaEXTERNAL_AWAY_ID": "90000944",
    "eventMetaEXTERNAL_GAME_ID": "90086930",
    "eventMetaPREDICT_MARKET_TYPE": "Player Prop",
    "eventMetaPREDICT_PERIOD_TYPE": "90 Minutes and Stoppage Time",
    "eventMetaPREDICT_CONTRACT_TYPE": "Anytime Goal Scorer",
    "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
    "eventMetaPREDICT_MARKET_ID": "WC-PROP-MKT",
}
WC_GOAL = json.dumps({**_WC_PROP, "SecurityID": "WC-GOAL-KANE",
                      "Symbol": "NX.F.OPT.FIFA-GOAL.Y",
                      "eventMetaPARTICIPANT": "Harry Kané",   # diacritic on purpose
                      "eventMetaPLAYER_ID": "90100001",
                      "eventMetaTEAM_ID": "90000858",
                      "eventMetaPREDICT_OUTCOME_ID": "WC-GOAL-OUT",
                      "eventName": "Harry Kane Anytime Goal Scorer"})


def test_parse_player_prop_carries_player_fields():
    """A Player Prop now passes parse_selection (was dropped), carrying
    the player name and id; PREDICT_VALUE is empty so value is None."""
    sel = parse_selection(WC_GOAL)
    assert sel is not None
    assert sel.market_group == "Player Prop"
    assert sel.contract_type == "Anytime Goal Scorer"
    assert sel.participant == "Harry Kané"
    assert sel.player_id == "90100001"
    assert sel.value is None


def test_anytime_goal_scorer_maps_to_anytime_goal_scorer():
    """Yes -> anytime_goal_scorer on the normalized player entity, so
    the crypto row merges onto Optic/Kalshi's goalscorer row."""
    (row,) = _build_wc(WC_GOAL)
    assert row.market_type == "anytime_goal_scorer"
    assert row.entity == "harry_kane"     # diacritic stripped by the shared normalizer
    assert row.line is None               # "1+" goals is a yes/no question
    assert row.side == "yes"
    assert row.crypto_security_id == "WC-GOAL-KANE"
    assert row.crypto_selection_name == "Harry Kane Anytime Goal Scorer"


def test_unmapped_prop_type_is_skipped_not_raised():
    """An unlisted prop contract is skipped, NOT raised."""
    hat_trick = json.dumps({**json.loads(WC_GOAL),
                            "eventMetaPREDICT_CONTRACT_TYPE": "To Score A Hat Trick"})
    assert parse_selection(hat_trick) is not None
    assert _build_wc(hat_trick) == []


def test_prop_wrong_period_is_skipped():
    """A prop outside the prop period gate is skipped."""
    half = json.dumps({**json.loads(WC_GOAL),
                       "eventMetaPREDICT_PERIOD_TYPE": "1st Half"})
    assert _build_wc(half) == []


def test_anytime_goal_scorer_no_is_skipped():
    """Anytime Goal Scorer is Yes-only; a No leg is skipped, not raised."""
    no = json.dumps({**json.loads(WC_GOAL),
                     "eventMetaPREDICT_OUTCOME_TYPE": "No"})
    assert _build_wc(no) == []


def test_player_alias_overrides_entity_by_player_id():
    """A player_aliases entry (keyed on crypto PLAYER_ID) replaces the
    name-derived entity — how crypto's common/short spellings reach
    Optic's full registry-name entities (config/<league>/
    player_aliases.toml, crypto_id key)."""
    sel = parse_selection(WC_GOAL)
    assert sel is not None
    (row,) = build_rows(
        "2026-06-13T19:00:00+00:00", "ENG", "CRO", [sel],
        SOCCER_CRYPTO, aliases=_WC_ALIASES, league="world_cup",
        player_aliases={"90100001": "harry_edward_kane"})
    assert row.entity == "harry_edward_kane"


def test_player_alias_misses_fall_back_to_name():
    """A player_id with no alias entry resolves by normalized name —
    the alias map is a patch table, not a roster."""
    sel = parse_selection(WC_GOAL)
    assert sel is not None
    (row,) = build_rows(
        "2026-06-13T19:00:00+00:00", "ENG", "CRO", [sel],
        SOCCER_CRYPTO, aliases=_WC_ALIASES, league="world_cup",
        player_aliases={"99999999": "someone_else"})
    assert row.entity == "harry_kane"


def test_crypto_name_alias_resolves_props_without_player_id():
    """Props sourced from crypto_underlying_securities carry no PLAYER_ID,
    so the id-keyed alias can't apply; the crypto_name fallback (keyed on
    the normalized crypto display name) re-applies the curated mapping."""
    no_id = json.dumps({**json.loads(WC_GOAL), "eventMetaPLAYER_ID": None})
    sel = parse_selection(no_id)
    assert sel is not None
    assert sel.player_id is None
    (row,) = build_rows(
        "2026-06-13T19:00:00+00:00", "ENG", "CRO", [sel],
        SOCCER_CRYPTO, aliases=_WC_ALIASES, league="world_cup",
        player_aliases={"90100001": "should_not_apply"},
        crypto_name_aliases={"harry_kane": "harry_edward_kane"})
    assert row.entity == "harry_edward_kane"


def test_player_id_alias_takes_precedence_over_crypto_name():
    """When PLAYER_ID is present and mapped, the id alias wins over the
    name fallback — the id is the stronger key."""
    sel = parse_selection(WC_GOAL)
    assert sel is not None
    (row,) = build_rows(
        "2026-06-13T19:00:00+00:00", "ENG", "CRO", [sel],
        SOCCER_CRYPTO, aliases=_WC_ALIASES, league="world_cup",
        player_aliases={"90100001": "by_id"},
        crypto_name_aliases={"harry_kane": "by_name"})
    assert row.entity == "by_id"


# === Soccer game props (World Cup) — Both Teams To Score ===

# A real BTTS shape from the 2026-06-18 burst: market group "Game Prop"
# (a third group, neither game line nor player prop), one Yes contract
# per game, blank PREDICT_VALUE, no player.  It shares the England v
# Croatia event context.  crypto lists only the Yes side.
WC_BTTS = json.dumps({
    "eventMetaLEAGUE": "FIFA", "eventMetaSPORTS_GROUPING": "SOCCER",
    "eventMetaEVENT_DATE": "2026-06-13T19:00:00+00:00",
    "eventMetaHOME_PARTICIPANT": "England",
    "eventMetaAWAY_PARTICIPANT": "Croatia",
    "eventMetaEXTERNAL_HOME_ID": "90000858",
    "eventMetaEXTERNAL_AWAY_ID": "90000944",
    "eventMetaEXTERNAL_GAME_ID": "90086930",
    "eventMetaPREDICT_MARKET_TYPE": "Game Prop",
    "eventMetaPREDICT_PERIOD_TYPE": "90 Minutes and Stoppage Time",
    "eventMetaPREDICT_CONTRACT_TYPE": "Both Teams To Score",
    "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
    "eventMetaPREDICT_MARKET_ID": "WC-BTTS-MKT",
    "eventMetaPREDICT_OUTCOME_ID": "WC-BTTS-OUT",
    "SecurityID": "WC-BTTS-YES", "Symbol": "NX.F.OPT.FIFA-BTTS.Y",
    "eventName": "Both Teams To Score"})


def test_parse_game_prop_passes_on_read():
    """A Game Prop (third market group) now passes parse_selection (was
    dropped): game-scoped, no player, blank value."""
    sel = parse_selection(WC_BTTS)
    assert sel is not None
    assert sel.market_group == "Game Prop"
    assert sel.contract_type == "Both Teams To Score"
    assert sel.participant is None        # game-scoped, no player
    assert sel.value is None              # blank PREDICT_VALUE


def test_btts_yes_is_game_scoped_yes_no():
    """Yes -> the "yes" side on a game-scoped BTTS row (no team, no line),
    so the crypto row merges onto Optic both_teams_to_score / Kalshi
    KXWCBTTS, which emit the same "yes"/"no" literals."""
    (row,) = _build_wc(WC_BTTS)
    assert row.market_type == "btts"
    assert row.side == "yes"
    assert row.entity is None             # game-scoped, no player
    assert row.line is None               # yes/no, no line
    assert row.home == "ENG" and row.away == "CRO"
    assert row.crypto_security_id == "WC-BTTS-YES"


def test_btts_wrong_period_is_skipped():
    """A BTTS outside the game-prop period gate is skipped."""
    half = json.dumps({**json.loads(WC_BTTS),
                       "eventMetaPREDICT_PERIOD_TYPE": "Extra Time"})
    assert _build_wc(half) == []


def test_unmapped_game_prop_type_is_skipped_not_raised():
    """An unmapped Game Prop type is skipped, NOT raised — the player-prop
    discipline (a chosen subset of an extendable group), not the game-line
    one.  crypto may add other game props later."""
    other = json.dumps({**json.loads(WC_BTTS),
                        "eventMetaPREDICT_CONTRACT_TYPE": "Total Corners"})
    assert parse_selection(other) is not None   # still parses (it's a game prop)
    assert _build_wc(other) == []               # but build_rows skips it


# === Robustness against real-feed shapes (2026-06-09 catalogue burst) ===

def test_shots_on_target_ladder_maps_over_under():
    """N+ Shots on Target → player_shots_on_target over (N−0.5)."""
    two_sot = json.dumps({**json.loads(WC_GOAL),
                          "eventMetaPREDICT_CONTRACT_TYPE": "2+ Shots on Target"})
    (row,) = _build_wc(two_sot)
    assert row.market_type == "player_shots_on_target"
    assert row.line == 1.5 and row.side == "over"


def test_first_goalscorer_blank_outcome_maps_yes_no():
    """First Goalscorer carries blank outcome_type → yes, no line."""
    fg = json.dumps({**json.loads(WC_GOAL),
                     "eventMetaPREDICT_CONTRACT_TYPE": "First Goalscorer",
                     "eventMetaPREDICT_OUTCOME_TYPE": None})
    sel = parse_selection(fg)
    assert sel is not None and sel.outcome_type is None
    (row,) = _build_wc(fg)
    assert row.market_type == "first_goal_scorer"
    assert row.side == "yes" and row.line is None


def test_saves_blank_outcome_maps_over():
    """The Saves ladder can carry blank outcome_type like First Goalscorer."""
    save = json.dumps({**json.loads(WC_GOAL),
                       "eventMetaPREDICT_CONTRACT_TYPE": "3+ Saves",
                       "eventMetaPREDICT_OUTCOME_TYPE": None})
    (row,) = _build_wc(save)
    assert row.market_type == "player_saves"
    assert row.line == 2.5 and row.side == "over"


def test_unlisted_prop_with_blank_outcome_is_skipped():
    """Blank outcome on an unmapped prop still parses and skips."""
    fg = json.dumps({**json.loads(WC_GOAL),
                     "eventMetaPREDICT_CONTRACT_TYPE": "To Score A Hat Trick",
                     "eventMetaPREDICT_OUTCOME_TYPE": None})
    sel = parse_selection(fg)
    assert sel is not None and sel.outcome_type is None
    assert _build_wc(fg) == []


# === Supersession dedupe (contract re-issuance) ===

# The feed re-issues a game's contracts under fresh SecurityIDs/Symbols
# (the sid's first 14 digits are the issuance timestamp), and the
# catalogue can carry both vintages of one question at once — modelled
# on the real Ko Itakura Anytime Goal Scorer pair from the 2026-06-09
# burst (sids 0922… and 0952…, identical on every betting field).
WC_GOAL_REISSUED = json.dumps({
    **json.loads(WC_GOAL),
    "SecurityID": "202606050952311202007635D",
    "Symbol": "NX.F.OPT.FIFA-GOAL.Y2",
    "eventMetaPREDICT_MARKET_ID": "WC-PROP-MKT-V2",
    "eventMetaPREDICT_OUTCOME_ID": "WC-GOAL-OUT-V2",
})
WC_GOAL_V1 = json.dumps({
    **json.loads(WC_GOAL),
    "SecurityID": "202606050922294302108608D",
})
WC_GOAL_V2_SAME_SYMBOL = json.dumps({
    **json.loads(WC_GOAL),
    "SecurityID": "202606050952311202007635D",
})


def _sels(*lines):
    return [s for ln in lines if (s := parse_selection(ln)) is not None]


def test_dedupe_keeps_latest_vintage_same_symbol_either_input_order():
    """One question, two sids under the same Symbol: only the later sid
    survives, regardless of feed file order."""
    for order in [(WC_GOAL_V1, WC_GOAL_V2_SAME_SYMBOL),
                  (WC_GOAL_V2_SAME_SYMBOL, WC_GOAL_V1)]:
        (kept,) = dedupe_superseded(_sels(*order))
        assert kept.security_id == "202606050952311202007635D"
        assert kept.symbol == "NX.F.OPT.FIFA-GOAL.Y"


def test_dedupe_keeps_both_when_symbol_changes():
    """Re-issue under a new Symbol is kept alongside the old leg — RFQs
    may still cite the superseded symbol (e.g. M.O.1.1 → M.O.1.4)."""
    deduped = dedupe_superseded(_sels(WC_GOAL_V1, WC_GOAL_REISSUED))
    assert len(deduped) == 2
    assert {s.symbol for s in deduped} == {
        "NX.F.OPT.FIFA-GOAL.Y", "NX.F.OPT.FIFA-GOAL.Y2"}


def test_dedupe_keeps_distinct_questions():
    """Different questions are never collapsed: another player's prop
    and the game's 3-way legs all survive alongside both goal symbols."""
    other_player = json.dumps({**json.loads(WC_GOAL),
                               "SecurityID": "202606050900000000000001D",
                               "eventMetaPARTICIPANT": "Jude Bellingham",
                               "eventMetaPLAYER_ID": "90100002"})
    sels = _sels(WC_GOAL_V1, WC_GOAL_REISSUED, other_player,
                 WC_HOME, WC_AWAY, WC_DRAW)
    deduped = dedupe_superseded(sels)
    assert len(deduped) == 6
    assert {s.security_id for s in deduped} == {
        "202606050922294302108608D", "202606050952311202007635D",
        "202606050900000000000001D",
        "WC-ENG-H", "WC-CRO-A", "WC-DRAW"}


def test_dedupe_output_order_is_input_order_independent():
    """Output is sorted by security_id so downstream row order does not
    depend on the scan order the fetcher happened to write."""
    a = dedupe_superseded(_sels(WC_HOME, WC_AWAY, WC_DRAW))
    b = dedupe_superseded(_sels(WC_DRAW, WC_HOME, WC_AWAY))
    assert [s.security_id for s in a] == [s.security_id for s in b]


def test_deduped_pair_builds_single_row_with_latest_sid():
    """End to end through build_rows: same-symbol re-issue yields one
    anytime_goal_scorer row stamped with the surviving (later) contract."""
    (row,) = _build_wc_deduped(WC_GOAL_V1, WC_GOAL_V2_SAME_SYMBOL)
    assert row.market_type == "anytime_goal_scorer"
    assert row.crypto_security_id == "202606050952311202007635D"
    assert row.crypto_symbol == "NX.F.OPT.FIFA-GOAL.Y"


def test_deduped_distinct_symbols_attach_as_satellite_rows():
    """Distinct symbols for the same question load as separate crypto rows."""
    from mappers.pipeline import attach_crypto_row

    crypto_rows = _build_wc_deduped(WC_GOAL_V1, WC_GOAL_REISSUED)
    assert len(crypto_rows) == 2
    row_index: dict = {}
    alt_crypto: dict = {}
    all_rows: list = []
    for cr in crypto_rows:
        attach_crypto_row(row_index, alt_crypto, all_rows, cr)
    assert len(all_rows) == 2
    symbols = {r.crypto_symbol for r in all_rows}
    assert symbols == {"NX.F.OPT.FIFA-GOAL.Y", "NX.F.OPT.FIFA-GOAL.Y2"}
    assert not all_rows[0].crypto_satellite
    assert all_rows[1].crypto_satellite


def _build_wc_deduped(*lines):
    return build_rows(
        "2026-06-13T19:00:00+00:00", "ENG", "CRO",
        dedupe_superseded(_sels(*lines)),
        SOCCER_CRYPTO, aliases=_WC_ALIASES, league="world_cup")


def test_gameless_game_line_dropped_on_read():
    """The feed mislabels a few gameless markets as Game Line (e.g. PGA
    "Ryder Cup") with no external_game_id or teams.  A real game line has
    the game id 100% of the time, so these are dropped on read rather
    than crashing the Selection model."""
    ryder = json.dumps({
        "eventMetaLEAGUE": "PGA", "eventMetaSPORTS_GROUPING": "GOLF",
        "eventMetaPREDICT_MARKET_TYPE": "Game Line",
        "eventMetaPREDICT_CONTRACT_TYPE": "Ryder Cup",
        "SecurityID": "PGA-RYDER", "Symbol": "NX.F.OPT.PGA-RYDER",
        # no EXTERNAL_GAME_ID / HOME / AWAY — not tied to a fixture
    })
    assert parse_selection(ryder) is None


def test_null_league_game_line_dropped_on_read():
    """A mappable Game Line with a fixture id but null LEAGUE cannot match
    any CRYPTO.league filter.  Drop on read instead of raising
    ValidationError (which used to abort every crypto-wired league)."""
    record = json.loads(MONEYLINE)
    record["eventMetaLEAGUE"] = None
    assert parse_selection(json.dumps(record)) is None


@pytest.mark.parametrize(("value", "line"), [("0.5", 0.5), ("1.5", 1.5)])
def test_mlb_total_hits_runs_rbis_maps_player_over_line(value, line) -> None:
    """MLB "Total Hits, Runs, & RBIs" (Over legs) -> player_hits_runs_rbis.

    Optic's own market is player_hits_+_runs_+_rbis (baseball vocab); the
    line comes from PREDICT_VALUE, side from the typed outcome.
    """
    payload = json.dumps({
        **_MLB_GAME,
        "eventMetaPREDICT_MARKET_TYPE": "Player Prop",
        "eventMetaPREDICT_CONTRACT_TYPE": "Total Hits, Runs, & RBIs",
        "eventMetaPREDICT_OUTCOME_TYPE": "Over",
        "eventMetaPREDICT_VALUE": value,
        "eventMetaPARTICIPANT": "Cooper Pratt",
        "eventMetaPREDICT_MARKET_ID": "MKT-MLB-HRR",
        "eventMetaPREDICT_OUTCOME_ID": "OUT-MLB-HRR",
        "SecurityID": "MLB-HRR-1",
        "Symbol": "NX.F.OPT.MLB-00001-260706-M.O.1.401",
        "eventName": f"Cooper Pratt Over {value} Total Hits",
    })
    sel = parse_selection(payload)
    assert sel is not None
    (row,) = build_rows(
        "2026-07-06T23:10:00+00:00", "KC", "PHI",
        [sel], MLB_CRYPTO, aliases=ALIASES, league="mlb")
    assert row.market_type == "player_hits_runs_rbis"
    assert row.entity == "cooper_pratt"
    assert row.side == "over"
    assert row.line == float(value)


# === NCAAB (CBB) half-period game lines ===
# Real rows: Notre Dame (away) @ Villanova (home), crypto_security_def 2026-10-31.

def _cbb_line(symbol, period, contract, outcome, value, desc):
    return json.dumps({
        "eventMetaLEAGUE": "CBB",
        "eventMetaSPORTS_GROUPING": "Basketball",
        "eventMetaEVENT_DATE": "2026-11-01T14:30:00+00:00",
        "eventMetaHOME_PARTICIPANT": "Villanova Wildcats",
        "eventMetaAWAY_PARTICIPANT": "Notre Dame Fighting Irish",
        "eventMetaEXTERNAL_HOME_ID": "60000058",
        "eventMetaEXTERNAL_AWAY_ID": "60000025",
        "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.CBB-00001-261101",
        "eventMetaPREDICT_MARKET_TYPE": "Game Line",
        "eventMetaPREDICT_PERIOD_TYPE": period,
        "eventMetaPREDICT_CONTRACT_TYPE": contract,
        "eventMetaPREDICT_OUTCOME_TYPE": outcome,
        "eventMetaPREDICT_VALUE": value,
        "SecurityID": symbol, "Symbol": symbol, "eventName": desc,
        "eventMetaPREDICT_MARKET_ID": "M-" + symbol,
        "eventMetaPREDICT_OUTCOME_ID": "O-" + symbol,
    })


_CBB_PFX = "NX.F.OPT.CBB-00001-261101-M.O.1."
_CBB_ALIASES = {"60000058": "VILL", "60000025": "ND"}
_CBB_LINES = [
    _cbb_line(_CBB_PFX + "9", "1st Half", "Spread", "Away", "4.5", "1st Half Notre Dame +4.5"),
    _cbb_line(_CBB_PFX + "8", "1st Half", "Spread", "Home", "-4.5", "1st Half Villanova -4.5"),
    _cbb_line(_CBB_PFX + "7", "2nd Half", "Spread", "Away", "3.5", "2nd Half Notre Dame +3.5"),
    _cbb_line(_CBB_PFX + "6", "2nd Half", "Spread", "Home", "-3.5", "2nd Half Villanova -3.5"),
    _cbb_line(_CBB_PFX + "10", "1st Half", "Total Points", "Over", "69.5", "1st Half Over 69.5"),
    _cbb_line(_CBB_PFX + "11", "1st Half", "Total Points", "Under", "69.5", "1st Half Under 69.5"),
    _cbb_line(_CBB_PFX + "3", "2nd Half", "Moneyline (3-Way)", "Away", None, "2nd Half Notre Dame"),
    _cbb_line(_CBB_PFX + "5", "2nd Half", "Moneyline (3-Way)", "Draw", None, "2nd Half Draw"),
    _cbb_line(_CBB_PFX + "21", "Full-Game", "Spread", "Away", "-4.5", "Notre Dame -4.5"),
    _cbb_line(_CBB_PFX + "19", "Full-Game", "Spread", "Away", "1.5", "Notre Dame +1.5"),
]


def _build_cbb(lines=None):
    from mappers.seed.fixture_store import load_fixture
    from mappers.seed.tip_factories import build_tip_league
    cfg = build_tip_league(next(r for r in load_fixture().leagues if r.league == "ncaab"))
    assert cfg.CRYPTO is not None
    rows = build_rows(
        "2026-11-01T14:30:00+00:00", "VILL", "ND",
        [s for ln in (lines or _CBB_LINES) if (s := parse_selection(ln)) is not None],
        cfg.CRYPTO, aliases=_CBB_ALIASES, league="ncaab",
        fixture_names={"VILL": "Villanova", "ND": "Notre Dame"})
    return {(r.crypto_symbol or "").removeprefix(_CBB_PFX): r for r in rows}


def test_ncaab_crypto_maps_half_spreads_and_totals():
    by = _build_cbb()
    got = {k: (r.market_type, r.side, r.line) for k, r in by.items()}
    assert got["9"] == ("1h_point_spread", "ND", 4.5)
    assert got["8"] == ("1h_point_spread", "VILL", -4.5)
    assert got["7"] == ("2h_point_spread", "ND", 3.5)
    assert got["6"] == ("2h_point_spread", "VILL", -3.5)
    assert got["10"] == ("1h_total", "over", 69.5)
    assert got["11"] == ("1h_total", "under", 69.5)


def test_ncaab_crypto_half_three_way_moneyline():
    by = _build_cbb()
    assert (by["3"].market_type, by["3"].side, by["3"].line) == ("2h_winner_3way", "ND", None)
    assert (by["5"].market_type, by["5"].side) == ("2h_winner_3way", TIE_SIDE)


def test_ncaab_crypto_full_game_spread_sign_unchanged():
    by = _build_cbb()
    assert (by["21"].market_type, by["21"].side, by["21"].line) == ("point_spread", "ND", -4.5)
    assert (by["19"].market_type, by["19"].side, by["19"].line) == ("point_spread", "ND", 1.5)


def test_nba_wnba_crypto_period_vocab_frozen():
    """NBA maps 1st half and Q1-Q3 (2nd half / Q4 overtime basis unclear); WNBA maps 1st Half only."""
    assert set(NBA_CRYPTO.period_contract_types) == {
        "1st Half", "1st Quarter", "2nd Quarter", "3rd Quarter"}
    assert WNBA_CRYPTO.period_contract_types == {
        "1st Half": {
            "Moneyline": MarketType.FIRST_HALF_MONEYLINE,
            "Spread": MarketType.FIRST_HALF_POINT_SPREAD,
            "Total Points": MarketType.FIRST_HALF_TOTAL,
        },
    }
    assert NBA_CRYPTO.contract_types == WNBA_CRYPTO.contract_types

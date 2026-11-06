"""Tests for the Novig exchange parser and row builder.

The properties that matter here are the ones the API makes easy to get
wrong: sidedness comes from ``outcome.index`` (NOT array order), the
spread strike is the HOME side's line, three-way soccer is three separate
Yes/No markets, and every team/player identity is an Optic id lookup that
must DROP rather than guess when the id is unknown.
"""

import json

import pytest

from mappers.exchanges.novig import (
    NovigConfig,
    build_rows,
    parse_event,
    parse_market,
)
from mappers.market_types import MarketType

HOME, AWAY = "DAL", "PHI"
HOME_OPTIC, AWAY_OPTIC = "0BDD5205ECCB", "EDCC2866B795"
TEAM_MAP = {HOME_OPTIC: HOME, AWAY_OPTIC: AWAY}
START = "2026-11-26T18:30:00Z"
PLAYER_OPTIC = "D88250CC9CF9"
PLAYER_NAMES = {PLAYER_OPTIC: "jonquel_jones"}


def _competitor(optic_id, short="X"):
    return {"id": "c-" + short, "name": short, "shortName": short,
            "opticOddsId": optic_id}


def _market(mtype, *, strike=None, outcomes, player=None, competitor=None,
            market_id="m1", event_id="e1", league="NFL"):
    return parse_market(json.dumps({
        "id": market_id, "type": mtype, "description": f"{mtype} desc",
        "status": "OPEN", "strike": strike, "league": league,
        "eventId": event_id, "playerId": (player or {}).get("id"),
        "player": player, "competitor": competitor,
        "outcomeIds": [o["id"] for o in outcomes], "outcomes": outcomes,
    }))


def _rows(market, mt, **kw):
    return build_rows(
        market, mt, home=HOME, away=AWAY, start_date=START, league="nfl",
        team_map=kw.pop("team_map", TEAM_MAP),
        player_names=kw.pop("player_names", PLAYER_NAMES))


# === sidedness: index, never array order ===

def test_side_comes_from_index_not_array_order():
    """outcomes[] is genuinely not returned in index order.

    The Under leg is listed FIRST with index 1; trusting position would
    label it "over" and silently invert the book.
    """
    market = _market(
        "TOTAL", strike=44.5,
        outcomes=[
            {"id": "o-under", "description": "Under 44.5", "type": "Under",
             "index": 1},
            {"id": "o-over", "description": "Over 44.5", "type": "Over",
             "index": 0},
        ])
    rows = _rows(market, MarketType.GAME_TOTAL)

    by_side = {r.side: r for r in rows}
    assert set(by_side) == {"over", "under"}
    assert by_side["over"].novig_outcome_id == "o-over"
    assert by_side["under"].novig_outcome_id == "o-under"
    assert by_side["over"].line == 44.5
    assert by_side["under"].line == 44.5


def test_moneyline_index_zero_is_home():
    market = _market(
        "MONEY",
        outcomes=[
            {"id": "o-home", "description": HOME, "type": "Home", "index": 0,
             "competitor": _competitor(HOME_OPTIC, HOME)},
            {"id": "o-away", "description": AWAY, "type": "Away", "index": 1,
             "competitor": _competitor(AWAY_OPTIC, AWAY)},
        ])
    rows = _rows(market, MarketType.MONEYLINE)

    by_side = {r.side: r.novig_outcome_id for r in rows}
    assert by_side == {HOME: "o-home", AWAY: "o-away"}
    assert all(r.line is None and r.entity is None for r in rows)


def test_moneyline_follows_competitor_when_index_zero_is_away():
    """Index 0 is not home. The competitor id still names the away team."""
    market = _market(
        "MONEY",
        outcomes=[
            {"id": "o-a", "description": AWAY, "type": "Home", "index": 0,
             "competitor": _competitor(AWAY_OPTIC, AWAY)},
            {"id": "o-b", "description": HOME, "type": "Away", "index": 1,
             "competitor": _competitor(HOME_OPTIC, HOME)},
        ])
    rows = _rows(market, MarketType.MONEYLINE)
    by_side = {r.side: r.novig_outcome_id for r in rows}
    assert by_side == {AWAY: "o-a", HOME: "o-b"}


def test_moneyline_dropped_when_competitors_are_unnamed():
    market = _market(
        "MONEY",
        outcomes=[
            {"id": "o-a", "description": HOME, "type": "Home", "index": 0},
            {"id": "o-b", "description": AWAY, "type": "Away", "index": 1},
        ])
    assert _rows(market, MarketType.MONEYLINE) == []


def test_market_dropped_when_indices_are_not_a_clean_pair():
    market = _market(
        "TOTAL", strike=44.5,
        outcomes=[
            {"id": "o1", "description": "Over", "type": "Over", "index": 0},
            {"id": "o2", "description": "Over", "type": "Over", "index": 0},
        ])
    assert _rows(market, MarketType.GAME_TOTAL) == []


# === spread: strike is the home line, away is its negation ===

def test_spread_signs_are_mirrored_around_the_home_strike():
    market = _market(
        "SPREAD", strike=-7.5,
        outcomes=[
            {"id": "o-home", "description": "DAL -7.5", "type": "Home",
             "index": 0, "competitor": _competitor(HOME_OPTIC, HOME)},
            {"id": "o-away", "description": "PHI +7.5", "type": "Away",
             "index": 1, "competitor": _competitor(AWAY_OPTIC, AWAY)},
        ])
    rows = _rows(market, MarketType.POINT_SPREAD)

    by_side = {r.side: r.line for r in rows}
    assert by_side == {HOME: -7.5, AWAY: 7.5}


def test_spread_without_competitors_keeps_typed_home_away():
    """Tennis game spreads name the side with type Home/Away, not a competitor id."""
    market = _market(
        "SPREAD", strike=-1.5,
        outcomes=[
            {"id": "n-home", "description": "G. Olivieri -1.5",
             "type": "Home", "index": 0},
            {"id": "n-away", "description": "T. Barrios Vera +1.5",
             "type": "Away", "index": 1},
        ])
    rows = _rows(market, MarketType.POINT_SPREAD)
    assert {r.side: r.line for r in rows} == {HOME: -1.5, AWAY: 1.5}


def test_spread_dropped_when_only_one_outcome_names_a_team():
    market = _market(
        "SPREAD", strike=-7.5,
        outcomes=[
            {"id": "o-home", "description": "DAL -7.5", "type": "Home",
             "index": 0, "competitor": _competitor(HOME_OPTIC, HOME)},
            {"id": "o-away", "description": "PHI +7.5", "type": "Away", "index": 1},
        ])
    assert _rows(market, MarketType.POINT_SPREAD) == []


def test_spread_dropped_when_one_competitor_names_the_other_side():
    """Index 0 has no id and is typed Home; index 1's competitor is the home team."""
    market = _market(
        "SPREAD", strike=-1.5,
        outcomes=[
            {"id": "n-home", "description": "home", "type": "Home", "index": 0},
            {"id": "n-away", "description": "away", "type": "Away", "index": 1,
             "competitor": _competitor(HOME_OPTIC, HOME)},
        ])
    assert _rows(market, MarketType.POINT_SPREAD) == []


def test_spread_dropped_when_type_disagrees_with_index():
    market = _market(
        "SPREAD", strike=-1.5,
        outcomes=[
            {"id": "n-away", "description": "away", "type": "Away", "index": 0},
            {"id": "n-home", "description": "home", "type": "Home", "index": 1},
        ])
    assert _rows(market, MarketType.POINT_SPREAD) == []


def test_spread_without_a_strike_is_dropped():
    market = _market(
        "SPREAD", strike=None,
        outcomes=[
            {"id": "a", "description": "h", "type": "Home", "index": 0},
            {"id": "b", "description": "a", "type": "Away", "index": 1},
        ])
    assert _rows(market, MarketType.POINT_SPREAD) == []


# === three-way soccer: one affirmative row per market ===

def _three_way(competitor, market_id="m3"):
    return _market(
        "MONEYLINE_3_WAY_WIN" if competitor else "MONEYLINE_3_WAY_DRAW",
        strike=0, market_id=market_id, league="MLS", competitor=competitor,
        outcomes=[
            {"id": market_id + "-yes", "description": "Yes", "type": "Over",
             "index": 0},
            {"id": market_id + "-no", "description": "No", "type": "Under",
             "index": 1},
        ])


def test_three_way_win_emits_one_row_keyed_to_the_market_competitor():
    rows = _rows(_three_way(_competitor(AWAY_OPTIC, AWAY)),
                 MarketType.MONEYLINE_3WAY)

    assert len(rows) == 1, "the No leg means 'any other result' — must drop"
    assert rows[0].side == AWAY
    assert rows[0].line is None
    assert rows[0].novig_outcome_id == "m3-yes"


def test_three_way_draw_emits_the_tie_side():
    rows = _rows(_three_way(None), MarketType.MONEYLINE_3WAY)

    assert len(rows) == 1
    assert rows[0].side == "_TIE"


def test_three_way_dropped_when_competitor_is_not_in_this_fixture():
    rows = _rows(_three_way(_competitor("UNKNOWN-TEAM-ID")),
                 MarketType.MONEYLINE_3WAY)
    assert rows == []


# === entity resolution is an id lookup, never a name guess ===

def test_team_total_entity_resolves_through_the_optic_team_id():
    market = _market(
        "TEAM_TOTAL", strike=22.5, competitor=_competitor(HOME_OPTIC, HOME),
        outcomes=[
            {"id": "o-over", "description": "Over 22.5", "type": "Over",
             "index": 0},
            {"id": "o-under", "description": "Under 22.5", "type": "Under",
             "index": 1},
        ])
    rows = _rows(market, MarketType.TEAM_TOTAL)

    assert {r.entity for r in rows} == {HOME}
    assert {r.side for r in rows} == {"over", "under"}


def test_team_scoped_market_dropped_when_the_team_id_is_unknown():
    market = _market(
        "TEAM_TOTAL", strike=22.5, competitor=_competitor("NOT-OURS"),
        outcomes=[
            {"id": "a", "description": "Over", "type": "Over", "index": 0},
            {"id": "b", "description": "Under", "type": "Under", "index": 1},
        ])
    assert _rows(market, MarketType.TEAM_TOTAL) == []


def test_player_prop_entity_comes_from_the_optic_player_id():
    market = _market(
        "ASSISTS", strike=2.5, league="WNBA",
        player={"id": "p1", "name": "Jonquel Jones",
                "fullName": "Jonquel Jones", "opticOddsId": PLAYER_OPTIC},
        outcomes=[
            {"id": "o-under", "description": "Under 2.5", "type": "Under",
             "index": 1},
            {"id": "o-over", "description": "Over 2.5", "type": "Over",
             "index": 0},
        ])
    rows = _rows(market, MarketType.PLAYER_ASSISTS)

    assert {r.entity for r in rows} == {"jonquel_jones"}
    by_side = {r.side: r.line for r in rows}
    assert by_side == {"over": 2.5, "under": 2.5}


def test_player_prop_dropped_when_optic_never_priced_that_player():
    market = _market(
        "ASSISTS", strike=2.5, league="WNBA",
        player={"id": "p9", "name": "Nobody", "fullName": "Nobody",
                "opticOddsId": "UNKNOWN-PLAYER"},
        outcomes=[
            {"id": "a", "description": "Over", "type": "Over", "index": 0},
            {"id": "b", "description": "Under", "type": "Under", "index": 1},
        ])
    assert _rows(market, MarketType.PLAYER_ASSISTS) == []


# === yes/no shapes ===

def test_yes_no_prop_ignores_the_half_line_strike():
    """Novig ships DOUBLE_DOUBLE as Over/Under 0.5; ours is a YES_NO type."""
    market = _market(
        "DOUBLE_DOUBLE", strike=0.5, league="WNBA",
        player={"id": "p1", "name": "Jonquel Jones",
                "fullName": "Jonquel Jones", "opticOddsId": PLAYER_OPTIC},
        outcomes=[
            {"id": "o-yes", "description": "Over 0.5", "type": "Over",
             "index": 0},
            {"id": "o-no", "description": "Under 0.5", "type": "Under",
             "index": 1},
        ])
    rows = _rows(market, MarketType.PLAYER_DOUBLE_DOUBLE)

    by_side = {r.side: r for r in rows}
    assert set(by_side) == {"yes", "no"}
    assert all(r.line is None for r in rows), "YES_NO carries no line"
    assert by_side["yes"].novig_outcome_id == "o-yes"


# === stamp + parsing ===

def test_stamp_carries_the_full_id_triple():
    market = _market(
        "MONEY", market_id="mkt-7", event_id="evt-7",
        outcomes=[
            {"id": "o-home", "description": HOME, "type": "Home", "index": 0,
             "competitor": _competitor(HOME_OPTIC, HOME)},
            {"id": "o-away", "description": AWAY, "type": "Away", "index": 1,
             "competitor": _competitor(AWAY_OPTIC, AWAY)},
        ])
    row = _rows(market, MarketType.MONEYLINE)[0]

    assert row.novig_event_id == "evt-7"
    assert row.novig_market_id == "mkt-7"
    assert row.novig_outcome_id in {"o-home", "o-away"}
    assert row.novig_market_type == "MONEY"


@pytest.mark.parametrize("bad", ["", "not json", "[]", '{"no":"id"}'])
def test_parse_market_returns_none_on_junk(bad):
    assert parse_market(bad) is None


def test_parse_event_reads_the_optic_fixture_id():
    event = parse_event(json.dumps({
        "id": "evt-1", "type": "Game", "status": "OPEN_PREGAME",
        "description": "PHI @ DAL", "league": "NFL",
        "scheduledStart": START, "opticOddsId": "202611262D84D5DD",
    }))
    assert event is not None
    assert event.opticOddsId == "202611262D84D5DD"
    assert event.league == "NFL"


def test_novig_config_defaults_to_no_ignored_types():
    cfg = NovigConfig(league="NFL", market_types={})
    assert cfg.ignored_types == frozenset()


# === UFC method of victory: the method lives in the TYPE ===
#
# Novig ships one Yes/No market per method rather than one market with a
# bucket per outcome, so the method has to come from market.type and reach
# grouping_key -- which is part of pipeline.row_key.

_MOV_METHODS = [
    ("VICTORY_BY_KO_KTO_OR_DQ", "ko_tko_dq"),
    ("VICTORY_BY_SUBMISSION", "submission"),
    ("VICTORY_BY_DECISION", "decision"),
]


def _mov(mtype, competitor_optic=HOME_OPTIC, market_id="mov1"):
    return _market(
        mtype,
        competitor=_competitor(competitor_optic),
        market_id=market_id,
        outcomes=[{"id": "o-yes", "description": "Yes", "type": "Over",
                   "index": 0},
                  {"id": "o-no", "description": "No", "type": "Under",
                   "index": 1}],
    )


@pytest.mark.parametrize("mtype,method", _MOV_METHODS)
def test_method_of_victory_puts_the_method_in_grouping_key(mtype, method):
    """entity is the fighter, side is yes, grouping_key is the method."""
    rows = _rows(_mov(mtype), MarketType.METHOD_OF_VICTORY)
    assert len(rows) == 1
    assert rows[0].entity == HOME
    assert rows[0].side == "yes"
    assert rows[0].grouping_key == method
    assert rows[0].line is None


def test_the_three_methods_do_not_collapse_onto_one_key():
    """The regression this guards: three contracts merging into one row.

    grouping_key is part of pipeline.row_key.  If the method did not reach
    it, all three of a fighter's method markets would key identically and
    Novig would stamp a submission outcome onto a decision row.
    """
    keys = set()
    for i, (mtype, _) in enumerate(_MOV_METHODS):
        rows = _rows(_mov(mtype, market_id=f"mov{i}"),
                     MarketType.METHOD_OF_VICTORY)
        assert len(rows) == 1
        keys.add((rows[0].entity, rows[0].side, rows[0].grouping_key))
    assert len(keys) == 3


def test_method_of_victory_drops_the_no_leg():
    """Optic emits only the affirmative side, so there is no twin to stamp."""
    rows = _rows(_mov("VICTORY_BY_SUBMISSION"), MarketType.METHOD_OF_VICTORY)
    assert [r.side for r in rows] == ["yes"]
    assert [r.novig_outcome_id for r in rows] == ["o-yes"]


def test_method_of_victory_dropped_when_the_fighter_id_is_unknown():
    rows = _rows(_mov("VICTORY_BY_DECISION", competitor_optic="NOT_IN_MAP"),
                 MarketType.METHOD_OF_VICTORY)
    assert rows == []


def test_method_of_victory_dropped_for_an_unmapped_method_type():
    """An unrecognised type is a drop, never a row with no method."""
    rows = _rows(_mov("VICTORY_BY_TELEPORTATION"),
                 MarketType.METHOD_OF_VICTORY)
    assert rows == []


def test_novig_method_key_only_covers_the_like_for_like_methods():
    from mappers.fight_props import novig_method_key
    for mtype, method in _MOV_METHODS:
        assert novig_method_key(mtype) == method
    # The fight-level draw has no like-for-like Optic/Kalshi twin.
    assert novig_method_key("DRAW") is None


def test_mma_crosswalk_maps_the_methods_and_still_ignores_draw():
    from mappers.vocab import novig_markets
    for mtype, _ in _MOV_METHODS:
        assert novig_markets.MMA[mtype] == MarketType.METHOD_OF_VICTORY
        assert mtype not in novig_markets.MMA_IGNORED
    assert "DRAW" in novig_markets.MMA_IGNORED
    assert "DRAW" not in novig_markets.MMA


# === football crosswalk ===

@pytest.mark.parametrize("mtype, mt", [
    ("RUSHING_AND_RECEIVING_YARDS", MarketType.PLAYER_RUSHING_RECEIVING_YARDS),
    ("PASSING_AND_RUSHING_YARDS", MarketType.PLAYER_PASSING_RUSHING_YARDS),
    ("LONGEST_COMPLETION", MarketType.PLAYER_LONGEST_PASSING_COMPLETION),
    ("TACKLES_ASSISTS", MarketType.PLAYER_TACKLES_ASSISTS),
    ("KICKING_POINTS", MarketType.PLAYER_KICKING_POINTS),
])
def test_football_player_props_map_to_their_optic_twins(mtype, mt):
    from mappers.vocab import novig_markets
    assert novig_markets.FOOTBALL[mtype] is mt
    assert mtype not in novig_markets.FOOTBALL_IGNORED
    # Every one of these is a canonical Optic football market, so the Novig
    # row has an Optic row to stamp onto.
    from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS
    assert mt in FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS.values()


def test_tackles_assists_builds_a_player_over_under_pair():
    market = _market(
        "TACKLES_ASSISTS", strike=5.5,
        player={"id": "p1", "name": "Jonquel Jones",
                "fullName": "Jonquel Jones", "opticOddsId": PLAYER_OPTIC},
        outcomes=[
            {"id": "o-under", "description": "Under 5.5", "type": "Under",
             "index": 1},
            {"id": "o-over", "description": "Over 5.5", "type": "Over",
             "index": 0},
        ])
    rows = _rows(market, MarketType.PLAYER_TACKLES_ASSISTS)

    assert {r.market_type for r in rows} == {"player_tackles_+_assists"}
    assert {r.side: r.line for r in rows} == {"over": 5.5, "under": 5.5}


# === hockey / baseball / soccer / basketball props ===

@pytest.mark.parametrize("sport, mtype, mt", [
    ("hockey", "PLAYER_GOALS", MarketType.PLAYER_GOALS),
    ("hockey", "ASSISTS", MarketType.PLAYER_ASSISTS),
    ("hockey", "POINTS", MarketType.PLAYER_POINTS),
    ("hockey", "SHOTS_ON_GOAL", MarketType.PLAYER_SHOTS_ON_GOAL),
    ("hockey", "FIRST_GOAL_SCORER", MarketType.FIRST_GOAL_SCORER),
    ("baseball", "RBIS", MarketType.PLAYER_RBIS),
    ("baseball", "RUNS", MarketType.PLAYER_RUNS),
    ("baseball", "STOLEN_BASES", MarketType.PLAYER_STOLEN_BASES),
    ("baseball", "BATTING_STRIKEOUTS", MarketType.PLAYER_BATTING_STRIKEOUTS),
    ("baseball", "BATTING_WALKS", MarketType.PLAYER_BATTING_WALKS),
    ("baseball", "WALKS", MarketType.PLAYER_WALKS_ALLOWED),
    ("baseball", "HITS_ALLOWED", MarketType.PLAYER_HITS_ALLOWED),
    ("baseball", "EARNED_RUNS", MarketType.PLAYER_EARNED_RUNS),
    ("baseball", "PITCHER_OUTS", MarketType.PLAYER_OUTS),
    ("soccer", "ASSISTS", MarketType.PLAYER_ASSISTS),
    ("basketball", "FIRST_BASKET", MarketType.FIRST_BASKET),
    ("football", "FIELD_GOALS_MADE", MarketType.PLAYER_FIELD_GOALS_MADE),
])
def test_prop_maps_to_a_canonical_type_optic_prices(sport, mtype, mt):
    """Every Novig prop mapped here has an Optic row on the same sport's table."""
    from mappers.vocab import (
        baseball_markets, basketball_markets, football_markets,
        hockey_markets, novig_markets, soccer_markets,
    )
    assert novig_markets.classify_novig_type(sport, mtype) == ("mapped", mt)
    optic = {
        "hockey": hockey_markets.HOCKEY_OPTIC_TABLE_TYPES,
        "baseball": baseball_markets.BASEBALL_OPTIC_TABLE_TYPES,
        "soccer": soccer_markets.SOCCER_OPTIC_TABLE_TYPES,
        "basketball": basketball_markets.BASKETBALL_OPTIC_TABLE_TYPES,
        "football": football_markets.FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES,
    }[sport]
    assert mt in optic.values()


def test_no_sport_but_mma_still_ignores_a_novig_type():
    from mappers.vocab import novig_markets
    ignored = {s: i for s, (_, i) in novig_markets._SPORT_TABLES.items() if i}
    assert ignored == {"mma": frozenset({"DRAW"})}


def test_first_goal_scorer_builds_a_yes_no_pair_for_the_player():
    market = _market(
        "FIRST_GOAL_SCORER", strike=0.0,
        player={"id": "p1", "name": "Adrian Kempe",
                "fullName": "Adrian Kempe", "opticOddsId": PLAYER_OPTIC},
        outcomes=[
            {"id": "o-yes", "description": "Yes", "type": "Over", "index": 0},
            {"id": "o-no", "description": "No", "type": "Under", "index": 1},
        ])
    rows = _rows(market, MarketType.FIRST_GOAL_SCORER)
    assert {r.market_type for r in rows} == {"first_goal_scorer"}
    assert {r.side for r in rows} == {"yes", "no"}


def test_hockey_shots_on_goal_builds_a_player_over_under_pair():
    market = _market(
        "SHOTS_ON_GOAL", strike=2.5,
        player={"id": "p1", "name": "Artemi Panarin",
                "fullName": "Artemi Panarin", "opticOddsId": PLAYER_OPTIC},
        outcomes=[
            {"id": "o-over", "description": "Over 2.5", "type": "Over", "index": 0},
            {"id": "o-under", "description": "Under 2.5", "type": "Under", "index": 1},
        ])
    rows = _rows(market, MarketType.PLAYER_SHOTS_ON_GOAL)
    assert {r.market_type for r in rows} == {"player_shots_on_goal"}
    assert {r.side: r.line for r in rows} == {"over": 2.5, "under": 2.5}


def test_code_wires_novig_for_liga_mx_and_challenger():
    from dataclasses import replace

    from mappers.market_types import MarketType as MT
    from mappers.seed.tip_factories import with_code_novig
    from mappers.sport import Sport
    from mappers.pipeline import LeagueConfig
    from mappers.exchanges.optic import OpticConfig

    def bare(sport):
        return LeagueConfig(
            league="x", sport=sport, PX=None,
            OPTIC=OpticConfig(league_id="x", table_types={}),
            OUTPUT_ORDER=(), MarketType=MT,
        )

    mx = with_code_novig(bare(Sport.SOCCER), "liga_mx").NOVIG
    assert mx is not None
    assert mx.league == "Liga MX"
    for t in ("PLAYER_GOALS", "FIRST_GOAL_SCORER", "SHOTS_ON_TARGET", "SAVES",
              "GOALS_ASSISTS", "ASSISTS", "BOTH_TEAMS_TO_SCORE",
              "TOTAL_CORNERS", "TEAM_TOTAL_CORNERS", "MONEYLINE_3_WAY_WIN"):
        assert t in mx.market_types

    ch = with_code_novig(bare(Sport.TENNIS), "atp_challenger").NOVIG
    assert ch is not None
    assert ch.league == "ATP"
    assert "SET_SPREAD" in ch.market_types

    # Unlisted slug untouched; a tip-wired league keeps the tip's config.
    assert with_code_novig(bare(Sport.SOCCER), "epl").NOVIG is None
    tip = NovigConfig(league="Tip", market_types={})
    assert with_code_novig(replace(bare(Sport.SOCCER), NOVIG=tip), "liga_mx").NOVIG is tip


# === football MONEY_1H: 2-way Novig market on Optic's 3-way half-winner key ===

def test_football_first_half_two_way_binds_home_and_away_to_the_3way_key():
    market = _market(
        "MONEY_1H",
        outcomes=[
            {"id": "o-home", "description": HOME, "type": "Home", "index": 0,
             "competitor": _competitor(HOME_OPTIC, HOME)},
            {"id": "o-away", "description": AWAY, "type": "Away", "index": 1,
             "competitor": _competitor(AWAY_OPTIC, AWAY)},
        ])
    rows = _rows(market, MarketType.FIRST_HALF_WINNER_3WAY)

    assert {r.side: r.novig_outcome_id for r in rows} == {HOME: "o-home", AWAY: "o-away"}
    assert {r.market_type for r in rows} == {"1h_winner_3way"}


def test_football_first_half_two_way_dropped_when_teams_unnamed():
    market = _market(
        "MONEY_1H",
        outcomes=[
            {"id": "o-a", "description": "A", "type": "Home", "index": 0,
             "competitor": _competitor("UNKNOWN0000", "A")},
            {"id": "o-b", "description": "B", "type": "Away", "index": 1,
             "competitor": _competitor("UNKNOWN1111", "B")},
        ])
    # unresolved teams must drop, never fall into the draw/tie row
    assert _rows(market, MarketType.FIRST_HALF_WINNER_3WAY) == []

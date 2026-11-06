"""Kalshi milestone identity: fixture, orientation and team by id.

Shapes are real Kalshi records (API, 2026-09-30): PSG v Rennes on
2026-08-23 is listed RENPSG by Kalshi (Rennes home) while Optic has PSG
home — the case that forbids assuming milestone home == Optic home.
"""

from __future__ import annotations

from mappers.exchanges.kalshi import (
    AWAY,
    HOME,
    KalshiConfig,
    Market,
    MoneylineMarket,
    SpreadMarket,
    ThreeWayMarket,
    parse_typed_market,
)
from mappers.exchanges.optic import Fixture, Odd
from mappers.fight_props import canonicalize_fight_prop_key
from mappers.pipeline import (
    ScheduleEntry,
    _milestone_entry,
    _milestone_orientation,
    _optic_player_names,
)
from mappers.sport import Sport

from fetch.kalshi import compact_milestone

_L1 = KalshiConfig(sport=Sport.SOCCER)
REN, PSG, TIE = "dcaae7b8", "ccdc8659", "111193d4"
ET = "KXLIGUE1GAME-26AUG23RENPSG"
MS = {
    "id": "ff446b2e", "start_date": "2026-08-23T18:45:00Z",
    "optic_fixture_id": "202608233F4B5ADD", "sportradar_id": "72036122",
    "home_id": REN, "away_id": PSG, "tie_id": TIE,
    "home_optic_id": None, "away_optic_id": None,
}


def _market(ticker: str, team: str | None, *, ms: dict = MS,
            floor: float | None = None, et: str = ET,
            scope: str = "Game") -> Market:
    return Market(
        event_ticker=et, ticker=ticker, title="",
        custom_strike={"soccer_team": team} if team else None,
        strike_type="greater" if floor is not None else "structured",
        floor_strike=floor, milestone=ms,
        competition_scope=scope, series_scope=scope,
    )


def _entry(odds: list[Odd] | None = None) -> ScheduleEntry:
    return ScheduleEntry(Fixture(
        fixture_id="202608233F4B5ADD", game_id="32924-31411-2026-08-23",
        sportradar_id="72036122", start_et="2026-08-23T14:45:00",
        start_date="2026-08-23T18:45:00Z", home="PSG", away="REN",
        home_name="Paris Saint-Germain FC", away_name="Stade Rennais FC",
        team_map={"6CE2C0F47875": "PSG", "C9C064312E88": "REN"},
        odds=odds or [], is_live=False,
    ))


def _odd(team_id: str, ticker: str, sel: str = "yes") -> Odd:
    return Odd(id=ticker, market_id="moneyline", team_id=team_id,
               grouping_key="default",
               source_ids={"Kalshi": {"market_id": ticker, "selection_id": sel}})


def test_compact_milestone_keeps_identity_fields():
    raw = {
        "id": "ff446b2e", "type": "soccer_tournament_multi_leg",
        "start_date": "2026-08-23T18:45:00Z",
        "source_ids": {"source_2_id": "202608233F4B5ADD",
                       "source_3_id": "sr:sport_event:72036122"},
        "details": {"home_team_id": REN, "away_team_id": PSG, "tie_id": TIE},
    }
    got = compact_milestone(raw, {REN: "C9C064312E88"})
    assert got["optic_fixture_id"] == "202608233F4B5ADD"
    assert got["sportradar_id"] == "72036122"
    assert (got["home_id"], got["away_id"], got["tie_id"]) == (REN, PSG, TIE)
    assert (got["home_optic_id"], got["away_optic_id"]) == ("C9C064312E88", None)


def test_entry_by_fixture_id_then_sportradar():
    e = _entry()
    assert _milestone_entry(MS, {"202608233F4B5ADD": e}, {}) is e
    no_fx = {**MS, "optic_fixture_id": None}
    assert _milestone_entry(no_fx, {}, {"72036122": e}) is e
    assert _milestone_entry({**no_fx, "sportradar_id": "1"}, {}, {"72036122": e}) is None


def test_entry_rejects_far_start_and_homeless_milestone():
    e = _entry()
    far = {**MS, "start_date": "2026-09-23T18:45:00Z"}
    assert _milestone_entry(far, {"202608233F4B5ADD": e}, {}) is None
    tennis = {**MS, "home_id": None, "away_id": None}
    assert _milestone_entry(tennis, {"202608233F4B5ADD": e}, {}) is None


def test_orientation_from_optic_source_ids_detects_flip():
    # Optic: ...-PSG yes is its PSG (home) selection; Kalshi: -PSG strike
    # is PSG = milestone away → Kalshi home is Optic away → flipped.
    e = _entry([_odd("6CE2C0F47875", f"{ET}-PSG")])
    assert _milestone_orientation(e, [_market(f"{ET}-PSG", PSG)]) is True


def test_orientation_from_team_optic_ids():
    ms = {**MS, "home_optic_id": "C9C064312E88", "away_optic_id": "6CE2C0F47875"}
    assert _milestone_orientation(_entry(), [_market(f"{ET}-TIE", TIE, ms=ms)]) is True
    ms_straight = {**MS, "home_optic_id": "6CE2C0F47875", "away_optic_id": "C9C064312E88"}
    assert _milestone_orientation(_entry(), [_market(f"{ET}-TIE", TIE, ms=ms_straight)]) is False


def test_orientation_unknown_without_evidence_or_on_conflict():
    assert _milestone_orientation(_entry(), [_market(f"{ET}-PSG", PSG)]) is None
    conflict = _entry([
        _odd("6CE2C0F47875", f"{ET}-PSG"),   # says flipped
        _odd("6CE2C0F47875", f"{ET}-REN"),   # says straight
    ])
    markets = [_market(f"{ET}-PSG", PSG), _market(f"{ET}-REN", REN)]
    assert _milestone_orientation(conflict, markets) is None


def test_side_from_oriented_milestone_ids():
    # Oriented milestone (home = Optic home PSG after the flip swap).
    oriented = {**MS, "home_id": PSG, "away_id": REN}
    p = parse_typed_market(_market(f"{ET}-PSG", PSG, ms=oriented), _L1)
    assert isinstance(p, ThreeWayMarket) and p.side == HOME
    tie = parse_typed_market(_market(f"{ET}-TIE", TIE, ms=oriented), _L1)
    assert isinstance(tie, ThreeWayMarket) and tie.side is None


def test_spread_side_and_line_are_typed_whatever_the_ticker_says():
    et = "KXLIGUE1SPREAD-26AUG23RENPSG"
    oriented = {**MS, "home_id": PSG, "away_id": REN}
    m = _market(f"{et}-XXX9", REN, ms=oriented, floor=1.5, et=et, scope="Spread")
    p = parse_typed_market(m, _L1)
    assert isinstance(p, SpreadMarket)
    assert (p.side, p.line) == (AWAY, 1.5)


def test_moneyline_side():
    nba = KalshiConfig(sport=Sport.BASKETBALL)
    et = "KXNBAGAME-26OCT20BOSDET"
    ms = {**MS, "home_id": "det", "away_id": "bos", "tie_id": None}
    m = Market(event_ticker=et, ticker=f"{et}-BOS", title="",
               custom_strike={"basketball_team": "bos"}, milestone=ms,
               competition_scope="Game", series_scope="Game")
    p = parse_typed_market(m, nba)
    assert isinstance(p, MoneylineMarket) and p.side == AWAY


def test_compact_milestone_first_second_and_esports_sides():
    tennis = {"id": "t", "source_ids": {},
              "details": {"first_competitor_id": "a", "second_competitor_id": "b"}}
    got = compact_milestone(tennis, {"a": "OPTA", "b": "OPTB"})
    assert (got["home_id"], got["away_id"]) == ("a", "b")
    assert (got["home_optic_id"], got["away_optic_id"]) == ("OPTA", "OPTB")
    esports = {"id": "e", "source_ids": {"source_2_id": "F"},
               "details": {"home_competitor_id": "h", "away_competitor_id": "w"}}
    assert compact_milestone(esports)["home_id"] == "h"
    fight = {"id": "f", "source_ids": {},
             "details": {"first_fighter_id": "x", "second_fighter_id": "y"}}
    assert compact_milestone(fight)["away_id"] == "y"


def test_entry_by_competitor_pair_when_no_fixture_ids():
    from mappers.pipeline import _competitor_pair_index
    e = _entry()
    ms = {**MS, "optic_fixture_id": None, "sportradar_id": None,
          "home_optic_id": "C9C064312E88", "away_optic_id": "6CE2C0F47875"}
    idx = _competitor_pair_index([e])
    assert _milestone_entry(ms, {}, {}, idx) is e
    no_ids = {**ms, "home_optic_id": None, "away_optic_id": None}
    assert _milestone_entry(no_ids, {}, {}, idx) is None


def test_strike_team_id_picks_the_single_side_key():
    from mappers.exchanges.kalshi import strike_team_id
    mov = Market(event_ticker="E", ticker="E-X", title="",
                 custom_strike={"Method": "Decision", "ufc_competitor": "f1"})
    assert strike_team_id(mov) == "f1"
    mof = Market(event_ticker="E", ticker="E-X", title="",
                 custom_strike={"Method": "Decision"})
    assert strike_team_id(mof) is None


def test_typed_ufc_method_and_round_from_custom_strike():
    from mappers.exchanges.kalshi import GameYesNoMarket, TeamYesNoMarket
    ufc = KalshiConfig(sport=Sport.MMA)
    ms = {**MS, "home_id": "spi", "away_id": "pet", "tie_id": None}
    et = "KXUFCMOV-26AUG22SPIPET"
    mov = Market(event_ticker=et, ticker=f"{et}-ZZZ", title="", milestone=ms,
                 competition_scope="Method of Victory",
                 custom_strike={"Method": "Submission", "ufc_competitor": "pet"})
    p = parse_typed_market(mov, ufc)
    assert isinstance(p, TeamYesNoMarket)
    assert (p.side, p.grouping_key) == (AWAY, "submission")
    draw = Market(event_ticker=et, ticker=f"{et}-DRAW", title="", milestone=ms,
                  competition_scope="Method of Victory",
                  custom_strike={"Method": "Draw/No Contest", "ufc_competitor": "nc"})
    p = parse_typed_market(draw, ufc)
    assert isinstance(p, GameYesNoMarket) and p.grouping_key == "draw_or_nc"
    et = "KXUFCMOF-26AUG22SPIPET"
    mof = Market(event_ticker=et, ticker=f"{et}-ZZZ", title="", milestone=ms,
                 competition_scope="Method of Finish",
                 custom_strike={"Method": "Draw/No Contest"})
    p = parse_typed_market(mof, ufc)
    assert isinstance(p, GameYesNoMarket) and p.grouping_key == "draw_or_nc"
    et = "KXUFCVICROUND-26AUG22SPIPET"
    vr = Market(event_ticker=et, ticker=f"{et}-ZZZ", title="", milestone=ms,
                competition_scope="Round of Victory",
                yes_sub_title="Sergey Spivak to win in Round 2",
                custom_strike={"Round": "2", "ufc_competitor": "spi"})
    p = parse_typed_market(vr, ufc)
    assert isinstance(p, GameYesNoMarket)
    assert (p.grouping_key or "").endswith("_round_2")
    other = Market(event_ticker=et, ticker=f"{et}-OTHER", title="", milestone=ms,
                   competition_scope="Round of Victory",
                   yes_sub_title="Decision / Draw / No Contest",
                   custom_strike={"Round": "Decision / Draw / No Contest",
                                  "ufc_competitor": "nc"})
    p = parse_typed_market(other, ufc)
    assert isinstance(p, GameYesNoMarket)
    assert p.grouping_key == canonicalize_fight_prop_key("Decision / Draw / No Contest")


def test_off_milestone_strike_id_resolved_only_by_optic_source_ids():
    from mappers.pipeline import _resolve_off_milestone_sides
    oriented = {**MS, "home_id": PSG, "away_id": REN}
    dup = _market(f"{ET}-PSG", "psg-duplicate-entity", ms=oriented)
    # No Optic evidence: untouched (parse will skip it).
    assert _resolve_off_milestone_sides(_entry(), [dup])[0].resolved_side_id is None
    e = _entry([_odd("6CE2C0F47875", f"{ET}-PSG")])
    got = _resolve_off_milestone_sides(e, [dup])[0]
    assert got.resolved_side_id == PSG
    p = parse_typed_market(got, _L1)
    assert isinstance(p, ThreeWayMarket) and p.side == HOME


def test_one_side_optic_id_orients_but_never_joins():
    from mappers.pipeline import _competitor_pair_index
    e = _entry()
    ms = {**MS, "optic_fixture_id": None, "sportradar_id": None,
          "home_optic_id": None, "away_optic_id": "6CE2C0F47875"}   # PSG
    # One player can have two fixtures inside the start tolerance
    # (qualifying and main draw), so one side's id is no join.
    assert _milestone_entry(ms, {}, {}, _competitor_pair_index([e])) is None
    # Once joined another way, it still settles orientation: Kalshi
    # away = PSG = Optic home → flipped.
    assert _milestone_orientation(e, [_market(f"{ET}-TIE", TIE, ms=ms)]) is True


def test_entry_by_optic_source_ids_naming_a_milestone_ticker():
    from mappers.pipeline import _optic_ref_index
    e = _entry([_odd("6CE2C0F47875", f"{ET}-PSG")])
    other = _entry([_odd("6CE2C0F47875", f"{ET}-REN")])
    ms = {**MS, "optic_fixture_id": None, "sportradar_id": None}
    named = _market(f"{ET}-PSG", PSG, ms=ms)
    unnamed = _market(f"{ET}-TIE", TIE, ms=ms)
    idx = _optic_ref_index([e], [named, unnamed])
    # The whole milestone follows the one ticker Optic names.
    assert _milestone_entry(unnamed.milestone, {}, {}, None, idx) is e
    # Tickers of one milestone pointing at two fixtures: no join.
    both = _optic_ref_index([e, other], [named, _market(f"{ET}-REN", REN, ms=ms)])
    assert _milestone_entry(ms, {}, {}, None, both) is None


def test_optic_player_names_only_where_optic_is_unambiguous():
    one = "KXNFLTD-26OCT04NYJCHI-CHICHIDST-1"
    two = "KXNFLTD-26OCT04NYJCHI-NYJBHALL20-1"
    odds = [
        Odd(id="a", market_id="anytime_touchdown_scorer", grouping_key="default",
            selection="Chicago Bears D/ST",
            source_ids={"Kalshi": {"market_id": one, "selection_id": "yes"}}),
        Odd(id="b", market_id="player_touchdowns", grouping_key="default:0.5",
            selection="Chicago Bears D/ST", selection_line="under",
            source_ids={"Kalshi": {"market_id": one, "selection_id": "no"}}),
        Odd(id="c", market_id="anytime_touchdown_scorer", grouping_key="default",
            selection="Breece Hall",
            source_ids={"Kalshi": {"market_id": two, "selection_id": "yes"}}),
        Odd(id="d", market_id="anytime_touchdown_scorer", grouping_key="default",
            selection="Braelon Allen",
            source_ids={"Kalshi": {"market_id": two, "selection_id": "yes"}}),
    ]
    assert _optic_player_names(_entry(odds).fixture) == {one: "Chicago Bears D/ST"}

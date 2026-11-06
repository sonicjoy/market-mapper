"""DKEX typed market records, classification and row construction.

Every market here is a real row from the staging REST catalogue
(``POST /api/v1/markets/queries``, 2026-09-28), stored verbatim minus the
rulebook text in ``tests/fixtures/dkex/staging_markets_2026-09-28.json``
and pushed through ``fetch.dkex.normalize`` exactly as the fetcher does.
Nothing below reads meaning out of a ticker: the tickers are only the
keys the fixtures are looked up by.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fetch.dkex import normalize
from mappers.exchanges.dkex import (
    SETTLEMENT_LAG,
    DkexConfig,
    DkexMarket,
    build_rows,
    canonical_strike_line,
    event_start,
    is_combo,
    league_token,
    market_from_row,
)
from mappers.market_types import MarketType
from mappers.profiles.registry import profile_registered
from mappers.sport import Sport
from mappers.vocab import dkex_markets as vocab

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_markets_2026-09-28.json"


def _raw() -> dict[str, dict]:
    return {r["ticker"]: r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))}


RAW = _raw()


def row(ticker: str) -> dict:
    """The normalized catalogue row for one real staging market."""
    return normalize(RAW[ticker], "api")


def market(ticker: str) -> DkexMarket:
    m = market_from_row(row(ticker))
    assert m is not None
    return m


# DEN Broncos @ SF 49ers, competition 01S2KTKBIUCN390 (NFL, 2026-10-04).
DEN_WIN = "NFL-WIN-FG-01S2KTKBIUCN390-DEOS024"
SF_WIN = "NFL-WIN-FG-01S2KTKBIUCN390-SFRS000"
SF_MOVY = "NFL-MOVY-FG-01S2KTKBIUCN390-SFRS000-GTE-P00035"
DEN_MOVY = "NFL-MOVY-FG-01S2KTKBIUCN390-DEOS024-GTE-P00035"
TPTS_FG = "NFL-TPTS-FG-01S2KTKBIUCN390-GTE-P00605"
TPTS_H1 = "NFL-TPTS-H1-01S2KTKBIUCN390-GTE-P00065"
DEN_TMPTS = "NFL-TMPTS-FG-01S2KTKBIUCN390-DEOS024-GTE-P00065"
DEN_WIN_Q2 = "NFL-WIN-Q2-01S2KTKBIUCN390-DEOS024"
# PIT Steelers @ CLE Browns, competition 01S2LVEPIUCM13O.
PREY = "NFL-PREY-FG-01S2LVEPIUCM13O-DEON230-GTE-P00195"
PREYOU = "NFL-PREYOU-FG-01S2LVEPIUCM13O-DEON230-GTE-P00465"
PTDS1 = "NFL-PTDS1-FG-01S2LVEPIUCM13O-AARS007"
FTD_PLAYER = "NFL-FTD-FG-00O2Q7JBQSTTPC0-BRDY014"
FTD_NONE = "NFL-FTD-FG-00O2Q7JBQSTTPC0-NONE"
BSA_MOVY = "BSA-MOVY-FG-02L4HV50HIO28DG-SALO008-GTE-P00035"
BSA_DRAW = "BSA-DWIN-FG-02L4G7P1HIOAEOO-DRAW"
BSA_BTTS = "BSA-BTMSC-FG-02L4G7P1HIOAEOO-BINARY"
CFB_MOVY = "CFB-MOVY-FG-00O054EUQSO63K8-APTE002-GTE-P00015"
MLB_F5 = "MLB-MOVY-IT5-00O043L4QSODRB8-DERS000-GTE-P00005"


# === Typed record ===

def test_market_is_built_from_typed_fields() -> None:
    """The brief's example: parameters + roles, not the ticker, carry identity."""
    m = market(BSA_MOVY)
    assert (m.league, m.market, m.period) == ("BSA", "MOVY", "FG")
    assert m.event_id == "02L4HV50HIO28DG"
    assert m.strike == 3.5
    assert m.outcome_type == "GTE"
    assert m.participant is not None
    assert (m.participant.id, m.participant.name, m.participant.role) == (
        "DKT_0122GRI10PFAO", "Sao Paulo", "away",
    )
    assert m.ticker == BSA_MOVY  # carried through as an opaque id


def test_typed_fields_win_over_a_lying_ticker() -> None:
    """If the ticker disagreed with the typed fields, the typed fields decide."""
    rec = row(SF_MOVY)
    rec["symbol"] = "XXX-TPTS-H2-ZZZZZZZZZZZZZZZ-GTE-P09995"
    m = market_from_row(rec)
    assert m is not None
    assert (m.league, m.market, m.period, m.strike) == ("NFL", "MOVY", "FG", 3.5)
    assert m.event_id == "01S2KTKBIUCN390"


def test_reports_row_is_untyped() -> None:
    """A CSV report row has only the symbol; it is never parsed to fill in."""
    rec = normalize({"ticker": DEN_WIN, "status": "Open"}, "reports")
    assert rec["stat_achievement"] is None and rec["competition_id"] is None
    assert market_from_row(rec) is None


@pytest.mark.parametrize(("sub_topic", "token"), [
    ("NFL", "NFL"), ("NCAAF", "CFB"), ("NCAA FCS", "CFB"), ("MLB", "MLB"),
    ("WNBA", "WNBA"), ("Brazil - Serie A", "BSA"), ("", ""), (None, ""),
])
def test_league_token_from_sub_topic(sub_topic: str | None, token: str) -> None:
    assert league_token(sub_topic) == token


def test_player_prop_has_no_role() -> None:
    m = market(PREY)
    assert m.participant is not None
    assert m.participant.name == "Denzel Boston"
    assert m.participant.role is None


def test_game_scoped_markets_have_no_participant() -> None:
    for ticker in (TPTS_FG, FTD_NONE, BSA_DRAW, BSA_BTTS):
        assert market(ticker).participant is None, ticker


def test_combo_is_read_from_typed_fields() -> None:
    """A combo is known by its product type or legs, never its ticker."""
    assert is_combo({"marketProductTypeName": "COMBO", "legs": [{"legIndex": 1}]})
    assert is_combo({"legs": [{"legIndex": 1}]})
    assert not is_combo({"ticker": "COMBO-12783464979703431470"})
    assert not is_combo({"marketProductTypeName": "NFL-WIN", "ticker": DEN_WIN})


def test_event_start_is_maturity_minus_thirty_days() -> None:
    """Report maturity is the event start plus exactly 30 days."""
    maturity = datetime(2026, 10, 14, 20, 15, tzinfo=UTC)
    assert event_start(maturity) == datetime(2026, 9, 14, 20, 15, tzinfo=UTC)
    assert SETTLEMENT_LAG.days == 30


# === Classification ===

FOOTBALL = DkexConfig(
    league="NFL",
    market_types=vocab.FOOTBALL,
    implied_lines=vocab.FOOTBALL_IMPLIED_LINES,
    ignored_markets=vocab.FOOTBALL_IGNORED,
)
BASEBALL = DkexConfig(
    league="MLB", market_types=vocab.BASEBALL, ignored_markets=vocab.BASEBALL_IGNORED,
)


@pytest.mark.parametrize(("ticker", "expected"), [
    (DEN_WIN, MarketType.MONEYLINE),
    (SF_MOVY, MarketType.POINT_SPREAD),
    (TPTS_FG, MarketType.GAME_TOTAL),
    (TPTS_H1, MarketType.FIRST_HALF_TOTAL),
    (DEN_TMPTS, MarketType.TEAM_TOTAL),
    (PREY, MarketType.PLAYER_RECEIVING_YARDS),
    (PREYOU, MarketType.PLAYER_RECEIVING_YARDS),
    (PTDS1, MarketType.PLAYER_TOUCHDOWNS),
    (FTD_PLAYER, MarketType.FIRST_TOUCHDOWN_SCORER),
])
def test_football_classification(ticker: str, expected: MarketType) -> None:
    assert FOOTBALL.market_type(market(ticker)) is expected


def test_quarter_winner_gets_its_own_type_not_the_full_game_one() -> None:
    """WIN/Q2 is the 2nd-quarter 3-way, never forced onto WIN/FG."""
    m = market(DEN_WIN_Q2)
    assert m.period == "Q2"
    assert FOOTBALL.market_type(m) is MarketType.SECOND_QUARTER_WINNER_3WAY
    assert not FOOTBALL.deliberately_unmapped(m)


def test_first_five_innings_is_not_a_half() -> None:
    assert BASEBALL.market_type(market(MLB_F5)) is MarketType.FIRST_FIVE_POINT_SPREAD


def test_futures_period_is_deliberately_unmapped() -> None:
    m = replace(market(DEN_WIN), market="WCHP", period="FS")
    assert FOOTBALL.market_type(m) is None
    assert FOOTBALL.deliberately_unmapped(m)


def test_ignored_market_is_not_classified() -> None:
    m = replace(market(PREY), market="WCHP")
    assert FOOTBALL.market_type(m) is None
    assert FOOTBALL.deliberately_unmapped(m)


def test_rush_rec_yards_and_rbis_classify() -> None:
    assert FOOTBALL.market_type(replace(market(PREY), market="PRUREY")) is (
        MarketType.PLAYER_RUSHING_RECEIVING_YARDS
    )
    assert BASEBALL.market_type(replace(market(MLB_F5), market="PRBI", period="FG")) is (
        MarketType.PLAYER_RBIS
    )


def test_first_period_moneyline_maps_to_the_three_way() -> None:
    """A tie settles 50/50 on DKEX; mapped onto Optic's 3-way anyway (team leg only)."""
    assert FOOTBALL.market_type(replace(market(DEN_WIN), period="H1")) is MarketType.FIRST_HALF_WINNER_3WAY
    assert BASEBALL.market_type(
        replace(market(MLB_F5), market="WIN", period="IT5")
    ) is MarketType.FIRST_FIVE_MONEYLINE_3WAY


def test_full_game_moneyline_still_maps() -> None:
    assert FOOTBALL.market_type(market(DEN_WIN)) is MarketType.MONEYLINE
    assert BASEBALL.market_type(replace(market(MLB_F5), market="WIN", period="FG")) is MarketType.MONEYLINE


def test_line_is_the_strike_price() -> None:
    assert FOOTBALL.line_for(market(PREY)) == 19.5
    assert FOOTBALL.line_for(market(TPTS_FG)) == 60.5


def test_touchdown_ladder_line() -> None:
    """PTDS1 carries strikePrice 0.5 on staging; the implied line agrees."""
    m = market(PTDS1)
    assert m.strike == 0.5
    assert FOOTBALL.line_for(m) == 0.5
    assert FOOTBALL.line_for(replace(m, strike=None)) == 0.5


def test_gt_maps_to_the_next_half_point() -> None:
    """outcomeType GT (> 19.5) keys as 20.0, never as GTE's 19.5."""
    m = market(PREY)
    assert canonical_strike_line(m) == 19.5
    assert canonical_strike_line(replace(m, outcome_type="GT")) == 20.0


@pytest.mark.parametrize("sport", [Sport.FOOTBALL, Sport.BASEBALL, Sport.BASKETBALL])
def test_dkex_profile_registered(sport: Sport) -> None:
    assert profile_registered("dkex_generic_v1", sport)


# === Row construction ===
#
# Optic has SF home, DEN away for this game.  ``team`` is what the pass
# resolves a participant to (participant id -> role -> fixture side).

def _rows(ticker: str, mt: MarketType, *, team: str | None = None,
          player: str | None = None, line: float | None = None):
    m = market(ticker)
    resolved = line if line is not None else FOOTBALL.line_for(m)
    return build_rows(
        m, mt, line=resolved, home="SF", away="DEN",
        start_date="2026-10-04T20:25:00Z", league="nfl",
        team=team, player=player,
    )


def test_moneyline_yes_is_the_named_team_and_no_is_the_opponent() -> None:
    yes, no = _rows(DEN_WIN, MarketType.MONEYLINE, team="DEN")
    assert (yes.side, yes.dkex_side) == ("DEN", "yes")
    assert (no.side, no.dkex_side) == ("SF", "no")
    assert yes.line is None and yes.entity is None


def test_spread_yes_is_the_team_laying_the_points() -> None:
    """MOVY GTE 3.5 on SF is SF -3.5; the no side is DEN +3.5."""
    yes, no = _rows(SF_MOVY, MarketType.POINT_SPREAD, team="SF")
    assert (yes.side, yes.line, yes.dkex_side) == ("SF", -3.5, "yes")
    assert (no.side, no.line, no.dkex_side) == ("DEN", 3.5, "no")


def test_rows_carry_typed_provenance_and_the_ticker_as_id() -> None:
    yes, no = _rows(DEN_MOVY, MarketType.POINT_SPREAD, team="DEN")
    assert yes.dkex_symbol == no.dkex_symbol == DEN_MOVY
    assert (yes.dkex_event_id, yes.dkex_market, yes.dkex_period) == (
        "01S2KTKBIUCN390", "MOVY", "FG",
    )


def test_game_total_yes_is_over() -> None:
    yes, no = _rows(TPTS_FG, MarketType.GAME_TOTAL)
    assert (yes.side, yes.line, yes.entity) == ("over", 60.5, None)
    assert (no.side, no.line) == ("under", 60.5)


def test_team_total_keeps_the_team_as_entity() -> None:
    yes, no = _rows(DEN_TMPTS, MarketType.TEAM_TOTAL, team="DEN")
    assert (yes.entity, yes.side, yes.line) == ("DEN", "over", 6.5)
    assert (no.entity, no.side) == ("DEN", "under")


def test_player_prop_over_under() -> None:
    yes, no = _rows(PREY, MarketType.PLAYER_RECEIVING_YARDS, player="denzel_boston")
    assert (yes.entity, yes.side, yes.line) == ("denzel_boston", "over", 19.5)
    assert (no.entity, no.side) == ("denzel_boston", "under")


def test_first_touchdown_scorer_is_yes_no() -> None:
    yes, no = _rows(FTD_PLAYER, MarketType.FIRST_TOUCHDOWN_SCORER, player="brock_purdy")
    assert (yes.side, yes.line, no.side) == ("yes", None, "no")


@pytest.mark.parametrize(("ticker", "mt"), [
    (DEN_WIN, MarketType.MONEYLINE),
    (SF_MOVY, MarketType.POINT_SPREAD),
    (DEN_TMPTS, MarketType.TEAM_TOTAL),
    (PREY, MarketType.PLAYER_RECEIVING_YARDS),
])
def test_unresolved_entity_drops_the_market_whole(ticker: str, mt: MarketType) -> None:
    """No resolved team/player emits neither side, never one."""
    assert _rows(ticker, mt) == []


def test_team_outside_the_fixture_drops() -> None:
    assert _rows(DEN_WIN, MarketType.MONEYLINE, team="KC") == []


def test_no_touchdown_scorer_has_no_participant_and_drops() -> None:
    """FTD with no participant ("No Touchdown Scorer") has no Optic selection."""
    assert _rows(FTD_NONE, MarketType.FIRST_TOUCHDOWN_SCORER) == []


def test_game_total_naming_a_participant_is_refused() -> None:
    m = replace(market(TPTS_FG), participant=market(DEN_WIN).participant)
    assert build_rows(
        m, MarketType.GAME_TOTAL, line=60.5, home="SF", away="DEN",
        start_date="2026-10-04T20:25:00Z", league="nfl",
    ) == []


def test_spread_without_a_line_is_dropped() -> None:
    assert build_rows(
        replace(market(SF_MOVY), strike=None), MarketType.POINT_SPREAD,
        line=None, home="SF", away="DEN", start_date="2026-10-04T20:25:00Z",
        league="nfl", team="SF",
    ) == []


# === Satellite tickers (attach_dkex_row) ===

def _index(rows):
    from mappers.pipeline import row_key
    return {row_key(r): r for r in rows}


def test_second_ticker_for_one_bet_becomes_a_satellite() -> None:
    """DKEX lists both moneyline tickers; neither may overwrite the other."""
    from mappers.pipeline import attach_dkex_row

    sf_yes, _den_no = _rows(SF_WIN, MarketType.MONEYLINE, team="SF")
    _den_yes, sf_no = _rows(DEN_WIN, MarketType.MONEYLINE, team="DEN")

    optic = sf_yes.model_copy(deep=True)
    optic.dkex_symbol = optic.dkex_side = None
    optic.optic_id = "optic-1"
    index = _index([optic])
    all_rows = [optic]
    alt: dict = {}

    assert attach_dkex_row(index, alt, all_rows, sf_yes) == "stamped"
    assert optic.dkex_symbol == SF_WIN
    # sf_no is the SAME canonical row (SF wins) under the other ticker.
    assert attach_dkex_row(index, alt, all_rows, sf_no) == "satellite"
    assert len(all_rows) == 2
    sat = all_rows[1]
    assert sat.dkex_satellite is True
    assert sat.dkex_symbol == DEN_WIN
    assert sat.dkex_side == "no"
    assert sat.optic_id == "optic-1"


def test_the_same_ticker_twice_is_not_a_second_row() -> None:
    from mappers.pipeline import attach_dkex_row

    yes, _no = _rows(SF_WIN, MarketType.MONEYLINE, team="SF")
    optic = yes.model_copy(deep=True)
    optic.dkex_symbol = optic.dkex_side = None
    index, all_rows, alt = _index([optic]), [optic], {}
    assert attach_dkex_row(index, alt, all_rows, yes) == "stamped"
    assert attach_dkex_row(index, alt, all_rows, yes) == "duplicate"
    assert len(all_rows) == 1


def test_no_optic_row_means_dropped_not_invented() -> None:
    from mappers.pipeline import attach_dkex_row

    yes, _no = _rows(SF_WIN, MarketType.MONEYLINE, team="SF")
    all_rows: list = []
    assert attach_dkex_row({}, {}, all_rows, yes) == "dropped_no_optic"
    assert all_rows == []


def test_merge_key_separates_the_two_dkex_tickers() -> None:
    """Both tickers must survive the BigQuery MERGE, not collide on it."""
    from BigQuery.load_mappings import _source_identity_sql

    sql = _source_identity_sql("t")
    assert "t.sportsbook = 'DKEX'" in sql
    assert sql.count("'$.market_id'") >= 1 and sql.count("'$.selection_id'") >= 1


def test_cfb_market_is_typed_as_cfb() -> None:
    m = market(CFB_MOVY)
    assert m.league == "CFB"
    assert m.participant is not None and m.participant.name == "Appalachian State"


# === Soccer ===
#
# Real staging rows (2026-09-29): Atletico Mineiro (home) vs RB Bragantino
# (away), Brasileirao, plus the Birmingham vs Middlesbrough goalscorers.
# Every contract settles on 90 minutes plus stoppage time (the venue's
# rules text), the same basis as Optic's moneyline / double_chance.

SOCCER_FIXTURE = FIXTURE.with_name("staging_soccer_2026-09-29.json")
SOCCER_RAW = {r["ticker"]: r for r in json.loads(SOCCER_FIXTURE.read_text(encoding="utf-8"))}
SOCCER = DkexConfig(league="BSA", market_types=vocab.SOCCER, ignored_markets=vocab.SOCCER_IGNORED)
CAM_WIN = "BSA-DWIN-FG-02L4G7P1HIOAEOO-ATRO002"
RBB_WIN = "BSA-DWIN-FG-02L4G7P1HIOAEOO-RBNO000"
DRAW = "BSA-DWIN-FG-02L4G7P1HIOAEOO-DRAW"
CAM_MOVY_15 = "BSA-MOVY-FG-02L4G7P1HIOAEOO-ATRO002-GTE-P00015"
TGLS_25 = "BSA-TGLS-FG-02L4G7P1HIOAEOO-GTE-P00025"
BTTS = "BSA-BTMSC-FG-02L4G7P1HIOAEOO-BINARY"
SCORER = "EFLC-SGL1-FG-01S1RKSTIU4CCJ8-AIIS004"
NO_SCORER = "EFLC-SGL1-FG-01S1RKSTIU4CCJ8-NONE"


def soccer_market(ticker: str) -> DkexMarket:
    m = market_from_row(normalize(SOCCER_RAW[ticker], "api"))
    assert m is not None
    return m


def _soccer_rows(ticker: str, *, team: str | None = None, player: str | None = None):
    m = soccer_market(ticker)
    mt = SOCCER.market_type(m)
    assert mt is not None
    return build_rows(
        m, mt, line=SOCCER.line_for(m), home="CAM", away="RBB",
        start_date="2026-10-03T21:30:00Z", league="brazil_serie_a",
        team=team, player=player,
    )


def _sides(rows) -> list[tuple[str, str, float | None, str | None]]:
    return [(r.market_type, r.side, r.line, r.dkex_side) for r in rows]


@pytest.mark.parametrize(("ticker", "expected"), [
    (CAM_WIN, MarketType.MONEYLINE_3WAY),
    (DRAW, MarketType.MONEYLINE_3WAY),
    (CAM_MOVY_15, MarketType.POINT_SPREAD),
    (TGLS_25, MarketType.GAME_TOTAL),
    (BTTS, MarketType.BTTS),
    (SCORER, MarketType.PLAYER_GOALS),
])
def test_soccer_classification(ticker: str, expected: MarketType) -> None:
    assert SOCCER.market_type(soccer_market(ticker)) is expected


def test_soccer_profile_registered() -> None:
    assert profile_registered("dkex_generic_v1", Sport.SOCCER)


def test_three_way_yes_is_the_team_and_no_is_the_other_two_outcomes() -> None:
    """"Atletico Mineiro: No" is Bragantino-or-draw, Optic's double chance."""
    assert _sides(_soccer_rows(CAM_WIN, team="CAM")) == [
        ("moneyline_3way", "CAM", None, "yes"),
        ("double_chance", "RBB/_TIE", None, "no"),
    ]
    assert _sides(_soccer_rows(RBB_WIN, team="RBB")) == [
        ("moneyline_3way", "RBB", None, "yes"),
        ("double_chance", "CAM/_TIE", None, "no"),
    ]


def test_draw_is_the_participant_less_three_way_leg() -> None:
    """The draw has no parameters.participant; its No is either team winning."""
    assert soccer_market(DRAW).participant is None
    assert _sides(_soccer_rows(DRAW)) == [
        ("moneyline_3way", "_TIE", None, "yes"),
        ("double_chance", "CAM/RBB", None, "no"),
    ]


def test_three_way_legs_never_share_a_canonical_row() -> None:
    rows = [r for t, team in ((CAM_WIN, "CAM"), (RBB_WIN, "RBB"), (DRAW, None))
            for r in _soccer_rows(t, team=team)]
    keys = [(r.market_type, r.side) for r in rows]
    assert len(keys) == len(set(keys)) == 6


def test_three_way_team_outside_the_fixture_drops() -> None:
    assert _soccer_rows(CAM_WIN, team="FLA") == []


def test_three_way_team_leg_without_a_resolved_team_drops() -> None:
    """A team leg whose participant did not resolve is not the draw."""
    assert _soccer_rows(CAM_WIN, team=None) == []


def test_soccer_spread_is_the_asian_handicap_half_line() -> None:
    assert _sides(_soccer_rows(CAM_MOVY_15, team="CAM")) == [
        ("point_spread", "CAM", -1.5, "yes"),
        ("point_spread", "RBB", 1.5, "no"),
    ]


def test_total_goals_yes_is_over() -> None:
    assert _sides(_soccer_rows(TGLS_25)) == [
        ("game_total", "over", 2.5, "yes"),
        ("game_total", "under", 2.5, "no"),
    ]


def test_btts_is_a_game_yes_no() -> None:
    rows = _soccer_rows(BTTS)
    assert _sides(rows) == [("btts", "yes", None, "yes"), ("btts", "no", None, "no")]
    assert all(r.entity is None for r in rows)


def test_btts_naming_a_participant_is_refused() -> None:
    m = soccer_market(CAM_WIN)
    assert build_rows(
        m, MarketType.BTTS, line=None, home="CAM", away="RBB",
        start_date="2026-10-03T21:30:00Z", league="brazil_serie_a", team="CAM",
    ) == []


def test_anytime_goalscorer_is_anytime_goal_scorer() -> None:
    rows = _soccer_rows(SCORER, player="aidan_morris")
    assert _sides(rows) == [
        ("anytime_goal_scorer", "yes", None, "yes"),
        ("player_goals", "under", 0.5, "no"),
    ]
    assert {r.entity for r in rows} == {"aidan_morris"}


def test_no_goalscorer_has_no_player_and_drops() -> None:
    assert soccer_market(NO_SCORER).participant is None
    assert _soccer_rows(NO_SCORER) == []


def test_short_club_names_are_on_for_soccer_only() -> None:
    from mappers.profiles.registry import lookup_profile
    from mappers.profiles.types import LeagueBuildContext

    def built(sport: Sport, slug: str) -> DkexConfig:
        profile = lookup_profile("dkex_generic_v1", sport)
        assert profile is not None
        cfg = profile.build({"league": "X"}, LeagueBuildContext(slug, sport, slug, 96.0, ()))
        assert isinstance(cfg, DkexConfig)
        return cfg

    assert built(Sport.SOCCER, "epl").club_short_names
    assert not built(Sport.FOOTBALL, "nfl").club_short_names


def test_single_inning_totals_map_for_innings_1_to_9() -> None:
    assert vocab.BASEBALL[("TRUNS", "I1")] is MarketType.FIRST_INNING_TOTAL
    for n in range(2, 10):
        assert vocab.BASEBALL[("TRUNS", f"I{n}")] is MarketType[f"INNING_{n}_TOTAL"]


def test_single_inning_three_way_maps_for_innings_1_to_8() -> None:
    for n in range(1, 9):
        assert vocab.BASEBALL[("WIN", f"I{n}")] is MarketType[f"INNING_{n}_WINNER_3WAY"]
    assert ("WIN", "I9") not in vocab.BASEBALL


def test_football_assists_maps_to_player_assists() -> None:
    """PAST is the defensive assisted tackle (rules text, 2026-10-12), Optic's NFL player_assists."""
    assert vocab.FOOTBALL[("PAST", "FG")] is MarketType.PLAYER_ASSISTS
    assert ("PAST", "FG") not in vocab.FOOTBALL_IGNORED

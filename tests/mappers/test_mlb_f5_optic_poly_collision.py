"""MLB F5: Optic's OWN rows are what the poly F5 rows must collide with.

tests/mappers/test_polymarket_mlb_integration.py proves the poly side attaches,
but it pre-seeds hand-written optic rows -- so it asserts against an ASSUMPTION
of the optic row shape. This module removes that assumption: it runs
`optic.build_rows` over a synthetic fixture carrying the three "1st_half_*"
markets (the family mlb.py OPTIC.table_types wires to the F5 MarketTypes), and
then attaches the real poly F5 markets to THOSE rows.

If optic's builder and the poly rules ever disagree on line sign, side
vocabulary, or the tie key, these tests fail instead of the mapping silently
dropping every F5 row in production.

The odd payload shapes follow optic.build_rows' documented contract:
  - SPREAD:    team_id set, points signed (positive = underdog)
  - TOTAL:     selection_line in ("over","under"), points >= 0 on BOTH sides
  - THREE_WAY: team_id set per team; the Draw ships team_id=null
"""

import dataclasses

from mappers.exchanges import optic
from mappers.exchanges import polymarket as pm
from mappers.pipeline import attach_polymarket_row, row_key
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league


def _mlb_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "mlb")
    return build_tip_league(row)

_HOME, _AWAY = "AZ", "STL"
_HOME_NAME, _AWAY_NAME = "Arizona Diamondbacks", "St. Louis Cardinals"
_START = "2026-07-21T23:00:00Z"
_TEAM_MAP = {"T_AZ": _HOME, "T_STL": _AWAY}

# The F5 lines poly actually quotes (prod bridge census): totals run 2.5-6.5,
# spreads -1.5/-2.5. 4.5 / -1.5 are the modal pair.
_TOTAL_LINE = 4.5
_SPREAD_LINE = -1.5


def _odd(market_id: str, selection: str, *, selection_line=None, points=None,
         team_id=None) -> optic.Odd:
    return optic.Odd(
        id=f"FIX1:book:{market_id}:{selection}", market_id=market_id,
        market=market_id, selection=selection, selection_line=selection_line,
        points=points, team_id=team_id, grouping_key="default",
    )


def _optic_f5_rows():
    """Optic's canonical rows for all three MLB F5 markets, keyed by row_key."""
    odds = [
        # 1st_half_run_line -> f5_point_spread
        _odd("1st_half_run_line", _HOME_NAME, points=_SPREAD_LINE, team_id="T_AZ"),
        _odd("1st_half_run_line", _AWAY_NAME, points=-_SPREAD_LINE, team_id="T_STL"),
        # 1st_half_total_runs -> f5_total
        _odd("1st_half_total_runs", "Over", selection_line="over", points=_TOTAL_LINE),
        _odd("1st_half_total_runs", "Under", selection_line="under", points=_TOTAL_LINE),
        # 1st_half_moneyline_3-way -> f5_moneyline_3way (Draw carries team_id=None)
        _odd("1st_half_moneyline_3-way", _HOME_NAME, team_id="T_AZ"),
        _odd("1st_half_moneyline_3-way", _AWAY_NAME, team_id="T_STL"),
        _odd("1st_half_moneyline_3-way", "Draw"),
    ]
    fixture = optic.Fixture(
        fixture_id="FIX1", game_id="GAME1", sportradar_id=None,
        start_et="2026-07-21T19:00:00", start_date=_START,
        home=_HOME, away=_AWAY, home_name=_HOME_NAME, away_name=_AWAY_NAME,
        team_map=_TEAM_MAP, odds=odds, is_live=False,
    )
    rows, _, _ = optic.build_rows(_START, _HOME, _AWAY, fixture,
                                  _mlb_cfg().OPTIC, league="mlb")
    return rows


def _poly(condition_id: str, slug: str, question: str, labels: list[str]):
    return pm.PolyMarket(
        condition_id=condition_id, slug=slug, question=question,
        outcomes=[pm.PolyOutcome(clob_token_id=f"c{i}", position_id=f"p{i}",
                                 outcome_label=lab, outcome_index=i)
                  for i, lab in enumerate(labels)])


def _attach(market: pm.PolyMarket, index) -> list[str]:
    """Parse + build + attach a poly market against an optic-built index."""
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None, market.question
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    rows = pm.build_rows(market, parsed, home=_HOME, away=_AWAY,
                         home_name=_HOME_NAME, away_name=_AWAY_NAME,
                         start_date=_START, cfg=cfg, league="mlb")
    assert rows, market.question
    return [attach_polymarket_row(index, r) for r in rows]


def test_optic_emits_all_three_f5_markets():
    """Guard the premise: _mlb_cfg().OPTIC really does turn the three "1st_half_*"
    market ids into F5 rows (and the Draw into the _TIE side)."""
    rows = _optic_f5_rows()
    by_type = {}
    for r in rows:
        by_type.setdefault(r.market_type, []).append(r)
    assert set(by_type) == {"f5_point_spread", "f5_total", "f5_moneyline_3way"}
    assert {r.side for r in by_type["f5_point_spread"]} == {_HOME, _AWAY}
    assert {r.side for r in by_type["f5_total"]} == {"over", "under"}
    assert {r.side for r in by_type["f5_moneyline_3way"]} == {_HOME, _AWAY, "_TIE"}
    # signed spread: the favourite keeps the negative line, the dog the positive
    signed = {r.side: r.line for r in by_type["f5_point_spread"]}
    assert signed == {_HOME: _SPREAD_LINE, _AWAY: -_SPREAD_LINE}


def test_poly_f5_total_collides_with_optic_row():
    index = {row_key(r): r for r in _optic_f5_rows()}
    results = _attach(_poly(
        "0xT", "mlb-az-stl-2026-07-21-f5-total-4pt5",
        f"{_HOME_NAME} vs. {_AWAY_NAME}: 1st 5 Innings O/U {_TOTAL_LINE}",
        ["Over", "Under"]), index)
    # BOTH sides find an optic row -- nothing dropped
    assert results == ["stamped", "stamped"], results


def test_poly_f5_spread_collides_with_optic_row():
    index = {row_key(r): r for r in _optic_f5_rows()}
    results = _attach(_poly(
        "0xS", "mlb-az-stl-2026-07-21-f5-spread-home-1pt5",
        f"1st 5 Innings Spread: {_HOME_NAME} ({_SPREAD_LINE})",
        [_HOME_NAME, _AWAY_NAME]), index)
    assert results == ["stamped", "stamped"], results


def test_poly_f5_three_way_legs_collide_with_optic_rows():
    """Both poly legs land on the one optic 3-way market: the team leg on the
    team side, the "Tied after 5" leg on _TIE."""
    index = {row_key(r): r for r in _optic_f5_rows()}
    team_leg = _poly("0xW", "mlb-az-stl-2026-07-21-first-five-winner-home",
                     f"{_HOME_NAME} winning after 5 innings?", ["Yes", "No"])
    draw_leg = _poly("0xD", "mlb-az-stl-2026-07-21-first-five-winner-draw",
                     f"{_HOME_NAME} vs. {_AWAY_NAME}: Tied after 5 innings?",
                     ["Yes", "No"])
    assert _attach(team_leg, index) == ["stamped"]
    assert _attach(draw_leg, index) == ["stamped"]

    stamped = {r.side: r.polymarket_condition_id for r in index.values()
               if r.market_type == "f5_moneyline_3way"}
    assert stamped[_HOME] == "0xW"
    assert stamped["_TIE"] == "0xD"
    # the away side has no poly leg in this test -> untouched, not mis-stamped
    assert stamped[_AWAY] is None


def test_poly_f5_total_does_not_collide_at_the_wrong_line():
    """A line optic did not price finds no row and drops -- the merge is keyed
    on the line, so a 5.5 poly total cannot land on the 4.5 optic row."""
    index = {row_key(r): r for r in _optic_f5_rows()}
    results = _attach(_poly(
        "0xT2", "mlb-az-stl-2026-07-21-f5-total-5pt5",
        f"{_HOME_NAME} vs. {_AWAY_NAME}: 1st 5 Innings O/U 5.5",
        ["Over", "Under"]), index)
    assert set(results) == {"dropped_no_optic"}, results


def test_poly_f5_rows_do_not_collide_with_full_game_rows():
    """The F5 rows must be distinct from the full-game ones at the same line:
    a poly F5 total must not stamp a full-game total row, and vice versa.
    """
    full_over = optic.CanonicalRow(
        league="mlb", start_date=_START, home=_HOME, away=_AWAY,
        market_type="game_total", line=_TOTAL_LINE, side="over", optic_id="G_O")
    full_under = optic.CanonicalRow(
        league="mlb", start_date=_START, home=_HOME, away=_AWAY,
        market_type="game_total", line=_TOTAL_LINE, side="under", optic_id="G_U")
    index = {row_key(full_over): full_over, row_key(full_under): full_under}
    results = _attach(_poly(
        "0xT3", "mlb-az-stl-2026-07-21-f5-total-4pt5",
        f"{_HOME_NAME} vs. {_AWAY_NAME}: 1st 5 Innings O/U {_TOTAL_LINE}",
        ["Over", "Under"]), index)
    assert set(results) == {"dropped_no_optic"}, results
    assert index[row_key(full_over)].polymarket_condition_id is None

import dataclasses

from mappers.exchanges import polymarket as pm
from mappers.pipeline import _match_poly_fixture, attach_polymarket_row, row_key
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.shared import CanonicalRow


def _mlb_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "mlb")
    return build_tip_league(row)


def _mlb_poly():
    poly = _mlb_cfg().POLYMARKET
    assert poly is not None
    return poly


def test_mlb_polymarket_config_present():
    poly = _mlb_poly()
    assert poly.slug_prefix == "mlb"
    assert poly.market_types["total"].value == "game_total"


class _FX:
    home, away = "AZ", "STL"
    home_name, away_name = "Arizona Diamondbacks", "St. Louis Cardinals"
    start_date = "2026-07-21T23:00:00Z"


def test_mlb_total_end_to_end_stamps_optic_row():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    # optic already priced the total -> row exists in the index
    optic_over = CanonicalRow(league="mlb", start_date=_FX.start_date, home="AZ",
                              away="STL", market_type="game_total", line=8.5,
                              side="over", optic_id="OPT_OVER")
    index = {row_key(optic_over): optic_over}

    market = pm.PolyMarket(condition_id="0xB", slug="mlb-az-stl-2026-07-21",
        question="Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5",
        outcomes=[pm.PolyOutcome(clob_token_id="cO", position_id="pO",
                                 outcome_label="Over", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="cU", position_id="pU",
                                 outcome_label="Under", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    fx = _match_poly_fixture(parsed, [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    # over stamps onto the optic row; under has no optic row -> dropped (guard #3)
    assert "stamped" in results and "dropped_no_optic" in results
    assert index[row_key(optic_over)].polymarket_clob_token_id == "cO"


def _optic_row(market_type, side, *, line=None, entity=None, optic_id="OPT"):
    return CanonicalRow(league="mlb", start_date=_FX.start_date, home="AZ", away="STL",
                        market_type=market_type, line=line, entity=entity, side=side,
                        optic_id=optic_id)


def test_mlb_spread_end_to_end_stamps_optic_run_line():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    # optic priced the run_line (POINT_SPREAD): AZ -1.5 / STL +1.5
    az = _optic_row("point_spread", "AZ", line=-1.5, optic_id="RL_AZ")
    stl = _optic_row("point_spread", "STL", line=1.5, optic_id="RL_STL")
    index = {row_key(az): az, row_key(stl): stl}
    market = pm.PolyMarket(condition_id="0xS", slug="mlb-az-stl-2026-07-21",
        question="Spread: Arizona Diamondbacks (-1.5)",
        outcomes=[pm.PolyOutcome(clob_token_id="sA", position_id="pA",
                                 outcome_label="Arizona Diamondbacks", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="sB", position_id="pB",
                                 outcome_label="St. Louis Cardinals", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    # spread resolves the fixture from the two outcome LABELS, not the question team
    fx = _match_poly_fixture(
        dataclasses.replace(parsed, team_a="arizona diamondbacks", team_b="st louis cardinals"),
        [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    assert results.count("stamped") == 2
    assert index[row_key(az)].polymarket_clob_token_id == "sA"
    assert index[row_key(stl)].polymarket_clob_token_id == "sB"


def test_mlb_first_inning_end_to_end_stamps_optic_row():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    # optic priced 1st_inning_total_runs @ 0.5 (over/under)
    over = _optic_row("first_inning_total", "over", line=0.5, optic_id="FI_O")
    index = {row_key(over): over}
    market = pm.PolyMarket(condition_id="0xF", slug="mlb-az-stl-2026-07-21",
        question=("Will there be a run scored in the first inning?: "
                  "Arizona Diamondbacks vs. St. Louis Cardinals"),
        outcomes=[pm.PolyOutcome(clob_token_id="fY", position_id="pY",
                                 outcome_label="Yes", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="fN", position_id="pN",
                                 outcome_label="No", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    fx = _match_poly_fixture(parsed, [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    # Yes->over stamps; No->under has no optic row -> dropped (guard #3)
    assert "stamped" in results and "dropped_no_optic" in results
    assert index[row_key(over)].polymarket_clob_token_id == "fY"


def test_mlb_home_runs_end_to_end_stamps_optic_player_row():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    # optic priced player_home_runs for Corbin Carroll @ 0.5 over
    opt = _optic_row("player_home_runs", "over", line=0.5, entity="corbin_carroll",
                     optic_id="HR_O")
    index = {row_key(opt): opt}
    market = pm.PolyMarket(condition_id="0xH", slug="mlb-az-stl-2026-07-21-hr-corbin-carroll-05",
        question="Corbin Carroll: Home Runs O/U 0.5",
        outcomes=[pm.PolyOutcome(clob_token_id="hO", position_id="pO",
                                 outcome_label="Over", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="hU", position_id="pU",
                                 outcome_label="Under", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    # player props resolve start_date/home/away from the fixture (via slug key
    # in the pipeline); here we build directly on the fixture.
    rows = pm.build_rows(market, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date=_FX.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    assert "stamped" in results and "dropped_no_optic" in results
    assert index[row_key(opt)].polymarket_clob_token_id == "hO"


def test_mlb_home_runs_wrong_player_does_not_stamp():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    # optic priced HR for a DIFFERENT player -> poly Aaron Judge prop finds no row
    opt = _optic_row("player_home_runs", "over", line=0.5, entity="corbin_carroll",
                     optic_id="HR_O")
    index = {row_key(opt): opt}
    market = pm.PolyMarket(condition_id="0xH2", slug="mlb-az-stl-2026-07-21-hr-aaron-judge-05",
        question="Aaron Judge: Home Runs O/U 0.5",
        outcomes=[pm.PolyOutcome(clob_token_id="hO", position_id="pO",
                                 outcome_label="Over", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="hU", position_id="pU",
                                 outcome_label="Under", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    rows = pm.build_rows(market, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date=_FX.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    # wrong-player entity => no matching optic row => both sides dropped
    assert "stamped" not in results
    assert index[row_key(opt)].polymarket_clob_token_id is None


def test_mlb_spread_wrong_team_label_drops_market():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    # an outcome label that is neither fixture team -> build_rows drops whole market
    market = pm.PolyMarket(condition_id="0xS2", slug="mlb-az-stl-2026-07-21",
        question="Spread: Arizona Diamondbacks (-1.5)",
        outcomes=[pm.PolyOutcome(clob_token_id="sA", position_id="pA",
                                 outcome_label="Arizona Diamondbacks", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="sX", position_id="pX",
                                 outcome_label="Chicago Cubs", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    rows = pm.build_rows(market, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date=_FX.start_date, cfg=cfg, league="mlb")
    assert rows == []  # flip-unsafe: a label resolves to no fixture side -> drop whole


# === F5 (1st-5-innings) end-to-end ===
#
# The poly half of the "1st_half_*" optic family wired in the
# baseball-first5-spreadstotals branch. Questions/slugs are byte-exact from the
# poly bridge (prod census 2026-08-04). NB no optic MLB "1st_half_*" tick exists
# yet (the three market ids are still being added to MMOpticOdds sport_subs), so
# in production every one of these rows currently drops as dropped_no_optic --
# these tests pre-seed the optic row the subscription will produce, which is
# exactly what they are for.


def test_mlb_f5_total_end_to_end_stamps_optic_row():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    over = _optic_row("f5_total", "over", line=4.5, optic_id="F5T_O")
    index = {row_key(over): over}
    market = pm.PolyMarket(condition_id="0xF5T", slug="mlb-az-stl-2026-07-21-f5-total-4pt5",
        question="Arizona Diamondbacks vs. St. Louis Cardinals: 1st 5 Innings O/U 4.5",
        outcomes=[pm.PolyOutcome(clob_token_id="tO", position_id="pO",
                                 outcome_label="Over", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="tU", position_id="pU",
                                 outcome_label="Under", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    fx = _match_poly_fixture(parsed, [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    assert "stamped" in results and "dropped_no_optic" in results
    assert index[row_key(over)].polymarket_clob_token_id == "tO"
    # and it must NOT have landed on the full-game total
    assert all(r.market_type == "f5_total" for r in rows)


def test_mlb_f5_spread_end_to_end_stamps_optic_row():
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    az = _optic_row("f5_point_spread", "AZ", line=-1.5, optic_id="F5RL_AZ")
    stl = _optic_row("f5_point_spread", "STL", line=1.5, optic_id="F5RL_STL")
    index = {row_key(az): az, row_key(stl): stl}
    market = pm.PolyMarket(condition_id="0xF5S",
        slug="mlb-az-stl-2026-07-21-f5-spread-home-1pt5",
        question="1st 5 Innings Spread: Arizona Diamondbacks (-1.5)",
        outcomes=[pm.PolyOutcome(clob_token_id="sA", position_id="pA",
                                 outcome_label="Arizona Diamondbacks", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="sB", position_id="pB",
                                 outcome_label="St. Louis Cardinals", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    # like the full-game spread, the fixture comes from the two outcome LABELS
    fx = _match_poly_fixture(
        dataclasses.replace(parsed, team_a="arizona diamondbacks", team_b="st louis cardinals"),
        [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    assert results.count("stamped") == 2
    # the named team keeps its signed line, the other is negated
    assert index[row_key(az)].polymarket_clob_token_id == "sA"
    assert index[row_key(stl)].polymarket_clob_token_id == "sB"


def test_mlb_f5_three_way_legs_stamp_the_same_optic_market():
    """Both poly legs -- "<Team> winning after 5 innings?" and "<A> vs. <B>:
    Tied after 5 innings?" -- land on the one 3-way optic market, on the team
    side and the _TIE side respectively.
    """
    cfg = _mlb_cfg().POLYMARKET
    assert cfg is not None
    az = _optic_row("f5_moneyline_3way", "AZ", optic_id="F5ML_AZ")
    tie = _optic_row("f5_moneyline_3way", "_TIE", optic_id="F5ML_TIE")
    index = {row_key(az): az, row_key(tie): tie}

    team_leg = pm.PolyMarket(condition_id="0xF5W",
        slug="mlb-az-stl-2026-07-21-first-five-winner-home",
        question="Arizona Diamondbacks winning after 5 innings?",
        outcomes=[pm.PolyOutcome(clob_token_id="wY", position_id="pY",
                                 outcome_label="Yes", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="wN", position_id="pN",
                                 outcome_label="No", outcome_index=1)])
    draw_leg = pm.PolyMarket(condition_id="0xF5D",
        slug="mlb-az-stl-2026-07-21-first-five-winner-draw",
        question="Arizona Diamondbacks vs. St. Louis Cardinals: Tied after 5 innings?",
        outcomes=[pm.PolyOutcome(clob_token_id="dY", position_id="pY2",
                                 outcome_label="Yes", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="dN", position_id="pN2",
                                 outcome_label="No", outcome_index=1)])

    for market in (team_leg, draw_leg):
        parsed = pm.parse_question(market.question, cfg)
        assert parsed is not None, market.question
        parsed = dataclasses.replace(parsed, date="2026-07-21")
        rows = pm.build_rows(market, parsed, home="AZ", away="STL",
                             home_name="Arizona Diamondbacks",
                             away_name="St. Louis Cardinals",
                             start_date=_FX.start_date, cfg=cfg, league="mlb")
        # THREE_WAY_FIXED emits ONE row (the affirmative "Yes"); "No" is dropped
        assert len(rows) == 1, market.question
        assert attach_polymarket_row(index, rows[0]) == "stamped", market.question

    assert index[row_key(az)].polymarket_clob_token_id == "wY"
    assert index[row_key(tie)].polymarket_clob_token_id == "dY"


def test_mlb_f5_winner_leg_slug_key_matches_the_game_slug():
    """The single-team F5 winner leg carries no second team, so it resolves in
    Phase B off the slug head -- which must equal the game slug's head.
    """
    from mappers.pipeline import _poly_slug_teams
    assert (_poly_slug_teams("mlb-az-stl-2026-07-21-first-five-winner-home")
            == _poly_slug_teams("mlb-az-stl-2026-07-21"))

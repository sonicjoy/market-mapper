from typing import Any

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType
from mappers.pipeline import canonical_row_to_json
from mappers.shared import TIE_SIDE, CanonicalRow, normalize_player_name


def _row(**kw):
    base: dict[str, Any] = {"league": "mlb", "start_date": "2026-07-21T23:00:00Z",
             "home": "AZ", "away": "STL", "market_type": "moneyline", "side": "AZ"}
    base.update(kw)
    return CanonicalRow(**base)


def test_canonical_row_has_polymarket_stamp_fields():
    r = _row(polymarket_clob_token_id="cX", polymarket_condition_id="0xabc",
             polymarket_position_id="pX", polymarket_slug="mlb-az-stl-2026-07-21",
             polymarket_question="Arizona Diamondbacks vs. St. Louis Cardinals")
    assert r.polymarket_clob_token_id == "cX"
    assert r.polymarket_position_id == "pX"


def test_canonical_row_to_json_emits_polymarket_block():
    r = _row(polymarket_clob_token_id="cX", polymarket_condition_id="0xabc",
             polymarket_position_id="pX", polymarket_slug="s", polymarket_question="q")
    j = canonical_row_to_json(r, {}, {})
    assert j["polymarket"] == {
        "clob_token_id": "cX", "condition_id": "0xabc",
        "position_id": "pX", "slug": "s", "question": "q",
    }


def test_canonical_row_to_json_polymarket_none_when_absent():
    j = canonical_row_to_json(_row(), {}, {})
    assert j["polymarket"] is None


MLB_CFG = pm.PolymarketConfig(
    slug_prefix="mlb",
    optic_league_id="mlb",
    market_types={"moneyline": MarketType.MONEYLINE, "total": MarketType.GAME_TOTAL},
    market_rules=(pm.mlb_total_rule, pm.mlb_moneyline_rule),
)


def test_parse_question_moneyline():
    out = pm.parse_question("Arizona Diamondbacks vs. St. Louis Cardinals", MLB_CFG)
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == "arizona diamondbacks"
    assert out.team_b == "st louis cardinals"
    assert out.line is None


def test_parse_question_total():
    out = pm.parse_question("Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5", MLB_CFG)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.line == 8.5


def test_parse_question_unknown_returns_none():
    assert pm.parse_question("Alec Burleson: Home Runs O/U 0.5", MLB_CFG) is None
    assert pm.parse_question("1st 5 Innings Spread: Arizona Diamondbacks (-1.5)", MLB_CFG) is None
    # vs.-phrased spread: falls through the total regex (no "o/u"), then
    # the bare-":" guard drops it before it can be mis-parsed as moneyline.
    assert pm.parse_question("Arizona Diamondbacks vs. St. Louis Cardinals: -1.5", MLB_CFG) is None


def test_parse_market_builds_model():
    import json
    line = json.dumps({
        "condition_id": "0xabc", "slug": "mlb-az-stl-2026-07-21",
        "question": "Arizona Diamondbacks vs. St. Louis Cardinals",
        "outcomes": [
            {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
            {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
        ],
    })
    m = pm.parse_market(line)
    assert m is not None
    assert m.condition_id == "0xabc" and len(m.outcomes) == 2
    assert m.outcomes[0].outcome_label == "Arizona Diamondbacks"


def _mkt(question, outcomes):
    return pm.PolyMarket(condition_id="0xabc", slug="mlb-az-stl-2026-07-21",
                         question=question,
                         outcomes=[pm.PolyOutcome(**o) for o in outcomes])


def test_build_rows_moneyline_binds_side_to_label():
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    assert parsed is not None
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    # side is the team the LABEL names, not the array position
    assert by_tok["cA"].side == "AZ" and by_tok["cA"].market_type == "moneyline"
    assert by_tok["cB"].side == "STL"
    assert by_tok["cA"].line is None


def test_build_rows_total_over_under():
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    assert parsed is not None
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cO"].side == "over" and by_tok["cO"].line == 8.5
    assert by_tok["cU"].side == "under" and by_tok["cU"].market_type == "game_total"


def test_build_rows_drops_market_when_labels_not_complementary():
    # both labels resolve to the same team -> not a valid two-sided market -> drop all
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Arizona Diamondbacks", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    assert parsed is not None
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    assert rows == []


def test_build_rows_moneyline_reversed_array_order_binds_by_label():
    # away-team label at index 0, home-team label at index 1 -> side must
    # still track the LABEL, not the array position.
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 0},
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    assert parsed is not None
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cA"].side == "AZ" and by_tok["cB"].side == "STL"


def test_build_rows_drops_market_with_three_outcomes():
    # 3 outcomes with a duplicated label pass the set-of-sides check
    # ({home, away}) but must still be dropped -- outcome count must be 2.
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cA1", "position_id": "pA1", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cA2", "position_id": "pA2", "outcome_label": "Arizona Diamondbacks", "outcome_index": 1},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 2},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    assert parsed is not None
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    assert rows == []


TENNIS_CFG = pm.PolymarketConfig(
    slug_prefix="atp", optic_league_id="atp",
    market_types={"moneyline": MarketType.MONEYLINE},
    question_style="tennis_prefix",
    market_rules=(pm.tennis_moneyline_rule,),
)


def test_parse_question_tennis_match_winner():
    out = pm.parse_question("Bloomfield Hills: Alex Michelsen vs Aidan Mayo", TENNIS_CFG)
    assert out is not None
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == pm._norm_name("Alex Michelsen", "tennis_prefix")
    assert out.team_b == pm._norm_name("Aidan Mayo", "tennis_prefix")


def test_parse_question_tennis_strips_multicolon_and_periods():
    out = pm.parse_question("ATP 250: Bloomfield Hills: J.J. Wolf vs Coleman Wong", TENNIS_CFG)
    assert out is not None
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == pm._norm_name("J.J. Wolf", "tennis_prefix")  # -> "jj_wolf"


def test_parse_question_tennis_rejects_totals_doubles_completed():
    for q in ["Added vs. Bax: Match O/U 21.5",
              "Adolfo Vallejo vs Kilian Feldbausch: Total Sets O/U 2.5",
              "Bloomfield Hills: Lammons/Withrow vs Galarneau/Tomic",
              "Completed Match: Oskari Paldanius vs Franco Roncadelli"]:
        assert pm.parse_question(q, TENNIS_CFG) is None


def test_name_match_tennis_exact_not_containment():
    # containment would wrongly equate "Rune" with "Holger Rune"; exact must not
    assert pm._name_match(pm._norm_name("Holger Rune", "tennis_prefix"),
                          pm._norm_name("Holger Rune", "tennis_prefix"), "tennis_prefix")
    assert not pm._name_match(pm._norm_name("Rune", "tennis_prefix"),
                              pm._norm_name("Holger Rune", "tennis_prefix"), "tennis_prefix")


def test_name_match_tennis_reverse_given_family():
    style = "tennis_prefix"
    assert pm._name_match(
        pm._norm_name("Lorenzo Lorusso", style),
        pm._norm_name("Lorusso Lorenzo", style),
        style,
    )
    assert not pm._name_match(
        pm._norm_name("Omar Kandil", style),
        pm._norm_name("Lorusso Lorenzo", style),
        style,
    )


def test_mlb_style_unchanged_containment():
    # mlb_suffix keeps containment behavior
    assert pm._name_match("arizona diamondbacks", "arizona diamondbacks", "mlb_suffix")
    assert pm._name_match("arizona", "arizona diamondbacks", "mlb_suffix")  # containment ok for teams


def test_parse_question_tennis_rejects_prefix_descriptor_set_markets():
    # descriptor in the PREFIX position, plain player names after the last colon
    for q in ["Set 1 Winner: Alex Michelsen vs Aidan Mayo",
              "1st Set: Alex Michelsen vs Aidan Mayo",
              "Total Games: Alex Michelsen vs Aidan Mayo"]:
        assert pm.parse_question(q, TENNIS_CFG) is None


def test_parse_question_tennis_still_parses_plain_match_winner():
    # regression: a normal tournament-prefixed match-winner must still parse
    out = pm.parse_question("ATP 250: Bloomfield Hills: J.J. Wolf vs Coleman Wong", TENNIS_CFG)
    assert out is not None and out.side_mode == pm.SideMode.TEAM_LABEL


# === (Scope, SideMode) build_rows dispatch — one test per SideMode, driving
#     build_rows directly with a hand-built ParsedMarket. Side is ALWAYS bound
#     to the outcome label or the entity named in the question, never an index. ===


def _bt(**kw):
    """build_rows with the common MLB fixture kwargs; caller passes market+parsed."""
    base = {"home": "AZ", "away": "STL", "home_name": "Arizona Diamondbacks",
            "away_name": "St. Louis Cardinals", "start_date": "2026-07-21T23:00:00Z",
            "cfg": MLB_CFG, "league": "mlb"}
    base.update(kw)
    return pm.build_rows(**base)


def test_build_rows_team_label_binds_side_to_outcome_label():
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.TEAM_LABEL)
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cA"].side == "AZ" and by["cA"].market_type == "moneyline"
    assert by["cA"].entity is None and by["cA"].line is None
    assert by["cB"].side == "STL"


def test_build_rows_spread_team_signs_named_and_negates_other():
    m = _mkt("Arizona Diamondbacks -1.5 vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
    ])
    # entity names the team carrying the signed line; the other side is negated.
    parsed = pm.ParsedMarket(market_type=MarketType.POINT_SPREAD,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.SPREAD_TEAM,
                             entity="arizona diamondbacks", line=-1.5)
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cA"].side == "AZ" and by["cA"].line == -1.5
    assert by["cB"].side == "STL" and by["cB"].line == 1.5
    assert by["cA"].market_type == "point_spread" and by["cA"].entity is None


def test_build_rows_spread_team_drops_when_named_team_absent():
    m = _mkt("Somebody Else -1.5 vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.POINT_SPREAD,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.SPREAD_TEAM,
                             entity="somebody else", line=-1.5)
    assert _bt(market=m, parsed=parsed) == []


def test_build_rows_over_under_player_entity():
    m = _mkt("Aaron Judge: Home Runs O/U 0.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.PLAYER_HOME_RUNS,
                             team_a=None, team_b=None,
                             side_mode=pm.SideMode.OVER_UNDER,
                             entity="aaron_judge", line=0.5)
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cO"].side == "over" and by["cO"].entity == "aaron_judge" and by["cO"].line == 0.5
    assert by["cU"].side == "under" and by["cU"].market_type == "player_home_runs"


def test_build_rows_over_under_drops_on_bad_arity():
    m = _mkt("Aaron Judge: Home Runs O/U 0.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over", "outcome_index": 0},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.PLAYER_HOME_RUNS,
                             team_a=None, team_b=None,
                             side_mode=pm.SideMode.OVER_UNDER,
                             entity="aaron_judge", line=0.5)
    assert _bt(market=m, parsed=parsed) == []


def test_build_rows_yesno_as_ou_maps_yes_to_over_no_to_under():
    m = _mkt("Aaron Judge: 2+ Hits", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.PLAYER_HITS,
                             team_a=None, team_b=None,
                             side_mode=pm.SideMode.YESNO_AS_OU,
                             entity="aaron_judge", line=1.5)
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cY"].side == "over" and by["cY"].line == 1.5 and by["cY"].entity == "aaron_judge"
    assert by["cN"].side == "under" and by["cN"].market_type == "player_hits"


def test_build_rows_yesno_btts_game_scope():
    m = _mkt("Both Teams To Score", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.BTTS,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.YESNO)
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cY"].side == "yes" and by["cY"].entity is None and by["cY"].line is None
    assert by["cN"].side == "no" and by["cN"].market_type == "btts"


def test_build_rows_yesno_drops_on_non_yesno_labels():
    m = _mkt("Both Teams To Score", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cM", "position_id": "pM", "outcome_label": "Maybe", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.BTTS,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.YESNO)
    assert _bt(market=m, parsed=parsed) == []


def test_build_rows_three_way_fixed_emits_single_team_row():
    m = _mkt("Will the Diamondbacks win in 90 minutes?", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE_3WAY,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.THREE_WAY_FIXED,
                             fixed_side_team="arizona diamondbacks")
    rows = _bt(market=m, parsed=parsed)
    assert len(rows) == 1  # only the affirmative outcome emits; the other is dropped
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == "AZ" and rows[0].market_type == "moneyline_3way"
    assert rows[0].line is None and rows[0].entity is None


def test_build_rows_three_way_fixed_tie_side_when_no_team():
    m = _mkt("Will the match end in a draw?", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE_3WAY,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.THREE_WAY_FIXED,
                             fixed_side_team=None)
    rows = _bt(market=m, parsed=parsed)
    assert len(rows) == 1 and rows[0].side == TIE_SIDE
    assert rows[0].polymarket_clob_token_id == "cY"


def test_build_rows_three_way_fixed_drops_when_named_team_absent():
    m = _mkt("Will Somebody Else win in 90 minutes?", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE_3WAY,
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.THREE_WAY_FIXED,
                             fixed_side_team="somebody else")
    assert _bt(market=m, parsed=parsed) == []


def test_build_rows_three_way_fixed_requires_three_way_shape():
    # a non-THREE_WAY market_type paired with THREE_WAY_FIXED must drop whole.
    m = _mkt("Will the Diamondbacks win in 90 minutes?", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE,  # Shape.MONEYLINE, not THREE_WAY
                             team_a="arizona diamondbacks", team_b="st louis cardinals",
                             side_mode=pm.SideMode.THREE_WAY_FIXED,
                             fixed_side_team="arizona diamondbacks")
    assert _bt(market=m, parsed=parsed) == []


# === Task 3: MLB full-taxonomy rules (R1 HR, R2 K, R3 spread, R4 first-inning) ===
#     Real probe strings from .superpowers/sdd/task-3-probe-findings.md.

MLB_FULL_CFG = pm.PolymarketConfig(
    slug_prefix="mlb", optic_league_id="mlb",
    market_types={
        "moneyline": MarketType.MONEYLINE,
        "total": MarketType.GAME_TOTAL,
        "spread": MarketType.POINT_SPREAD,
        "first_inning": MarketType.FIRST_INNING_TOTAL,
        "home_runs": MarketType.PLAYER_HOME_RUNS,
        "strikeouts": MarketType.PLAYER_STRIKEOUTS,
        "extra_innings": MarketType.EXTRA_INNINGS,
        "f5_total": MarketType.FIRST_FIVE_TOTAL,
        "f5_spread": MarketType.FIRST_FIVE_POINT_SPREAD,
        "f5_moneyline_3way": MarketType.FIRST_FIVE_MONEYLINE_3WAY,
    },
    # exact-prefix + prop rules before the bare-"A vs B" moneyline catch-all;
    # total first (moneyline drops any ":"). Mirrors mlb.LEAGUE.POLYMARKET's
    # market_rules order, F5 rules included.
    market_rules=(pm.mlb_f5_total_rule, pm.mlb_f5_spread_rule,
                  pm.mlb_f5_winner_rule, pm.mlb_f5_tied_rule,
                  pm.mlb_total_rule, pm.mlb_first_inning_rule,
                  pm.mlb_extra_innings_rule, pm.mlb_spread_rule,
                  pm.mlb_home_runs_rule, pm.mlb_strikeouts_rule, pm.mlb_moneyline_rule),
)


def test_parse_home_runs_prop():
    out = pm.parse_question("Aaron Judge: Home Runs O/U 0.5", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_HOME_RUNS
    assert out.side_mode == pm.SideMode.OVER_UNDER
    # entity must equal the optic PLAYER entity (normalize_player_name), not the
    # mlb_suffix team normalizer — else the merge key never matches optic.
    assert out.entity == normalize_player_name("Aaron Judge") == "aaron_judge"
    assert out.line == 0.5
    assert out.team_a is None and out.team_b is None


def test_parse_home_runs_prop_line_1_5_and_jr_suffix():
    out = pm.parse_question("Fernando Tatis Jr.: Home Runs O/U 1.5", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_HOME_RUNS
    assert out.entity == normalize_player_name("Fernando Tatis Jr.") == "fernando_tatis"
    assert out.line == 1.5


def test_parse_strikeouts_prop():
    out = pm.parse_question("Tarik Skubal: Strikeouts O/U 6.5", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_STRIKEOUTS
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.entity == normalize_player_name("Tarik Skubal")
    assert out.line == 6.5


def test_parse_spread_negative_line():
    out = pm.parse_question("Spread: Arizona Diamondbacks (-1.5)", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.POINT_SPREAD
    assert out.side_mode == pm.SideMode.SPREAD_TEAM
    # the question-named team goes in entity; build_rows binds its signed line
    assert out.entity == pm._norm_name("Arizona Diamondbacks", "mlb_suffix")
    assert out.line == -1.5
    assert out.team_a is None and out.team_b is None


def test_parse_spread_positive_line():
    out = pm.parse_question("Spread: St. Louis Cardinals (+1.5)", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.POINT_SPREAD
    assert out.entity == pm._norm_name("St. Louis Cardinals", "mlb_suffix")
    assert out.line == 1.5


def test_parse_first_inning_run():
    out = pm.parse_question(
        "Will there be a run scored in the first inning?: "
        "Arizona Diamondbacks vs. St. Louis Cardinals", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_INNING_TOTAL
    assert out.side_mode == pm.SideMode.YESNO_AS_OU
    assert out.line == 0.5
    assert out.entity is None
    assert out.team_a == pm._norm_name("Arizona Diamondbacks", "mlb_suffix")
    assert out.team_b == pm._norm_name("St. Louis Cardinals", "mlb_suffix")


def test_parse_rejects_unmappable_forms():
    # futures / games-total are noise; the bare tied-after form carries no
    # fixture at all.
    for q in [
        # no "<A> vs. <B>" head -> no fixture to resolve, so it cannot become an
        # F5 draw leg (mlb_f5_tied_rule requires both teams). The live shape does
        # carry the head and IS mapped -- see test_parse_f5_tied_leg.
        "Tied after 5 innings?",
        # N is not 5 -> NOT a 1st-5-innings market. Both F5 3-way legs anchor on
        # a literal 5 so a different N drops rather than mis-stamping onto F5.
        "Arizona Diamondbacks winning after 7 innings?",
        "Arizona Diamondbacks vs. St. Louis Cardinals: Tied after 7 innings?",
        "Games Total: O/U 5.5",
        "American League",
    ]:
        assert pm.parse_question(q, MLB_FULL_CFG) is None, q


# === F5 (1st-5-innings): the poly half of optic's "1st_half_*" family ===
#
# All four question forms are byte-exact from the poly bridge (prod, 14d census
# 2026-08-04). Each asserts the shape the pipeline depends on, not just that it
# parses.


def test_parse_f5_total():
    out = pm.parse_question(
        "Arizona Diamondbacks vs. St. Louis Cardinals: 1st 5 Innings O/U 4.5",
        MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_FIVE_TOTAL
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.line == 4.5
    assert out.team_a == pm._norm_name("Arizona Diamondbacks", "mlb_suffix")
    assert out.team_b == pm._norm_name("St. Louis Cardinals", "mlb_suffix")


def test_parse_f5_total_does_not_take_full_game_total():
    # the two totals must not cross: neither pattern can match the other's form
    out = pm.parse_question(
        "Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL


def test_parse_f5_spread():
    out = pm.parse_question("1st 5 Innings Spread: Arizona Diamondbacks (-1.5)",
                            MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_FIVE_POINT_SPREAD
    assert out.side_mode == pm.SideMode.SPREAD_TEAM
    assert out.entity == pm._norm_name("Arizona Diamondbacks", "mlb_suffix")
    assert out.line == -1.5


def test_parse_f5_spread_does_not_take_full_game_spread():
    out = pm.parse_question("Spread: Arizona Diamondbacks (-1.5)", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.POINT_SPREAD


def test_parse_f5_winner_leg():
    # single team named -> team_b None so the pipeline defers to Phase B
    out = pm.parse_question("Arizona Diamondbacks winning after 5 innings?",
                            MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_FIVE_MONEYLINE_3WAY
    assert out.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert out.fixed_side_team == pm._norm_name("Arizona Diamondbacks", "mlb_suffix")
    assert out.team_b is None
    assert out.line is None


def test_parse_f5_tied_leg():
    # the draw leg of the SAME 3-way market; fixed_side_team None -> _TIE
    out = pm.parse_question(
        "Minnesota Twins vs. Cleveland Guardians: Tied after 5 innings?",
        MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_FIVE_MONEYLINE_3WAY
    assert out.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert out.fixed_side_team is None
    assert out.team_a == pm._norm_name("Minnesota Twins", "mlb_suffix")
    assert out.team_b == pm._norm_name("Cleveland Guardians", "mlb_suffix")


def test_parse_extra_innings_not_taken_by_f5_tied_rule():
    # "goes to extra innings" is a different bet from "tied after 5" -- the F5
    # rules must not swallow it
    out = pm.parse_question(
        "Will the game go to extra innings?: "
        "Arizona Diamondbacks vs. St. Louis Cardinals", MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.EXTRA_INNINGS


def test_parse_f5_forms_drop_when_league_omits_the_kind():
    # a league config without the F5 kinds drops them (config is the source of
    # truth) -- MLB_CFG declares only moneyline/total
    for q in [
        "1st 5 Innings Spread: Arizona Diamondbacks (-1.5)",
        "Arizona Diamondbacks vs. St. Louis Cardinals: 1st 5 Innings O/U 4.5",
    ]:
        assert pm.parse_question(q, MLB_CFG) is None, q


# === Extra innings (poly half of optic's will_there_be_extra_innings) ===

_EXTRA_Q = ("Will the game go to extra innings?: "
            "Arizona Diamondbacks vs. St. Louis Cardinals")


def test_parse_extra_innings():
    out = pm.parse_question(_EXTRA_Q, MLB_FULL_CFG)
    assert out is not None
    assert out.market_type == MarketType.EXTRA_INNINGS
    # a genuine GAME yes/no -- NOT YESNO_AS_OU@0.5 like the first-inning form,
    # because optic's counterpart is (Scope.GAME, Shape.YES_NO), so neither side
    # carries a line.
    assert out.side_mode == pm.SideMode.YESNO
    assert out.line is None
    assert out.entity is None
    assert out.team_a == pm._norm_name("Arizona Diamondbacks", "mlb_suffix")
    assert out.team_b == pm._norm_name("St. Louis Cardinals", "mlb_suffix")


def test_parse_extra_innings_is_dropped_when_league_omits_the_kind():
    """A league whose market_types lacks "extra_innings" must drop, not crash --
    the cfg stays the single source of truth for which kinds are live."""
    cfg = pm.PolymarketConfig(
        slug_prefix="mlb", optic_league_id="mlb",
        market_types={"moneyline": MarketType.MONEYLINE},
        market_rules=(pm.mlb_extra_innings_rule, pm.mlb_moneyline_rule),
    )
    assert pm.parse_question(_EXTRA_Q, cfg) is None


def test_build_rows_extra_innings_yes_no_end_to_end():
    m = _mkt(_EXTRA_Q, [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_FULL_CFG)
    rows = _bf(market=m, parsed=parsed)
    by = {r.polymarket_clob_token_id: r for r in rows}
    assert set(by) == {"cY", "cN"}
    for tok, side in (("cY", "yes"), ("cN", "no")):
        assert by[tok].side == side
        assert by[tok].market_type == "extra_innings"
        # must match optic's row exactly: game-scoped, no entity, no line
        assert by[tok].entity is None
        assert by[tok].line is None


def test_build_rows_extra_innings_drops_reversed_labels_safely():
    """Side is bound to the LABEL, never the outcome index (flip-safety): a feed
    that lists No first must still map No->no."""
    m = _mkt(_EXTRA_Q, [
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 0},
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_FULL_CFG)
    by = {r.polymarket_clob_token_id: r for r in _bf(market=m, parsed=parsed)}
    assert by["cY"].side == "yes" and by["cN"].side == "no"


def test_build_rows_extra_innings_drops_incomplete_pair():
    """Guard #2 (complementary-pair/arity): a lone Yes must drop the market
    whole rather than emit a half-market."""
    m = _mkt(_EXTRA_Q, [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
    ])
    parsed = pm.parse_question(m.question, MLB_FULL_CFG)
    assert _bf(market=m, parsed=parsed) == []


def test_extra_innings_wired_on_both_sides_of_the_shipped_mlb_config():
    """The point of the rule: poly's form and optic's market must resolve to the
    SAME MarketType, or the poly row can never find an optic row to stamp."""
    from mappers.seed.fixture_store import load_fixture
    from mappers.seed.tip_factories import build_tip_league

    mlb = build_tip_league(next(r for r in load_fixture().leagues if r.league == "mlb"))
    poly = mlb.POLYMARKET
    assert poly is not None
    assert poly.market_types["extra_innings"] == MarketType.EXTRA_INNINGS
    assert (mlb.OPTIC.table_types["will_there_be_extra_innings"]
            == MarketType.EXTRA_INNINGS)
    assert poly.market_types["extra_innings"] == \
        mlb.OPTIC.table_types["will_there_be_extra_innings"]
    assert pm.mlb_extra_innings_rule in poly.market_rules
    assert MarketType.EXTRA_INNINGS in set(mlb.OUTPUT_ORDER)


def test_extra_innings_parses_under_the_shipped_mlb_config():
    """Exercise the real shipped config, not just the test fixture."""
    from mappers.seed.fixture_store import load_fixture
    from mappers.seed.tip_factories import build_tip_league

    mlb = build_tip_league(next(r for r in load_fixture().leagues if r.league == "mlb"))
    poly = mlb.POLYMARKET
    assert poly is not None
    out = pm.parse_question(_EXTRA_Q, poly)
    assert out is not None and out.market_type == MarketType.EXTRA_INNINGS
    assert out.side_mode == pm.SideMode.YESNO and out.line is None


def test_parse_moneyline_and_total_still_win_under_full_config():
    # regression: adding the new rules must not shadow the existing forms.
    ml = pm.parse_question("Arizona Diamondbacks vs. St. Louis Cardinals", MLB_FULL_CFG)
    assert ml is not None
    assert ml.market_type == MarketType.MONEYLINE and ml.side_mode == pm.SideMode.TEAM_LABEL
    tot = pm.parse_question(
        "Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5", MLB_FULL_CFG)
    assert tot is not None
    assert tot.market_type == MarketType.GAME_TOTAL and tot.line == 8.5


def _bf(**kw):
    """build_rows with common MLB fixture kwargs under MLB_FULL_CFG."""
    base = {"home": "AZ", "away": "STL", "home_name": "Arizona Diamondbacks",
            "away_name": "St. Louis Cardinals", "start_date": "2026-07-21T23:00:00Z",
            "cfg": MLB_FULL_CFG, "league": "mlb"}
    base.update(kw)
    return pm.build_rows(**base)


def test_build_rows_home_runs_prop_end_to_end():
    m = _mkt("Aaron Judge: Home Runs O/U 0.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_FULL_CFG)
    by = {r.polymarket_clob_token_id: r for r in _bf(market=m, parsed=parsed)}
    assert by["cO"].side == "over" and by["cO"].entity == "aaron_judge" and by["cO"].line == 0.5
    assert by["cU"].side == "under" and by["cU"].market_type == "player_home_runs"


def test_build_rows_spread_binds_named_team_line():
    m = _mkt("Spread: Arizona Diamondbacks (-1.5)", [
        {"clob_token_id": "cA", "position_id": "pA",
         "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB",
         "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_FULL_CFG)
    by = {r.polymarket_clob_token_id: r for r in _bf(market=m, parsed=parsed)}
    assert by["cA"].side == "AZ" and by["cA"].line == -1.5
    assert by["cB"].side == "STL" and by["cB"].line == 1.5
    assert by["cA"].market_type == "point_spread"


def test_build_rows_first_inning_yes_over_no_under():
    m = _mkt("Will there be a run scored in the first inning?: "
             "Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_FULL_CFG)
    by = {r.polymarket_clob_token_id: r for r in _bf(market=m, parsed=parsed)}
    assert by["cY"].side == "over" and by["cY"].line == 0.5 and by["cY"].entity is None
    assert by["cN"].side == "under" and by["cN"].market_type == "first_inning_total"

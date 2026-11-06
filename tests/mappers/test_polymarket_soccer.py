"""Unit tests for the soccer reuse-mode recognizers (Task 2 of the soccer wave).

Covers `soccer_total_rule`, `soccer_team_total_rule`, `soccer_spread_rule`, and
`soccer_first_half_total_rule` -- the four forms that reuse SideModes already
exercised by MLB (OVER_UNDER, SPREAD_TEAM). Question templates and outcome
labels are byte-exact from `.superpowers/sdd/wave-4-probe-findings.md` section C.

This is standalone unit coverage of the recognizers only -- no league is wired
(that's Task 7) and build_rows is not touched here (frozen).
"""

import pytest

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType, Scope
from mappers.pipeline import _match_poly_fixture
from mappers.run import LEAGUES
from mappers.shared import TIE_SIDE, normalize_player_name
from mappers.sport import Sport
from mappers.vocab.soccer_question import soccer_draw_sides

# Minimal soccer test config (per task-2-brief.md ambiguity resolutions):
# question_style="mlb_suffix" is correct for soccer per the wave-4 probe.
# market_types carries the "kind" keys this file's rules look up, mirroring
# MLB_CFG / TENNIS_CFG in test_polymarket.py.
SOCCER_CFG = pm.PolymarketConfig(
    slug_prefix="mls",
    optic_league_id="usa_-_major_league_soccer",
    market_types={
        "total": MarketType.GAME_TOTAL,
        "team_total": MarketType.TEAM_TOTAL,
        "spread": MarketType.POINT_SPREAD,
        "first_half_total": MarketType.FIRST_HALF_TOTAL,
        "btts": MarketType.BTTS,
        "first_half_btts": MarketType.FIRST_HALF_BTTS,
        "moneyline_3way": MarketType.MONEYLINE_3WAY,
        "first_half_winner_3way": MarketType.FIRST_HALF_WINNER_3WAY,
    },
    question_style="mlb_suffix",
    market_rules=(
        pm.soccer_total_rule,
        pm.soccer_team_total_rule,
        pm.soccer_spread_rule,
        pm.soccer_first_half_total_rule,
        pm.soccer_btts_rule,
        pm.soccer_first_half_btts_rule,
    ),
)


# --- soccer_total_rule (full-game total) ---


def test_soccer_full_total():
    pm_ = pm.soccer_total_rule("Austin FC vs. Seattle Sounders FC: O/U 2.5", SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.GAME_TOTAL
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.line == 2.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_total_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_total_rule("Austin FC vs. Seattle Sounders FC: O/U 2.5", cfg) is None


def test_soccer_total_rejects_team_total_variant():
    # ordering guard: the team-total question must NOT be captured by the
    # full-total rule (anchoring, mirrors mlb_total_rule's guard)
    assert pm.soccer_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5", SOCCER_CFG
    ) is None


def test_soccer_total_rejects_half_variants():
    assert pm.soccer_total_rule(
        "Austin FC vs. Seattle Sounders FC: 1st Half O/U 1.5", SOCCER_CFG
    ) is None
    assert pm.soccer_total_rule(
        "Austin FC vs. Seattle Sounders FC: 2nd Half O/U 1.5", SOCCER_CFG
    ) is None


# --- soccer_team_total_rule ---


def test_soccer_team_total_binds_named_team():
    pm_ = pm.soccer_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5", SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.TEAM_TOTAL
    assert pm_.market_type.scope == Scope.TEAM
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.entity == pm._norm_name("Austin FC", "mlb_suffix")  # TEAM-scope entity
    assert pm_.line == 1.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_team_total_rejects_half_variants():
    # ordering guard: the team-half-total form must not be captured here
    assert pm.soccer_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 1st Half O/U 1.5", SOCCER_CFG
    ) is None
    assert pm.soccer_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 2nd Half O/U 1.5", SOCCER_CFG
    ) is None


def test_soccer_team_total_rejects_plain_full_total():
    assert pm.soccer_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: O/U 2.5", SOCCER_CFG
    ) is None


# --- soccer_spread_rule ---


def test_soccer_spread_signs_named_team_negative():
    pm_ = pm.soccer_spread_rule("Spread: Austin FC (-1.5)", SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.POINT_SPREAD
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.SPREAD_TEAM
    assert pm_.entity == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.line == -1.5


def test_soccer_spread_signs_named_team_positive():
    pm_ = pm.soccer_spread_rule("Spread: Seattle Sounders FC (+1.5)", SOCCER_CFG)
    assert pm_ is not None
    assert pm_.entity == pm._norm_name("Seattle Sounders FC", "mlb_suffix")
    assert pm_.line == 1.5


# --- soccer_first_half_total_rule ---


def test_soccer_first_half_total():
    pm_ = pm.soccer_first_half_total_rule(
        "Austin FC vs. Seattle Sounders FC: 1st Half O/U 1.5", SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.FIRST_HALF_TOTAL
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.line == 1.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_first_half_total_rejects_team_half_variant():
    # out-of-scope form: "<Team> 1st Half O/U N" must NOT match the plain
    # ": 1st Half O/U" form.
    assert pm.soccer_first_half_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 1st Half O/U 1.5", SOCCER_CFG
    ) is None


def test_soccer_first_half_total_rejects_full_total():
    assert pm.soccer_first_half_total_rule(
        "Austin FC vs. Seattle Sounders FC: O/U 2.5", SOCCER_CFG
    ) is None


# --- parse_question end-to-end (first-match-wins ordering, per SOCCER_CFG) ---


def test_parse_question_dispatches_full_total():
    out = pm.parse_question("Austin FC vs. Seattle Sounders FC: O/U 2.5", SOCCER_CFG)
    assert out is not None and out.market_type == MarketType.GAME_TOTAL


def test_parse_question_dispatches_team_total():
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5", SOCCER_CFG
    )
    assert out is not None and out.market_type == MarketType.TEAM_TOTAL


def test_parse_question_dispatches_spread():
    out = pm.parse_question("Spread: Austin FC (-1.5)", SOCCER_CFG)
    assert out is not None and out.market_type == MarketType.POINT_SPREAD


def test_parse_question_dispatches_first_half_total():
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: 1st Half O/U 1.5", SOCCER_CFG
    )
    assert out is not None and out.market_type == MarketType.FIRST_HALF_TOTAL


# --- soccer_btts_rule / soccer_first_half_btts_rule (first live YESNO) ---
#
# Question templates + outcome labels (Yes/No) are byte-exact from
# .superpowers/sdd/wave-4-probe-findings.md section C.


def test_soccer_btts_parse():
    pm_ = pm.soccer_btts_rule(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score", SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.BTTS
    assert pm_.side_mode == pm.SideMode.YESNO
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_btts_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_btts_rule(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score", cfg
    ) is None


def test_btts_first_half_not_captured_by_plain_btts():
    # ordering guard: the 1st-half variant must NOT be captured by the plain
    # BTTS rule (anchoring, mirrors soccer_total_rule's guard vs. half forms).
    assert pm.soccer_btts_rule(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score in First Half",
        SOCCER_CFG,
    ) is None


def test_soccer_btts_first_half_parse():
    pm_ = pm.soccer_first_half_btts_rule(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score in First Half",
        SOCCER_CFG,
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.FIRST_HALF_BTTS
    assert pm_.side_mode == pm.SideMode.YESNO
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_first_half_btts_rejects_plain_btts():
    assert pm.soccer_first_half_btts_rule(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score", SOCCER_CFG
    ) is None


def test_parse_question_dispatches_btts():
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score", SOCCER_CFG
    )
    assert out is not None and out.market_type == MarketType.BTTS


def test_parse_question_dispatches_first_half_btts():
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score in First Half",
        SOCCER_CFG,
    )
    assert out is not None and out.market_type == MarketType.FIRST_HALF_BTTS


def _soccer_mkt(question, outcomes):
    return pm.PolyMarket(
        condition_id="0xabc", slug="mls-atx-sea-2026-07-22",
        question=question,
        outcomes=[pm.PolyOutcome(**o) for o in outcomes],
    )


def test_build_rows_btts_yesno_binds_side_to_label():
    # First live YESNO exercise: soccer_btts_rule's ParsedMarket fed straight
    # into build_rows (frozen) with a synthetic 2-outcome poly market. Side
    # must bind to the outcome LABEL ("Yes"/"No"), never to array index.
    m = _soccer_mkt(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score",
        [
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 0},
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_btts_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 2
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    # "Yes" is outcome_index 1, "No" is outcome_index 0 -- side is bound to the
    # LABEL, not the index, so this ordering is a deliberate flip-safety check.
    assert by_tok["cY"].side == "yes" and by_tok["cY"].market_type == "btts"
    assert by_tok["cN"].side == "no" and by_tok["cN"].market_type == "btts"
    assert by_tok["cY"].entity is None and by_tok["cY"].line is None


# === Task 4: soccer 3-way moneyline + 1st-half-winner (first live
#     THREE_WAY_FIXED). Question templates byte-exact from
#     .superpowers/sdd/wave-4-probe-findings.md section C. Poly encodes soccer
#     3-way ML as THREE separate Yes/No markets per fixture ("Will A win?",
#     "Will B win?", "Will A vs B end in a draw?") -- each recognizer here owns
#     exactly ONE of those question shapes; the frozen build_rows
#     THREE_WAY_FIXED branch emits only the single affirmative outcome. ===


# --- soccer_ml_team_win_rule ---


def test_soccer_ml_team_win_binds_named_team():
    pm_ = pm.soccer_ml_team_win_rule("Will Austin FC win on 2026-07-22?", SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.MONEYLINE_3WAY
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    # single team named -> team_a set, team_b stays None (mirrors the
    # single-team MLB spread/prop rules; build_rows' THREE_WAY_FIXED branch
    # never reads team_a/team_b, only fixed_side_team + the caller-supplied
    # home_name/away_name -- see build_rows integration test below).
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b is None
    assert pm_.fixed_side_team == pm._norm_name("Austin FC", "mlb_suffix")


def test_soccer_ml_team_win_rejects_draw_form():
    # flip-safety / ordering guard: the draw question must NOT be captured by
    # the team-win rule -- soccer_ml_draw_rule owns that shape.
    assert pm.soccer_ml_team_win_rule(
        "Will Austin FC vs. Seattle Sounders FC end in a draw?", SOCCER_CFG
    ) is None


def test_soccer_ml_team_win_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_ml_team_win_rule("Will Austin FC win on 2026-07-22?", cfg) is None


# --- soccer_ml_draw_rule ---


def test_soccer_ml_draw_is_tie():
    pm_ = pm.soccer_ml_draw_rule(
        "Will Austin FC vs. Seattle Sounders FC end in a draw?", SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.MONEYLINE_3WAY
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert pm_.fixed_side_team is None  # resolves to _TIE in build_rows
    # both teams named -> team_a/team_b both set (unlike the team-win form).
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_draw_sides_match_the_live_rule():
    # Gap harvest binds names via soccer_question.soccer_draw_sides; it must
    # read the SAME grammar as the live rule, or an overlay pin lands on the
    # wrong side (a generic "<A> vs. <B>" capture folds "end in a draw" into
    # team B, whose bind key then becomes "draw").
    q = "Will Austin FC vs. Seattle Sounders FC end in a draw?"
    pm_ = pm.soccer_ml_draw_rule(q, SOCCER_CFG)
    sides = soccer_draw_sides(q)
    assert pm_ is not None
    assert sides is not None
    style = SOCCER_CFG.question_style
    assert (pm._norm_name(sides[0], style), pm._norm_name(sides[1], style)) == (
        pm_.team_a,
        pm_.team_b,
    )
    assert soccer_draw_sides("Will Austin FC win on 2026-07-22?") is None


def test_soccer_ml_draw_rejects_team_win_form():
    # flip-safety / ordering guard: the reverse -- team-win question must NOT
    # be captured by the draw rule.
    assert pm.soccer_ml_draw_rule("Will Austin FC win on 2026-07-22?", SOCCER_CFG) is None


def test_soccer_ml_draw_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_ml_draw_rule(
        "Will Austin FC vs. Seattle Sounders FC end in a draw?", cfg
    ) is None


# --- soccer_first_half_leader_rule ---


def test_soccer_first_half_leader_binds_named_team():
    pm_ = pm.soccer_first_half_leader_rule("Austin FC leading at halftime?", SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.FIRST_HALF_WINNER_3WAY
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b is None
    assert pm_.fixed_side_team == pm._norm_name("Austin FC", "mlb_suffix")


def test_soccer_first_half_leader_rejects_draw_form():
    assert pm.soccer_first_half_leader_rule(
        "Austin FC vs. Seattle Sounders FC: Draw at halftime?", SOCCER_CFG
    ) is None


def test_soccer_first_half_leader_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_first_half_leader_rule("Austin FC leading at halftime?", cfg) is None


# --- soccer_first_half_draw_rule ---


def test_soccer_first_half_draw_is_tie():
    pm_ = pm.soccer_first_half_draw_rule(
        "Austin FC vs. Seattle Sounders FC: Draw at halftime?", SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.FIRST_HALF_WINNER_3WAY
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert pm_.fixed_side_team is None
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_first_half_draw_rejects_leader_form():
    assert pm.soccer_first_half_draw_rule(
        "Austin FC leading at halftime?", SOCCER_CFG
    ) is None


def test_soccer_first_half_draw_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_first_half_draw_rule(
        "Austin FC vs. Seattle Sounders FC: Draw at halftime?", cfg
    ) is None


# --- build_rows integration (first live THREE_WAY_FIXED exercise) ---
#
# Each test feeds a recognizer's ParsedMarket straight into the frozen
# build_rows dispatch with a synthetic 2-outcome (Yes/No) poly market and
# asserts EXACTLY ONE row emits (the affirmative outcome; the complementary
# "No" outcome is intentionally dropped by the THREE_WAY_FIXED branch).


def test_build_rows_soccer_ml_team_win_binds_named_team():
    m = _soccer_mkt(
        "Will Austin FC win on 2026-07-22?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_ml_team_win_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == "ATX" and rows[0].market_type == "moneyline_3way"
    assert rows[0].line is None and rows[0].entity is None


def test_build_rows_soccer_ml_draw_is_tie_side():
    m = _soccer_mkt(
        "Will Austin FC vs. Seattle Sounders FC end in a draw?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_ml_draw_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == TIE_SIDE and rows[0].market_type == "moneyline_3way"


def test_build_rows_soccer_first_half_leader_binds_named_team():
    m = _soccer_mkt(
        "Austin FC leading at halftime?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_first_half_leader_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == "ATX" and rows[0].market_type == "1h_winner_3way"


def test_build_rows_soccer_first_half_draw_is_tie_side():
    m = _soccer_mkt(
        "Austin FC vs. Seattle Sounders FC: Draw at halftime?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_first_half_draw_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == TIE_SIDE and rows[0].market_type == "1h_winner_3way"


def test_build_rows_soccer_ml_team_win_drops_when_named_team_absent():
    # flip-safety: a named team that resolves to neither fixture side drops
    # the whole market rather than guessing.
    m = _soccer_mkt(
        "Will Somebody Else win on 2026-07-22?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_ml_team_win_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert rows == []


# === Task 5: player-goals recognizer + shared soccer_market_rules tuple ===
#
# Player-goals question template is byte-exact from .superpowers/sdd/
# wave-4-probe-findings.md section C (WORLD-CUP-only in poly -- confirmed
# 0/8,330 mls/mex/ucl rows, present for fifwc). ALL_SOCCER_CFG wires
# soccer_market_rules verbatim (as Task 6/7 leagues will) and declares every
# market_types key the 11 rules reference, proving the tuple ordering + the
# key set are self-consistent end to end via parse_question.

ALL_SOCCER_CFG = pm.PolymarketConfig(
    slug_prefix="mls",
    optic_league_id="usa_-_major_league_soccer",
    market_types={
        "total": MarketType.GAME_TOTAL,
        "team_total": MarketType.TEAM_TOTAL,
        "spread": MarketType.POINT_SPREAD,
        "first_half_total": MarketType.FIRST_HALF_TOTAL,
        "btts": MarketType.BTTS,
        "first_half_btts": MarketType.FIRST_HALF_BTTS,
        "moneyline_3way": MarketType.MONEYLINE_3WAY,
        "first_half_winner_3way": MarketType.FIRST_HALF_WINNER_3WAY,
        "player_goals": MarketType.PLAYER_GOALS,
        # Rescue tier (Task R1 / wave-rescue-probe-findings.md).
        "second_half_total": MarketType.SECOND_HALF_TOTAL,
        "first_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
        "second_half_team_total": MarketType.SECOND_HALF_TEAM_TOTAL,
        "second_half_winner_3way": MarketType.SECOND_HALF_WINNER_3WAY,
        "first_team_to_score": MarketType.FIRST_TEAM_TO_SCORE,
        "player_assists": MarketType.PLAYER_ASSISTS,
        "player_shots": MarketType.PLAYER_SHOTS,
        "player_shots_on_target": MarketType.PLAYER_SHOTS_ON_TARGET,
        "player_goals_or_assists": MarketType.PLAYER_GOALS_OR_ASSIST,
        # Task R4 (wave-rescue-probe-findings.md).
        "exact_score": MarketType.CORRECT_SCORE,
    },
    question_style="mlb_suffix",
    market_rules=pm.soccer_market_rules,
)


# --- soccer_player_goals_rule ---


def test_soccer_player_goals_ladder():
    pm_ = pm.soccer_player_goals_rule("Alexander Sørloth: 1+ goals", ALL_SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.PLAYER_GOALS
    assert pm_.market_type.scope == Scope.PLAYER
    assert pm_.side_mode == pm.SideMode.YESNO_AS_OU
    # entity must equal the optic PLAYER entity (normalize_player_name), not the
    # mlb_suffix team normalizer -- else the merge key never matches optic.
    assert pm_.entity == normalize_player_name("Alexander Sørloth")
    assert pm_.line == 0.5
    assert pm_.team_a is None and pm_.team_b is None


def test_soccer_player_goals_ladder_second_rung():
    # N+ = over (N-0.5): "2+ goals" -> line 1.5, not 2.0.
    pm_ = pm.soccer_player_goals_rule("Alexander Sørloth: 2+ goals", ALL_SOCCER_CFG)
    assert pm_ is not None
    assert pm_.line == 1.5


def test_soccer_player_goals_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="fifwc", optic_league_id="world_cup",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_player_goals_rule("Alexander Sørloth: 1+ goals", cfg) is None


def test_soccer_player_goals_rejects_assists():
    # only "goals" matches -- optic doesn't price player_assists in this wave.
    assert pm.soccer_player_goals_rule(
        "Alexander Sørloth: 1+ assists", ALL_SOCCER_CFG
    ) is None


def test_soccer_player_goals_rejects_shots():
    assert pm.soccer_player_goals_rule(
        "Alexander Sørloth: 1+ shots", ALL_SOCCER_CFG
    ) is None


def test_soccer_player_goals_rejects_goals_plus_assists():
    # a distinct poly form ("goals_+_assists") that happens to contain the
    # literal "goals" substring -- must NOT be captured by this rule.
    assert pm.soccer_player_goals_rule(
        "Alexander Sørloth: 1+ goals + assists", ALL_SOCCER_CFG
    ) is None


# === Task R1: rescue-tier recognizers reusing existing SideModes ===
#
# Question templates + outcome labels are byte-exact from
# .superpowers/sdd/wave-rescue-probe-findings.md section A. Every one reuses
# an already-shipped SideMode (OVER_UNDER / YESNO_AS_OU / THREE_WAY_FIXED);
# build_rows (frozen) is not touched.

# --- soccer_second_half_total_rule ---


def test_soccer_second_half_total():
    pm_ = pm.soccer_second_half_total_rule(
        "Austin FC vs. Seattle Sounders FC: 2nd Half O/U 0.5", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.SECOND_HALF_TOTAL
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.line == 0.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_second_half_total_rejects_team_variant():
    # ordering guard: "<Team> 2nd Half O/U N" must NOT be caught here.
    assert pm.soccer_second_half_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 2nd Half O/U 0.5", ALL_SOCCER_CFG
    ) is None


def test_soccer_second_half_total_rejects_first_half_variant():
    assert pm.soccer_second_half_total_rule(
        "Austin FC vs. Seattle Sounders FC: 1st Half O/U 0.5", ALL_SOCCER_CFG
    ) is None


# --- soccer_first_half_team_total_rule / soccer_second_half_team_total_rule ---


def test_soccer_first_half_team_total_binds_named_team():
    pm_ = pm.soccer_first_half_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 1st Half O/U 0.5", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.FIRST_HALF_TEAM_TOTAL
    assert pm_.market_type.scope == Scope.TEAM
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.entity == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.line == 0.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_first_half_team_total_rejects_second_half_variant():
    # ordering guard: team-half rules must not cross-catch each other's half.
    assert pm.soccer_first_half_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 2nd Half O/U 0.5", ALL_SOCCER_CFG
    ) is None


def test_soccer_first_half_team_total_rejects_game_half_variant():
    # ordering guard: team-half rules must come before / not be shadowed by
    # the plain game-half form (no team named).
    assert pm.soccer_first_half_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: 1st Half O/U 0.5", ALL_SOCCER_CFG
    ) is None


def test_soccer_second_half_team_total_binds_named_team():
    pm_ = pm.soccer_second_half_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 2nd Half O/U 0.5", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.SECOND_HALF_TEAM_TOTAL
    assert pm_.market_type.scope == Scope.TEAM
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.entity == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.line == 0.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_second_half_team_total_rejects_first_half_variant():
    assert pm.soccer_second_half_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC 1st Half O/U 0.5", ALL_SOCCER_CFG
    ) is None


def test_soccer_second_half_team_total_rejects_game_half_variant():
    assert pm.soccer_second_half_team_total_rule(
        "Austin FC vs. Seattle Sounders FC: 2nd Half O/U 0.5", ALL_SOCCER_CFG
    ) is None


# --- soccer_second_half_winner_rule / soccer_second_half_draw_rule ---


def test_soccer_second_half_winner_binds_named_team():
    pm_ = pm.soccer_second_half_winner_rule("Austin FC to win the second half?", ALL_SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.SECOND_HALF_WINNER_3WAY
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b is None
    assert pm_.fixed_side_team == pm._norm_name("Austin FC", "mlb_suffix")


def test_soccer_second_half_winner_rejects_draw_form():
    assert pm.soccer_second_half_winner_rule(
        "Austin FC vs. Seattle Sounders FC: Second half draw?", ALL_SOCCER_CFG
    ) is None


def test_soccer_second_half_draw_is_tie():
    pm_ = pm.soccer_second_half_draw_rule(
        "Austin FC vs. Seattle Sounders FC: Second half draw?", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.SECOND_HALF_WINNER_3WAY
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert pm_.fixed_side_team is None
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_second_half_draw_rejects_winner_form():
    assert pm.soccer_second_half_draw_rule(
        "Austin FC to win the second half?", ALL_SOCCER_CFG
    ) is None


def test_build_rows_soccer_second_half_winner_binds_named_team():
    m = _soccer_mkt(
        "Austin FC to win the second half?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_second_half_winner_rule(m.question, ALL_SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=ALL_SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == "ATX" and rows[0].market_type == "2h_winner_3way"


def test_build_rows_soccer_second_half_draw_is_tie_side():
    m = _soccer_mkt(
        "Austin FC vs. Seattle Sounders FC: Second half draw?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_second_half_draw_rule(m.question, ALL_SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=ALL_SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].side == TIE_SIDE and rows[0].market_type == "2h_winner_3way"


# --- soccer_first_to_score_rule (+ the "Neither" drop) ---


def test_soccer_first_to_score_binds_first_named_team():
    pm_ = pm.soccer_first_to_score_rule(
        "Austin FC to score first vs. Seattle Sounders FC?", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.FIRST_TEAM_TO_SCORE
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.side_mode == pm.SideMode.THREE_WAY_FIXED
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")
    assert pm_.fixed_side_team == pm._norm_name("Austin FC", "mlb_suffix")


_NEITHER_Q = "Austin FC vs. Seattle Sounders FC: Neither team to score first?"


def test_soccer_first_to_score_rejects_neither_form():
    """The TEAM-leg rule must still not claim the neither form -- its anchor
    requires the literal "to score first vs." substring. The neither form is now
    mapped, but by its OWN rule (below), never by this one; if this rule ever
    matched it, it would bind a team side to a no-goal question."""
    assert pm.soccer_first_to_score_rule(_NEITHER_Q, ALL_SOCCER_CFG) is None


def test_soccer_neither_scores_first_binds_the_tie_side():
    """Reversal of the earlier deliberate drop. Optic's first_team_to_score
    ships a third selection literally named "Draw" with a null team_id -- 16,921
    ticks / 588 fixtures over 14d, all 7 wired soccer leagues -- which
    optic.build_rows maps to TIE_SIDE. Within this market "Draw" can only mean
    "no goal scored" (a 1-1 match already belongs to a team selection), so the
    poly question has exactly one clean optic counterpart and nothing is
    invented."""
    out = pm.soccer_neither_scores_first_rule(_NEITHER_Q, ALL_SOCCER_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_TEAM_TO_SCORE
    assert out.side_mode == pm.SideMode.THREE_WAY_FIXED
    # None fixed_side_team is what selects _TIE rather than a team abbrev
    assert out.fixed_side_team is None
    # both teams named -> resolves its fixture in Phase A, like the team-leg rule
    assert out.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert out.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")
    assert out.line is None and out.entity is None


def test_parse_question_neither_first_maps_via_full_tuple():
    out = pm.parse_question(_NEITHER_Q, ALL_SOCCER_CFG)
    assert out is not None
    assert out.market_type == MarketType.FIRST_TEAM_TO_SCORE
    assert out.fixed_side_team is None


def test_build_rows_neither_scores_first_emits_only_the_tie_side():
    """THREE_WAY_FIXED emits the affirmative outcome only: poly's "No" leg is the
    union of the two team selections and has no single optic counterpart, so it
    must not emit."""
    m = _soccer_mkt(_NEITHER_Q, [
        {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
        {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, ALL_SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=ALL_SOCCER_CFG,
        league="usa_-_major_league_soccer",
    )
    assert [r.polymarket_clob_token_id for r in rows] == ["cY"]
    assert rows[0].side == TIE_SIDE
    assert rows[0].market_type == "first_team_to_score"
    assert rows[0].line is None and rows[0].entity is None


def test_neither_scores_first_dropped_when_league_omits_the_kind():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={"total": MarketType.GAME_TOTAL},
        market_rules=(pm.soccer_neither_scores_first_rule,),
    )
    assert pm.parse_question(_NEITHER_Q, cfg) is None


# === Anytime goalscorer -> PLAYER_GOALS @ 0.5 (no new MarketType) ===


def test_soccer_anytime_goalscorer_folds_onto_player_goals_half_line():
    """Optic's separate anytime_goal_scorer market is ignored BY DESIGN (every
    book quoting it also quotes player_goals over 0.5 for the same players, so a
    dedicated MarketType would double-count one question across two rows).
    LEAGUES['world_cup'].py's own remedy is to synthesize line=0.5/side=over onto the
    player_goals row -- which is exactly what this rule does."""
    out = pm.parse_question("Erling Haaland: Anytime Goalscorer", ALL_SOCCER_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_GOALS
    assert out.side_mode == pm.SideMode.YESNO_AS_OU
    assert out.line == 0.5
    assert out.entity == normalize_player_name("Erling Haaland")
    # player-only form: no teams in the question, so it defers to Phase B
    assert out.team_a is None and out.team_b is None


def test_anytime_goalscorer_and_one_plus_goals_agree_on_the_row():
    """"Anytime goalscorer" and "1+ goals" are the same bet, so both forms must
    land on the identical (market_type, entity, line) -- otherwise one of them is
    mispriced against optic."""
    a = pm.parse_question("Erling Haaland: Anytime Goalscorer", ALL_SOCCER_CFG)
    b = pm.parse_question("Erling Haaland: 1+ goals", ALL_SOCCER_CFG)
    assert a is not None and b is not None
    assert (a.market_type, a.entity, a.line, a.side_mode) == \
           (b.market_type, b.entity, b.line, b.side_mode)


def test_anytime_goalscorer_does_not_swallow_the_ladder_forms():
    for q in [
        "Erling Haaland: 2+ goals",
        "Erling Haaland: 3+ saves",
        "Erling Haaland: 1+ goals + assists",
        "Erling Haaland: Anytime Assister",
    ]:
        out = pm.soccer_anytime_goalscorer_rule(q, ALL_SOCCER_CFG)
        assert out is None, q


def test_build_rows_soccer_first_to_score_binds_named_team():
    m = _soccer_mkt(
        "Austin FC to score first vs. Seattle Sounders FC?",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.soccer_first_to_score_rule(m.question, ALL_SOCCER_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="ATX", away="SEA",
        home_name="Austin FC", away_name="Seattle Sounders FC",
        start_date="2026-07-22T23:00:00Z", cfg=ALL_SOCCER_CFG, league="usa_-_major_league_soccer",
    )
    assert len(rows) == 1
    assert rows[0].polymarket_clob_token_id == "cY"
    assert rows[0].side == "ATX" and rows[0].market_type == "first_team_to_score"


# --- World Cup player-prop rescue rules ---


def test_soccer_player_assists_ladder():
    pm_ = pm.soccer_player_assists_rule("Anthony Gordon: 1+ assists", ALL_SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.PLAYER_ASSISTS
    assert pm_.market_type.scope == Scope.PLAYER
    assert pm_.side_mode == pm.SideMode.YESNO_AS_OU
    assert pm_.entity == normalize_player_name("Anthony Gordon")
    assert pm_.line == 0.5
    assert pm_.team_a is None and pm_.team_b is None


def test_soccer_player_assists_rejects_goals():
    assert pm.soccer_player_assists_rule("Anthony Gordon: 1+ goals", ALL_SOCCER_CFG) is None


def test_soccer_player_shots_ladder():
    pm_ = pm.soccer_player_shots_rule("Alexis Mac Allister: 1+ shots", ALL_SOCCER_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.PLAYER_SHOTS
    assert pm_.market_type.scope == Scope.PLAYER
    assert pm_.side_mode == pm.SideMode.YESNO_AS_OU
    assert pm_.entity == normalize_player_name("Alexis Mac Allister")
    assert pm_.line == 0.5


def test_soccer_player_shots_rejects_shots_on_target_variant():
    # ordering guard: must NOT also match "N+ shots on target".
    assert pm.soccer_player_shots_rule(
        "Alexis Mac Allister: 1+ shots on target", ALL_SOCCER_CFG
    ) is None


def test_soccer_player_shots_on_target_ladder():
    pm_ = pm.soccer_player_shots_on_target_rule(
        "Alexis Mac Allister: 1+ shots on target", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.PLAYER_SHOTS_ON_TARGET
    assert pm_.market_type.scope == Scope.PLAYER
    assert pm_.side_mode == pm.SideMode.YESNO_AS_OU
    assert pm_.entity == normalize_player_name("Alexis Mac Allister")
    assert pm_.line == 0.5


def test_soccer_player_shots_on_target_rejects_plain_shots():
    # ordering guard: the plain "N+ shots" form must not be caught here.
    assert pm.soccer_player_shots_on_target_rule(
        "Alexis Mac Allister: 1+ shots", ALL_SOCCER_CFG
    ) is None


def test_soccer_player_goals_or_assists_ladder():
    pm_ = pm.soccer_player_goals_or_assists_rule(
        "Anthony Gordon: 1+ goals + assists", ALL_SOCCER_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.PLAYER_GOALS_OR_ASSIST
    assert pm_.market_type.scope == Scope.PLAYER
    assert pm_.side_mode == pm.SideMode.YESNO_AS_OU
    assert pm_.entity == normalize_player_name("Anthony Gordon")
    assert pm_.line == 0.5


def test_soccer_player_goals_or_assists_rejects_plain_goals():
    # ordering guard: must not match the bare "N+ goals" form (the reverse --
    # soccer_player_goals_rule rejecting "goals + assists" -- is already
    # covered by test_soccer_player_goals_rejects_goals_plus_assists above).
    assert pm.soccer_player_goals_or_assists_rule(
        "Anthony Gordon: 1+ goals", ALL_SOCCER_CFG
    ) is None


def test_soccer_player_goals_or_assists_rejects_plain_assists():
    assert pm.soccer_player_goals_or_assists_rule(
        "Anthony Gordon: 1+ assists", ALL_SOCCER_CFG
    ) is None


# --- soccer_market_rules: ordered tuple of ALL 22 recognizers ---


def test_soccer_market_rules_is_ordered_tuple_of_27():
    assert isinstance(pm.soccer_market_rules, tuple)
    assert len(pm.soccer_market_rules) == 27
    assert set(pm.soccer_market_rules) == {
        pm.soccer_neither_scores_first_rule,
        pm.soccer_anytime_goalscorer_rule,
        pm.soccer_total_corners_rule,
        pm.soccer_team_total_corners_rule,
        pm.soccer_player_saves_rule,
        pm.soccer_player_goals_rule,
        pm.soccer_total_rule,
        pm.soccer_team_total_rule,
        pm.soccer_spread_rule,
        pm.soccer_first_half_total_rule,
        pm.soccer_btts_rule,
        pm.soccer_first_half_btts_rule,
        pm.soccer_ml_team_win_rule,
        pm.soccer_ml_draw_rule,
        pm.soccer_first_half_leader_rule,
        pm.soccer_first_half_draw_rule,
        pm.soccer_second_half_total_rule,
        pm.soccer_first_half_team_total_rule,
        pm.soccer_second_half_team_total_rule,
        pm.soccer_second_half_winner_rule,
        pm.soccer_second_half_draw_rule,
        pm.soccer_first_to_score_rule,
        pm.soccer_player_assists_rule,
        pm.soccer_player_shots_rule,
        pm.soccer_player_shots_on_target_rule,
        pm.soccer_player_goals_or_assists_rule,
        pm.soccer_exact_score_rule,
    }
    # ordering: player_goals first (most specific -- no team-name overlap
    # risk with any GAME-scope form); team_total/first_half_total before the
    # more-general full total; first_half_btts before plain btts; ml_draw
    # before ml_team_win; first_half_draw before first_half_leader.
    order = {rule: i for i, rule in enumerate(pm.soccer_market_rules)}
    assert order[pm.soccer_team_total_rule] < order[pm.soccer_total_rule]
    assert order[pm.soccer_first_half_total_rule] < order[pm.soccer_total_rule]
    assert order[pm.soccer_first_half_btts_rule] < order[pm.soccer_btts_rule]
    assert order[pm.soccer_ml_draw_rule] < order[pm.soccer_ml_team_win_rule]
    assert order[pm.soccer_first_half_draw_rule] < order[pm.soccer_first_half_leader_rule]
    # rescue-tier ordering (task-r1-brief.md "critical" callouts):
    # team-half totals before the game-half totals and the plain team-total/
    # full-total forms; shots-on-target before plain shots; goals+assists
    # before plain goals/assists; second-half draw before second-half winner.
    assert order[pm.soccer_first_half_team_total_rule] < order[pm.soccer_first_half_total_rule]
    assert order[pm.soccer_first_half_team_total_rule] < order[pm.soccer_team_total_rule]
    assert order[pm.soccer_second_half_team_total_rule] < order[pm.soccer_second_half_total_rule]
    assert order[pm.soccer_second_half_team_total_rule] < order[pm.soccer_team_total_rule]
    assert order[pm.soccer_second_half_total_rule] < order[pm.soccer_total_rule]
    assert order[pm.soccer_player_shots_on_target_rule] < order[pm.soccer_player_shots_rule]
    assert order[pm.soccer_player_goals_or_assists_rule] < order[pm.soccer_player_goals_rule]
    assert order[pm.soccer_player_goals_or_assists_rule] < order[pm.soccer_player_assists_rule]
    assert order[pm.soccer_second_half_draw_rule] < order[pm.soccer_second_half_winner_rule]
    # corners ordering: the corners O/U form must be considered before every
    # goals-based O/U form. Its regex already requires a " Total Corners" tail
    # that none of those can match (and their `$` anchors reject it), so this
    # is defence-in-depth: if one of those anchors regressed, a corners
    # question must still resolve to the corners market rather than silently
    # landing on a goals total.
    assert order[pm.soccer_total_corners_rule] < order[pm.soccer_total_rule]
    assert order[pm.soccer_total_corners_rule] < order[pm.soccer_team_total_rule]
    assert order[pm.soccer_total_corners_rule] < order[pm.soccer_first_half_total_rule]
    assert order[pm.soccer_total_corners_rule] < order[pm.soccer_second_half_total_rule]
    assert order[pm.soccer_team_total_corners_rule] < order[pm.soccer_team_total_rule]
    assert order[pm.soccer_team_total_corners_rule] < order[pm.soccer_total_corners_rule]
    # exact_score (Task R4) is uniquely anchored on the "Exact Score:" prefix
    # -- disjoint from every form above, so its position is not
    # correctness-critical (no ordering assertion needed); it's simply a
    # member of the tuple (see the set membership check above).


def test_soccer_rules_ordering_team_total_wins():
    # a team-total question must resolve to TEAM_TOTAL, not GAME_TOTAL, when
    # parsed through the whole soccer_market_rules tuple.
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5", ALL_SOCCER_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.TEAM_TOTAL


# --- parse_question through the full tuple: one exact section-C example of
#     EACH of the 22 forms resolves to its correct MarketType. This proves
#     the tuple ordering + the market_types dict keys are consistent. ---


def test_parse_question_all_22_soccer_forms():
    cases = [
        ("Austin FC vs. Seattle Sounders FC: O/U 2.5", MarketType.GAME_TOTAL),
        ("Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5", MarketType.TEAM_TOTAL),
        ("Spread: Austin FC (-1.5)", MarketType.POINT_SPREAD),
        ("Will Austin FC win on 2026-07-22?", MarketType.MONEYLINE_3WAY),
        ("Will Austin FC vs. Seattle Sounders FC end in a draw?", MarketType.MONEYLINE_3WAY),
        ("Austin FC vs. Seattle Sounders FC: 1st Half O/U 1.5", MarketType.FIRST_HALF_TOTAL),
        ("Austin FC leading at halftime?", MarketType.FIRST_HALF_WINNER_3WAY),
        (
            "Austin FC vs. Seattle Sounders FC: Draw at halftime?",
            MarketType.FIRST_HALF_WINNER_3WAY,
        ),
        ("Austin FC vs. Seattle Sounders FC: Both Teams to Score", MarketType.BTTS),
        (
            "Austin FC vs. Seattle Sounders FC: Both Teams to Score in First Half",
            MarketType.FIRST_HALF_BTTS,
        ),
        ("Alexander Sørloth: 1+ goals", MarketType.PLAYER_GOALS),
        # rescue tier (Task R1):
        (
            "Austin FC vs. Seattle Sounders FC: 2nd Half O/U 0.5",
            MarketType.SECOND_HALF_TOTAL,
        ),
        (
            "Austin FC vs. Seattle Sounders FC: Austin FC 1st Half O/U 0.5",
            MarketType.FIRST_HALF_TEAM_TOTAL,
        ),
        (
            "Austin FC vs. Seattle Sounders FC: Austin FC 2nd Half O/U 0.5",
            MarketType.SECOND_HALF_TEAM_TOTAL,
        ),
        ("Austin FC to win the second half?", MarketType.SECOND_HALF_WINNER_3WAY),
        (
            "Austin FC vs. Seattle Sounders FC: Second half draw?",
            MarketType.SECOND_HALF_WINNER_3WAY,
        ),
        (
            "Austin FC to score first vs. Seattle Sounders FC?",
            MarketType.FIRST_TEAM_TO_SCORE,
        ),
        ("Anthony Gordon: 1+ assists", MarketType.PLAYER_ASSISTS),
        ("Alexis Mac Allister: 1+ shots", MarketType.PLAYER_SHOTS),
        ("Alexis Mac Allister: 1+ shots on target", MarketType.PLAYER_SHOTS_ON_TARGET),
        ("Anthony Gordon: 1+ goals + assists", MarketType.PLAYER_GOALS_OR_ASSIST),
        # rescue tier (Task R4):
        (
            "Exact Score: Austin FC 2 - 1 Seattle Sounders FC?",
            MarketType.CORRECT_SCORE,
        ),
    ]
    for question, expected in cases:
        out = pm.parse_question(question, ALL_SOCCER_CFG)
        assert out is not None, question
        assert out.market_type == expected, (question, out.market_type, expected)


# === Task 6: wire the two parity soccer leagues (EPL + WORLD_CUP) ===
#
# Both already have an OpticConfig; this task adds POLYMARKET, reusing
# pm.SOCCER_MARKET_TYPES + pm.soccer_market_rules verbatim (DRY — see
# .superpowers/sdd/task-6-report.md for the per-league map-vs-drop breakdown).


def test_world_cup_polymarket_config_present():
    cfg = LEAGUES["world_cup"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "fifwc"
    assert cfg.optic_league_id == "fifa_-_world_cup"
    assert cfg.market_types == pm.SOCCER_MARKET_TYPES
    assert cfg.market_rules is pm.soccer_market_rules


def test_epl_polymarket_config_present():
    cfg = LEAGUES["epl"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "epl"  # BEST-GUESS, UNVALIDATED -- see LEAGUES['epl'].py comment
    assert cfg.optic_league_id == "england_-_premier_league"
    assert cfg.market_types == pm.SOCCER_MARKET_TYPES
    assert cfg.market_rules is pm.soccer_market_rules


def test_world_cup_player_goals_parses_via_league_config():
    cfg = LEAGUES["world_cup"].POLYMARKET
    assert cfg is not None
    out = pm.parse_question("Kylian Mbappe: 1+ goals", cfg)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_GOALS
    assert out.entity == normalize_player_name("Kylian Mbappe")
    assert out.line == 0.5


def test_world_cup_btts_parses_via_league_config():
    cfg = LEAGUES["world_cup"].POLYMARKET
    assert cfg is not None
    out = pm.parse_question("Argentina vs. France: Both Teams to Score", cfg)
    assert out is not None
    assert out.market_type == MarketType.BTTS
    assert out.side_mode == pm.SideMode.YESNO


def test_world_cup_optic_prices_both_3way_market_types():
    # Guards the reviewer's optic-mapping concern: soccer moneyline is 3-way,
    # so both the full-game and 1st-half winner forms must resolve to the
    # THREE_WAY (not 2-way MONEYLINE_DNB) MarketType in World Cup's own
    # OpticConfig.table_types -- checked by value, not just identity.
    table_values_by_value = {mt.value for mt in LEAGUES['world_cup'].OPTIC.table_types.values()}
    assert MarketType.MONEYLINE_3WAY.value in table_values_by_value
    assert MarketType.FIRST_HALF_WINNER_3WAY.value in table_values_by_value


# === Task 7: wire MLS + the poly team-name alias overlay it needs
# (wave-4-probe-findings.md section D). ===


def test_mls_in_leagues():
    assert "mls" in LEAGUES


def test_mls_polymarket_config_present():
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "mls"
    assert cfg.optic_league_id == "usa_-_major_league_soccer"
    assert cfg.market_types == pm.SOCCER_MARKET_TYPES
    assert cfg.market_rules is pm.soccer_market_rules


def test_mls_optic_table_types_covers_9_soccer_market_types():
    table_values = set(LEAGUES["mls"].OPTIC.table_types.values())
    expected = {
        MarketType.MONEYLINE_3WAY,
        MarketType.POINT_SPREAD,
        MarketType.GAME_TOTAL,
        MarketType.TEAM_TOTAL,
        MarketType.FIRST_HALF_WINNER_3WAY,
        MarketType.FIRST_HALF_TOTAL,
        MarketType.BTTS,
        MarketType.FIRST_HALF_BTTS,
        MarketType.PLAYER_GOALS,
    }
    assert expected <= table_values


# --- poly team-name alias overlay ---
#
# The 5 MLS franchises whose poly question name and Optic fixture name share
# no containment substring under plain mlb_suffix matching (wave-4 probe
# section D). Tested at the _match_poly_fixture level per task-7a-brief.md:
# a synthetic Optic fixture named the optic way + a parsed poly market named
# the poly way must resolve through team_alias_scope(cfg.team_name_aliases).


class _FX:
    """Minimal optic-fixture stand-in carrying only what _match_poly_fixture reads."""

    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _mls_parsed(team_a_poly_name: str, team_b_poly_name: str, date: str):
    """A minimal GAME-scope ParsedMarket with poly team names pre-normalized
    the way parse_question's soccer rules would (mlb_suffix, MLS's style)."""
    return pm.ParsedMarket(
        market_type=MarketType.MONEYLINE_3WAY,
        team_a=pm._norm_name(team_a_poly_name, "mlb_suffix"),
        team_b=pm._norm_name(team_b_poly_name, "mlb_suffix"),
        side_mode=pm.SideMode.THREE_WAY_FIXED,
        date=date,
    )


def test_mls_alias_resolves_cf_montreal_fixture():
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Club de Foot Montréal", "Austin FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("CF Montréal", "Austin FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_mls_alias_resolves_la_galaxy_fixture():
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("LA Galaxy", "Austin FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("Los Angeles Galaxy", "Austin FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_mls_alias_resolves_nycfc_fixture():
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("New York City Football Club", "Austin FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("New York City FC", "Austin FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_mls_alias_resolves_dc_united_fixture():
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("DC United", "Austin FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("D.C. United SC", "Austin FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_mls_alias_resolves_inter_miami_fixture():
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Club Internacional de Fútbol Miami", "Austin FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("Inter Miami CF", "Austin FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_mls_alias_without_scope_does_not_match():
    # Without team_alias_scope active, the mismatch is real: plain
    # containment alone can never bridge "cf montreal" / "club de foot
    # montreal" -- confirms the overlay (not some incidental normalization
    # change) is what makes the above tests pass.
    fixtures = [_FX("Club de Foot Montréal", "Austin FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("CF Montréal", "Austin FC", "2026-07-22")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_mls_alias_regression_normal_franchise_still_matches():
    # Austin FC <-> Austin FC: plain containment, unaffected by the alias
    # overlay being active -- regression guard for the ~30 other MLS
    # franchises that already reconcile without an alias.
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Austin FC", "Seattle Sounders FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("Austin FC", "Seattle Sounders FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_mls_alias_genuinely_absent_team_still_drops():
    # A team that's neither the real fixture nor an alias target must still
    # drop -- the overlay must never manufacture a match out of thin air.
    cfg = LEAGUES["mls"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Austin FC", "Seattle Sounders FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("Toronto FC", "Charlotte FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is None


# === Task 7b: wire Liga MX + UCL (poly-only, KALSHI=None), cloned from MLS's
# Task 7a pattern, plus each league's own team-name alias overlay
# (wave-4-probe-findings.md section D method, applied fresh per league --
# see LEAGUES['liga_mx'].py's / LEAGUES['ucl'].py's module docstrings for the live-data provenance
# of every alias below) ===


@pytest.mark.parametrize("league", ["liga_mx", "ucl"])
def test_expansion_league_in_leagues(league):
    assert league in LEAGUES


def test_liga_mx_multiexchange_after_merge():
    league = LEAGUES["liga_mx"]
    assert league.KALSHI is not None
    assert league.CRYPTO is not None
    assert league.POLYMARKET is not None


def test_ucl_multiexchange_after_merge():
    # Post-merge with `test`: UCL gained Kalshi (KXUCL) + crypto coverage
    # (test-branch UCL config), unioned with the Polymarket config added here.
    # It is no longer poly-only.
    league = LEAGUES["ucl"]
    assert league.KALSHI is not None
    assert league.CRYPTO is not None
    assert league.POLYMARKET is not None


@pytest.mark.parametrize("league", ["liga_mx", "ucl"])
def test_expansion_league_polymarket_config_present(league):
    cfg = LEAGUES[league].POLYMARKET
    assert cfg is not None
    assert cfg.market_types == pm.SOCCER_MARKET_TYPES
    assert cfg.market_rules is pm.soccer_market_rules


def test_liga_mx_polymarket_slug_and_optic_league_id():
    # Slug prefix "mex" is deliberately NOT "mexico"/"liga_mx" (wave-4 probe
    # section C footnote) -- distinct from the Optic league_id on purpose.
    cfg = LEAGUES["liga_mx"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "mex"
    assert cfg.optic_league_id == "mexico_-_liga_mx"


def test_ucl_polymarket_slug_and_optic_league_id():
    cfg = LEAGUES["ucl"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "ucl"
    assert cfg.optic_league_id == "uefa_-_champions_league"


@pytest.mark.parametrize("league", ["liga_mx", "ucl"])
def test_expansion_league_optic_table_types_covers_9_soccer_market_types(league):
    table_values = set(LEAGUES[league].OPTIC.table_types.values())
    expected = {
        MarketType.MONEYLINE_3WAY,
        MarketType.POINT_SPREAD,
        MarketType.GAME_TOTAL,
        MarketType.TEAM_TOTAL,
        MarketType.FIRST_HALF_WINNER_3WAY,
        MarketType.FIRST_HALF_TOTAL,
        MarketType.BTTS,
        MarketType.FIRST_HALF_BTTS,
        MarketType.PLAYER_GOALS,
    }
    assert expected <= table_values


# --- poly team-name alias overlay: Liga MX (4 franchises, LEAGUES['liga_mx'].py) ---
#
# Each pair below is a (poly question name, Optic fixture name) mismatch from
# LEAGUES['liga_mx'].py's TEAM_NAME_ALIASES / module docstring, confirmed via a live BQ
# bridge pull + a live Optic fixtures/active pull (18/18 Liga MX clubs).
_LIGA_MX_ALIAS_CASES = [
    ("Atlético San Luis", "Atlético de San Luis"),
    ("CF América", "Club de Fútbol América"),
    ("Pumas de la UNAM", "Pumas de la Universidad Nacional Autonoma de Mexico"),
    ("Tigres de la UANL", "Club Tigres de la Universidad Autónoma de Nuevo León"),
]


@pytest.mark.parametrize("poly_name,optic_name", _LIGA_MX_ALIAS_CASES)
def test_liga_mx_alias_resolves_fixture(poly_name, optic_name):
    cfg = LEAGUES["liga_mx"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "CF Pachuca", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed(poly_name, "CF Pachuca", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


@pytest.mark.parametrize("poly_name,optic_name", _LIGA_MX_ALIAS_CASES)
def test_liga_mx_alias_without_scope_does_not_match(poly_name, optic_name):
    # Confirms the overlay (not incidental normalization) bridges the gap --
    # same regression shape as test_mls_alias_without_scope_does_not_match.
    fixtures = [_FX(optic_name, "CF Pachuca", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed(poly_name, "CF Pachuca", "2026-07-22")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_liga_mx_alias_regression_normal_franchise_still_matches():
    # Atlante FC <-> Atlante FC: plain containment, unaffected by the overlay
    # being active -- regression guard for the 14 other Liga MX clubs that
    # already reconcile without an alias.
    cfg = LEAGUES["liga_mx"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Atlante FC", "Atlas FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("Atlante FC", "Atlas FC", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_liga_mx_alias_genuinely_absent_team_still_drops():
    cfg = LEAGUES["liga_mx"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Atlante FC", "Atlas FC", "2026-07-22T23:30:00Z")]
    parsed = _mls_parsed("Club Necaxa", "Club Puebla", "2026-07-22")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is None


# --- poly team-name alias overlay: UCL (13 franchises, LEAGUES['ucl'].py) ---
#
# Each pair below is a (poly question name, Optic fixture name) mismatch from
# LEAGUES['ucl'].py's TEAM_NAME_ALIASES / module docstring, each confirmed via a live
# same-fixture cross-check (same opponent + same/adjacent date) between the
# BQ poly bridge pull and a live Optic fixtures/active pull.
_UCL_ALIAS_CASES = [
    ("Aarhus GF", "Aarhus Gymnastikforening"),
    ("Ararat-Armenia FA", "Ararat-Armenia FC"),
    ("Qairat FK", "Kairat Almaty"),
    ("AS Omónoia Leukosías", "AC Omonia Nicosia"),
    ("KF Egnatia Rrogozhinë", "KS Egnatia Rrogozhinë"),
    ("SK Puntigamer Sturm Graz", "SK Sturm Graz"),
    ("Fenerbahçe SK", "Fenerbahçe Spor Kulübü"),
    ("Universitatea Craiova CS", "Universitatea Craiova 1948 Club Sportiv"),
    ("MH Hapoel Be'er Sheva", "Hapoel Be'er Sheva FC"),
    ("KF Víkingur", "Víkingur Reykjavík"),
    ("SK Iberia 1999", "FC Iberia 1999"),
    ("Kuopion PS", "Kuopion Palloseura"),
]


@pytest.mark.parametrize("poly_name,optic_name", _UCL_ALIAS_CASES)
def test_ucl_alias_resolves_fixture(poly_name, optic_name):
    cfg = LEAGUES["ucl"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "Larne FC", "2026-07-29T18:00:00Z")]
    parsed = _mls_parsed(poly_name, "Larne FC", "2026-07-29")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


@pytest.mark.parametrize("poly_name,optic_name", _UCL_ALIAS_CASES)
def test_ucl_alias_without_scope_does_not_match(poly_name, optic_name):
    fixtures = [_FX(optic_name, "Larne FC", "2026-07-29T18:00:00Z")]
    parsed = _mls_parsed(poly_name, "Larne FC", "2026-07-29")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


@pytest.mark.parametrize(
    "poly_name,optic_name",
    [
        # FK Crvena zvezda / FC Thun: both already resolve via plain
        # containment (poly's shorter name is a prefix-substring of Optic's
        # full name) -- deliberately NOT in TEAM_NAME_ALIASES (FC Thun was an
        # early alias-candidate draft, caught as redundant and dropped -- see
        # LEAGUES['ucl'].py's docstring). Regression guard that the overlay being active
        # doesn't disturb either.
        ("FK Crvena zvezda", "FK Crvena zvezda Beograd"),
        ("FC Thun", "FC Thun Berner Oberland"),
    ],
)
def test_ucl_alias_regression_normal_franchise_still_matches(poly_name, optic_name):
    cfg = LEAGUES["ucl"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "Larne FC", "2026-07-29T18:00:00Z")]
    parsed = _mls_parsed(poly_name, "Larne FC", "2026-07-29")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_ucl_alias_genuinely_absent_team_still_drops():
    # A club not covered by this wave's alias pull (e.g. FC Flora -- see
    # LEAGUES['ucl'].py's docstring "NOT aliased" list) must still drop safely, not
    # invent a match.
    cfg = LEAGUES["ucl"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("FK Crvena zvezda Beograd", "Larne FC", "2026-07-29T18:00:00Z")]
    parsed = _mls_parsed("FC Flora", "FK Vardar Skopje", "2026-07-29")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is None


# --- poly team-name alias overlay: club friendlies (3 pins, LEAGUES['international_club_friendlies'].py) ---
# Evidence: rs-marketmaking opticodds_fixtures 2026-08-11/12/14 + RFQ Yes gaps.
_CLF_ALIAS_CASES = [
    ("Athletic Bilbao", "Athletic Club"),
    ("Borussia Monchengladbach", "Borussia M'gladbach"),
    ("RC Deportivo De La Coruna", "Deportivo La Coruna"),
]


@pytest.mark.parametrize("poly_name,optic_name", _CLF_ALIAS_CASES)
def test_clf_alias_resolves_fixture(poly_name, optic_name):
    cfg = LEAGUES["international_club_friendlies"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "Real Madrid", "2026-08-12T18:00:00Z")]
    parsed = _mls_parsed(poly_name, "Real Madrid", "2026-08-12")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


@pytest.mark.parametrize("poly_name,optic_name", _CLF_ALIAS_CASES)
def test_clf_alias_without_scope_does_not_match(poly_name, optic_name):
    fixtures = [_FX(optic_name, "Real Madrid", "2026-08-12T18:00:00Z")]
    parsed = _mls_parsed(poly_name, "Real Madrid", "2026-08-12")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_clf_alias_regression_normal_franchise_still_matches():
    cfg = LEAGUES["international_club_friendlies"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("Coventry City", "AS Monaco", "2026-08-14T18:00:00Z")]
    parsed = _mls_parsed("Coventry City", "AS Monaco", "2026-08-14")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


# === Task R2: wire Task R1's 10 rescue-tier recognizers' MarketTypes into
# all 5 soccer leagues' OpticConfig.table_types
# (wave-rescue-probe-findings.md section B / task-r1-report.md) ===
#
# Task R1 shipped the recognizers (soccer_market_rules grew 11 -> 21) but
# deliberately left every league's OpticConfig.table_types untouched, so a
# rescue-form poly row parsed fine but had no matching optic row to stamp
# onto. This task wires 9 of those 10 new MarketTypes (every rescue form
# except "Neither team to score first?", which R1 intentionally left
# unmapped -- see task-r1-report.md) onto the exact optic market_id strings
# from the probe's section B, uniformly across all 5 soccer leagues.

_RESCUE_SOCCER_LEAGUES = [
    "world_cup", "epl", "mls", "liga_mx", "ucl",
]

# optic market_id -> MarketType, byte-exact from wave-rescue-probe-findings.md
# section B (B.1 correct_score is explicitly OUT of scope for this task).
_RESCUE_TABLE_TYPES: dict[str, MarketType] = {
    "2nd_half_moneyline":     MarketType.SECOND_HALF_WINNER_3WAY,
    "first_team_to_score":    MarketType.FIRST_TEAM_TO_SCORE,
    "2nd_half_total_goals":   MarketType.SECOND_HALF_TOTAL,
    "1st_half_team_total":    MarketType.FIRST_HALF_TEAM_TOTAL,
    "2nd_half_team_total":    MarketType.SECOND_HALF_TEAM_TOTAL,
    "player_assists":         MarketType.PLAYER_ASSISTS,
    "player_shots":           MarketType.PLAYER_SHOTS,
    "player_shots_on_target": MarketType.PLAYER_SHOTS_ON_TARGET,
    "player_goals_+_assists": MarketType.PLAYER_GOALS_OR_ASSIST,
}


@pytest.mark.parametrize("league", _RESCUE_SOCCER_LEAGUES)
def test_rescue_tier_optic_table_types_wired(league):
    """Every soccer league's OpticConfig.table_types carries all 9 rescue-tier
    optic market_id -> MarketType entries, so a poly row parsed by one of
    Task R1's new recognizers finds a matching optic row to stamp onto."""
    table_types = LEAGUES[league].OPTIC.table_types
    for market_id, expected_type in _RESCUE_TABLE_TYPES.items():
        assert market_id in table_types, (league, market_id)
        assert table_types[market_id] == expected_type, (league, market_id)


@pytest.mark.parametrize("league", _RESCUE_SOCCER_LEAGUES)
def test_rescue_tier_wiring_keeps_preexisting_keys(league):
    """Regression guard: extending table_types must not remove or overwrite
    any previously-wired optic market_id -> MarketType entry."""
    table_types = LEAGUES[league].OPTIC.table_types
    assert table_types["moneyline"] == MarketType.MONEYLINE_3WAY
    assert table_types["asian_handicap"] == MarketType.POINT_SPREAD
    assert table_types["total_goals"] == MarketType.GAME_TOTAL
    # EPL used to be the one soccer league missing the other 6 original soccer
    # keys (its table_types was built for Kalshi parity -- task-6-report.md).
    # A 2026-07-27 BQ census of opticodds_prices showed optic prices all six
    # for england_-_premier_league (14d: 1st_half_total_goals 86k ticks,
    # team_total 20k, 1st_half_moneyline 7.3k, both_teams_to_score 687,
    # 1st_half_both_teams_to_score 611), so poly BTTS/1H/team-total/
    # player-goals legs on EPL were dropping for want of an optic row to stamp
    # onto. EPL is now wired like every other soccer league, so this test no
    # longer special-cases it.
    assert table_types["team_total"] == MarketType.TEAM_TOTAL
    assert table_types["1st_half_moneyline"] == MarketType.FIRST_HALF_WINNER_3WAY
    assert table_types["1st_half_total_goals"] == MarketType.FIRST_HALF_TOTAL
    assert table_types["both_teams_to_score"] == MarketType.BTTS
    assert table_types["1st_half_both_teams_to_score"] == MarketType.FIRST_HALF_BTTS
    assert table_types["player_goals"] == MarketType.PLAYER_GOALS


@pytest.mark.parametrize("league", _RESCUE_SOCCER_LEAGUES)
def test_rescue_tier_table_types_no_collision_with_existing_values(league):
    """The 9 new MarketTypes are distinct from every pre-existing
    OpticConfig.table_types value for that league (no accidental key
    aliasing onto an already-used MarketType)."""
    table_types = LEAGUES[league].OPTIC.table_types
    preexisting_values = {
        mt for market_id, mt in table_types.items()
        if market_id not in _RESCUE_TABLE_TYPES
    }
    assert not preexisting_values & set(_RESCUE_TABLE_TYPES.values())


def test_rescue_tier_output_order_covers_new_types_per_league():
    """Sanity guard mirroring test_table_completeness's global invariant,
    scoped to just the 9 rescue types this task adds -- every league's
    OUTPUT_ORDER must include each rescue MarketType it now uses via
    OPTIC.table_types (otherwise the global completeness test would already
    catch it, but this pins the rescue-specific cause if it regresses)."""
    for league in _RESCUE_SOCCER_LEAGUES:
        cfg = LEAGUES[league]
        order_set = set(cfg.OUTPUT_ORDER)
        for mt in _RESCUE_TABLE_TYPES.values():
            assert mt in order_set, (league, mt)


# === Corners / saves parity (2026-07-27 MAPPING_FAILED audit) ==================
#
# "<A> vs. <B>: O/U <N> Total Corners" was the largest addressable soccer
# market-type gap in the audit (~$3.5M declined stake over 48h; the top
# unmapped form for bra/mex/swe/nor/kor/uslc), and optic prices `total_corners`
# for every wired soccer league. `player_saves` is the same story at World Cup
# scale. Both use a real cfg built from the shipped SOCCER_MARKET_TYPES /
# soccer_market_rules so these tests also cover the dispatch wiring.

CORNERS_CFG = pm.PolymarketConfig(
    slug_prefix="mls",
    optic_league_id="usa_-_major_league_soccer",
    market_types=pm.SOCCER_MARKET_TYPES,
    question_style="mlb_suffix",
    market_rules=pm.soccer_market_rules,
)


def test_soccer_total_corners_parse():
    pm_ = pm.soccer_total_corners_rule(
        "Austin FC vs. Seattle Sounders FC: O/U 9.5 Total Corners", CORNERS_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.TOTAL_CORNERS
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.market_type.scope == Scope.GAME
    assert pm_.line == 9.5
    assert pm_.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert pm_.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")


def test_soccer_team_total_corners_parse():
    pm_ = pm.soccer_team_total_corners_rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC O/U 5.5 Corners", CORNERS_CFG
    )
    assert pm_ is not None
    assert pm_.market_type == MarketType.TEAM_TOTAL_CORNERS
    assert pm_.side_mode == pm.SideMode.OVER_UNDER
    assert pm_.market_type.scope == Scope.TEAM
    assert pm_.line == 5.5
    assert pm_.entity == pm._norm_name("Austin FC", "mlb_suffix")


@pytest.mark.parametrize("question", [
    # Half-corners: optic prices no 1st/2nd-half corners market, so these must
    # stay unmapped rather than land on the full-game corners line.
    "Austin FC vs. Seattle Sounders FC: 1st Half O/U 4.5 Total Corners",
    "Austin FC vs. Seattle Sounders FC: 2nd Half O/U 4.5 Total Corners",
    # The two non-O/U corners forms poly lists; no optic market for either.
    "Austin FC vs. Seattle Sounders FC: Total Corners Odd or Even?",
    "Austin FC vs. Seattle Sounders FC: Team to Take First Corner",
    # A goals total must never be read as a corners total.
    "Austin FC vs. Seattle Sounders FC: O/U 2.5",
])
def test_soccer_total_corners_rejects_non_full_game_corners(question):
    assert pm.soccer_total_corners_rule(question, CORNERS_CFG) is None


@pytest.mark.parametrize("question", [
    "Austin FC vs. Seattle Sounders FC: O/U 9.5 Total Corners",
    "Austin FC vs. Seattle Sounders FC: 1st Half O/U 4.5 Total Corners",
    "Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5",
])
def test_soccer_team_total_corners_rejects_non_team_corners(question):
    assert pm.soccer_team_total_corners_rule(question, CORNERS_CFG) is None


@pytest.mark.parametrize("rule", [
    pm.soccer_total_rule,
    pm.soccer_team_total_rule,
    pm.soccer_first_half_total_rule,
    pm.soccer_second_half_total_rule,
])
def test_corners_question_not_captured_by_any_goals_total_rule(rule):
    """Flip-safety: a corners question stamped onto a goals total would be a
    wrong-market mismap. Every goals-based O/U rule must reject it outright
    (each anchors `$` right after its line group, so the " Total Corners" tail
    can't be swallowed)."""
    assert rule(
        "Austin FC vs. Seattle Sounders FC: O/U 9.5 Total Corners", CORNERS_CFG
    ) is None
    assert rule(
        "Austin FC vs. Seattle Sounders FC: Austin FC O/U 5.5 Corners", CORNERS_CFG
    ) is None


def test_soccer_total_corners_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_total_corners_rule(
        "Austin FC vs. Seattle Sounders FC: O/U 9.5 Total Corners", cfg
    ) is None


def test_parse_question_dispatches_total_corners():
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: O/U 9.5 Total Corners", CORNERS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.TOTAL_CORNERS
    assert out.line == 9.5


def test_parse_question_dispatches_team_total_corners():
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: Seattle Sounders FC O/U 4.5 Corners",
        CORNERS_CFG,
    )
    assert out is not None
    assert out.market_type == MarketType.TEAM_TOTAL_CORNERS
    assert out.entity == pm._norm_name("Seattle Sounders FC", "mlb_suffix")
    assert out.line == 4.5


def test_parse_question_still_dispatches_plain_goals_total():
    """Regression guard: adding the corners rule ahead of the goals-total
    family must not divert the plain goals total."""
    out = pm.parse_question(
        "Austin FC vs. Seattle Sounders FC: O/U 2.5", CORNERS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL
    assert out.line == 2.5


def test_soccer_player_saves_parse():
    pm_ = pm.soccer_player_saves_rule("Emiliano Martínez: 3+ saves", CORNERS_CFG)
    assert pm_ is not None
    assert pm_.market_type == MarketType.PLAYER_SAVES
    assert pm_.side_mode == pm.SideMode.YESNO_AS_OU
    assert pm_.market_type.scope == Scope.PLAYER
    # "N+" is an at-least ladder -> over N-0.5, same as the goals/shots ladders.
    assert pm_.line == 2.5
    assert pm_.entity == normalize_player_name("Emiliano Martínez")


@pytest.mark.parametrize("question", [
    "Emiliano Martínez: 3+ shots",
    "Emiliano Martínez: 3+ goals",
    "Emiliano Martínez: 3+ assists",
    "Emiliano Martínez: 3+ shots on target",
])
def test_soccer_player_saves_rejects_other_stat_ladders(question):
    assert pm.soccer_player_saves_rule(question, CORNERS_CFG) is None


def test_parse_question_dispatches_player_saves():
    out = pm.parse_question("Emiliano Martínez: 3+ saves", CORNERS_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_SAVES
    assert out.line == 2.5


# Derived from the tip rather than a Python League enum so this stays an
# invariant ("EVERY wired soccer league prices corners") instead of a snapshot
# of whichever leagues existed when it was written.
_SOCCER_LEAGUES = sorted(
    slug for slug, cfg in LEAGUES.items() if cfg.sport == Sport.SOCCER
)


@pytest.mark.parametrize("league", _SOCCER_LEAGUES)
def test_total_corners_wired_and_in_output_order(league):
    cfg = LEAGUES[league]
    assert cfg.OPTIC.table_types["total_corners"] == MarketType.TOTAL_CORNERS
    assert MarketType.TOTAL_CORNERS in set(cfg.OUTPUT_ORDER)


@pytest.mark.parametrize("league", _SOCCER_LEAGUES)
def test_team_total_corners_wired_and_in_output_order(league):
    cfg = LEAGUES[league]
    assert cfg.OPTIC.table_types["team_total_corners"] == MarketType.TEAM_TOTAL_CORNERS
    assert MarketType.TEAM_TOTAL_CORNERS in set(cfg.OUTPUT_ORDER)

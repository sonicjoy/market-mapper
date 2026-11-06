"""Unit tests for Task R4: poly "Exact Score" <-> optic `correct_score`.

Covers `soccer_exact_score_rule`, the frozen-but-PURELY-ADDITIVE EXACT_SCORE
branch of `polymarket.build_rows`, the equally-additive CORRECT_SCORE branch
of `optic.build_rows`, and — the critical proof — that the two branches
produce a byte-identical row_key so a poly leg actually stamps onto the
matching optic row via `pipeline.attach_polymarket_row`.

Question template + Optic selection/selection_line shape are byte-exact
from `.superpowers/sdd/wave-rescue-probe-findings.md` sections A.1/B.1.
"""

from mappers.exchanges import optic
from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType, Scope, Shape
from mappers.pipeline import attach_polymarket_row, row_key
from mappers.run import LEAGUES
from mappers.shared import TIE_SIDE, normalize_line

# Minimal soccer test config exercising only the exact_score recognizer
# (mirrors SOCCER_CFG's pattern in test_polymarket_soccer.py).
SOCCER_CFG = pm.PolymarketConfig(
    slug_prefix="mls",
    optic_league_id="usa_-_major_league_soccer",
    market_types={"exact_score": MarketType.CORRECT_SCORE},
    question_style="mlb_suffix",
    market_rules=(pm.soccer_exact_score_rule,),
)

START_DATE = "2026-07-22T23:00:00Z"
HOME, AWAY = "ATX", "SEA"
HOME_NAME, AWAY_NAME = "Austin FC", "Seattle Sounders FC"
LEAGUE_ID = "usa_-_major_league_soccer"


# === soccer_exact_score_rule (recognizer) ===


def test_soccer_exact_score_binds_scoreline():
    parsed = pm.soccer_exact_score_rule(
        "Exact Score: Austin FC 2 - 1 Seattle Sounders FC?", SOCCER_CFG
    )
    assert parsed is not None
    assert parsed.market_type == MarketType.CORRECT_SCORE
    assert parsed.market_type.scope == Scope.GAME
    assert parsed.market_type.shape == Shape.CORRECT_SCORE
    assert parsed.side_mode == pm.SideMode.EXACT_SCORE
    assert parsed.team_a == pm._norm_name("Austin FC", "mlb_suffix")
    assert parsed.team_b == pm._norm_name("Seattle Sounders FC", "mlb_suffix")
    assert parsed.team_a_goals == 2
    assert parsed.team_b_goals == 1


def test_soccer_exact_score_any_other_score_drops():
    # Never invent: the catch-all sibling has no digit group at all, so it
    # structurally fails _Q_SOCCER_EXACT_SCORE and returns None.
    assert pm.soccer_exact_score_rule("Exact Score: Any Other Score?", SOCCER_CFG) is None


def test_soccer_exact_score_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="mls", optic_league_id="usa_-_major_league_soccer",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.soccer_exact_score_rule(
        "Exact Score: Austin FC 2 - 1 Seattle Sounders FC?", cfg
    ) is None


def test_soccer_exact_score_rejects_non_exact_score_question():
    assert pm.soccer_exact_score_rule(
        "Austin FC vs. Seattle Sounders FC: O/U 2.5", SOCCER_CFG
    ) is None


# === build_rows (polymarket.py) — EXACT_SCORE branch ===


def _score_mkt(question):
    return pm.PolyMarket(
        condition_id="0xabc", slug="mls-atx-sea-2026-07-22",
        question=question,
        outcomes=[
            pm.PolyOutcome(clob_token_id="cY", position_id="pY", outcome_label="Yes", outcome_index=0),
            pm.PolyOutcome(clob_token_id="cN", position_id="pN", outcome_label="No", outcome_index=1),
        ],
    )


def _poly_rows(question):
    m = _score_mkt(question)
    parsed = pm.soccer_exact_score_rule(m.question, SOCCER_CFG)
    assert parsed is not None
    return pm.build_rows(
        m, parsed, home=HOME, away=AWAY,
        home_name=HOME_NAME, away_name=AWAY_NAME,
        start_date=START_DATE, cfg=SOCCER_CFG, league=LEAGUE_ID,
    )


def test_build_rows_exact_score_home_win():
    rows = _poly_rows("Exact Score: Austin FC 2 - 1 Seattle Sounders FC?")
    assert len(rows) == 1  # only "Yes" emits; "No" drops
    r = rows[0]
    assert r.polymarket_clob_token_id == "cY"
    assert r.market_type == "correct_score"
    assert r.entity is None
    assert r.side == HOME
    assert normalize_line(r.line) == normalize_line(2 + 1 / 100.0)


def test_build_rows_exact_score_away_win_is_winner_anchored():
    # Austin (home) 1, Seattle (away) 2 -> Seattle wins -> side=away,
    # scoreline is winner's-goals-first (2, 1), NOT team_a's-goals-first
    # (1, 2) -- same numeric line as a home team winning 2-1.
    rows = _poly_rows("Exact Score: Austin FC 1 - 2 Seattle Sounders FC?")
    assert len(rows) == 1
    r = rows[0]
    assert r.side == AWAY
    assert normalize_line(r.line) == normalize_line(2 + 1 / 100.0)


def test_build_rows_exact_score_draw():
    rows = _poly_rows("Exact Score: Austin FC 1 - 1 Seattle Sounders FC?")
    assert len(rows) == 1
    r = rows[0]
    assert r.side == TIE_SIDE
    assert normalize_line(r.line) == normalize_line(1 + 1 / 100.0)


def test_build_rows_exact_score_drops_when_named_teams_absent():
    # Flip-safety: neither named team resolves to a fixture side -> drop
    # whole, never guess.
    rows = _poly_rows("Exact Score: Somebody 2 - 1 Else FC?")
    assert rows == []


def test_build_rows_exact_score_drops_when_both_teams_resolve_same_side():
    # Both captured names match the SAME fixture side (e.g. a stray
    # containment collision) -> ambiguous, drop rather than guess.
    rows = _poly_rows("Exact Score: Austin FC 2 - 1 Austin FC?")
    assert rows == []


# === build_rows (optic.py) — CORRECT_SCORE branch ===

OPTIC_CFG = optic.OpticConfig(
    league_id=LEAGUE_ID,
    table_types={"correct_score": MarketType.CORRECT_SCORE},
)
TEAM_MAP = {"T_ATX": HOME, "T_SEA": AWAY}


def _optic_row(*, selection: str, selection_line: str, team_id: str | None):
    odd = optic.Odd(
        id="O1", market_id="correct_score", selection=selection,
        selection_line=selection_line, team_id=team_id, grouping_key="g1",
    )
    fixture = optic.Fixture(
        fixture_id="FIX1", game_id="game-1", sportradar_id=None,
        start_et="2026-07-22T19:00:00", start_date=START_DATE,
        home=HOME, away=AWAY, home_name=HOME_NAME, away_name=AWAY_NAME,
        team_map=TEAM_MAP, odds=[odd], is_live=False,
    )
    rows, odd_lookup, _ = optic.build_rows(
        START_DATE, HOME, AWAY, fixture, OPTIC_CFG, league=LEAGUE_ID,
    )
    assert len(rows) == 1
    return rows[0]


def test_optic_build_rows_correct_score_home_anchored():
    r = _optic_row(selection=HOME_NAME, selection_line="2:1", team_id="T_ATX")
    assert r.market_type == "correct_score"
    assert r.entity is None
    assert r.side == HOME
    assert normalize_line(r.line) == normalize_line(2 + 1 / 100.0)


def test_optic_build_rows_correct_score_away_anchored():
    r = _optic_row(selection=AWAY_NAME, selection_line="2:1", team_id="T_SEA")
    assert r.side == AWAY
    assert normalize_line(r.line) == normalize_line(2 + 1 / 100.0)


def test_optic_build_rows_correct_score_draw():
    r = _optic_row(selection="Draw", selection_line="1:1", team_id=None)
    assert r.side == TIE_SIDE
    assert normalize_line(r.line) == normalize_line(1 + 1 / 100.0)


# === The join test (critical): poly EXACT_SCORE row and optic
#     CORRECT_SCORE row for the SAME real scoreline must produce a
#     byte-identical row_key, so a poly leg actually stamps onto the optic
#     row via pipeline.attach_polymarket_row (the real production path —
#     not just a field-by-field comparison). ===


def _assert_joins(poly_question: str, *, optic_selection: str, optic_selection_line: str,
                   optic_team_id: str | None):
    optic_row = _optic_row(
        selection=optic_selection, selection_line=optic_selection_line, team_id=optic_team_id,
    )
    poly_rows = _poly_rows(poly_question)
    assert len(poly_rows) == 1
    poly_row = poly_rows[0]

    # Key fields byte-identical (market_type, entity, line, side — the part
    # of row_key beyond the shared league/start_date/home/away/grouping_key).
    assert poly_row.market_type == optic_row.market_type
    assert poly_row.entity == optic_row.entity
    assert normalize_line(poly_row.line) == normalize_line(optic_row.line)
    assert poly_row.side == optic_row.side

    row_index = {row_key(optic_row): optic_row}
    result = attach_polymarket_row(row_index, poly_row)
    assert result == "stamped"
    assert optic_row.polymarket_clob_token_id == poly_row.polymarket_clob_token_id


def test_join_home_win():
    _assert_joins(
        "Exact Score: Austin FC 2 - 1 Seattle Sounders FC?",
        optic_selection=HOME_NAME, optic_selection_line="2:1", optic_team_id="T_ATX",
    )


def test_join_away_win_winner_anchor_swap():
    # poly "A 1 - 2 B" (home=1, away=2) must join optic's away-anchored
    # selection=B, selection_line="2:1" (B's own goals first) -- the
    # winner-anchor swap the probe's B.1 section documents.
    _assert_joins(
        "Exact Score: Austin FC 1 - 2 Seattle Sounders FC?",
        optic_selection=AWAY_NAME, optic_selection_line="2:1", optic_team_id="T_SEA",
    )


def test_join_draw():
    _assert_joins(
        "Exact Score: Austin FC 1 - 1 Seattle Sounders FC?",
        optic_selection="Draw", optic_selection_line="1:1", optic_team_id=None,
    )


# === Config: correct_score -> CORRECT_SCORE wired into all 5 soccer leagues ===

_SOCCER_LEAGUES = ("mls", "liga_mx", "ucl", "epl", "world_cup")


def test_correct_score_wired_into_all_5_soccer_optic_configs():
    for league_key in _SOCCER_LEAGUES:
        league = LEAGUES[league_key]
        assert league.OPTIC.table_types.get("correct_score") == MarketType.CORRECT_SCORE, league_key
        assert MarketType.CORRECT_SCORE in league.OUTPUT_ORDER, league_key


def test_correct_score_key_wired_into_shared_soccer_market_types():
    assert pm.SOCCER_MARKET_TYPES.get("exact_score") == MarketType.CORRECT_SCORE


def test_soccer_market_rules_includes_exact_score_rule():
    assert pm.soccer_exact_score_rule in pm.soccer_market_rules

"""Unit tests for the basketball recognizer surface (Wave 5, Task 2).

Per `.superpowers/sdd/wave-5-probe-findings.md` (sections B/C), WNBA poly
offers exactly 6 forms, all structurally identical to existing MLB rules:

  - moneyline: bare "<A> vs. <B>"                      -> reuses mlb_moneyline_rule
  - game total: "<A> vs. <B>: O/U <N>"                 -> reuses mlb_total_rule
  - spread: "Spread: <Team> (-N)"                      -> reuses mlb_spread_rule
  - player points: "<Player>: Points O/U <N>"          -> NEW, YESNO_AS_OU
  - player rebounds: "<Player>: Rebounds O/U <N>"      -> NEW, YESNO_AS_OU
  - player assists: "<Player>: Assists O/U <N>"        -> NEW, YESNO_AS_OU

The one deviation from the MLB player-prop template: WNBA player props use
Yes/No outcome labels (not Over/Under), confirmed 100% across 962 probe rows,
so each new rule passes side_mode=SideMode.YESNO_AS_OU explicitly (NOT
_player_prop_rule's OVER_UNDER default).

Question templates + outcome labels are byte-exact from the probe.
"""

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType, Scope
from mappers.shared import normalize_player_name

# Basketball test config (mirrors SOCCER_CFG / MLB_FULL_CFG in the sibling
# test modules): question_style="mlb_suffix" per the probe; market_types
# carries exactly the keys the 6 reused/new rules look up.
BB_CFG = pm.PolymarketConfig(
    slug_prefix="wnba",
    optic_league_id="wnba",
    market_types=pm.BASKETBALL_MARKET_TYPES,
    question_style="mlb_suffix",
    market_rules=pm.basketball_market_rules,
)


def _bb_mkt(question, outcomes):
    return pm.PolyMarket(
        condition_id="0xabc", slug="wnba-chi-dal-2026-07-28",
        question=question,
        outcomes=[pm.PolyOutcome(**o) for o in outcomes],
    )


# --- moneyline (reused mlb_moneyline_rule) ---


def test_basketball_moneyline_parse():
    out = pm.mlb_moneyline_rule("Chicago Sky vs. Dallas Wings", BB_CFG)
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE
    assert out.market_type.scope == Scope.GAME
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == pm._norm_name("Chicago Sky", "mlb_suffix")
    assert out.team_b == pm._norm_name("Dallas Wings", "mlb_suffix")


# --- game total (reused mlb_total_rule) ---


def test_basketball_total_parse():
    out = pm.mlb_total_rule("Chicago Sky vs. Dallas Wings: O/U 176.5", BB_CFG)
    assert out is not None
    assert out.market_type == MarketType.GAME_TOTAL
    assert out.market_type.scope == Scope.GAME
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.line == 176.5
    assert out.team_a == pm._norm_name("Chicago Sky", "mlb_suffix")
    assert out.team_b == pm._norm_name("Dallas Wings", "mlb_suffix")


# --- spread (reused mlb_spread_rule) ---


def test_basketball_spread_parse():
    out = pm.mlb_spread_rule("Spread: Minnesota Lynx (-12.5)", BB_CFG)
    assert out is not None
    assert out.market_type == MarketType.POINT_SPREAD
    assert out.market_type.scope == Scope.GAME
    assert out.side_mode == pm.SideMode.SPREAD_TEAM
    assert out.entity == pm._norm_name("Minnesota Lynx", "mlb_suffix")
    assert out.line == -12.5


# --- player points (NEW) ---


def test_basketball_player_points_parse():
    out = pm.basketball_player_points_rule("Paige Bueckers: Points O/U 21.5", BB_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_POINTS
    assert out.market_type.scope == Scope.PLAYER
    assert out.side_mode == pm.SideMode.YESNO_AS_OU
    assert out.entity == normalize_player_name("Paige Bueckers")
    assert out.line == 21.5
    assert out.team_a is None and out.team_b is None


def test_basketball_player_points_rejects_missing_kind_config():
    cfg = pm.PolymarketConfig(
        slug_prefix="wnba", optic_league_id="wnba",
        market_types={}, question_style="mlb_suffix", market_rules=(),
    )
    assert pm.basketball_player_points_rule("Paige Bueckers: Points O/U 21.5", cfg) is None


def test_basketball_player_points_rejects_other_stat():
    # anchoring guard: must match ONLY "Points", not Rebounds/Assists.
    assert pm.basketball_player_points_rule("Paige Bueckers: Rebounds O/U 5.5", BB_CFG) is None
    assert pm.basketball_player_points_rule("Paige Bueckers: Assists O/U 5.5", BB_CFG) is None


# --- player rebounds (NEW) ---


def test_basketball_player_rebounds_parse():
    out = pm.basketball_player_rebounds_rule("Aliyah Boston: Rebounds O/U 8.5", BB_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_REBOUNDS
    assert out.market_type.scope == Scope.PLAYER
    assert out.side_mode == pm.SideMode.YESNO_AS_OU
    assert out.entity == normalize_player_name("Aliyah Boston")
    assert out.line == 8.5
    assert out.team_a is None and out.team_b is None


def test_basketball_player_rebounds_rejects_other_stat():
    assert pm.basketball_player_rebounds_rule("Aliyah Boston: Points O/U 12.5", BB_CFG) is None
    assert pm.basketball_player_rebounds_rule("Aliyah Boston: Assists O/U 2.5", BB_CFG) is None


# --- player assists (NEW) ---


def test_basketball_player_assists_parse():
    out = pm.basketball_player_assists_rule("Caitlin Clark: Assists O/U 6.5", BB_CFG)
    assert out is not None
    assert out.market_type == MarketType.PLAYER_ASSISTS
    assert out.market_type.scope == Scope.PLAYER
    assert out.side_mode == pm.SideMode.YESNO_AS_OU
    assert out.entity == normalize_player_name("Caitlin Clark")
    assert out.line == 6.5
    assert out.team_a is None and out.team_b is None


def test_basketball_player_assists_rejects_other_stat():
    assert pm.basketball_player_assists_rule("Caitlin Clark: Points O/U 18.5", BB_CFG) is None
    assert pm.basketball_player_assists_rule("Caitlin Clark: Rebounds O/U 4.5", BB_CFG) is None


# --- build_rows integration: the YESNO_AS_OU proof ---
#
# Feeds a basketball_player_points_rule ParsedMarket + a synthetic 2-outcome
# poly market with Yes/No labels straight into the frozen build_rows dispatch.
# Asserts two rows, Yes->"over" / No->"under", bound to the LABELS
# (inversion-safe: swap outcome_index and it must still resolve correctly).


def test_build_rows_player_points_yesno_binds_side_to_label():
    m = _bb_mkt(
        "Paige Bueckers: Points O/U 21.5",
        [
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 0},
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 1},
        ],
    )
    parsed = pm.basketball_player_points_rule(m.question, BB_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="CHI", away="DAL",
        home_name="Chicago Sky", away_name="Dallas Wings",
        start_date="2026-07-28T23:00:00Z", cfg=BB_CFG, league="wnba",
    )
    assert len(rows) == 2
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    # "Yes" is outcome_index 1, "No" is outcome_index 0 -- side is bound to the
    # LABEL, not the index, so this ordering is a deliberate flip-safety check.
    assert by_tok["cY"].side == "over" and by_tok["cY"].market_type == "player_points"
    assert by_tok["cN"].side == "under" and by_tok["cN"].market_type == "player_points"
    assert by_tok["cY"].entity == normalize_player_name("Paige Bueckers")
    assert by_tok["cY"].line == 21.5
    assert by_tok["cN"].line == 21.5


def test_build_rows_player_points_yesno_index_swapped_still_binds_to_label():
    # inversion-safety: swap which index carries Yes/No and the sides must
    # still resolve by label, not flip.
    m = _bb_mkt(
        "Paige Bueckers: Points O/U 21.5",
        [
            {"clob_token_id": "cY", "position_id": "pY", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "cN", "position_id": "pN", "outcome_label": "No", "outcome_index": 1},
        ],
    )
    parsed = pm.basketball_player_points_rule(m.question, BB_CFG)
    assert parsed is not None
    rows = pm.build_rows(
        m, parsed, home="CHI", away="DAL",
        home_name="Chicago Sky", away_name="Dallas Wings",
        start_date="2026-07-28T23:00:00Z", cfg=BB_CFG, league="wnba",
    )
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cY"].side == "over"
    assert by_tok["cN"].side == "under"


# --- basketball_market_rules: ordered tuple of all 6 recognizers ---


def test_basketball_market_rules_is_ordered_tuple_of_6():
    assert isinstance(pm.basketball_market_rules, tuple)
    assert len(pm.basketball_market_rules) == 6
    assert set(pm.basketball_market_rules) == {
        pm.mlb_moneyline_rule,
        pm.mlb_total_rule,
        pm.mlb_spread_rule,
        pm.basketball_player_points_rule,
        pm.basketball_player_rebounds_rule,
        pm.basketball_player_assists_rule,
    }
    # ordering: the bare moneyline catch-all ("<A> vs. <B>", no colon) must
    # come last so the colon-guarded/prop forms above never get shadowed --
    # mirrors MLB_FULL_CFG's convention in test_polymarket.py.
    assert pm.basketball_market_rules[-1] is pm.mlb_moneyline_rule


# --- parse_question through the full tuple: one exact probe example of EACH
#     of the 6 forms resolves to its correct MarketType via BB_CFG. Proves
#     the reused MLB rules resolve basketball MarketTypes through
#     BASKETBALL_MARKET_TYPES, and the dict keys are consistent. ---


def test_parse_question_all_6_basketball_forms():
    cases = [
        ("Chicago Sky vs. Dallas Wings", MarketType.MONEYLINE),
        ("Chicago Sky vs. Dallas Wings: O/U 176.5", MarketType.GAME_TOTAL),
        ("Spread: Minnesota Lynx (-12.5)", MarketType.POINT_SPREAD),
        ("Paige Bueckers: Points O/U 21.5", MarketType.PLAYER_POINTS),
        ("Aliyah Boston: Rebounds O/U 8.5", MarketType.PLAYER_REBOUNDS),
        ("Caitlin Clark: Assists O/U 6.5", MarketType.PLAYER_ASSISTS),
    ]
    for question, expected in cases:
        out = pm.parse_question(question, BB_CFG)
        assert out is not None, question
        assert out.market_type == expected, (question, out.market_type, expected)


# --- ordering/disjointness: moneyline vs. total/player forms never cross-match ---


def test_basketball_moneyline_not_matched_by_total_or_player_rules():
    q = "Chicago Sky vs. Dallas Wings"
    assert pm.mlb_total_rule(q, BB_CFG) is None
    assert pm.basketball_player_points_rule(q, BB_CFG) is None
    assert pm.basketball_player_rebounds_rule(q, BB_CFG) is None
    assert pm.basketball_player_assists_rule(q, BB_CFG) is None


def test_basketball_total_not_matched_by_moneyline_or_player_rules():
    q = "Chicago Sky vs. Dallas Wings: O/U 176.5"
    assert pm.mlb_moneyline_rule(q, BB_CFG) is None
    assert pm.basketball_player_points_rule(q, BB_CFG) is None
    assert pm.basketball_player_rebounds_rule(q, BB_CFG) is None
    assert pm.basketball_player_assists_rule(q, BB_CFG) is None


def test_basketball_player_prop_not_matched_by_moneyline_or_total_rules():
    for q in [
        "Paige Bueckers: Points O/U 21.5",
        "Aliyah Boston: Rebounds O/U 8.5",
        "Caitlin Clark: Assists O/U 6.5",
    ]:
        assert pm.mlb_moneyline_rule(q, BB_CFG) is None
        assert pm.mlb_total_rule(q, BB_CFG) is None


def test_basketball_spread_not_matched_by_other_rules():
    q = "Spread: Minnesota Lynx (-12.5)"
    assert pm.mlb_moneyline_rule(q, BB_CFG) is None
    assert pm.mlb_total_rule(q, BB_CFG) is None
    assert pm.basketball_player_points_rule(q, BB_CFG) is None
    assert pm.basketball_player_rebounds_rule(q, BB_CFG) is None
    assert pm.basketball_player_assists_rule(q, BB_CFG) is None


# --- BASKETBALL_MARKET_TYPES key set ---


def test_basketball_market_types_key_set():
    assert set(pm.BASKETBALL_MARKET_TYPES) == {
        "moneyline", "total", "spread",
        "player_points", "player_rebounds", "player_assists",
    }
    assert pm.BASKETBALL_MARKET_TYPES["moneyline"] == MarketType.MONEYLINE
    assert pm.BASKETBALL_MARKET_TYPES["total"] == MarketType.GAME_TOTAL
    assert pm.BASKETBALL_MARKET_TYPES["spread"] == MarketType.POINT_SPREAD
    assert pm.BASKETBALL_MARKET_TYPES["player_points"] == MarketType.PLAYER_POINTS
    assert pm.BASKETBALL_MARKET_TYPES["player_rebounds"] == MarketType.PLAYER_REBOUNDS
    assert pm.BASKETBALL_MARKET_TYPES["player_assists"] == MarketType.PLAYER_ASSISTS

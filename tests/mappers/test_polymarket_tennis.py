"""Tests for the tennis rescue Tier 1 (total_sets) + the GOTCHA-1 build_rows fix.

See .superpowers/sdd/wave-tennis-probe-findings.md section B.3 (total_sets
template) and section C.1 (the OVER_UNDER outcome-label/line collision).
"""

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league


def _atp_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "atp")
    return build_tip_league(row)


def _wta_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "wta")
    return build_tip_league(row)

TENNIS_TOTAL_SETS_CFG = pm.PolymarketConfig(
    slug_prefix="atp",
    optic_league_id="atp",
    market_types=pm.TENNIS_MARKET_TYPES,
    question_style="tennis_prefix",
    market_rules=pm.tennis_market_rules,
)


def _mkt(question, outcomes):
    return pm.PolyMarket(
        condition_id="0xabc",
        slug="atp-bloomfield-2026-07-22",
        question=question,
        outcomes=[pm.PolyOutcome(**o) for o in outcomes],
    )


# === tennis_total_sets_rule parsing ===


def test_tennis_total_sets_rule_parses_full_names_and_line():
    out = pm.tennis_total_sets_rule(
        "Yunchaokete Bu vs. Borna Gojo: Total Sets O/U 2.5", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.TOTAL_SETS
    assert out.market_type.scope.value == "game"
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.line == 2.5
    # FULL names captured (not surname-only) -- same normalization as moneyline.
    assert out.team_a == pm._norm_name("Yunchaokete Bu", "tennis_prefix")
    assert out.team_b == pm._norm_name("Borna Gojo", "tennis_prefix")


def test_tennis_total_sets_rule_via_parse_question_dispatch():
    # first-match-wins through the shared tennis_market_rules tuple.
    out = pm.parse_question(
        "Marta Kostyuk vs. Linda Noskova: Total Sets O/U 2.5", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.TOTAL_SETS
    assert out.line == 2.5


def test_tennis_total_sets_rule_returns_none_for_other_forms():
    assert pm.tennis_total_sets_rule(
        "Bloomfield Hills: Yunchaokete Bu vs Borna Gojo", TENNIS_TOTAL_SETS_CFG
    ) is None  # plain moneyline, no "Total Sets O/U"
    assert pm.tennis_total_sets_rule(
        "Galarneau vs. Ruiz: Match O/U 21.5", TENNIS_TOTAL_SETS_CFG
    ) is None  # match_total_games, a different market_id/kind


def test_tennis_moneyline_still_wins_for_moneyline_questions():
    # moneyline questions must still resolve to MONEYLINE, not be shadowed by
    # the new rule -- tennis_total_sets_rule's own anchor requires "Total Sets
    # O/U", so a plain moneyline question never matches it.
    out = pm.parse_question(
        "Bloomfield Hills: Yunchaokete Bu vs Borna Gojo", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE
    assert out.side_mode == pm.SideMode.TEAM_LABEL


# === atp/wta wiring ===


def test_atp_wta_optic_config_has_total_sets():
    for lg in (_atp_cfg(), _wta_cfg()):
        assert lg.OPTIC.table_types["total_sets"] == MarketType.TOTAL_SETS


def test_atp_wta_polymarket_config_has_total_sets():
    for lg in (_atp_cfg(), _wta_cfg()):
        pcfg = lg.POLYMARKET
        assert pcfg is not None
        assert pcfg.market_types["total_sets"] == MarketType.TOTAL_SETS
        assert pm.tennis_total_sets_rule in pcfg.market_rules


def test_atp_wta_output_order_includes_total_sets():
    assert MarketType.TOTAL_SETS in _atp_cfg().OUTPUT_ORDER
    assert MarketType.TOTAL_SETS in _wta_cfg().OUTPUT_ORDER


# === GOTCHA-1: build_rows OVER_UNDER outcome_label/line collision ===


def _bt_tennis(market, parsed):
    return pm.build_rows(
        market, parsed,
        home="BU", away="GOJO",
        home_name="Yunchaokete Bu", away_name="Borna Gojo",
        start_date="2026-07-22T18:00:00Z",
        cfg=TENNIS_TOTAL_SETS_CFG, league="atp",
    )


def test_build_rows_total_sets_over_2_5_binds_correctly():
    """This is the regression the fix targets: 'Over 2.5'/'Under 2.5' labels
    bake the line into outcome_label, unlike every other OVER_UNDER form's
    bare 'Over'/'Under'. Before the fix, `lab == over_lab` (over_lab="over")
    never matched _normalize("Over 2.5") == "over 2 5" -> build_rows dropped
    the market whole (returned [])."""
    m = _mkt("Yunchaokete Bu vs. Borna Gojo: Total Sets O/U 2.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over 2.5", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under 2.5", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, TENNIS_TOTAL_SETS_CFG)
    assert parsed is not None
    rows = _bt_tennis(m, parsed)
    assert rows != []  # would be [] before the fix
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cO"].side == "over" and by_tok["cO"].line == 2.5
    assert by_tok["cU"].side == "under" and by_tok["cU"].market_type == "total_sets"


def test_build_rows_bare_over_under_labels_still_bind_backward_compat():
    """Backward-compat: every existing OVER_UNDER form (MLB/soccer/basketball
    totals, tennis's own match_total_games/set_games) ships a bare
    'Over'/'Under' label with no line baked in. The fix's `==` arm must keep
    matching these byte-identically -- this is the same shape as the
    pre-existing test_build_rows_total_over_under in test_polymarket.py,
    re-asserted here against the tennis config as an explicit backward-compat
    guard for the GOTCHA-1 fix."""
    m = _mkt("Yunchaokete Bu vs. Borna Gojo: Total Sets O/U 2.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, TENNIS_TOTAL_SETS_CFG)
    rows = _bt_tennis(m, parsed)
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cO"].side == "over" and by_tok["cO"].line == 2.5
    assert by_tok["cU"].side == "under"


def test_build_rows_over_under_guard_rejects_overtime_style_label():
    """Tight-guard check: a label that merely starts with 'over' but isn't a
    space-separated continuation (e.g. a hypothetical 'Overtime') must NOT
    falsely match -- the fix uses `startswith(over_lab + " ")`, not a bare
    `startswith(over_lab)`, specifically to keep this rejected."""
    m = _mkt("Yunchaokete Bu vs. Borna Gojo: Total Sets O/U 2.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Overtime", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under 2.5", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, TENNIS_TOTAL_SETS_CFG)
    rows = _bt_tennis(m, parsed)
    assert rows == []  # "Overtime" doesn't resolve to either complementary side -> drop whole market


def test_normalize_over_2_5_and_overtime_evidence():
    """Pin the exact _normalize output the fix's guard relies on."""
    assert pm._normalize("Over 2.5") == "over 2 5"
    assert pm._normalize("Under 2.5") == "under 2 5"
    assert pm._normalize("Over") == "over"
    assert pm._normalize("Overtime") == "overtime"
    # "over 2 5" starts with "over " (space) -> matches; "overtime" does not.
    assert "over 2 5".startswith("over ")
    assert not "overtime".startswith("over ")


# === Tier 2 (task TN3): the 4 SURNAME-only forms ===
# .superpowers/sdd/wave-tennis-probe-findings.md section B.2 (match_total_games),
# B.4 (set_games), B.5 (set_handicap), B.6 (set_winner). All four set
# name_granularity="surname" since poly's labels/names here are the last
# whitespace token of the full name, not the full name (unlike moneyline/
# total_sets above).


def test_tennis_match_total_games_rule_parses_surnames_and_line():
    out = pm.tennis_match_total_games_rule(
        "Galarneau vs. Ruiz: Match O/U 21.5", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.MATCH_TOTAL_GAMES
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.line == 21.5
    assert out.name_granularity == "surname"
    assert out.team_a == pm._norm_name("Galarneau", "tennis_prefix")
    assert out.team_b == pm._norm_name("Ruiz", "tennis_prefix")


def test_tennis_match_total_games_rule_not_confused_with_total_sets():
    # "Total Sets O/U" must not satisfy the "Match O/U" anchor.
    assert pm.tennis_match_total_games_rule(
        "Yunchaokete Bu vs. Borna Gojo: Total Sets O/U 2.5", TENNIS_TOTAL_SETS_CFG
    ) is None


def test_tennis_total_sets_rule_not_confused_with_match_total_games():
    # disjointness the other direction -- "Match O/U" must not satisfy the
    # "Total Sets O/U" anchor.
    assert pm.tennis_total_sets_rule(
        "Galarneau vs. Ruiz: Match O/U 21.5", TENNIS_TOTAL_SETS_CFG
    ) is None


def test_tennis_set_games_rule_set_1_maps_to_first_set_total_games():
    out = pm.tennis_set_games_rule(
        "Muchova vs. Noskova: Set 1 Games O/U 10.5", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.FIRST_SET_TOTAL_GAMES
    assert out.side_mode == pm.SideMode.OVER_UNDER
    assert out.line == 10.5
    assert out.name_granularity == "surname"
    assert out.team_a == pm._norm_name("Muchova", "tennis_prefix")
    assert out.team_b == pm._norm_name("Noskova", "tennis_prefix")


def test_tennis_set_games_rule_set_2_maps_to_second_set_total_games():
    out = pm.tennis_set_games_rule(
        "Malmkjaer vs. Bartashevich: Set 2 Games O/U 10.5", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.SECOND_SET_TOTAL_GAMES
    assert out.line == 10.5
    assert out.name_granularity == "surname"


def test_tennis_set_games_rule_set_3_and_4_return_none():
    # Best-of-5 tail (Grand-Slam-only, low volume) -- deferred, not built.
    assert pm.tennis_set_games_rule(
        "Sinner vs. Zverev: Set 3 Games O/U 9.5", TENNIS_TOTAL_SETS_CFG
    ) is None
    assert pm.tennis_set_games_rule(
        "Sinner vs. Zverev: Set 4 Games O/U 9.5", TENNIS_TOTAL_SETS_CFG
    ) is None


def test_tennis_set_handicap_rule_parses_entity_and_signed_line():
    out = pm.tennis_set_handicap_rule(
        "Set Handicap: Gojo (-1.5) vs Bu (+1.5)", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.SET_HANDICAP
    assert out.side_mode == pm.SideMode.SPREAD_TEAM
    assert out.name_granularity == "surname"
    # named (first, negative-signed) side carries the signed line as entity.
    assert out.entity == pm._norm_name("Gojo", "tennis_prefix")
    assert out.line == -1.5
    # team_a/team_b are None -- the pipeline resolves the fixture from the two
    # outcome labels for SPREAD_TEAM, same convention as mlb_spread_rule.
    assert out.team_a is None
    assert out.team_b is None


def test_tennis_set_handicap_rule_anchored_on_fixed_prefix():
    assert pm.tennis_set_handicap_rule(
        "Lajovic vs. Assche: Match O/U 21.5", TENNIS_TOTAL_SETS_CFG
    ) is None  # no "Set Handicap:" prefix


def test_tennis_set_winner_rule_set_1_maps_to_first_set_winner():
    out = pm.tennis_set_winner_rule(
        "Set 1 Winner: Ichikawa vs Yamasaki", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.FIRST_SET_WINNER
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.name_granularity == "surname"
    assert out.team_a == pm._norm_name("Ichikawa", "tennis_prefix")
    assert out.team_b == pm._norm_name("Yamasaki", "tennis_prefix")


def test_tennis_set_winner_rule_set_2_maps_to_second_set_winner():
    out = pm.tennis_set_winner_rule(
        "Set 2 Winner: Muchova vs Noskova", TENNIS_TOTAL_SETS_CFG
    )
    assert out is not None
    assert out.market_type == MarketType.SECOND_SET_WINNER
    assert out.name_granularity == "surname"


def test_tennis_set_winner_rule_set_3_and_4_return_none():
    assert pm.tennis_set_winner_rule(
        "Set 3 Winner: Zverev vs Sinner", TENNIS_TOTAL_SETS_CFG
    ) is None
    assert pm.tennis_set_winner_rule(
        "Set 4 Winner: Zverev vs Sinner", TENNIS_TOTAL_SETS_CFG
    ) is None


def test_tennis_set_winner_rule_disjoint_from_set_handicap():
    # "Set Handicap:" must never satisfy the "Set K Winner:" anchor.
    assert pm.tennis_set_winner_rule(
        "Set Handicap: Gojo (-1.5) vs Bu (+1.5)", TENNIS_TOTAL_SETS_CFG
    ) is None


def test_tennis_new_forms_via_parse_question_dispatch():
    # first-match-wins through the shared tennis_market_rules tuple, for each
    # of the 4 new forms.
    cases = [
        ("Galarneau vs. Ruiz: Match O/U 21.5", MarketType.MATCH_TOTAL_GAMES),
        ("Muchova vs. Noskova: Set 1 Games O/U 10.5", MarketType.FIRST_SET_TOTAL_GAMES),
        ("Set Handicap: Gojo (-1.5) vs Bu (+1.5)", MarketType.SET_HANDICAP),
        ("Set 1 Winner: Ichikawa vs Yamasaki", MarketType.FIRST_SET_WINNER),
    ]
    for question, expected in cases:
        out = pm.parse_question(question, TENNIS_TOTAL_SETS_CFG)
        assert out is not None, question
        assert out.market_type == expected, question


# === atp/wta wiring (Tier 2) ===


def test_atp_wta_optic_config_has_tier2_forms():
    for lg in (_atp_cfg(), _wta_cfg()):
        assert lg.OPTIC.table_types["total_games"] == MarketType.MATCH_TOTAL_GAMES
        assert lg.OPTIC.table_types["1st_set_total_games"] == MarketType.FIRST_SET_TOTAL_GAMES
        assert lg.OPTIC.table_types["2nd_set_total_games"] == MarketType.SECOND_SET_TOTAL_GAMES
        assert lg.OPTIC.table_types["set_handicap"] == MarketType.SET_HANDICAP
        assert lg.OPTIC.table_types["1st_set_moneyline"] == MarketType.FIRST_SET_WINNER
        assert lg.OPTIC.table_types["2nd_set_moneyline"] == MarketType.SECOND_SET_WINNER


def test_atp_wta_polymarket_config_has_tier2_forms():
    for lg in (_atp_cfg(), _wta_cfg()):
        pcfg = lg.POLYMARKET
        assert pcfg is not None
        mt = pcfg.market_types
        assert mt["match_total_games"] == MarketType.MATCH_TOTAL_GAMES
        assert mt["1st_set_total_games"] == MarketType.FIRST_SET_TOTAL_GAMES
        assert mt["2nd_set_total_games"] == MarketType.SECOND_SET_TOTAL_GAMES
        assert mt["set_handicap"] == MarketType.SET_HANDICAP
        assert mt["1st_set_winner"] == MarketType.FIRST_SET_WINNER
        assert mt["2nd_set_winner"] == MarketType.SECOND_SET_WINNER
        for rule in (
            pm.tennis_match_total_games_rule,
            pm.tennis_set_games_rule,
            pm.tennis_set_handicap_rule,
            pm.tennis_set_winner_rule,
        ):
            assert rule in pcfg.market_rules


def test_atp_wta_output_order_includes_tier2_forms():
    for order in (_atp_cfg().OUTPUT_ORDER, _wta_cfg().OUTPUT_ORDER):
        assert MarketType.MATCH_TOTAL_GAMES in order
        assert MarketType.FIRST_SET_TOTAL_GAMES in order
        assert MarketType.SECOND_SET_TOTAL_GAMES in order
        assert MarketType.SET_HANDICAP in order
        assert MarketType.FIRST_SET_WINNER in order
        assert MarketType.SECOND_SET_WINNER in order

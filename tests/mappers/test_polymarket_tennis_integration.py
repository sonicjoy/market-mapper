import dataclasses

from mappers.exchanges import polymarket as pm
from mappers.pipeline import _match_poly_fixture, attach_polymarket_row, row_key
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.shared import CanonicalRow


def _atp_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "atp")
    return build_tip_league(row)


def _wta_cfg():
    row = next(r for r in load_fixture().leagues if r.league == "wta")
    return build_tip_league(row)


def test_atp_wta_polymarket_config():
    for lg in (_atp_cfg(), _wta_cfg()):
        assert lg.POLYMARKET is not None
        assert lg.POLYMARKET.question_style == "tennis_prefix"
        assert lg.POLYMARKET.market_types == {
            "moneyline": pm.MarketType.MONEYLINE,
            "total_sets": pm.MarketType.TOTAL_SETS,
            "match_total_games": pm.MarketType.MATCH_TOTAL_GAMES,
            "1st_set_total_games": pm.MarketType.FIRST_SET_TOTAL_GAMES,
            "2nd_set_total_games": pm.MarketType.SECOND_SET_TOTAL_GAMES,
            "set_handicap": pm.MarketType.SET_HANDICAP,
            "1st_set_winner": pm.MarketType.FIRST_SET_WINNER,
            "2nd_set_winner": pm.MarketType.SECOND_SET_WINNER,
        }


class _FX:
    home, away = "MIC", "MAY"
    home_name, away_name = "Alex Michelsen", "Aidan Mayo"
    start_date = "2026-07-22T18:00:00Z"


def test_atp_match_winner_end_to_end_stamps_optic_row():
    cfg = _atp_cfg().POLYMARKET
    assert cfg is not None
    # optic priced the match-winner (moneyline) for player MIC
    optic_mic = CanonicalRow(league="atp", start_date=_FX.start_date, home="MIC",
                             away="MAY", market_type="moneyline", side="MIC", optic_id="O1")
    index = {row_key(optic_mic): optic_mic}
    market = pm.PolyMarket(condition_id="0xT", slug="atp-bloomfield-2026-07-22",
        question="Bloomfield Hills: Alex Michelsen vs Aidan Mayo",
        outcomes=[pm.PolyOutcome(clob_token_id="cM", position_id="pM",
                                 outcome_label="Alex Michelsen", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="cY", position_id="pY",
                                 outcome_label="Aidan Mayo", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-22")
    fx = _match_poly_fixture(parsed, [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="atp")
    results = [attach_polymarket_row(index, r) for r in rows]
    assert "stamped" in results  # MIC side stamps onto the optic moneyline row
    assert "dropped_no_optic" in results  # the away side optic never priced -> dropped, not stamped
    assert index[row_key(optic_mic)].polymarket_clob_token_id == "cM"


# === Tier 2 (task TN3): surname-only forms end-to-end ===
#
# Each test proves the FULL chain -- parse (surname captured) ->
# _match_poly_fixture (surname resolved against a synthetic fixture with FULL
# competitor names) -> build_rows (rows correctly bound). Fixture names mirror
# the probe's own examples (wave-tennis-probe-findings.md section B.2/B.4-6):
# "Luca Van Assche" -> surname "Assche" (last whitespace token, not the true
# tennis surname "Van Assche" -- the poly-side convention this mechanism
# reproduces).


class _FxAssche:
    home, away = "GAL", "ASS"
    home_name, away_name = "Felix Galarneau", "Luca Van Assche"
    start_date = "2026-07-22T18:00:00Z"


def test_match_total_games_end_to_end_resolves_surname_fixture_and_rows():
    cfg = _atp_cfg().POLYMARKET
    assert cfg is not None
    market = pm.PolyMarket(
        condition_id="0xT1", slug="atp-galarneau-assche-2026-07-22",
        question="Galarneau vs. Assche: Match O/U 21.5",
        outcomes=[
            pm.PolyOutcome(clob_token_id="cO", position_id="pO", outcome_label="Over", outcome_index=0),
            pm.PolyOutcome(clob_token_id="cU", position_id="pU", outcome_label="Under", outcome_index=1),
        ],
    )
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    assert parsed.market_type == pm.MarketType.MATCH_TOTAL_GAMES
    parsed = dataclasses.replace(parsed, date="2026-07-22")
    fx = _match_poly_fixture(parsed, [_FxAssche()], cfg.question_style)
    assert fx is not None  # "Assche" resolved -> "Luca Van Assche" via last-token surname
    assert fx.home_name == "Felix Galarneau"
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="atp")
    by_side = {r.side: r for r in rows}
    assert by_side["over"].line == 21.5
    assert by_side["over"].entity is None  # GAME scope
    assert by_side["under"].market_type == "match_total_games"


def test_set_games_end_to_end_resolves_surname_fixture_and_rows():
    cfg = _atp_cfg().POLYMARKET
    assert cfg is not None

    class _FxSet:
        home, away = "MUC", "NOS"
        home_name, away_name = "Karolina Muchova", "Linda Noskova"
        start_date = "2026-07-22T18:00:00Z"

    market = pm.PolyMarket(
        condition_id="0xT2", slug="wta-muchova-noskova-2026-07-22",
        question="Muchova vs. Noskova: Set 1 Games O/U 10.5",
        outcomes=[
            pm.PolyOutcome(clob_token_id="cO", position_id="pO", outcome_label="Over", outcome_index=0),
            pm.PolyOutcome(clob_token_id="cU", position_id="pU", outcome_label="Under", outcome_index=1),
        ],
    )
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    assert parsed.market_type == pm.MarketType.FIRST_SET_TOTAL_GAMES
    parsed = dataclasses.replace(parsed, date="2026-07-22")
    fx = _match_poly_fixture(parsed, [_FxSet()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="wta")
    by_side = {r.side: r for r in rows}
    assert by_side["over"].line == 10.5
    assert by_side["under"].line == 10.5


def test_set_handicap_end_to_end_binds_signed_line_to_named_side():
    cfg = _atp_cfg().POLYMARKET
    assert cfg is not None

    class _FxHandi:
        home, away = "GOJ", "BU"
        home_name, away_name = "Borna Gojo", "Yunchaokete Bu"
        start_date = "2026-07-22T18:00:00Z"

    market = pm.PolyMarket(
        condition_id="0xT3", slug="atp-gojo-bu-2026-07-22",
        question="Set Handicap: Gojo (-1.5) vs Bu (+1.5)",
        outcomes=[
            pm.PolyOutcome(clob_token_id="cG", position_id="pG", outcome_label="Gojo", outcome_index=0),
            pm.PolyOutcome(clob_token_id="cB", position_id="pB", outcome_label="Bu", outcome_index=1),
        ],
    )
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    assert parsed.market_type == pm.MarketType.SET_HANDICAP
    assert parsed.entity == pm._norm_name("Gojo", "tennis_prefix")
    assert parsed.line == -1.5
    parsed = dataclasses.replace(parsed, date="2026-07-22")
    # SPREAD_TEAM fixture resolution: team_a/team_b are None on the parsed
    # market itself; _match_poly_game_fixture (the pipeline entry point) is
    # what substitutes the outcome labels before calling _match_poly_fixture
    # -- replicate that substitution directly here, mirroring
    # mappers.pipeline._match_poly_game_fixture's SPREAD_TEAM branch.
    labels = [o.outcome_label for o in market.outcomes]
    probe = dataclasses.replace(
        parsed,
        team_a=pm._norm_name(labels[0], cfg.question_style),
        team_b=pm._norm_name(labels[1], cfg.question_style),
    )
    fx = _match_poly_fixture(probe, [_FxHandi()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="atp")
    by_side = {r.side: r for r in rows}
    # Gojo is the named (-1.5) reference side; Bu carries the complementary +1.5.
    assert by_side["GOJ"].line == -1.5
    assert by_side["BU"].line == 1.5


def test_set_winner_end_to_end_resolves_surname_side():
    """The task's own worked example: tennis_set_winner_rule("Set 1 Winner:
    Zverev vs Sinner") -> resolves "Zverev" -> "Alexander Zverev" side."""
    cfg = _atp_cfg().POLYMARKET
    assert cfg is not None

    class _FxWinner:
        home, away = "ZVE", "SIN"
        home_name, away_name = "Alexander Zverev", "Jannik Sinner"
        start_date = "2026-07-22T18:00:00Z"

    market = pm.PolyMarket(
        condition_id="0xT4", slug="atp-zverev-sinner-2026-07-22",
        question="Set 1 Winner: Zverev vs Sinner",
        outcomes=[
            pm.PolyOutcome(clob_token_id="cZ", position_id="pZ", outcome_label="Zverev", outcome_index=0),
            pm.PolyOutcome(clob_token_id="cS", position_id="pS", outcome_label="Sinner", outcome_index=1),
        ],
    )
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    assert parsed.market_type == pm.MarketType.FIRST_SET_WINNER
    parsed = dataclasses.replace(parsed, date="2026-07-22")
    fx = _match_poly_fixture(parsed, [_FxWinner()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="atp")
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cZ"].side == "ZVE"  # "Zverev" -> "Alexander Zverev" -> home abbrev
    assert by_tok["cS"].side == "SIN"


def test_set_winner_within_fixture_surname_collision_drops():
    """Flip-safety (TN2 mechanism, reused verbatim): a fixture whose two
    competitors share the same last-token surname is inherently ambiguous
    under granularity="surname" -- must drop, never guess."""
    cfg = _atp_cfg().POLYMARKET
    assert cfg is not None

    class _FxCollide:
        home, away = "S1", "S2"
        home_name, away_name = "Bruno Silva", "Diego Silva"
        start_date = "2026-07-22T18:00:00Z"

    market = pm.PolyMarket(
        condition_id="0xT5", slug="atp-silva-silva-2026-07-22",
        question="Set 1 Winner: Silva vs Silva",
        outcomes=[
            pm.PolyOutcome(clob_token_id="c1", position_id="p1", outcome_label="Silva", outcome_index=0),
            pm.PolyOutcome(clob_token_id="c2", position_id="p2", outcome_label="Silva", outcome_index=1),
        ],
    )
    parsed = pm.parse_question(market.question, cfg)
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-22")
    fx = _match_poly_fixture(parsed, [_FxCollide()], cfg.question_style)
    assert fx is None  # ambiguous -- dropped, not guessed

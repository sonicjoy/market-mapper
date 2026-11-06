import dataclasses

from mappers.exchanges.polymarket import MarketType, ParsedMarket, SideMode
from mappers.pipeline import _match_poly_fixture


class _FX:
    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _parsed(team_a, team_b, date):
    """A minimal MONEYLINE ParsedMarket carrying the fields _match_poly_fixture reads."""
    return ParsedMarket(market_type=MarketType.MONEYLINE, team_a=team_a, team_b=team_b,
                        side_mode=SideMode.TEAM_LABEL, date=date)


def test_match_poly_fixture_by_name_and_date():
    fixtures = [
        _FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-21T23:00:00Z"),
        _FX("Boston Red Sox", "New York Yankees", "2026-07-21T23:00:00Z"),
    ]
    parsed = _parsed("arizona diamondbacks", "st louis cardinals", "2026-07-21")
    fx = _match_poly_fixture(parsed, fixtures, "mlb_suffix")
    assert fx is fixtures[0]


def test_match_poly_fixture_none_when_no_name_match():
    fixtures = [_FX("Boston Red Sox", "New York Yankees", "2026-07-21T23:00:00Z")]
    parsed = _parsed("arizona diamondbacks", "st louis cardinals", "2026-07-21")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_match_poly_fixture_within_one_day_after_matches():
    # Late-ET game whose UTC start_date has rolled to the next day still matches.
    fixtures = [_FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-22T02:00:00Z")]
    parsed = _parsed("arizona diamondbacks", "st louis cardinals", "2026-07-21")
    fx = _match_poly_fixture(parsed, fixtures, "mlb_suffix")
    assert fx is fixtures[0]


def test_match_poly_fixture_two_days_off_does_not_match():
    fixtures = [_FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-23T02:00:00Z")]
    parsed = _parsed("arizona diamondbacks", "st louis cardinals", "2026-07-21")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_match_poly_fixture_prefers_exact_date_over_adjacent():
    # Same matchup on consecutive days (MLB series). Both are within optic's
    # 48h horizon and within ±1 day of the slug date, and the D-1 fixture is
    # listed FIRST (entries are sorted by start ascending). A poly market for
    # day D must map to the day-D fixture, not the day D-1 one it sees first.
    fixtures = [
        _FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-20T23:00:00Z"),  # D-1
        _FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-21T23:00:00Z"),  # D
    ]
    parsed = _parsed("arizona diamondbacks", "st louis cardinals", "2026-07-21")
    fx = _match_poly_fixture(parsed, fixtures, "mlb_suffix")
    assert fx is fixtures[1]


# ── Authoritative game-start instant (Gamma gameStartTime) ────────────────────
# The slug date is the VENUE-LOCAL date; fx.start_date is UTC. For any US night
# game the two never agree, so the exact-date test above cannot fire and the
# ±1-day fallback picks whichever same-teams fixture it sees first — a coin flip
# in a consecutive-day series. Prod case: the Aug-5 DET@SEA market
# (mlb-det-sea-2026-08-05-f5-spread-away-1pt5, gameStartTime 2026-08-06T01:40Z)
# was stamped onto the Aug-6 13:10-PT fixture (2026-08-06T20:10Z). When the
# market carries its own start instant, match on THAT and never fall back to a
# date window.


def _parsed_at(team_a, team_b, date, game_start_time):
    return dataclasses.replace(_parsed(team_a, team_b, date), game_start_time=game_start_time)


def test_match_poly_fixture_prefers_authoritative_game_start_instant():
    fixtures = [
        _FX("Seattle Mariners", "Detroit Tigers", "2026-08-06T20:10:00Z"),  # Aug-6 13:10 PT
        _FX("Seattle Mariners", "Detroit Tigers", "2026-08-06T01:40:00Z"),  # Aug-5 18:40 PT
    ]
    # Same UTC date on both, so the slug-date path cannot separate them.
    parsed = _parsed_at("seattle mariners", "detroit tigers", "2026-08-05", "2026-08-06 01:40:00+00")
    fx = _match_poly_fixture(parsed, fixtures, "mlb_suffix")
    assert fx is fixtures[1]


def test_match_poly_fixture_instant_does_not_fall_back_to_adjacent_day():
    # Only the sibling game is present. With an authoritative instant that matches
    # nothing, drop the market (fail closed) rather than stamp the wrong fixture.
    fixtures = [_FX("Seattle Mariners", "Detroit Tigers", "2026-08-06T20:10:00Z")]
    parsed = _parsed_at("seattle mariners", "detroit tigers", "2026-08-05", "2026-08-06 01:40:00+00")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_match_poly_fixture_instant_tolerates_small_feed_skew():
    # Feeds disagree by minutes on kickoff; a few minutes must still match.
    fixtures = [_FX("Seattle Mariners", "Detroit Tigers", "2026-08-06T01:47:00Z")]
    parsed = _parsed_at("seattle mariners", "detroit tigers", "2026-08-05", "2026-08-06 01:40:00+00")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is fixtures[0]


def test_parse_market_carries_game_start_time_from_the_bridge_line():
    """Wiring guard: bridge column -> fetch line -> PolyMarket -> pipeline injection.

    If any hop drops the field the matcher silently reverts to slug-date matching,
    which is the bug this replaces — so assert the whole hop chain explicitly.
    """
    import json

    from mappers.exchanges.polymarket import parse_market
    line = json.dumps({
        "condition_id": "0xA",
        "slug": "mlb-det-sea-2026-08-05-f5-spread-away-1pt5",
        "question": "1st 5 Innings Spread: Detroit Tigers (-1.5)",
        "game_start_time": "2026-08-06 01:40:00+00",
        "outcomes": [],
    })
    market = parse_market(line)
    assert market is not None
    assert market.game_start_time == "2026-08-06 01:40:00+00"


def test_match_poly_fixture_without_instant_keeps_slug_date_behaviour():
    # Bridge rows written before game_start_time existed carry None — the slug-date
    # path must still resolve them exactly as before.
    fixtures = [_FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-21T23:00:00Z")]
    parsed = _parsed_at("arizona diamondbacks", "st louis cardinals", "2026-07-21", None)
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is fixtures[0]


def test_match_poly_fixture_tennis_exact_player_match():
    from mappers.exchanges import polymarket as pm

    fixtures = [
        _FX("Alex Michelsen", "Aidan Mayo", "2026-07-21T23:00:00Z"),
    ]
    parsed = pm.parse_question(
        "Bloomfield Hills: Alex Michelsen vs Aidan Mayo",
        pm.PolymarketConfig(slug_prefix="atp", optic_league_id="atp",
                            market_types={"moneyline": pm.MarketType.MONEYLINE},
                            question_style="tennis_prefix",
                            market_rules=(pm.tennis_moneyline_rule,)),
    )
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    fx = _match_poly_fixture(parsed, fixtures, "tennis_prefix")
    assert fx is fixtures[0]


def test_match_poly_fixture_tennis_wrong_player_does_not_match():
    from mappers.exchanges import polymarket as pm

    fixtures = [
        _FX("Holger Rune", "Coleman Wong", "2026-07-21T23:00:00Z"),
    ]
    parsed = pm.parse_question(
        "Bloomfield Hills: Alex Michelsen vs Aidan Mayo",
        pm.PolymarketConfig(slug_prefix="atp", optic_league_id="atp",
                            market_types={"moneyline": pm.MarketType.MONEYLINE},
                            question_style="tennis_prefix",
                            market_rules=(pm.tennis_moneyline_rule,)),
    )
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-21")
    assert _match_poly_fixture(parsed, fixtures, "tennis_prefix") is None


def test_build_optic_poly_index_maps_clob_to_row_key():
    from mappers.exchanges import optic
    from mappers.pipeline import _build_optic_poly_index, row_key
    from mappers.shared import CanonicalRow

    over = CanonicalRow(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ",
                        away="STL", market_type="game_total", line=8.5, side="over",
                        optic_id="ODD_OVER")
    under = CanonicalRow(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ",
                         away="STL", market_type="game_total", line=8.5, side="under",
                         optic_id="ODD_UNDER")
    row_index = {row_key(over): over, row_key(under): under}
    odd_lookup = {
        # optic mapped clob "cX" to the UNDER side (via Polymarket source_ids)
        "ODD_UNDER": optic.Odd(id="ODD_UNDER", market_id="total_runs", grouping_key="g",
                               source_ids={"Polymarket": {"selection_id": "cX"}}),
        "ODD_OVER": optic.Odd(id="ODD_OVER", market_id="total_runs", grouping_key="g",
                              source_ids={}),
    }
    idx = _build_optic_poly_index(row_index, odd_lookup)
    assert idx == {"cX": row_key(under)}
    # a poly row that parsed cX as OVER would have a DIFFERENT row_key -> conflict
    assert idx["cX"] != row_key(over)


def test_build_optic_poly_index_handles_usa_key_and_skips_unmapped():
    from mappers.exchanges import optic
    from mappers.pipeline import _build_optic_poly_index, row_key
    from mappers.shared import CanonicalRow
    r = CanonicalRow(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ",
                     away="STL", market_type="moneyline", side="AZ", optic_id="O1")
    r2 = CanonicalRow(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ",
                      away="STL", market_type="moneyline", side="STL", optic_id=None)
    row_index = {row_key(r): r, row_key(r2): r2}
    odd_lookup = {"O1": optic.Odd(id="O1", market_id="moneyline", grouping_key="g",
                                  source_ids={"Polymarket (USA)": {"selection_id": "cUSA"}})}
    idx = _build_optic_poly_index(row_index, odd_lookup)
    assert idx == {"cUSA": row_key(r)}   # USA key honored; the optic_id=None row skipped


# === Task 3: slug-team parser + two-phase player-prop fixture resolution ===

def test_poly_slug_teams_game_and_prop_share_key():
    from mappers.pipeline import _poly_slug_teams
    # The game slug and a player-prop slug for the same fixture share the
    # identical <prefix>-<teams>-<date> head, so the opaque team-token key
    # matches (independent of any poly->optic abbrev map).
    assert _poly_slug_teams("mlb-az-stl-2026-07-21") == ("az", "stl")
    assert _poly_slug_teams("mlb-az-stl-2026-07-21-hr-aaron-judge-05") == ("az", "stl")
    assert frozenset(_poly_slug_teams("mlb-az-stl-2026-07-21")) == \
        frozenset(_poly_slug_teams("mlb-az-stl-2026-07-21-k-tarik-skubal-65"))


def test_poly_slug_teams_no_date_returns_empty():
    from mappers.pipeline import _poly_slug_teams
    assert _poly_slug_teams("mlb-only") == ()
    assert _poly_slug_teams("") == ()


class _FullFX:
    """A minimal optic-Fixture stand-in with the fields the poly pass reads."""
    def __init__(self, home, away, home_name, away_name, start_date,
                 game_id=None):
        self.home, self.away = home, away
        self.home_name, self.away_name = home_name, away_name
        self.start_date = start_date
        self.game_id = game_id or f"{home}-{away}-{start_date}"


def _mkt(slug, question, outcomes):
    from mappers.exchanges import polymarket as pm
    return pm.PolyMarket(condition_id="0x" + slug, slug=slug, question=question,
                         outcomes=[pm.PolyOutcome(**o) for o in outcomes])


_MLB_FULL_CFG = None


def _mlb_cfg():
    global _MLB_FULL_CFG
    if _MLB_FULL_CFG is None:
        from mappers.seed.fixture_store import load_fixture
        from mappers.seed.tip_factories import build_tip_league
        row = next(r for r in load_fixture().leagues if r.league == "mlb")
        _MLB_FULL_CFG = build_tip_league(row).POLYMARKET
    return _MLB_FULL_CFG


def test_resolve_poly_markets_two_phase_prop_resolves_via_seeded_game():
    from mappers.pipeline import _resolve_poly_markets
    cfg = _mlb_cfg()
    assert cfg is not None
    fx = _FullFX("AZ", "STL", "Arizona Diamondbacks", "St. Louis Cardinals",
                 "2026-07-21T23:00:00Z")
    game = _mkt("mlb-az-stl-2026-07-21",
                "Arizona Diamondbacks vs. St. Louis Cardinals",
                [{"clob_token_id": "gA", "position_id": "pA",
                  "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
                 {"clob_token_id": "gB", "position_id": "pB",
                  "outcome_label": "St. Louis Cardinals", "outcome_index": 1}])
    prop = _mkt("mlb-az-stl-2026-07-21-hr-corbin-carroll-05",
                "Corbin Carroll: Home Runs O/U 0.5",
                [{"clob_token_id": "hO", "position_id": "pO",
                  "outcome_label": "Over", "outcome_index": 0},
                 {"clob_token_id": "hU", "position_id": "pU",
                  "outcome_label": "Under", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([prop, game], [fx], cfg)
    # the game seeds the slug key; the prop (listed first, no team in its
    # question) resolves to the same fixture via that key.
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[game.slug] is fx
    assert by_slug[prop.slug] is fx
    assert stats["no_fixture"] == 0


def test_resolve_poly_markets_doubleheader_slug_collision_keeps_last(
        capsys, monkeypatch):
    """Same-teams-same-date siblings share a Phase B key; last seed wins."""
    from mappers import pipeline
    cfg = _mlb_cfg()
    assert cfg is not None
    g1 = _FullFX("AZ", "STL", "Arizona Diamondbacks", "St. Louis Cardinals",
                 "2026-07-21T17:00:00Z", game_id="dh-game-1")
    g2 = _FullFX("AZ", "STL", "Arizona Diamondbacks", "St. Louis Cardinals",
                 "2026-07-21T23:00:00Z", game_id="dh-game-2")
    game_a = _mkt("mlb-az-stl-2026-07-21",
                  "Arizona Diamondbacks vs. St. Louis Cardinals",
                  [{"clob_token_id": "aA", "position_id": "pA",
                    "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
                   {"clob_token_id": "aB", "position_id": "pB",
                    "outcome_label": "St. Louis Cardinals", "outcome_index": 1}])
    game_b = _mkt("mlb-az-stl-2026-07-21-spread",
                  "Arizona Diamondbacks vs. St. Louis Cardinals",
                  [{"clob_token_id": "bA", "position_id": "qA",
                    "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
                   {"clob_token_id": "bB", "position_id": "qB",
                    "outcome_label": "St. Louis Cardinals", "outcome_index": 1}])
    prop = _mkt("mlb-az-stl-2026-07-21-hr-corbin-carroll-05",
                "Corbin Carroll: Home Runs O/U 0.5",
                [{"clob_token_id": "hO", "position_id": "pO",
                  "outcome_label": "Over", "outcome_index": 0},
                 {"clob_token_id": "hU", "position_id": "pU",
                  "outcome_label": "Under", "outcome_index": 1}])
    # Force each Phase A game onto a different sibling — real matching
    # returns the first exact-date hit, so without this the collision
    # path is unreachable in a unit test.
    assigned = {game_a.slug: g1, game_b.slug: g2}

    def _fake_match(parsed, market, fixtures, style):
        return assigned.get(market.slug)

    monkeypatch.setattr(pipeline, "_match_poly_game_fixture", _fake_match)
    resolved, _stats = pipeline._resolve_poly_markets(
        [prop, game_a, game_b], [g1, g2], cfg)
    err = capsys.readouterr().err
    assert "doubleheader slug key collision" in err
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[prop.slug].game_id == "dh-game-2"


def test_resolve_poly_markets_unseeded_prop_drops():
    from mappers.pipeline import _resolve_poly_markets
    cfg = _mlb_cfg()
    assert cfg is not None
    # A prop whose fixture no game market seeded this run drops (no fixture).
    prop = _mkt("mlb-lad-sf-2026-07-21-k-clayton-kershaw-65",
                "Clayton Kershaw: Strikeouts O/U 6.5",
                [{"clob_token_id": "kO", "position_id": "pO",
                  "outcome_label": "Over", "outcome_index": 0},
                 {"clob_token_id": "kU", "position_id": "pU",
                  "outcome_label": "Under", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([prop], [], cfg)
    assert resolved == []
    assert stats["no_fixture"] == 1


def test_resolve_poly_markets_spread_resolves_via_outcome_labels():
    from mappers.pipeline import _resolve_poly_markets
    cfg = _mlb_cfg()
    assert cfg is not None
    fx = _FullFX("AZ", "STL", "Arizona Diamondbacks", "St. Louis Cardinals",
                 "2026-07-21T23:00:00Z")
    # the spread question names ONE team; the fixture resolves from the two
    # outcome LABELS (both team names), NOT the slug.
    spread = _mkt("mlb-az-stl-2026-07-21",
                  "Spread: Arizona Diamondbacks (-1.5)",
                  [{"clob_token_id": "sA", "position_id": "pA",
                    "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
                   {"clob_token_id": "sB", "position_id": "pB",
                    "outcome_label": "St. Louis Cardinals", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([spread], [fx], cfg)
    assert len(resolved) == 1 and resolved[0][2] is fx
    assert stats["no_fixture"] == 0


# === Task 4b: single-team GAME-scope THREE_WAY_FIXED markets (soccer 3-way ML
# team-win / 1st-half-leader) must resolve via the same Phase-B slug key as
# player props -- see .superpowers/sdd/task-4-report.md's flagged gap. ===


def _soccer_ml_cfg():
    """Minimal soccer PolymarketConfig wiring only the 3-way-ML rules this
    task cares about (no league is wired yet; that's a later task)."""
    from mappers.exchanges import polymarket as pm
    return pm.PolymarketConfig(
        slug_prefix="mls",
        optic_league_id="usa_-_major_league_soccer",
        market_types={"moneyline_3way": pm.MarketType.MONEYLINE_3WAY},
        question_style="mlb_suffix",
        market_rules=(pm.soccer_ml_team_win_rule, pm.soccer_ml_draw_rule),
    )


def test_resolve_poly_markets_three_way_team_win_resolves_via_seeded_draw():
    from mappers.pipeline import _resolve_poly_markets
    cfg = _soccer_ml_cfg()
    fx = _FullFX("ATX", "SEA", "Austin FC", "Seattle Sounders FC", "2026-07-22T23:00:00Z")
    # the draw sub-market names BOTH teams -> resolves in Phase A and seeds
    # fixture_by_slug_key for the shared (prefix, teams, date) slug head.
    draw = _mkt("mls-atx-sea-2026-07-22",
                "Will Austin FC vs. Seattle Sounders FC end in a draw?",
                [{"clob_token_id": "dY", "position_id": "pdY",
                  "outcome_label": "Yes", "outcome_index": 0},
                 {"clob_token_id": "dN", "position_id": "pdN",
                  "outcome_label": "No", "outcome_index": 1}])
    # the team-win sub-market names only ONE team (team_b=None) -> cannot
    # name-match in Phase A; must defer to Phase B and resolve via the slug key.
    team_win = _mkt("mls-atx-sea-2026-07-22-ml-atx",
                    "Will Austin FC win on 2026-07-22?",
                    [{"clob_token_id": "wY", "position_id": "pwY",
                      "outcome_label": "Yes", "outcome_index": 0},
                     {"clob_token_id": "wN", "position_id": "pwN",
                      "outcome_label": "No", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([team_win, draw], [fx], cfg)
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[draw.slug] is fx
    assert by_slug[team_win.slug] is fx  # was silently dropped before the fix
    assert stats["no_fixture"] == 0


def test_resolve_poly_markets_three_way_team_win_drops_when_unseeded():
    from mappers.pipeline import _resolve_poly_markets
    cfg = _soccer_ml_cfg()
    # No same-fixture market seeds fixture_by_slug_key this run -> drops
    # gracefully (counted no_fixture), never crashes.
    team_win = _mkt("mls-atx-sea-2026-07-22-ml-atx",
                    "Will Austin FC win on 2026-07-22?",
                    [{"clob_token_id": "wY", "position_id": "pwY",
                      "outcome_label": "Yes", "outcome_index": 0},
                     {"clob_token_id": "wN", "position_id": "pwN",
                      "outcome_label": "No", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([team_win], [], cfg)
    assert resolved == []
    assert stats["no_fixture"] == 1


def test_resolve_poly_markets_three_way_draw_still_resolves_via_phase_a():
    """Regression: the DRAW form names both teams and must keep resolving via
    Phase A's name-match path unchanged (never rerouted into Phase B)."""
    from mappers.pipeline import _resolve_poly_markets
    cfg = _soccer_ml_cfg()
    fx = _FullFX("ATX", "SEA", "Austin FC", "Seattle Sounders FC", "2026-07-22T23:00:00Z")
    draw = _mkt("mls-atx-sea-2026-07-22",
                "Will Austin FC vs. Seattle Sounders FC end in a draw?",
                [{"clob_token_id": "dY", "position_id": "pdY",
                  "outcome_label": "Yes", "outcome_index": 0},
                 {"clob_token_id": "dN", "position_id": "pdN",
                  "outcome_label": "No", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([draw], [fx], cfg)
    assert len(resolved) == 1 and resolved[0][2] is fx
    assert stats["no_fixture"] == 0


def test_resolve_poly_markets_player_scope_still_defers_regression():
    """Regression: PLAYER-scope markets must still defer to Phase B exactly as
    before the deferral condition was extended."""
    from mappers.pipeline import _resolve_poly_markets
    cfg = _mlb_cfg()
    assert cfg is not None
    fx = _FullFX("AZ", "STL", "Arizona Diamondbacks", "St. Louis Cardinals",
                 "2026-07-21T23:00:00Z")
    game = _mkt("mlb-az-stl-2026-07-21",
                "Arizona Diamondbacks vs. St. Louis Cardinals",
                [{"clob_token_id": "gA", "position_id": "pA",
                  "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
                 {"clob_token_id": "gB", "position_id": "pB",
                  "outcome_label": "St. Louis Cardinals", "outcome_index": 1}])
    prop = _mkt("mlb-az-stl-2026-07-21-hr-corbin-carroll-05",
                "Corbin Carroll: Home Runs O/U 0.5",
                [{"clob_token_id": "hO", "position_id": "pO",
                  "outcome_label": "Over", "outcome_index": 0},
                 {"clob_token_id": "hU", "position_id": "pU",
                  "outcome_label": "Under", "outcome_index": 1}])
    resolved, stats = _resolve_poly_markets([prop, game], [fx], cfg)
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[prop.slug] is fx
    assert stats["no_fixture"] == 0

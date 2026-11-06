"""Tests for the UFC (MMA) v1 matcher (task-u1, ufc-probe-findings.md).

4 of poly's 6 UFC question forms are built (~67%/253 of the 346-market
census), reusing existing SideModes/Shapes verbatim -- no new Shape, no new
SideMode:
  - FIGHTER_MONEYLINE -> reuse MarketType.MONEYLINE (TEAM_LABEL).
  - TOTAL_ROUNDS_OU -> new MarketType.TOTAL_ROUNDS (OVER_UNDER).
  - GO_THE_DISTANCE -> new MarketType.FIGHT_GOES_DISTANCE (YESNO).
  - GAME_WIN_BY_KOTKO -> new MarketType.GAME_WIN_BY_KOTKO (YESNO).

The other 2 forms (GAME_WIN_BY_SUBMISSION, FIGHTER_WIN_BY_KOTKO) are
explicitly NOT built (no clean optic target / would silently mis-price onto
a broader "any finish" market) -- guard tests below confirm they parse to
None rather than being force-fit.

Slugs/questions below are byte-exact from the real bridge snapshot
(ufc_bridge_dump.json, condition_id
0xb8d1db7f6264ed8c4eae9c18f32bc213ae23048c2e013d730ef537e0a6cad208 and its
sibling markets for the same fight) -- NOT synthesized -- confirming the
slug format `ufc-<code><n>-<code><n>-YYYY-MM-DD[-<suffix>]` really does
share an identical <teams>-<date> head across the moneyline and the
zero-fighter forms, so pipeline._poly_slug_teams keys them identically and
Phase B can seed off Phase A's moneyline resolution.
"""

import dataclasses
import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch.optic import optic_config_for  # noqa: E402
from fetch.tip import optic_api_key_secret  # noqa: E402
from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.exchanges.kalshi import KalshiConfig  # noqa: E402
from mappers.market_types import MarketType, Scope, Shape  # noqa: E402
from mappers.pipeline import _match_poly_fixture, _resolve_poly_markets  # noqa: E402
from mappers.sport import Sport  # noqa: E402
from mappers.vocab.combat_markets import (  # noqa: E402
    UFC_MARKET_TYPES,
    ufc_market_rules,
)
from tests.mappers._combat_helpers import ufc_league_config  # noqa: E402

# === Wiring: UFC tip-only profile build ===


def test_ufc_profile_builds_from_tip():
    cfg = ufc_league_config()
    assert cfg.league == "ufc"
    assert cfg.sport is not None
    assert cfg.sport.value == "mma"


def test_ufc_kalshi_config_present():
    assert KalshiConfig(sport=Sport.MMA) == ufc_league_config().KALSHI


def test_ufc_px_is_none():
    assert ufc_league_config().PX is None


def test_ufc_polymarket_config_present():
    cfg = ufc_league_config().POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "ufc"
    assert cfg.optic_league_id == "ufc"
    assert cfg.question_style == "tennis_prefix"
    assert cfg.market_types == UFC_MARKET_TYPES
    assert cfg.market_rules is ufc_market_rules


def test_ufc_optic_league_id():
    assert ufc_league_config().OPTIC.league_id == "ufc"


def test_ufc_optic_table_types_include_polymarket_targets():
    table_types = ufc_league_config().OPTIC.table_types
    assert {
        "moneyline", "total_rounds", "go_the_distance", "win_by_ko_tko",
    } <= set(table_types)
    assert table_types["moneyline"] == MarketType.MONEYLINE
    assert table_types["total_rounds"] == MarketType.TOTAL_ROUNDS
    assert table_types["go_the_distance"] == MarketType.FIGHT_GOES_DISTANCE
    assert table_types["win_by_ko_tko"] == MarketType.GAME_WIN_BY_KOTKO


def test_ufc_has_tip_optic_secret():
    """UFC is tip-only; optic_config_for resolves it from the activated tip."""
    assert optic_api_key_secret("ufc") == "opticodds_access_key"
    assert optic_config_for("ufc") is not None


# === New MarketType (scope, shape) invariants ===


def test_total_rounds_is_game_total():
    mt = MarketType.TOTAL_ROUNDS
    assert mt.value == "total_rounds"
    assert mt.scope == Scope.GAME
    assert mt.shape == Shape.TOTAL


def test_fight_goes_distance_is_game_yes_no():
    mt = MarketType.FIGHT_GOES_DISTANCE
    assert mt.value == "fight_goes_distance"
    assert mt.scope == Scope.GAME
    assert mt.shape == Shape.YES_NO


def test_game_win_by_kotko_is_game_yes_no():
    mt = MarketType.GAME_WIN_BY_KOTKO
    assert mt.value == "game_win_by_kotko"
    assert mt.scope == Scope.GAME
    assert mt.shape == Shape.YES_NO


def test_moneyline_reused_no_new_constant():
    # Explicit per task spec: FIGHTER_MONEYLINE reuses MarketType.MONEYLINE
    # verbatim, no MarketType.FIGHTER_MONEYLINE constant exists.
    assert not hasattr(MarketType, "FIGHTER_MONEYLINE")
    assert MarketType.MONEYLINE.scope == Scope.GAME
    assert MarketType.MONEYLINE.shape == Shape.MONEYLINE


# === Parse tests: exact byte strings from ufc_bridge_dump.json ===


def _cfg():
    return ufc_league_config().POLYMARKET


def test_moneyline_parses():
    cfg = _cfg()
    assert cfg is not None
    out = pm.parse_question(
        "UFC Fight Night: Alberto Montes vs. Tommy McMillen (Featherweight, Main Card)", cfg,
    )
    assert out is not None
    assert out.market_type == MarketType.MONEYLINE
    assert out.side_mode == pm.SideMode.TEAM_LABEL
    assert out.team_a == pm.normalize_player_name("Alberto Montes")
    assert out.team_b == pm.normalize_player_name("Tommy McMillen")


def test_total_rounds_parses_every_line():
    cfg = _cfg()
    assert cfg is not None
    for line_str, line in [
        ("0.5", 0.5), ("1.5", 1.5), ("2.5", 2.5), ("3.5", 3.5), ("4.5", 4.5),
    ]:
        out = pm.parse_question(f"O/U {line_str} Rounds", cfg)
        assert out is not None, line_str
        assert out.market_type == MarketType.TOTAL_ROUNDS
        assert out.side_mode == pm.SideMode.OVER_UNDER
        assert out.line == line
        assert out.team_a is None
        assert out.team_b is None


def test_go_the_distance_parses():
    cfg = _cfg()
    assert cfg is not None
    out = pm.parse_question("Fight to Go the Distance?", cfg)
    assert out is not None
    assert out.market_type == MarketType.FIGHT_GOES_DISTANCE
    assert out.side_mode == pm.SideMode.YESNO
    assert out.team_a is None
    assert out.team_b is None


def test_game_win_by_kotko_parses():
    cfg = _cfg()
    assert cfg is not None
    out = pm.parse_question("Will the fight be won by KO or TKO?", cfg)
    assert out is not None
    assert out.market_type == MarketType.GAME_WIN_BY_KOTKO
    assert out.side_mode == pm.SideMode.YESNO
    assert out.team_a is None
    assert out.team_b is None


# === Dropped forms: must return None (intentionally unbuilt, never force-fit) ===


def test_game_win_by_submission_drops():
    # GAME_WIN_BY_SUBMISSION -- no clean optic target; confirmed absent from
    # UFC_MARKET_TYPES/ufc_market_rules entirely.
    cfg = _cfg()
    assert cfg is not None
    assert pm.parse_question("Will the fight be won by submission?", cfg) is None


def test_fighter_win_by_kotko_drops():
    # FIGHTER_WIN_BY_KOTKO -- only clean optic target is the BROADER "any
    # finish" market (a silent probability skew); deferred to a follow-up.
    cfg = _cfg()
    assert cfg is not None
    assert pm.parse_question("Will Tommy McMillen win by KO or TKO?", cfg) is None
    assert pm.parse_question("Will Alberto Montes win by KO or TKO?", cfg) is None


def test_dropped_forms_have_no_market_type_entries():
    assert "win_by_submission" not in UFC_MARKET_TYPES
    assert not any(mt.value == "game_win_by_submission" for mt in MarketType)
    assert not any(mt.value == "fighter_win_by_kotko" for mt in MarketType)


# === Pipeline: 0-fighter Phase-B resolution (the task's core verification) ===
#
# Real slugs from ufc_bridge_dump.json for condition_id
# 0xb8d1db7f6264ed8c4eae9c18f32bc213ae23048c2e013d730ef537e0a6cad208 and its
# siblings (same fight, 2026-07-18 card):
#   ufc-alb10-tom15-2026-07-18                      (moneyline)
#   ufc-alb10-tom15-2026-07-18-totals-0pt5           (total_rounds)
#   ufc-alb10-tom15-2026-07-18-go-the-distance       (go_the_distance)
#   ufc-alb10-tom15-2026-07-18-win-by-ko-tko         (game_win_by_kotko)
# All 5 share the identical "alb10"/"tom15" slug-team tokens + date head --
# verified directly against pipeline._poly_slug_teams/_poly_market_date.


class _FullFX:
    """Minimal optic-Fixture stand-in with the fields the poly pass reads."""

    def __init__(self, home, away, home_name, away_name, start_date):
        self.home, self.away = home, away
        self.home_name, self.away_name = home_name, away_name
        self.start_date = start_date


def _mkt(slug, question, outcomes):
    return pm.PolyMarket(
        condition_id="0x" + slug, slug=slug, question=question,
        outcomes=[pm.PolyOutcome(**o) for o in outcomes],
    )


_FX = _FullFX(
    "MONTES", "MCMILLEN", "Alberto Montes", "Tommy McMillen", "2026-07-18T23:00:00Z",
)

_ML = _mkt(
    "ufc-alb10-tom15-2026-07-18",
    "UFC Fight Night: Alberto Montes vs. Tommy McMillen (Featherweight, Main Card)",
    [
        {"clob_token_id": "mA", "position_id": "pA",
         "outcome_label": "Alberto Montes", "outcome_index": 0},
        {"clob_token_id": "mB", "position_id": "pB",
         "outcome_label": "Tommy McMillen", "outcome_index": 1},
    ],
)


def _rounds_market():
    return _mkt(
        "ufc-alb10-tom15-2026-07-18-totals-0pt5",
        "O/U 0.5 Rounds",
        [
            {"clob_token_id": "rO", "position_id": "pO",
             "outcome_label": "Over", "outcome_index": 0},
            {"clob_token_id": "rU", "position_id": "pU",
             "outcome_label": "Under", "outcome_index": 1},
        ],
    )


def _distance_market():
    return _mkt(
        "ufc-alb10-tom15-2026-07-18-go-the-distance",
        "Fight to Go the Distance?",
        [
            {"clob_token_id": "gY", "position_id": "pgY",
             "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "gN", "position_id": "pgN",
             "outcome_label": "No", "outcome_index": 1},
        ],
    )


def test_total_rounds_resolves_via_seeded_moneyline():
    cfg = _cfg()
    assert cfg is not None
    rounds = _rounds_market()
    resolved, stats = _resolve_poly_markets([rounds, _ML], [_FX], cfg)
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[_ML.slug] is _FX
    # Would silently drop as no_fixture before the pipeline gate change --
    # team_a is None (no fighter named), so Phase A's name-match can never
    # resolve it; the gate now defers it to Phase B, which resolves it via
    # the slug-team-token key the moneyline market seeded.
    assert by_slug[rounds.slug] is _FX
    assert stats["no_fixture"] == 0


def test_go_the_distance_resolves_via_seeded_moneyline():
    cfg = _cfg()
    assert cfg is not None
    distance = _distance_market()
    resolved, stats = _resolve_poly_markets([distance, _ML], [_FX], cfg)
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[_ML.slug] is _FX
    assert by_slug[distance.slug] is _FX
    assert stats["no_fixture"] == 0


def test_game_win_by_kotko_resolves_via_seeded_moneyline():
    cfg = _cfg()
    assert cfg is not None
    kotko = _mkt(
        "ufc-alb10-tom15-2026-07-18-win-by-ko-tko",
        "Will the fight be won by KO or TKO?",
        [
            {"clob_token_id": "kY", "position_id": "pkY",
             "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "kN", "position_id": "pkN",
             "outcome_label": "No", "outcome_index": 1},
        ],
    )
    resolved, stats = _resolve_poly_markets([kotko, _ML], [_FX], cfg)
    by_slug = {m.slug: rfx for (m, _p, rfx) in resolved}
    assert by_slug[_ML.slug] is _FX
    assert by_slug[kotko.slug] is _FX
    assert stats["no_fixture"] == 0


def test_total_rounds_drops_when_unseeded():
    # No same-fight moneyline market resolved this run -> the slug key is
    # never seeded -> drops gracefully (counted no_fixture), never crashes.
    cfg = _cfg()
    assert cfg is not None
    rounds = _rounds_market()
    resolved, stats = _resolve_poly_markets([rounds], [], cfg)
    assert resolved == []
    assert stats["no_fixture"] == 1


def test_moneyline_still_resolves_via_phase_a_unchanged():
    # Regression: the moneyline itself (both fighters named) must keep
    # resolving via Phase A's name-match path, never deferred.
    cfg = _cfg()
    assert cfg is not None
    resolved, stats = _resolve_poly_markets([_ML], [_FX], cfg)
    assert len(resolved) == 1 and resolved[0][2] is _FX
    assert stats["no_fixture"] == 0


def test_slug_team_tokens_agree_across_all_forms_for_same_fight():
    """Direct verification of the task's slug-format precondition: the
    zero-fighter forms and the moneyline for the SAME fight share an
    identical (frozenset(teams), date) key."""
    from mappers.pipeline import _poly_market_date, _poly_slug_teams

    slugs = [
        _ML.slug,
        "ufc-alb10-tom15-2026-07-18-totals-0pt5",
        "ufc-alb10-tom15-2026-07-18-go-the-distance",
        "ufc-alb10-tom15-2026-07-18-win-by-ko-tko",
    ]
    keys = {(frozenset(_poly_slug_teams(s)), _poly_market_date(s)) for s in slugs}
    assert len(keys) == 1  # all 4 forms share exactly one slug-team-token key


# === Fighter-name alias overlay (probe section D: 2 transliteration mismatches) ===


def test_zaynukov_alias_resolves_fixture():
    cfg = _cfg()
    assert cfg is not None
    fixtures = [_FullFX("ZAY", "OPP", "Magomed Zayunokov", "Some Opponent", "2026-07-18T23:00:00Z")]
    parsed = pm.parse_question(
        "UFC Fight Night: Magomed Zaynukov vs. Some Opponent (Lightweight, Main Card)", cfg,
    )
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-18")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_zaynukov_alias_without_scope_does_not_match():
    # Confirms the overlay (not some incidental normalization) is what
    # bridges the mismatch -- without team_alias_scope open, exact
    # tennis_prefix matching genuinely fails on the transliteration variant.
    cfg = _cfg()
    assert cfg is not None
    fixtures = [_FullFX("ZAY", "OPP", "Magomed Zayunokov", "Some Opponent", "2026-07-18T23:00:00Z")]
    parsed = pm.parse_question(
        "UFC Fight Night: Magomed Zaynukov vs. Some Opponent (Lightweight, Main Card)", cfg,
    )
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-18")
    assert _match_poly_fixture(parsed, fixtures, cfg.question_style) is None


def test_seokhyeon_ko_alias_resolves_fixture():
    cfg = _cfg()
    assert cfg is not None
    fixtures = [_FullFX("KO", "OPP", "Seok Hyun Ko", "Some Opponent", "2026-07-18T23:00:00Z")]
    parsed = pm.parse_question(
        "UFC Fight Night: Seokhyeon Ko vs. Some Opponent (Bantamweight, Prelims)", cfg,
    )
    assert parsed is not None
    parsed = dataclasses.replace(parsed, date="2026-07-18")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_ufc_alias_regression_normal_fighter_still_matches():
    # Regression guard: the other ~97% of fighters (no alias needed) still
    # resolve unaffected by the overlay being active.
    cfg = _cfg()
    assert cfg is not None
    fx = _match_poly_fixture(
        pm.ParsedMarket(
            market_type=MarketType.MONEYLINE,
            team_a=pm.normalize_player_name("Alberto Montes"),
            team_b=pm.normalize_player_name("Tommy McMillen"),
            side_mode=pm.SideMode.TEAM_LABEL,
            date="2026-07-18",
        ),
        [_FX],
        cfg.question_style,
    )
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx2 = _match_poly_fixture(
            pm.ParsedMarket(
                market_type=MarketType.MONEYLINE,
                team_a=pm.normalize_player_name("Alberto Montes"),
                team_b=pm.normalize_player_name("Tommy McMillen"),
                side_mode=pm.SideMode.TEAM_LABEL,
                date="2026-07-18",
            ),
            [_FX],
            cfg.question_style,
        )
    assert fx is _FX
    assert fx2 is _FX

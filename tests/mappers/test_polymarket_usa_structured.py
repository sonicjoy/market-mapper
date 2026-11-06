"""Polymarket US Path 2 on structured gateway fields (no symbol parsing).

Market shapes are copied from live ``gateway.polymarket.us`` payloads
(2026-09-26): MLB spreads carry an UNSIGNED ``line`` with the sign on the
long side's description, NFL spreads a SIGNED one; soccer 3-way winners
are one market per outcome with a team-less draw.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mappers.exchanges import optic
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.market_types import MarketType
from mappers.pipeline import (
    _build_optic_usa_index,
    _strip_unverified_usa_passthrough,
    _usa_bind_events,
    _usa_market_rows,
    _usa_slug_fixtures,
    _usa_stamp_rows,
    row_key,
)
from mappers.shared import TIE_SIDE, CanonicalRow
from mappers.vocab.poly_usa_smt import smt_spec

_NO_ALIASES = pus.TeamAliases(usa={}, kalshi={})


@dataclass
class _FX:
    fixture_id: str
    home: str
    away: str
    home_name: str
    away_name: str
    start_date: str
    sportradar_id: str | None = None
    home_optic_abbr: str = ""
    away_optic_abbr: str = ""


_DET_PIT = _FX(
    "F1", "DET", "PIT", "Detroit Tigers", "Pittsburgh Pirates",
    "2026-09-26T17:10:00Z", sportradar_id="63303065",
)
# Doubleheader game 2, same teams, 6h later.
_DET_PIT_DH2 = _FX(
    "F2", "DET", "PIT", "Detroit Tigers", "Pittsburgh Pirates",
    "2026-09-26T23:10:00Z",
)
_PIT = {"id": "3021", "abbreviation": "pit", "name": "Pittsburgh Pirates"}
_DET = {"id": "3010", "abbreviation": "det", "name": "Detroit Tigers"}

def _rec(
    smt: str,
    sides: list[dict[str, Any]],
    *,
    slug: str,
    line: float | None = None,
    event_id: str = "123158",
    start: str = "2026-09-26T17:10:00Z",
    sr: str = "4d3fd422-0b9a-475c-8392-fc3225a7f4b8",
    teams: list[dict[str, Any]] | None = None,
    league_id: int = 5,
    metadata: dict[str, Any] | None = None,
    market_id: str | None = None,
) -> pus.UsMarket:
    obj = {
        "league_id": league_id, "event_id": event_id, "event_ticker": "evt",
        "event_start": start, "sportradar_game_id": sr,
        "teams": teams if teams is not None else [_PIT, _DET],
        "market_id": market_id or slug, "slug": slug,
        "sports_market_type": smt, "line": line,
        "metadata": metadata or {}, "sides": sides,
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def _side(desc: str, long: bool, team: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"id": f"{desc}-{long}", "long": long, "description": desc}
    if team:
        out["team_id"] = team
    return out


def _bind(fx: _FX = _DET_PIT) -> pus.EventBind:
    return pus.EventBind(fixture=fx, team_sides={"3021": "PIT", "3010": "DET"})


# === SMT table ===


def test_smt_spec_maps_straight_to_market_types():
    assert smt_spec("baseball_team_full_game_spread") == (MarketType.POINT_SPREAD, "spread")
    assert smt_spec("baseball_player_total_bases") == (MarketType.PLAYER_BASES, "player_ou")
    assert smt_spec("baseball_team_inning3_winner") == (
        MarketType.INNING_3_WINNER_3WAY, "winner",
    )
    assert smt_spec("baseball_team_inning9_winner") is None


def test_smt_spec_generic_player_prop_falls_back_to_player_market_type():
    assert smt_spec("basketball_player_points") == (MarketType.PLAYER_POINTS, "player_ou")
    assert smt_spec("baseball_player_hits_allowed") == (
        MarketType.PLAYER_HITS_ALLOWED, "player_ou",
    )
    assert smt_spec("football_player_fantasy_points_ppr") is None


def test_not_equivalent_enums_never_map():
    assert smt_spec("ufc_round_of_finish") == (MarketType.TO_START_ROUND_2, "rof")
    # Exact score maps from its title since 2026-09-27 (polymarket_usa_titles).
    assert smt_spec("soccer_game_exact_score") == (MarketType.CORRECT_SCORE, "exact_score")
    # 2H / 4Q map despite the OT difference (a trading decision).
    assert smt_spec("football_team_second_half_spread") == (
        MarketType.SECOND_HALF_POINT_SPREAD, "spread",
    )


# === Event bind ===


def _any_market(**kw: Any) -> pus.UsMarket:
    return _rec("baseball_team_full_game_total", [], slug="tsc-x", **kw)


def test_bind_by_teams_and_kickoff_uses_names_not_symbol():
    bind, via = pus.bind_event(_any_market(), [_DET_PIT], _NO_ALIASES, set())
    assert via == "teams_kickoff"
    assert bind is not None
    assert bind.fixture is _DET_PIT
    assert bind.team_sides == {"3021": "PIT", "3010": "DET"}


def test_bind_doubleheader_by_kickoff_window():
    late = _any_market(start="2026-09-26T23:10:00Z")
    bind, _via = pus.bind_event(late, [_DET_PIT, _DET_PIT_DH2], _NO_ALIASES, set())
    assert bind is not None and bind.fixture is _DET_PIT_DH2


def test_bind_by_sportradar_int_when_gateway_uses_sr_form():
    soccer = _any_market(sr="sr:sport_event:63303065", start="2026-09-20T00:00:00Z")
    bind, via = pus.bind_event(soccer, [_DET_PIT], _NO_ALIASES, set())
    assert via == "sportradar"
    assert bind is not None and bind.fixture is _DET_PIT


def test_sportradar_uuid_never_joins():
    assert pus.sportradar_int("4d3fd422-0b9a-475c-8392-fc3225a7f4b8") == ""
    assert pus.sportradar_int("sr:match:52864807") == "52864807"


def test_bind_by_optic_passthrough_evidence():
    stranger = _any_market(teams=[{"id": "1", "name": "Nobody FC"}], start="2020-01-01T00:00:00Z")
    bind, via = pus.bind_event(stranger, [_DET_PIT], _NO_ALIASES, {"F1"})
    assert via == "optic_passthrough"
    assert bind is not None and bind.team_sides == {}


def test_venue_kickoff_outranks_optic_passthrough():
    # 2026-09-25 BAL@NYY: Optic hung props on doubleheader game 2, the
    # venue kickoff named game 1. The venue wins; passthrough gets stripped.
    bind, via = pus.bind_event(
        _any_market(), [_DET_PIT, _DET_PIT_DH2], _NO_ALIASES, {"F2"},
    )
    assert via == "teams_kickoff"
    assert bind is not None and bind.fixture is _DET_PIT


def test_sportradar_vs_teams_kickoff_conflict_drops():
    other = _FX("F7", "DET", "PIT", "Detroit Tigers", "Pittsburgh Pirates",
                "2026-09-01T17:10:00Z", sportradar_id="999")
    market = _any_market(sr="sr:sport_event:999")
    bind, reason = pus.bind_event(market, [_DET_PIT, other], _NO_ALIASES, set())
    assert bind is None and reason == "conflict_sportradar_vs_teams_kickoff"


def test_passthrough_breaks_teams_kickoff_tie():
    twin = _FX("F9", "DET", "PIT", "Detroit Tigers", "Pittsburgh Pirates",
               "2026-09-26T18:00:00Z")
    bind, via = pus.bind_event(_any_market(), [_DET_PIT, twin], _NO_ALIASES, {"F9"})
    assert via == "optic_passthrough" and bind is not None and bind.fixture is twin


def test_bind_ambiguous_kickoff_drops():
    twin = _FX("F9", "DET", "PIT", "Detroit Tigers", "Pittsburgh Pirates",
               "2026-09-26T18:00:00Z")
    bind, reason = pus.bind_event(_any_market(), [_DET_PIT, twin], _NO_ALIASES, set())
    assert bind is None and reason == "ambiguous_teams_kickoff"


def test_bind_team_by_alias_code_when_names_differ():
    fx = _FX("F3", "WHUF6", "MIL", "Hammers", "Milan", "2026-09-26T17:10:00Z")
    teams = [{"id": "a", "abbreviation": "whu", "name": "West Ham United"},
             {"id": "b", "abbreviation": "mil", "name": "AC Milan"}]
    aliases = pus.TeamAliases(usa={"whu": "WHUF6"}, kalshi={})
    bind, via = pus.bind_event(_any_market(teams=teams), [fx], aliases, set())
    assert via == "teams_kickoff"
    assert bind is not None and bind.team_sides == {"a": "WHUF6", "b": "MIL"}


def test_club_name_containment_binds_and_elimination_names_the_other():
    """Nueva Chicago ⊂ CA Nueva Chicago binds; Dubai Basketball ≠ BC Dubai only by elimination."""
    fx = _FX("F4", "CHI", "ALM", "CA Nueva Chicago", "Club Almagro", "2026-09-27T18:30:00Z")
    teams = [{"id": "a", "abbreviation": "zzz", "name": "Club Almagro"},
             {"id": "b", "abbreviation": "yyy", "name": "Nueva Chicago"}]
    m = _any_market(teams=teams, start="2026-09-27T18:30:00Z", sr="")
    bind, via = pus.bind_event(m, [fx], _NO_ALIASES, set())
    assert via == "teams_kickoff"
    assert bind is not None and bind.team_sides == {"a": "ALM", "b": "CHI"}
    fx2 = _FX("F5", "FEN", "DUB", "Fenerbahce", "BC Dubai", "2026-10-02T17:45:00Z")
    teams2 = [{"id": "c", "abbreviation": "qqq", "name": "Fenerbahce Istanbul"},
              {"id": "d", "abbreviation": "rrr", "name": "Dubai Basketball"}]
    m2 = _any_market(teams=teams2, start="2026-10-02T17:45:00Z", sr="")
    # One team alone never binds the event...
    assert pus.bind_event(m2, [fx2], _NO_ALIASES, set())[0] is None
    # ...but once bound (here by passthrough), elimination names the other side.
    bind2, _ = pus.bind_event(m2, [fx2], _NO_ALIASES, {"F5"})
    assert bind2 is not None and bind2.team_sides == {"c": "FEN", "d": "DUB"}


def test_fighter_binds_on_optic_surname_initials_form():
    """Optic lists most boxers as "Richards C."; the gateway has full names."""
    fx = _FX("F6", "MAA9", "AGZ5", "MacMillan A.", "Azagier G.", "2026-09-26T17:30:00Z")
    teams = [{"id": "a", "abbreviation": "alemac", "name": "Alex Macmillan"},
             {"id": "b", "abbreviation": "guiaza", "name": "Guillaume Azagier"}]
    m = _any_market(teams=teams, start="2026-09-26T17:30:00Z", sr="", league_id=55)
    bind, via = pus.bind_event(m, [fx], _NO_ALIASES, set(), person=True)
    assert via == "teams_kickoff"
    assert bind is not None and bind.team_sides == {"a": "MAA9", "b": "AGZ5"}
    # Clubs never take the initials path.
    assert pus.bind_event(m, [fx], _NO_ALIASES, set())[0] is None


def test_surname_initials_needs_surname_and_every_initial():
    from mappers.canonical_codes import person_surname_initials as fits

    assert fits("Cesar Mateo Tapia", "Tapia C. M.")
    assert fits("Alexis de la Cerda", "De la Cerda A.")
    assert not fits("Craig Richards", "Richards D.")
    assert not fits("Craig Richards", "Richardson C.")
    assert not fits("Cesar Tapia", "Tapia C. M.")
    assert not fits("Richards", "Richards C.")


def test_boxing_league_builds_from_tip_with_its_crypto_pin():
    """crypto_mma_v1 on boxing_matches must not drop the whole league."""
    from mappers.control_plane.rows import LeagueRow
    from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
    from mappers.seed.tip_factories import build_tip_league, tip_only_ok, with_code_poly_usa

    row = LeagueRow(
        league="boxing_matches", sport="boxing", optic_league_id="boxing_matches",
        extra_optic_league_ids=[], fixture_source="api", fixture_horizon_hours=168.0,
        enabled=True, output_order=[], notes=None, tombstone=False, settings={},
        exchanges=[
            {"sportsbook": "optic", "enabled": True, "parser_profile": "optic_standard_v1",
             "settings": {"entity_type": "fighter"}, "source_league_id": "boxing_matches"},
            {"sportsbook": "crypto.com", "enabled": True, "parser_profile": "crypto_mma_v1",
             "settings": {"league": "WBA", "sport_grouping": "BOXING"},
             "source_league_id": "WBA"},
            {"sportsbook": "polymarket_usa", "enabled": True,
             "parser_profile": "poly_usa_generic_v1",
             "settings": {"slug_prefix": "boxing"}, "source_league_id": "boxing"},
        ],
    )
    assert tip_only_ok(row)
    cfg = build_tip_league(row)
    assert cfg.CRYPTO is None
    # The tip pin builds nothing; code reads gateway league 55 (Boxing).
    assert cfg.POLYMARKET_USA is None
    assert PolyUsaConfig(frozenset({55})) == with_code_poly_usa(cfg).POLYMARKET_USA


def test_esports_games_are_maps_and_cricket_winner_wired():
    assert smt_spec("esports_series_total_games") == (MarketType.TOTAL_MAPS, "total")
    assert smt_spec("esports_series_game_handicap") == (MarketType.MAP_HANDICAP, "spread")
    assert smt_spec("esports_game_winner_2") == (MarketType.MAP_2_WINNER, "team_outcome")
    assert smt_spec("cricket_match_winner") == (MarketType.MONEYLINE, "winner")
    assert smt_spec("boxing_match_winner") == (MarketType.MONEYLINE, "winner")
    assert smt_spec("hockey_team_full_game_spread") == (MarketType.POINT_SPREAD, "spread")
    assert smt_spec("soccer_game_total_corners") == (MarketType.TOTAL_CORNERS, "total")


def test_per_team_outcome_maps_the_yes_side_only():
    m = _rec(
        "esports_map_winner_1",
        [_side("Yes", True, "3021"), _side("No", False, "3021")], slug="map1-pit",
    )
    assert pus.market_bets(m, _bind()) == [("map_1_winner", None, None, "PIT")]


# === Market → bets ===


def test_mlb_spread_unsigned_line_signed_from_long_description():
    m = _rec(
        "baseball_team_full_game_spread",
        [_side("+2.50", True, "3021"), _side("-2.50", False, "3010")],
        slug="asc-mlb-pit-det-2026-09-26-pos-2pt5", line=2.5,
    )
    bets = pus.market_bets(m, _bind())
    assert bets == [
        ("point_spread", None, 2.5, "PIT"),
        ("point_spread", None, -2.5, "DET"),
    ]


def test_nfl_spread_signed_line():
    m = _rec(
        "baseball_team_full_game_spread",
        [_side("-10.50", True, "3021"), _side("+10.50", False, "3010")],
        slug="s", line=-10.5,
    )
    assert pus.market_bets(m, _bind())[0] == ("point_spread", None, -10.5, "PIT")


def test_spread_description_disagreeing_with_line_drops():
    m = _rec(
        "baseball_team_full_game_spread",
        [_side("+1.50", True, "3021"), _side("-1.50", False, "3010")],
        slug="s", line=2.5,
    )
    assert pus.market_bets(m, _bind()) == []


def test_integer_line_total_stamps_only_the_paying_side():
    # "Over 45" Yes; No also wins at exactly 45 → not Optic's under.
    m = _rec(
        "baseball_team_full_game_total",
        [_side("Over", True), _side("Under", False)], slug="tsc", line=45,
    )
    assert pus.market_bets(m, _bind()) == [("game_total", None, 45.0, "over")]


def test_integer_spread_stamps_only_long_side():
    m = _rec(
        "baseball_team_full_game_spread",
        [_side("-3.00", True, "3021"), _side("+3.00", False, "3010")], slug="s", line=-3,
    )
    assert pus.market_bets(m, _bind()) == [("point_spread", None, -3.0, "PIT")]


def test_total_stamps_over_and_under():
    m = _rec(
        "baseball_team_full_game_total",
        [_side("Over", True), _side("Under", False)], slug="tsc", line=7.5,
    )
    assert pus.market_bets(m, _bind()) == [
        ("game_total", None, 7.5, "over"), ("game_total", None, 7.5, "under"),
    ]


def test_team_total_yes_no_sides_with_team_entity():
    m = _rec(
        "baseball_team_total_runs",
        [_side("Yes", True, "3010"), _side("No", False, "3010")], slug="tt", line=3.5,
    )
    assert pus.market_bets(m, _bind()) == [
        ("team_total", "DET", 3.5, "over"), ("team_total", "DET", 3.5, "under"),
    ]


def test_two_team_winner_stamps_both_sides():
    m = _rec(
        "baseball_team_full_game_winner",
        [_side("Pittsburgh Pirates", True, "3021"), _side("Detroit Tigers", False, "3010")],
        slug="aec-mlb-pit-det-2026-09-26",
    )
    assert pus.market_bets(m, _bind()) == [
        ("moneyline", None, None, "PIT"), ("moneyline", None, None, "DET"),
    ]


def test_player_at_least_n_is_over_n_minus_half():
    m = _rec(
        "baseball_player_home_runs",
        [_side("Yes", True, "3021"), _side("No", False, "3021")],
        slug="astatc-hr", line=1,
        metadata={"playerName": "Brandon Lowe", "lineLabel": "1+"},
    )
    bets = pus.market_bets(m, _bind())
    assert bets == [
        ("player_home_runs", "brandon_lowe", 0.5, "over"),
        ("player_home_runs", "brandon_lowe", 0.5, "under"),
    ]


def test_player_integer_line_without_plus_label_drops():
    m = _rec(
        "baseball_player_home_runs",
        [_side("Yes", True), _side("No", False)], slug="p", line=15,
        metadata={"playerName": "Bryce Young", "lineLabel": "O15"},
    )
    assert pus.market_bets(m, _bind()) == []


def test_unwired_market_type_drops():
    m = _rec("baseball_team_inning9_winner", [_side("Yes", True), _side("No", False)], slug="i9")
    assert pus.market_bets(m, _bind()) == []


def _soccer_group() -> list[pus.UsMarket]:
    smt = "soccer_team_full_time_winner"
    return [
        _rec(smt, [_side("Yes", True, "3021"), _side("No", False, "3021")], slug="w-pit"),
        _rec(smt, [_side("Yes", True, "3010"), _side("No", False, "3010")], slug="w-det"),
        _rec(smt, [_side("Yes", True), _side("No", False)], slug="w-draw"),
    ]


def test_three_way_draw_identified_by_elimination():
    group = _soccer_group()
    draws = pus.draw_market_ids(group)
    assert draws == frozenset({"w-draw"})
    sides = [pus.market_bets(m, _bind(), draws) for m in group]
    assert sides == [
        [("moneyline_3way", None, None, "PIT")],
        [("moneyline_3way", None, None, "DET")],
        [("moneyline_3way", None, None, TIE_SIDE)],
    ]


def test_teamless_winner_outside_complete_group_is_not_a_draw():
    lone = _soccer_group()[2:]
    assert pus.draw_market_ids(lone) == frozenset()
    assert pus.market_bets(lone[0], _bind()) == []


def test_btts_yes_no():
    m = _rec("soccer_game_btts", [_side("Yes", True), _side("No", False)], slug="b", line=1)
    assert pus.market_bets(m, _bind()) == [
        ("btts", None, None, "yes"), ("btts", None, None, "no"),
    ]


# === Pipeline: bind → strip → stamp ===


_SPREAD_SLUG = "asc-mlb-pit-det-2026-09-26-pos-2pt5"


def _row(fx: _FX, side: str, line: float, optic_id: str) -> CanonicalRow:
    return CanonicalRow(
        league="mlb", start_date=fx.start_date, home=fx.home, away=fx.away,
        market_type="point_spread", side=side, line=line, optic_id=optic_id,
    )


def _odd(oid: str, slug: str | None) -> optic.Odd:
    src = {"Polymarket (USA)": {"market_id": slug}} if slug else {}
    return optic.Odd(id=oid, market_id="point_spread", grouping_key="default", source_ids=src)


def _spread_market() -> pus.UsMarket:
    return _rec(
        "baseball_team_full_game_spread",
        [_side("+2.50", True, "3021"), _side("-2.50", False, "3010")],
        slug=_SPREAD_SLUG, line=2.5,
    )


def _run(rows: list[CanonicalRow], odds: dict[str, optic.Odd], fixtures: list[_FX],
         markets: list[pus.UsMarket]) -> tuple[dict[tuple, CanonicalRow], dict[str, int]]:
    row_index = {row_key(r): r for r in rows}
    stats = {"stamped": 0, "dropped_no_optic": 0, "no_bets": 0,
             "agree": 0, "conflict": 0, "stripped": 0}
    binds = _usa_bind_events(
        markets, fixtures, _NO_ALIASES,
        _usa_slug_fixtures(_build_optic_usa_index(row_index, odds), fixtures),
        person=False, stats=stats,
    )
    computed = _usa_market_rows(markets, binds, {}, "mlb", stats)
    stats["stripped"] = _strip_unverified_usa_passthrough(
        row_index, odds, markets, binds, computed, None)
    _usa_stamp_rows(
        computed, _build_optic_usa_index(row_index, odds), row_index, stats, odds, None,
    )
    return row_index, stats


def test_stamps_both_spread_sides_when_optic_has_no_passthrough():
    rows = [_row(_DET_PIT, "PIT", 2.5, "o1"), _row(_DET_PIT, "DET", -2.5, "o2")]
    odds = {"o1": _odd("o1", None), "o2": _odd("o2", None)}
    row_index, stats = _run(rows, odds, [_DET_PIT], [_spread_market()])
    assert stats["stamped"] == 2
    assert {r.polymarket_usa_market_id for r in row_index.values()} == {_SPREAD_SLUG}


def test_keeps_matching_passthrough_and_counts_agree():
    rows = [_row(_DET_PIT, "PIT", 2.5, "o1")]
    odds = {"o1": _odd("o1", _SPREAD_SLUG)}
    _row_index, stats = _run(rows, odds, [_DET_PIT], [_spread_market()])
    assert stats["stripped"] == 0 and stats["agree"] == 1
    assert "Polymarket (USA)" in odds["o1"].source_ids


def test_strips_passthrough_hung_on_wrong_side():
    rows = [_row(_DET_PIT, "PIT", -2.5, "o1")]
    odds = {"o1": _odd("o1", _SPREAD_SLUG)}
    _row_index, stats = _run(rows, odds, [_DET_PIT], [_spread_market()])
    assert stats["stripped"] == 1
    assert "Polymarket (USA)" not in odds["o1"].source_ids


def test_strips_passthrough_on_clone_fixture_then_restamps_true_one():
    # Optic hangs the symbol on the doubleheader game 2; teams+kickoff say game 1.
    rows = [_row(_DET_PIT_DH2, "PIT", 2.5, "clone"), _row(_DET_PIT, "PIT", 2.5, "true")]
    odds = {"clone": _odd("clone", _SPREAD_SLUG), "true": _odd("true", None)}
    row_index, stats = _run(rows, odds, [_DET_PIT, _DET_PIT_DH2], [_spread_market()])
    assert stats["stripped"] == 1
    assert "Polymarket (USA)" not in odds["clone"].source_ids
    assert stats["stamped"] == 1
    true_row = next(r for r in row_index.values() if r.optic_id == "true")
    assert true_row.polymarket_usa_market_id == _SPREAD_SLUG


def test_unwired_type_passthrough_pinned_to_bound_fixture():
    # Bound event, unwired type: passthrough on ANOTHER fixture is stripped.
    unwired = _rec("baseball_team_inning9_winner", [_side("Yes", True), _side("No", False)],
                   slug="atc-i9")
    rows = [_row(_DET_PIT_DH2, "PIT", 2.5, "o1")]
    odds = {"o1": _odd("o1", "atc-i9")}
    _row_index, stats = _run(rows, odds, [_DET_PIT, _DET_PIT_DH2], [unwired])
    assert stats["stripped"] == 1


def test_unknown_symbol_passthrough_is_kept():
    rows = [_row(_DET_PIT, "PIT", 2.5, "o1")]
    odds = {"o1": _odd("o1", "asc-mlb-never-seen")}
    _row_index, stats = _run(rows, odds, [_DET_PIT], [_spread_market()])
    assert stats["stripped"] == 0


def test_empty_gateway_snapshot_strips_nothing():
    rows = [_row(_DET_PIT, "PIT", -2.5, "o1")]
    odds = {"o1": _odd("o1", _SPREAD_SLUG)}
    _row_index, stats = _run(rows, odds, [_DET_PIT], [])
    assert stats["stripped"] == 0


def test_unwired_type_on_bound_event_keeps_passthrough():
    unwired = _rec("baseball_team_inning9_winner", [_side("Yes", True), _side("No", False)],
                   slug="atc-i9")
    rows = [_row(_DET_PIT, "PIT", 2.5, "o1")]
    odds = {"o1": _odd("o1", "atc-i9")}
    _row_index, stats = _run(rows, odds, [_DET_PIT], [_spread_market(), unwired])
    assert stats["stripped"] == 0
    assert stats["no_bets"] == 1


def test_clob_only_selection_id_is_not_judged():
    rows = [_row(_DET_PIT, "PIT", -2.5, "o1")]
    odd = optic.Odd(id="o1", market_id="point_spread", grouping_key="default",
                    source_ids={"Polymarket (USA)": {"selection_id": _SPREAD_SLUG}})
    _row_index, stats = _run(rows, {"o1": odd}, [_DET_PIT], [_spread_market()])
    assert stats["stripped"] == 0


def test_race_to_points_team_and_neither_by_elimination():
    smt = "football_game_race_to_points"
    group = [
        _rec(smt, [_side("Yes", True, "3021"), _side("No", False, "3021")], slug="r35-pit", line=35),
        _rec(smt, [_side("Yes", True, "3010"), _side("No", False, "3010")], slug="r35-det", line=35),
        _rec(smt, [_side("Yes", True), _side("No", False)], slug="r35-none", line=35),
        _rec(smt, [_side("Yes", True, "3021"), _side("No", False, "3021")], slug="r7-pit", line=7),
    ]
    draws = pus.draw_market_ids(group)
    assert draws == frozenset({"r35-none"})
    assert [pus.market_bets(m, _bind(), draws) for m in group] == [
        [("race_to_points", None, 35.0, "PIT")],
        [("race_to_points", None, 35.0, "DET")],
        [("race_to_points", None, 35.0, TIE_SIDE)],
        [("race_to_points", None, 7.0, "PIT")],
    ]


def test_yrfi_at_least_one_run_is_first_inning_over_half():
    m = _rec(
        "baseball_team_first_inning_run",
        [_side("Yes", True, "3010"), _side("No", False, "3010")],
        slug="astatc-mlb-atl-mia-2026-09-26-yrfi", line=1,
    )
    assert pus.market_bets(m, _bind()) == [
        ("first_inning_total", None, 0.5, "over"),
        ("first_inning_total", None, 0.5, "under"),
    ]


def _split_squad(event_id: str, slug: str) -> pus.UsMarket:
    return _rec(
        "baseball_team_full_game_spread",
        [_side("+2.50", True, "3021"), _side("-2.50", False, "3010")],
        slug=slug, line=2.5, event_id=event_id,
    )


def test_two_events_on_one_fixture_drop_unless_passthrough_names_one():
    """Split-squad: same teams, same kickoff, two venue events, one Optic game."""
    a, b = _split_squad("E1", "asc-a"), _split_squad("E2", "asc-b")
    stats: dict[str, int] = {}
    binds = _usa_bind_events([a, b], [_DET_PIT], _NO_ALIASES, {}, person=False, stats=stats)
    assert binds == {} and stats["bind_shared_fixture"] == 2
    stats = {}
    binds = _usa_bind_events(
        [a, b], [_DET_PIT], _NO_ALIASES, {"asc-b": {"F1"}}, person=False, stats=stats,
    )
    assert set(binds) == {"E2"} and stats["bind_shared_fixture"] == 1

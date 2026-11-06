"""STX pass over the 2026-10-28 capture: what maps, what is held and why, players, row shape, key parity."""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta

import pytest

from BigQuery.load_mappings import ALL_COLUMNS
from mappers.exchanges import optic
from mappers.exchanges.stx import HOME, NO, YES
from mappers.exchanges.stx_fixtures import fixture_from_mmmapper
from mappers.exchanges.stx_names import exact_name
from mappers.exchanges.stx_pass import StxContext, StxSideMapping, event_gate, market_mapping_row, run_pass
from mappers.exchanges.stx_players import optic_player_index
from mappers.pipeline import row_key
from mappers.shared import TIE_SIDE, normalize_line, parse_iso_datetime
from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES
from mappers.vocab.stx_markets import TIE_PAYS_HALF, StxMarketRule
from tests.mappers import _stx_capture as cap

REASON_CODES = {
    "unknown_rules",
    "excluded_family",
    "unknown_competition",
    "competition_held",
    "family_held",
    "family_not_reviewed",
    "no_optic_market",
    "unknown_stat",
    "optic_market_not_in_vocab",
    "not_a_game",
    "market_not_open",
    "event_not_scheduled",
    "event_started",
    "no_fixture",
    "ambiguous_fixture",
    "orientation_flip",
    "team_unresolved",
    "no_team_lands",
    "no_side",
    "unreadable_market",
    "no_roster",
    "player_not_on_roster",
    "player_ambiguous_on_roster",
    "roster_team_not_in_event",
    "no_optic_players",
    "player_not_in_optic",
    "player_ambiguous_in_optic",
    "shape_mismatch",
}


def _ctx(**kw) -> StxContext:
    return StxContext(
        fixtures=list(cap.fixtures()), as_of=cap.AS_OF, rosters=cap.rosters(), optic_players=cap.optic_players(), **kw
    )


_PASS: list[StxSideMapping] = []


def _sides() -> list[StxSideMapping]:
    if not _PASS:
        _PASS.extend(run_pass(cap.markets(), _ctx())[0])
    return _PASS


def _by_market(market_id: str) -> dict[str, StxSideMapping]:
    return {s.side: s for s in _sides() if s.market.market_id == market_id}


def _rule(s: StxSideMapping) -> StxMarketRule:
    assert s.rule is not None
    return s.rule


def _home(s: StxSideMapping) -> str:
    home = s.market.participant(HOME)
    return home.name if home else ""


def test_mapped_sides_per_family_on_the_capture():
    """Regression lock on the 2026-10-28 capture: only safe-now families map."""
    mapped = Counter((s.market.competition, _rule(s).family) for s in _sides() if s.mapped)
    assert mapped == Counter(
        {
            ("NFL", "team_total"): 504,
            ("NFL", "player_prop"): 310,
            ("NCAAF", "winner"): 204,
            ("NFL", "spread"): 140,
            ("NFL", "total"): 140,
            ("NBA", "player_prop"): 136,
            ("NFL", "winner"): 56,
            ("NBA", "winner"): 48,
            ("NHL", "winner"): 16,
            ("Serie A", "3way"): 15,
            ("ISL", "3way"): 3,
        }
    )


def test_every_market_gets_both_sides_and_every_refusal_a_known_reason():
    sides = _sides()
    assert len(sides) == 2 * len(cap.markets())
    assert {s.reason_code for s in sides if not s.mapped} <= REASON_CODES


@pytest.mark.parametrize(
    ("competition", "rules", "stat", "code", "needle"),
    [
        ("NHL", "spread", None, "family_held", "Q6"),
        ("NHL", "over_under", None, "family_held", "total_goals"),
        ("NCAAF", "player_stat_line", "TD_SCORE", "family_held", "Q4"),
        ("NHL", "player_stat_line", "GOALS", "family_not_reviewed", "NHL player_prop"),
        ("AFC", "home_winner_regulation_3way", None, "competition_held", "AFC"),
        ("Ranji Trophy", "draw_regulation_3way", None, "competition_held", "cricket"),
        ("MLB", "home_winner", None, "competition_held", "MLB"),
        ("NFL", "event_stat_line", "BOTH_SCORE", "no_optic_market", "BOTH_SCORE"),
        ("NFL", "event_stat_line", "OVERTIME", "family_not_reviewed", "will_there_be_overtime"),
        ("Serie A", "home_winner_regulation_3way_r1", None, "family_not_reviewed", "3way_1h"),
        ("NFL", "superbowl_champion", None, "excluded_family", "superbowl_champion"),
        ("Bitcoin", "race_winner", None, "excluded_family", "race_winner"),
    ],
)
def test_held_families_carry_their_reason(competition, rules, stat, code, needle):
    hits = [
        s
        for s in _sides()
        if s.market.competition == competition and s.market.rules == rules and (stat is None or s.market.stat == stat)
    ]
    assert hits
    assert {s.reason_code for s in hits} == {code}
    assert all(needle in (s.reason or "") for s in hits)


def test_the_26_stale_started_events_are_all_gated():
    stale = {}
    for m in cap.markets():
        if m.event_type.endswith(("_game", "_match")) and parse_iso_datetime(m.event_start) < cap.AS_OF - timedelta(
            hours=6
        ):
            stale.setdefault(m.event_id, m)
    assert len(stale) == 26
    assert Counter(m.event_status for m in stale.values()) == Counter(in_progress=18, completed=7, scheduled=1)
    assert all(event_gate(m, cap.AS_OF) for m in stale.values())


def test_suspended_markets_keep_their_mapping():
    suspended = [
        s
        for s in _sides()
        if s.market.status == "suspended"
        and s.market.competition == "NFL"
        and s.market.rules == "participant_stat_line"
    ]
    assert suspended and all(s.mapped for s in suspended if s.market.event_id == cap.GB_CAR_EVENT)


def test_neutral_site_event_maps_nothing():
    navy = [s for s in _sides() if _home(s) == "Navy Midshipmen" and s.market.rules in ("home_winner", "away_winner")]
    assert navy and {s.reason_code for s in navy} == {"orientation_flip"}


def test_gb_car_lines():
    """Green Bay (home) v Carolina, 2026-10-30 00:15Z: Optic fixture 20261030CB911D38."""
    win = _by_market("0a0b4f52-d056-4be2-9632-f8a33cb938ff")  # home_winner
    assert (win[YES].selection_side, win[NO].selection_side) == ("GB", "CAR")
    assert _rule(win[YES]).flags == (TIE_PAYS_HALF,) == _rule(win[NO]).flags
    spread = _by_market("8e833e5c-ba98-4105-8ffe-8a1684be25c2")  # spread -2.5
    assert (spread[YES].selection_side, spread[YES].line) == ("GB", -2.5)
    assert (spread[NO].selection_side, spread[NO].line) == ("CAR", 2.5)
    total = _by_market("846559f6-455b-4e8c-ac23-09e752fd31aa")  # over_under 46.5
    assert (total[YES].selection_side, total[NO].selection_side, total[NO].line) == ("over", "under", 46.5)
    fg = _by_market("fd625c0d-a084-4234-a6bb-02a1a71c060a")  # away FIELD_GOALS 1.5
    assert (fg[YES].entity, fg[YES].selection_side, _rule(fg[YES]).optic_market_id) == (
        "CAR",
        "over",
        "team_total_field_goals",
    )
    pass_yds = _by_market("37b4970c-0572-42c5-b10b-d8da580af3ab")  # Jordan Love PASS_YDS 260.5
    assert (pass_yds[YES].entity, pass_yds[YES].optic_player_id, pass_yds[NO].selection_side) == (
        "jordan_love",
        "E7BCA7FF5B4A",
        "under",
    )


def test_soccer_draw_is_the_tie_side_and_its_no_is_not_mapped():
    draws = [s for s in _sides() if s.market.competition == "Serie A" and s.market.rules == "draw_regulation_3way"]
    assert {s.selection_side for s in draws if s.side == YES} == {TIE_SIDE}
    assert {s.reason_code for s in draws if s.side == NO} == {"no_side"}


def _prop_players(event_id: str) -> set[str]:
    return {m.player for m in cap.markets() if m.event_id == event_id and m.rules == "player_stat_line" and m.player}


def test_106_of_106_prop_players_match_one_optic_player_by_exact_name():
    games = {
        cap.GB_CAR_EVENT: "NFL GB v CAR",
        cap.WSH_PHI_EVENT: "NHL WSH v PHI",
        cap.ATL_MIA_EVENT: "NBA ATL v MIA",
        cap.UGA_FLA_EVENT: "NCAAF UGA v FLA",
    }
    total = 0
    for event_id, game in games.items():
        idx = optic_player_index((r["player_id"], r["selection"]) for r in cap.player_selection_rows(game))
        for name in _prop_players(event_id):
            assert len(idx.get(exact_name(name), {})) == 1, (game, name)
            total += 1
    assert total == 106


def test_396_of_396_props_on_the_rostered_games_find_one_roster_listing():
    n = 0
    for event_id in (cap.GB_CAR_EVENT, cap.WSH_PHI_EVENT, cap.ATL_MIA_EVENT):
        roster = cap.rosters()[event_id]
        assert roster is not None
        for m in cap.markets():
            if m.event_id == event_id and m.rules == "player_stat_line":
                assert len(roster.listings[exact_name(m.player)]) == 1, m.player
                n += 1
    assert n == 396
    assert cap.rosters()[cap.UGA_FLA_EVENT] is None


def test_last_name_is_never_enough():
    idx = cap.optic_players()["202610282B59BAE2"]  # ATL v MIA
    assert {"aaron wiggins", "andrew wiggins"} <= set(idx)
    assert idx["aaron wiggins"].keys() != idx["andrew wiggins"].keys()


def test_market_mapping_row_shape():
    mapped = market_mapping_row(_by_market("8e833e5c-ba98-4105-8ffe-8a1684be25c2")[YES])
    assert set(ALL_COLUMNS) <= set(mapped)
    assert mapped["sportsbook"] == "STX"
    assert mapped["source_ids"] == {
        "market_id": "8e833e5c-ba98-4105-8ffe-8a1684be25c2",
        "selection_id": "yes",
        "event_id": cap.GB_CAR_EVENT,
    }
    assert (mapped["sport"], mapped["league"], mapped["fixture_id"], mapped["market_id"]) == (
        "football",
        "nfl",
        cap.GB_CAR_FIXTURE,
        "point_spread",
    )
    assert (mapped["market_type"], mapped["side"], mapped["points"], mapped["mapping_status"]) == (
        "point_spread",
        "GB",
        -2.5,
        "mapped",
    )
    held = market_mapping_row(next(s for s in _sides() if s.reason_code == "family_held"))
    assert (held["mapping_status"], held["fixture_id"], held["market_id"]) == ("unmapped", None, None)
    assert held["reason"].startswith("family_held") and held["source_ids"]["market_id"]
    json.dumps(mapped)


def _optic_game() -> dict:
    """An Optic ``/fixtures/odds`` record for GB v CAR with one odd per STX family under test (synthetic odds)."""
    gb, car, gid = "2C6CB429C60C", "EB5E972AB475", "GBCAR-2026-10-29"
    odds = [
        ("moneyline", "Green Bay Packers", None, None, gb, None),
        ("moneyline", "Carolina Panthers", None, None, car, None),
        ("point_spread", "Green Bay Packers", None, -2.5, gb, None),
        ("point_spread", "Carolina Panthers", None, 2.5, car, None),
        ("total_points", "Over", "over", 46.5, None, None),
        ("total_points", "Under", "under", 46.5, None, None),
        ("team_total_field_goals", "Carolina Panthers Over", "over", 1.5, car, None),
        ("team_total_field_goals", "Carolina Panthers Under", "under", 1.5, car, None),
        ("player_passing_yards", "Jordan Love", "over", 260.5, gb, "E7BCA7FF5B4A"),
        ("player_passing_yards", "Jordan Love", "under", 260.5, gb, "E7BCA7FF5B4A"),
    ]
    return {
        "id": cap.GB_CAR_FIXTURE,
        "game_id": gid,
        "start_date": "2026-10-30T00:15:00Z",
        "status": "unplayed",
        "is_live": False,
        "league": {"id": "nfl"},
        "home_competitors": [{"id": gb, "name": "Green Bay Packers", "abbreviation": "GB"}],
        "away_competitors": [{"id": car, "name": "Carolina Panthers", "abbreviation": "CAR"}],
        "odds": [
            {
                "id": f"{gid}:draftkings:{mkt}:{sel}:{pts}:{line}",
                "market_id": mkt,
                "selection": sel,
                "selection_line": line,
                "points": pts,
                "team_id": tid,
                "player_id": pid,
                "grouping_key": "default",
            }
            for mkt, sel, line, pts, tid, pid in odds
        ],
    }


def test_stx_keys_equal_the_pipeline_keys_of_the_same_optic_selections():
    """The canonical key a mapped STX side carries is the key ``optic.build_rows`` gives the Optic odd it prices."""
    cfg = optic.OpticConfig(league_id="nfl", table_types=FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES)
    ((fx,),) = optic.load_fixtures([json.dumps(_optic_game())], cfg).values()
    rows, _, _ = optic.build_rows(fx.start_date, fx.home, fx.away, fx, cfg, league="nfl")
    pipeline = {row_key(r)[4:8] for r in rows}
    ctx = StxContext(
        fixtures=[fixture_from_mmmapper(fx)],
        as_of=cap.AS_OF,
        rosters=cap.rosters(),
        optic_players={fx.fixture_id: optic_player_index((o.player_id, o.selection) for o in fx.odds)},
    )
    wanted = {
        "0a0b4f52-d056-4be2-9632-f8a33cb938ff",
        "8e833e5c-ba98-4105-8ffe-8a1684be25c2",
        "846559f6-455b-4e8c-ac23-09e752fd31aa",
        "fd625c0d-a084-4234-a6bb-02a1a71c060a",
        "37b4970c-0572-42c5-b10b-d8da580af3ab",
    }
    sides, _ = run_pass([m for m in cap.markets() if m.market_id in wanted], ctx)
    assert len(sides) == 10 and all(s.mapped for s in sides)
    stx = {(_rule(s).market_type.value, s.entity, normalize_line(s.line), s.selection_side) for s in sides}
    assert stx == pipeline

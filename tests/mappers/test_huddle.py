"""Deterministic NFL Huddle matcher: 1-1 Optic bind, merge-only."""

from __future__ import annotations

from pathlib import Path

from mappers.control_plane.rows import LeagueRow
from mappers.exchanges.huddle import (
    HuddleConfig,
    attach_huddle_stamp,
    build_rows,
    parse_selection,
    run_huddle_pass,
)
from mappers.exchanges.optic import Fixture
from mappers.market_types import MarketType
from mappers.pipeline import canonical_row_to_json, row_key
from mappers.seed.tip_factories import build_tip_league
from mappers.shared import TIE_SIDE, CanonicalRow, normalize_player_name
from mappers.vocab.football_huddle import (
    EXC_OT_CODES,
    GAME_TYPES,
    NFL_COMPETITION_ID,
    resolve_market_type,
)

_CID = NFL_COMPETITION_ID
_CFG = HuddleConfig(
    competition_ids=(_CID,),
    table_types=dict(GAME_TYPES),
    ignored_codes=EXC_OT_CODES,
)


def _fx() -> Fixture:
    return Fixture(
        fixture_id="FIX1",
        game_id="g1",
        sportradar_id="66456904",
        start_et="2026-09-21T13:00:00",
        start_date="2026-09-21T17:00:00Z",
        home="KC",
        away="LAC",
        home_name="Kansas City Chiefs",
        away_name="Los Angeles Chargers",
        team_map={},
        odds=[],
        is_live=False,
    )


def _raw(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "event_id": "ev1",
        "market_id": "m1",
        "selection_id": "s1",
        "market_code": "RESULT",
        "selection_code": "HOME",
        "competition_id": _CID,
        "betradar_extid": "66456904",
        "start_date": "2026-09-21T17:00:00Z",
        "line": None,
        "team": None,
        "milestone": None,
        "player_name": None,
        "period": None,
        "half": None,
    }
    base.update(fields)
    return base


def _sel(**fields: object):
    parsed = parse_selection(_raw(**fields))
    assert parsed is not None
    return parsed


def test_result_home_maps_moneyline() -> None:
    rows = build_rows(
        [_sel(), _sel(selection_id="s2", selection_code="AWAY")],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    by_side = {row.side: row for row in rows}
    assert set(by_side) == {"KC", "LAC"}
    assert by_side["KC"].market_type == MarketType.MONEYLINE.value
    assert by_side["KC"].huddle_selection_id == "s1"


def test_draw_on_two_way_moneyline_skips_draw_only() -> None:
    rows = build_rows(
        [
            _sel(),
            _sel(selection_id="s2", selection_code="AWAY"),
            _sel(selection_id="s3", selection_code="DRAW"),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    assert {row.side for row in rows} == {"KC", "LAC"}
    assert len(rows) == 2


def test_exc_ot_and_unknown_codes_drop() -> None:
    assert resolve_market_type(
        "POINT_OVER_UNDER_EXC_OT", half=None, period=None, table_types=GAME_TYPES,
    ) is None
    assert resolve_market_type(
        "PLAYER_ANYTIME_TOUCHDOWN", half=None, period=None, table_types=GAME_TYPES,
    ) is None
    rows = build_rows(
        [
            _sel(market_code="POINT_OVER_UNDER_EXC_OT", selection_code="OVER", line=45.5),
            _sel(market_code="CORRECT_SCORE", selection_id="s9"),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    assert rows == []


def test_period_two_and_bare_half_code_drop() -> None:
    assert resolve_market_type(
        "PERIOD_RESULT", half=None, period=2.0, table_types=GAME_TYPES,
    ) is None
    assert resolve_market_type(
        "HALF_RESULT", half=None, period=None, table_types=GAME_TYPES,
    ) is None


def test_first_half_result_maps_when_half_is_set() -> None:
    rows = build_rows(
        [
            _sel(market_code="HALF_RESULT", half=1.0, selection_code="HOME"),
            _sel(
                market_code="HALF_RESULT", half=1.0,
                selection_id="s2", selection_code="AWAY",
            ),
            _sel(
                market_code="HALF_RESULT", half=1.0,
                selection_id="s3", selection_code="DRAW",
            ),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    assert {row.side for row in rows} == {"KC", "LAC", TIE_SIDE}
    assert rows[0].market_type == MarketType.FIRST_HALF_WINNER_3WAY.value


def test_player_passing_yards_uses_normalized_name() -> None:
    rows = build_rows(
        [
            _sel(
                market_code="PLAYER_PASSING_YARDS_OVER_UNDER",
                selection_code="OVER",
                line=249.5,
                player_name="Patrick Mahomes",
            ),
            _sel(
                market_code="PLAYER_PASSING_YARDS_OVER_UNDER",
                selection_id="s2",
                selection_code="UNDER",
                line=249.5,
                player_name="Patrick Mahomes",
            ),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    assert len(rows) == 2
    assert rows[0].entity == normalize_player_name("Patrick Mahomes")
    assert rows[0].side == "over"
    assert rows[0].line == 249.5


def test_merge_only_stamps_existing_optic_row(tmp_path: Path) -> None:
    optic = CanonicalRow(
        league="nfl",
        start_date="2026-09-21T17:00:00Z",
        home="KC",
        away="LAC",
        market_type=MarketType.MONEYLINE.value,
        side="KC",
        optic_id="odd-1",
    )
    index = {row_key(optic): optic}
    huddle = CanonicalRow(
        league="nfl",
        start_date="2026-09-21T17:00:00Z",
        home="KC",
        away="LAC",
        market_type=MarketType.MONEYLINE.value,
        side="KC",
        huddle_selection_id="sel-9",
        huddle_event_id="ev-9",
        huddle_market_id="m-9",
    )
    assert attach_huddle_stamp(index, huddle) == "stamped"
    assert optic.huddle_selection_id == "sel-9"
    missing = huddle.model_copy(update={"side": "LAC"})
    assert attach_huddle_stamp(index, missing) == "dropped_no_optic"

    path = tmp_path / "huddle_markets.jsonl"
    path.write_text(
        '{"event_id":"ev1","market_id":"m1","selection_id":"s1",'
        '"market_code":"RESULT","selection_code":"HOME",'
        f'"competition_id":"{_CID}","betradar_extid":"66456904",'
        '"start_date":"2026-09-21T17:00:00Z"}\n',
        encoding="utf-8",
    )
    stamped, dropped = run_huddle_pass(
        data_dir=tmp_path,
        cfg=_CFG,
        league="nfl",
        fixtures=[_fx()],
        row_index=index,
    )
    assert stamped == 1
    assert dropped == 0


def test_serialize_emits_huddle_block_only_when_stamped() -> None:
    row = CanonicalRow(
        league="nfl",
        start_date="2026-09-21T17:00:00Z",
        home="KC",
        away="LAC",
        market_type=MarketType.MONEYLINE.value,
        side="KC",
        huddle_selection_id="sel-9",
        huddle_event_id="ev-9",
        huddle_market_id="m-9",
    )
    payload = canonical_row_to_json(row, {}, {})
    assert payload["huddle"] == {
        "selection_id": "sel-9",
        "event_id": "ev-9",
        "market_id": "m-9",
    }
    bare = CanonicalRow(
        league="nfl",
        start_date="2026-09-21T17:00:00Z",
        home="KC",
        away="LAC",
        market_type=MarketType.MONEYLINE.value,
        side="KC",
    )
    assert "huddle" not in canonical_row_to_json(bare, {}, {})


def test_spread_negates_away_line() -> None:
    rows = build_rows(
        [
            _sel(
                market_code="POINT_HANDICAP",
                selection_code="HOME",
                line=-4.5,
            ),
            _sel(
                market_code="POINT_HANDICAP",
                selection_id="s2",
                selection_code="AWAY",
                line=-4.5,
            ),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    by_side = {row.side: row for row in rows}
    assert by_side["KC"].line == -4.5
    assert by_side["LAC"].line == 4.5


def test_european_handicap_skips_draw_keeps_spread() -> None:
    rows = build_rows(
        [
            _sel(
                market_code="POINT_HANDICAP",
                selection_code="HOME",
                line=-1.5,
            ),
            _sel(
                market_code="POINT_HANDICAP",
                selection_id="s2",
                selection_code="AWAY",
                line=-1.5,
            ),
            _sel(
                market_code="POINT_HANDICAP",
                selection_id="s3",
                selection_code="DRAW",
                line=-1.5,
            ),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    assert {row.side for row in rows} == {"KC", "LAC"}
    assert all(row.market_type == MarketType.POINT_SPREAD.value for row in rows)


def test_first_touchdown_drops_no_keeps_yes_player() -> None:
    rows = build_rows(
        [
            _sel(
                market_code="PLAYER_FIRST_TOUCHDOWN_SCORER",
                selection_code="YES",
                player_name="Travis Kelce",
            ),
            _sel(
                market_code="PLAYER_FIRST_TOUCHDOWN_SCORER",
                selection_id="s2",
                selection_code="NO",
                player_name="Travis Kelce",
            ),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    assert len(rows) == 1
    assert rows[0].side == "yes"
    assert rows[0].entity == normalize_player_name("Travis Kelce")


def test_team_total_uses_team_field() -> None:
    rows = build_rows(
        [
            _sel(
                market_code="TEAM_FIELD_GOAL_OVER_UNDER",
                selection_code="OVER",
                line=1.5,
                team=0,
            ),
            _sel(
                market_code="TEAM_FIELD_GOAL_OVER_UNDER",
                selection_id="s2",
                selection_code="UNDER",
                line=1.5,
                team=1,
            ),
        ],
        cfg=_CFG,
        league="nfl",
        sr_index={"66456904": _fx()},
    )
    by_entity = {(row.entity, row.side): row for row in rows}
    assert ("KC", "over") in by_entity
    assert ("LAC", "under") in by_entity


def test_period_zero_treated_as_full_game() -> None:
    assert resolve_market_type(
        "RESULT", half=0.0, period=0.0, table_types=GAME_TYPES,
    ) == MarketType.MONEYLINE


def test_bad_jsonl_lines_skipped_good_row_still_stamps(tmp_path: Path) -> None:
    path = tmp_path / "huddle_markets.jsonl"
    path.write_text(
        "not json\n"
        '{"event_id":"ev1"}\n'
        '{"event_id":"ev1","market_id":"m1","selection_id":"s1",'
        '"market_code":"RESULT","selection_code":"HOME",'
        f'"competition_id":"{_CID}","betradar_extid":"66456904",'
        '"start_date":"2026-09-21T17:00:00Z"}\n',
        encoding="utf-8",
    )
    optic = CanonicalRow(
        league="nfl",
        start_date="2026-09-21T17:00:00Z",
        home="KC",
        away="LAC",
        market_type=MarketType.MONEYLINE.value,
        side="KC",
        optic_id="odd-1",
    )
    index = {row_key(optic): optic}
    stamped, dropped = run_huddle_pass(
        data_dir=tmp_path,
        cfg=_CFG,
        league="nfl",
        fixtures=[_fx()],
        row_index=index,
    )
    assert stamped == 1
    assert dropped == 0


def test_nfl_huddle_tip_pin_builds_config() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=[
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
            },
            {
                "sportsbook": "huddle",
                "enabled": True,
                "parser_profile": "huddle_nfl_v1",
                "source_league_id": _CID,
            },
        ],
    )
    cfg = build_tip_league(row)
    assert cfg.HUDDLE is not None
    assert cfg.HUDDLE.competition_ids == (_CID,)
    assert cfg.HUDDLE.table_types["RESULT"] == MarketType.MONEYLINE
    assert "POINT_OVER_UNDER_EXC_OT" in cfg.HUDDLE.ignored_codes

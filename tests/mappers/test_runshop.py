"""Tests for mappers/exchanges/runshop.py."""

import tomllib
from pathlib import Path

from mappers.exchanges import optic, runshop
from mappers.exchanges.runshop_crosswalk import load_crosswalk, load_runshop_markets
from mappers.market_types import MarketType
from mappers.shared import CanonicalRow

MARKETS_PATH = Path("vendor/world_cup/runshop_markets.toml")
CROSSWALK_PATH = Path("vendor/world_cup/runshop_crosswalk.toml")
RUNSHOP_CFG = runshop.RunshopConfig(
    markets_path=MARKETS_PATH,
    crosswalk_path=CROSSWALK_PATH,
)


def _fixture(
    *,
    fixture_id: str = "FIX1",
    home: str = "CAN",
    away: str = "MAR",
    home_name: str = "Canada",
    away_name: str = "Morocco",
    start_date: str = "2026-07-04T19:00:00Z",
) -> optic.Fixture:
    return optic.Fixture(
        fixture_id=fixture_id,
        game_id="game-1",
        sportradar_id=None,
        start_et="2026-07-04T15:00:00",
        start_date=start_date,
        home=home,
        away=away,
        home_name=home_name,
        away_name=away_name,
        team_map={},
        odds=[],
        is_live=False,
    )


def _active_rules(rows: list[CanonicalRow]) -> list[runshop.CrosswalkRule]:
    markets = load_runshop_markets(MARKETS_PATH)
    rules = load_crosswalk(CROSSWALK_PATH)
    return runshop.active_crosswalk_rules(rules, markets, rows)


def test_load_runshop_markets_loads_full_toml():
    with MARKETS_PATH.open("rb") as f:
        expected = len(tomllib.load(f).get("market", []))
    markets = load_runshop_markets(MARKETS_PATH)
    assert len(markets) == expected
    by_id = {m.id: m for m in markets}
    assert by_id[3].market == "OU Goals"
    assert by_id[3].value == 0.5
    assert by_id[629].market == "Total Corners - FT"
    assert by_id[153].market == "Asian Handicap"


def test_active_crosswalk_requires_toml_and_upstream():
    rules = load_crosswalk(CROSSWALK_PATH)
    markets = load_runshop_markets(MARKETS_PATH)
    row = CanonicalRow(
        league="world_cup",
        start_date="2026-07-04T19:00:00Z",
        home="CAN",
        away="MAR",
        market_type=MarketType.GAME_TOTAL.value,
        line=0.5,
        side="over",
        optic_id="odd-1",
    )
    active = runshop.active_crosswalk_rules(rules, markets, [row])
    assert any(r.runshop_market == "OU Goals" for r in active)

    other = CanonicalRow(
        league="world_cup",
        start_date="2026-07-04T19:00:00Z",
        home="CAN",
        away="MAR",
        market_type=MarketType.MONEYLINE_3WAY.value,
        side="CAN",
        optic_id="odd-2",
    )
    active_ml = runshop.active_crosswalk_rules(rules, markets, [other])
    assert not any(r.runshop_market == "OU Goals" for r in active_ml)


def test_lookup_runshop_market_id_game_total():
    markets = load_runshop_markets(MARKETS_PATH)
    index = runshop.build_market_index(markets)
    row = CanonicalRow(
        league="world_cup",
        start_date="2026-07-04T19:00:00Z",
        home="CAN",
        away="MAR",
        market_type=MarketType.GAME_TOTAL.value,
        line=0.5,
        side="over",
        optic_id="odd-1",
    )
    active = _active_rules([row])
    assert runshop.lookup_runshop_market_id(row, index, active) == 3


def test_lookup_runshop_market_id_asian_handicap_home():
    markets = load_runshop_markets(MARKETS_PATH)
    index = runshop.build_market_index(markets)
    row = CanonicalRow(
        league="world_cup",
        start_date="2026-07-04T19:00:00Z",
        home="CAN",
        away="MAR",
        market_type=MarketType.POINT_SPREAD.value,
        line=-1.5,
        side="CAN",
        optic_id="odd-2",
    )
    active = _active_rules([row])
    market_id = runshop.lookup_runshop_market_id(row, index, active)
    assert market_id is not None
    assert index[("Asian Handicap", -1.5, "Home")] == market_id


def test_lookup_runshop_market_id_team_total_corners():
    markets = load_runshop_markets(MARKETS_PATH)
    index = runshop.build_market_index(markets)
    row = CanonicalRow(
        league="world_cup",
        start_date="2026-07-04T19:00:00Z",
        home="CAN",
        away="MAR",
        market_type=MarketType.TEAM_TOTAL_CORNERS.value,
        entity="CAN",
        line=4.5,
        side="over",
        optic_id="odd-3",
    )
    active = _active_rules([row])
    market_id = runshop.lookup_runshop_market_id(row, index, active)
    assert market_id is not None
    assert index[("Home Team Corners - FT", 4.5, "Over")] == market_id


def test_build_fixture_chain_index_matches_poly_title():
    chain = [
        runshop.FixtureChainRecord(
            tx_odds_fixture_id=905827989,
            tx_legacy_fixture_id=905827989,
            poly_game_id="90086996",
            poly_title="Canada vs. Morocco",
            poly_start_time="2026-07-04 19:00:00+00",
        ),
    ]
    fixtures = [_fixture()]
    index = runshop.build_fixture_chain_index(chain, fixtures)
    assert index["FIX1"].tx_odds_fixture_id == 905827989
    assert index["FIX1"].flipped is False


def test_crossed_title_marks_the_link_flipped():
    chain = [
        runshop.FixtureChainRecord(
            tx_odds_fixture_id=1,
            tx_legacy_fixture_id=1,
            poly_game_id="1",
            poly_title="Morocco vs. Canada",
            poly_start_time="2026-07-04 19:00:00+00",
        ),
    ]
    index = runshop.build_fixture_chain_index(chain, [_fixture()])
    assert index["FIX1"].flipped is True


def test_stamp_runshop_rows(tmp_path: Path):
    chain_path = tmp_path / "runshop_fixture_chain.jsonl"
    chain_path.write_text(
        '{"tx_odds_fixture_id":905827989,"tx_legacy_fixture_id":905827989,'
        '"poly_game_id":"90086996","poly_title":"Canada vs. Morocco",'
        '"poly_start_time":"2026-07-04T19:00:00+00:00"}\n',
        encoding="utf-8",
    )
    row = CanonicalRow(
        league="world_cup",
        start_date="2026-07-04T19:00:00Z",
        home="CAN",
        away="MAR",
        market_type=MarketType.GAME_TOTAL.value,
        line=0.5,
        side="over",
        optic_id="odd-1",
    )
    game_ref = {"odd-1": optic.GameRef(fixture_id="FIX1", game_id="game-1")}
    stamped = runshop.stamp_runshop_rows(
        [row],
        game_ref,
        [_fixture()],
        chain_path,
        RUNSHOP_CFG,
    )
    assert stamped == 1
    assert row.runshop_tx_odds_fixture_id == 905827989
    assert row.runshop_market_id == 3

"""Tests for BQ taxonomy overlay on all sportsbooks."""

from __future__ import annotations

from types import SimpleNamespace

from mappers.control_plane.gap_market_bind import overlay_applies, simulate_overlay_applies
from mappers.control_plane.rows import MarketRuleRow
from mappers.exchanges.huddle import HuddleConfig
from mappers.exchanges.novig import NovigConfig
from mappers.exchanges.optic import OpticConfig
from mappers.exchanges.underdog import UnderdogConfig
from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.seed.overlay_taxonomy import (
    overlay_crypto,
    overlay_huddle,
    overlay_novig,
    overlay_optic,
    overlay_px,
    overlay_runshop,
    overlay_underdog,
)
from mappers.seed.sot import overlay_league_config
from mappers.vocab import novig_markets
from mappers.vocab.football_huddle import EXC_OT_CODES, GAME_TYPES
from mappers.vocab.football_markets import (
    FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES,
    NFL_CRYPTO,
)

CS2_CRYPTO = LEAGUES["cs2"].CRYPTO
CS2_LEAGUE = LEAGUES["cs2"]
EPL_LEAGUE = LEAGUES["epl"]
EPL_PX = LEAGUES["epl"].PX
WORLD_CUP_LEAGUE = LEAGUES["world_cup"]
WORLD_CUP_RUNSHOP = LEAGUES["world_cup"].RUNSHOP


def _map_row(*, league: str, sportsbook: str, key_type: str, key: str, canonical: str) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id="r0",
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=key_type,
        source_key=key,
        action="map",
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="id_verified",
    )


def test_overlay_px_reads_suffix_rules():
    row = MarketRuleRow(
        rule_id="r1",
        league="epl",
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="market_name",
        source_key="Spread",
        action="map",
        canonical_market_type=MarketType.POINT_SPREAD.value,
        priority=80,
        enabled=True,
        confidence="id_verified",
        match_operator="suffix",
    )
    px = EPL_PX
    assert px is not None
    out = overlay_px(px, [row], EPL_LEAGUE)
    assert any(suffix == "Spread" for suffix, _mt in out.suffix)


def test_overlay_crypto_reads_contract_rules():
    row = MarketRuleRow(
        rule_id="r2",
        league="cs2",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="contract_type",
        source_key="Total Points",
        action="map",
        canonical_market_type=MarketType.GAME_TOTAL.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
    )
    crypto = CS2_CRYPTO
    assert crypto is not None
    out = overlay_crypto(crypto, [row], CS2_LEAGUE)
    assert out.contract_types["Total Points"] == MarketType.GAME_TOTAL
    assert "Moneyline" in out.contract_types


def test_overlay_crypto_merges_player_and_team_props():
    player = MarketRuleRow(
        rule_id="r-player",
        league="nfl",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="player_prop_contract_type",
        source_key="To Score a Touchdown",
        action="map",
        canonical_market_type=MarketType.PLAYER_TOUCHDOWNS.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        notes="trader: touchdown scorer is a player prop",
    )
    team = MarketRuleRow(
        rule_id="r-team",
        league="nfl",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="team_prop_contract_type",
        source_key="Total Points",
        action="map",
        canonical_market_type=MarketType.TEAM_TOTAL.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        notes="crypto team_prop",
    )
    crypto = NFL_CRYPTO
    assert crypto is not None
    out = overlay_crypto(crypto, [player, team], CS2_LEAGUE)
    assert out.contract_types["Moneyline"] == MarketType.MONEYLINE
    assert out.prop_contract_types["To Score a Touchdown"] == MarketType.PLAYER_TOUCHDOWNS
    assert out.team_prop_contract_types["Total Points"] == MarketType.TEAM_TOTAL


def test_overlay_crypto_rejects_mis_pinned_team_total_on_game_line_key():
    bad = MarketRuleRow(
        rule_id="r-bad-team-total",
        league="nfl",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="contract_type",
        source_key="Total Points",
        action="map",
        canonical_market_type=MarketType.TEAM_TOTAL.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
    )
    crypto = NFL_CRYPTO
    assert crypto is not None
    out = overlay_crypto(crypto, [bad], CS2_LEAGUE)
    assert out.contract_types["Total Points"] == MarketType.GAME_TOTAL
    assert out.team_prop_contract_types["Total Points"] == MarketType.TEAM_TOTAL


def test_overlay_crypto_merges_game_prop_contract_type():
    row = MarketRuleRow(
        rule_id="r-gp",
        league="world_cup",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="game_prop_contract_type",
        source_key="Novel BTTS",
        action="map",
        canonical_market_type=MarketType.BTTS.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        notes="crypto game_prop",
    )
    crypto = WORLD_CUP_LEAGUE.CRYPTO
    assert crypto is not None
    out = overlay_crypto(crypto, [row], WORLD_CUP_LEAGUE)
    assert out.game_prop_contract_types["Novel BTTS"] == MarketType.BTTS
    assert "Novel BTTS" not in out.prop_contract_types


def test_overlay_crypto_notes_do_not_choose_the_table():
    """A notes tag on contract_type stays a game-line row."""
    row = MarketRuleRow(
        rule_id="r-gp-notes",
        league="world_cup",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="contract_type",
        source_key="Novel BTTS",
        action="map",
        canonical_market_type=MarketType.BTTS.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        notes="crypto game_prop",
    )
    crypto = WORLD_CUP_LEAGUE.CRYPTO
    assert crypto is not None
    out = overlay_crypto(crypto, [row], WORLD_CUP_LEAGUE)
    assert out.contract_types["Novel BTTS"] == MarketType.BTTS
    assert "Novel BTTS" not in out.game_prop_contract_types
    assert "Novel BTTS" not in out.prop_contract_types


def test_simulate_overlay_applies_crypto_props_by_source_key_type():
    """Prop tables follow source_key_type. Notes are not the route."""
    wc = LEAGUES["world_cup"]
    novel = "Novel Fixture Question"
    canonical = MarketType.BTTS.value
    assert not simulate_overlay_applies(
        wc,
        [],
        sportsbook="crypto.com",
        source_key_type="contract_type",
        source_key=novel,
        canonical=canonical,
        market_group="Game Prop",
        notes="crypto game_prop",
    )
    assert simulate_overlay_applies(
        wc,
        [],
        sportsbook="crypto.com",
        source_key_type="game_prop_contract_type",
        source_key=novel,
        canonical=canonical,
        market_group="Game Prop",
        notes="keep the trader sentence",
    )
    nfl = LEAGUES["nfl"]
    player = "Novel Sacks Market"
    player_canonical = MarketType.PLAYER_INTERCEPTIONS.value
    assert not simulate_overlay_applies(
        nfl,
        [],
        sportsbook="crypto.com",
        source_key_type="contract_type",
        source_key=player,
        canonical=player_canonical,
        market_group="Player Prop",
        notes="crypto player_prop",
    )
    assert simulate_overlay_applies(
        nfl,
        [],
        sportsbook="crypto.com",
        source_key_type="player_prop_contract_type",
        source_key=player,
        canonical=player_canonical,
        market_group="Player Prop",
        notes="keep the trader sentence",
    )


def test_overlay_applies_team_prop_type_without_market_group():
    cfg = SimpleNamespace(MarketType=MarketType, CRYPTO=NFL_CRYPTO)
    assert overlay_applies(
        cfg,
        sportsbook="crypto.com",
        source_key_type="team_prop_contract_type",
        source_key="Total Points",
        canonical=MarketType.TEAM_TOTAL.value,
        market_group="",
    )
    assert overlay_applies(
        cfg,
        sportsbook="crypto.com",
        source_key_type="contract_type",
        source_key="Total Points",
        canonical=MarketType.GAME_TOTAL.value,
        market_group="",
    )
    assert overlay_applies(
        cfg,
        sportsbook="crypto.com",
        source_key_type="contract_type",
        source_key="To Score a Touchdown",
        canonical=MarketType.PLAYER_TOUCHDOWNS.value,
        market_group="",
    )


def test_overlay_crypto_notes_alone_do_not_route_team_prop():
    row = MarketRuleRow(
        rule_id="r-notes-only",
        league="nfl",
        sportsbook="crypto.com",
        rule_kind="taxonomy",
        source_key_type="contract_type",
        source_key="Total Points",
        action="map",
        canonical_market_type=MarketType.TEAM_TOTAL.value,
        priority=100,
        enabled=True,
        confidence="id_verified",
        notes="crypto team_prop",
    )
    crypto = NFL_CRYPTO
    assert crypto is not None
    out = overlay_crypto(crypto, [row], CS2_LEAGUE)
    assert out.contract_types["Total Points"] == MarketType.GAME_TOTAL
    assert out.team_prop_contract_types["Total Points"] == MarketType.TEAM_TOTAL
    row = MarketRuleRow(
        rule_id="r3",
        league="epl",
        sportsbook="polymarket",
        rule_kind="taxonomy",
        source_key_type="kind",
        source_key="moneyline",
        action="map",
        canonical_market_type=MarketType.MONEYLINE_3WAY.value,
        priority=100,
        enabled=True,
        confidence="semantic",
    )
    out = overlay_league_config(EPL_LEAGUE, [row])
    assert out.POLYMARKET is not None
    assert out.POLYMARKET.market_types["moneyline"] == MarketType.MONEYLINE_3WAY


def test_overlay_runshop_reads_crosswalk_rules():
    row = MarketRuleRow(
        rule_id="r4",
        league="world_cup",
        sportsbook="runshop",
        rule_kind="crosswalk",
        source_key_type="optic_market_type",
        source_key="game_total",
        action="map",
        canonical_market_type="OU Goals",
        priority=100,
        enabled=True,
        confidence="human_verified",
        match_operator="over_under",
    )
    out = overlay_runshop(WORLD_CUP_RUNSHOP, [row], WORLD_CUP_LEAGUE, runshop_enabled=True)
    assert out is not None
    assert any(rule.runshop_market == "OU Goals" for rule in out.crosswalk_rules)


def test_overlay_league_config_applies_runshop_crosswalk():
    row = MarketRuleRow(
        rule_id="r5",
        league="world_cup",
        sportsbook="runshop",
        rule_kind="crosswalk",
        source_key_type="optic_market_type",
        source_key="game_total",
        action="map",
        canonical_market_type="OU Goals",
        priority=100,
        enabled=True,
        confidence="human_verified",
        match_operator="over_under",
    )
    from mappers.control_plane.rows import LeagueRow

    league_row = LeagueRow(
        league="world_cup",
        sport="soccer",
        optic_league_id="fifa_-_world_cup",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[],
        settings={"runshop_enabled": True},
    )
    out = overlay_league_config(WORLD_CUP_LEAGUE, [row], league_row)
    assert out.RUNSHOP is not None
    assert any(rule.runshop_market == "OU Goals" for rule in out.RUNSHOP.crosswalk_rules)


def _ignore_row(*, league: str, sportsbook: str, key_type: str, key: str) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id="r-ign",
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=key_type,
        source_key=key,
        action="ignore",
        canonical_market_type=None,
        priority=50,
        enabled=True,
        confidence="human_verified",
    )


def test_underdog_overlay_ignores_tip_rules() -> None:
    """Underdog's crosswalk is code keyed on Optic market ids; the tip cannot add to it."""
    underdog = UnderdogConfig(league="NFL", market_types={})
    rows = [
        _map_row(
            league="nfl", sportsbook="underdog",
            key_type="product_period", key="PASSYDS",
            canonical=MarketType.PLAYER_PASSING_YARDS.value,
        ),
    ]
    assert overlay_underdog(underdog, rows, LEAGUES["nfl"]) is underdog


def test_nfl_optic_overlay_keeps_python_period_ids() -> None:
    optic = OpticConfig(league_id="nfl", table_types=dict(FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES))
    row = _map_row(
        league="nfl", sportsbook="optic",
        key_type="market_id", key="moneyline", canonical=MarketType.MONEYLINE.value,
    )
    out = overlay_optic(optic, [row], LEAGUES["nfl"])
    assert out.table_types["moneyline"] == MarketType.MONEYLINE
    assert out.table_types["1st_half_moneyline_3-way"] == (
        MarketType.FIRST_HALF_WINNER_3WAY
    )
    assert out.table_types["player_interceptions"] == MarketType.PLAYER_INTERCEPTIONS

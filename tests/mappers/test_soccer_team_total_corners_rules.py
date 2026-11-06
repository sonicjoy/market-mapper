"""Soccer team_total_corners BQ market-rule pin payload."""

import csv
from pathlib import Path

from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.market_types import MarketType
from mappers.run import LEAGUES
from mappers.seed.soccer_team_total_corners_rules import (
    build_soccer_team_total_corners_payload,
    build_soccer_team_total_corners_payload_from_tip,
    desired_market_rule_pins,
    missing_market_rule_pins,
    soccer_league_slugs,
)

_SPINE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "mapping-rules"
    / "optic_spine.csv"
)


def _row(
    league: str,
    sportsbook: str,
    source_key_type: str,
    source_key: str,
    canonical: str,
    *,
    action: str = "map",
) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"mr_{league}_{sportsbook}_{source_key}",
        league=league,
        sportsbook=sportsbook,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action=action,
        canonical_market_type=canonical if action == "map" else None,
        priority=100,
        enabled=True,
        confidence="id_verified",
    )


def _league(
    league: str,
    *,
    exchanges: list[dict[str, object]] | None = None,
) -> LeagueRow:
    return LeagueRow(
        league=league,
        sport="soccer",
        optic_league_id=f"{league}_optic",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96,
        enabled=True,
        output_order=["team_total_corners"],
        exchanges=exchanges or [{"sportsbook": "optic", "enabled": True}],
    )


def test_desired_pins_include_optic_for_every_soccer_league():
    for league in soccer_league_slugs(LEAGUES):
        pins = desired_market_rule_pins(league, LEAGUES[league])
        keys = {(p.sportsbook, p.source_key_type, p.source_key) for p in pins}
        assert ("optic", "market_id", "team_total_corners") in keys


def test_desired_pins_follow_exchange_wiring():
    epl = desired_market_rule_pins("epl", LEAGUES["epl"])
    keys = {(p.sportsbook, p.source_key) for p in epl}
    assert ("optic", "team_total_corners") in keys
    assert ("polymarket", "team_total_corners") in keys
    assert not any(book == "kalshi" for book, _ in keys)
    assert ("novig", "TEAM_TOTAL_CORNERS") in keys

    latvia = desired_market_rule_pins(
        "latvia_virsliga", LEAGUES["latvia_virsliga"],
    )
    latvia_keys = {(p.sportsbook, p.source_key) for p in latvia}
    assert ("polymarket", "team_total_corners") in latvia_keys
    assert ("novig", "TEAM_TOTAL_CORNERS") not in latvia_keys


def test_missing_pins_skip_existing_tip_rows():
    tip = [
        _row(
            "epl",
            "optic",
            "market_id",
            "team_total_corners",
            "team_total_corners",
        ),
    ]
    miss = missing_market_rule_pins("epl", tip, cfg=LEAGUES["epl"])
    miss_keys = {(p.sportsbook, p.source_key) for p in miss}
    assert ("optic", "team_total_corners") not in miss_keys
    assert ("polymarket", "team_total_corners") in miss_keys


def test_from_tip_follows_tip_exchanges_not_python_cfg():
    tip_leagues = [
        _league(
            "epl",
            exchanges=[
                {"sportsbook": "optic", "enabled": True},
                {"sportsbook": "novig", "enabled": True},
            ],
        ),
    ]
    payload = build_soccer_team_total_corners_payload_from_tip([], tip_leagues)
    assert len(payload.market_rules) == 1
    keys = {(p.sportsbook, p.source_key) for p in payload.market_rules[0].rules}
    assert keys == {("optic", "team_total_corners"), ("novig", "TEAM_TOTAL_CORNERS")}


def test_build_payload_groups_by_league():
    payload = build_soccer_team_total_corners_payload([], LEAGUES)
    assert payload.market_rules
    leagues = {group.league for group in payload.market_rules}
    assert "epl" in leagues
    epl_group = next(g for g in payload.market_rules if g.league == "epl")
    assert any(
        pin.canonical_market_type == MarketType.TEAM_TOTAL_CORNERS.value
        for pin in epl_group.rules
    )


def test_spine_team_total_corners_is_not_a_lonely_slice():
    by_league: dict[str, set[str]] = {}
    with _SPINE.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            slug = (row.get("league") or "").strip()
            mid = (row.get("optic_market_id") or "").strip()
            if slug and mid:
                by_league.setdefault(slug, set()).add(mid)
    lonely = sorted(
        slug
        for slug, mids in by_league.items()
        if "team_total_corners" in mids and len(mids) == 1
    )
    assert lonely == []

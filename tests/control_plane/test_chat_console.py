"""Mapper Chat sees Editor, Rules, Coverage, and Unmapped from page_context."""

from __future__ import annotations

from mappers.control_plane.chat_console import (
    console_has_context,
    coverage_href,
    merge_rules_view,
    page_league,
    parse_page_context,
    rules_query_from_page,
    show_on_console,
    unmapped_href,
)
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore


def test_page_league_prefers_entry_then_rules_dropdown() -> None:
    page = parse_page_context(
        {"entry": {"league": "epl"}, "rules": {"league": ["nba"]}},
    )
    assert page_league(page) == "epl"
    assert page_league(parse_page_context({"rules": {"league": ["nba", "nfl"]}})) == "nba"


def test_rules_dropdowns_are_on_mapping_page() -> None:
    assert console_has_context(parse_page_context({"rules": {"kind": "market_rules"}}))
    assert console_has_context(parse_page_context({"rules": {"league": ["epl"]}}))
    assert not console_has_context(parse_page_context({}))


def test_show_on_console_keeps_dropdowns() -> None:
    page = parse_page_context(
        {
            "path": "/rules",
            "rules": {
                "kind": "market_rules",
                "q": "spread",
                "league": ["epl"],
                "sportsbook": ["kalshi"],
                "action": ["ignore"],
            },
        }
    )
    actions = show_on_console(rules=merge_rules_view(page, kind="entities", q="M05"))
    filt = next(a for a in actions if a["type"] == "rules_filter")
    assert filt["kind"] == "entities"
    assert filt["q"] == "M05"
    assert filt["league"] == ["epl"]
    assert filt["sportsbook"] == ["kalshi"]
    assert filt["action"] == ["ignore"]


def test_count_uses_rules_league_dropdown() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="nfl",
                sport="football",
                optic_league_id="usa_-_nfl",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
            LeagueRow(
                league="epl",
                sport="soccer",
                optic_league_id="epl",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        market_rules=[
            MarketRuleRow(
                rule_id="nfl-map",
                league="nfl",
                sportsbook="optic",
                rule_kind="taxonomy",
                source_key_type="market_id",
                source_key="moneyline",
                action="map",
                canonical_market_type="moneyline",
                priority=100,
                enabled=True,
                confidence="manual",
            ),
            MarketRuleRow(
                rule_id="nfl-ign",
                league="nfl",
                sportsbook="optic",
                rule_kind="taxonomy",
                source_key_type="market_id",
                source_key="props",
                action="ignore",
                canonical_market_type=None,
                priority=100,
                enabled=True,
                confidence="manual",
            ),
            MarketRuleRow(
                rule_id="epl-ign",
                league="epl",
                sportsbook="kalshi",
                rule_kind="taxonomy",
                source_key_type="ticker_type",
                source_key="PLAYER",
                action="ignore",
                canonical_market_type=None,
                priority=100,
                enabled=True,
                confidence="manual",
            ),
        ],
        activate=True,
    )
    resp = handle_chat_turn(
        ChatRequest(
            message="how many ignored market rules",
            conversation_id="rules-dd",
            page_context={
                "path": "/rules",
                "rules": {"kind": "market_rules", "league": ["nfl"]},
            },
        ),
        settings=Settings(gcp_project="marketmaking-test", chat_enabled=True),
        store=store,
    )
    filt = next(a for a in resp.ui_actions if a["type"] == "rules_filter")
    assert filt["league"] == ["nfl"]
    assert "**2**" in resp.reply_markdown
    assert "**1** ignored" in resp.reply_markdown
    query = rules_query_from_page(
        parse_page_context({"rules": {"kind": "market_rules", "league": ["nfl"]}}),
    )
    assert query.league == ("nfl",)


def test_page_league_prefers_coverage_on_coverage_path() -> None:
    page = parse_page_context(
        {
            "path": "/coverage",
            "entry": {"league": "epl"},
            "coverage": {"league": "atp", "sport": "tennis"},
        },
    )
    assert page_league(page) == "atp"
    assert console_has_context(page)


def test_page_league_unmapped_does_not_inherit_entry() -> None:
    """All/empty Unmapped filters must not fall back to leftover Editor league."""
    empty = parse_page_context(
        {
            "path": "/unmapped",
            "entry": {"league": "epl"},
            "unmapped": {"sport": "esports", "platform": "polymarket", "q": ""},
        },
    )
    assert page_league(empty) == ""
    filtered = parse_page_context(
        {
            "path": "/unmapped",
            "entry": {"league": "epl"},
            "unmapped": {"league": "atp", "sport": "tennis"},
        },
    )
    assert page_league(filtered) == "atp"


def test_show_on_console_opens_coverage_and_drops_unknown_paths() -> None:
    ok = show_on_console(navigate=coverage_href(league="atp", fixture="abc"))
    assert ok == [{"type": "navigate", "path": "/coverage?league=atp&fixture=abc"}]
    assert show_on_console(navigate="https://evil.example/") == []
    assert show_on_console(navigate="/admin") == []


def test_show_on_console_opens_unmapped() -> None:
    actions = show_on_console(navigate="/unmapped")
    assert actions == [{"type": "navigate", "path": "/unmapped"}]
    league = show_on_console(navigate=unmapped_href(league="mlb"))
    assert league == [{"type": "navigate", "path": "/unmapped?league=mlb"}]


def test_show_on_console_market_prefill_lifts_canonical() -> None:
    actions = show_on_console(
        navigate="/entry",
        tab="market",
        prefill={
            "tab": "market",
            "league": "austria_ofb_cup",
            "sportsbook": "crypto.com",
            "code": "To Advance",
            "entity_name": "to_advance",
        },
    )
    fields = next(a["fields"] for a in actions if a["type"] == "prefill_form")
    assert fields["source_key"] == "To Advance"
    assert fields["canonical_market_type"] == "to_advance"
    assert fields["action"] == "map"

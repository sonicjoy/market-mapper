"""Mapper Chat routing catalog — lookups, fixture coverage, mixed cart."""

from __future__ import annotations

from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM, ToolCall
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.chat_tools_fixture import fixture_coverage
from mappers.control_plane.chat_tools_lookup import lookup_entities
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore


def _settings(**kwargs: object) -> Settings:
    base = {
        "gcp_project": "marketmaking-test",
        "chat_enabled": True,
        "chat_provider": "fake",
        "chat_model": "fake",
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="atp",
                entity_type="player",
                canonical_key="SINNER",
                canonical_name="Jannik Sinner",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": "E0133F3BCA247846",
                    },
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "SIN"},
                ],
            ),
            EntityRow(
                league="atp",
                entity_type="player",
                canonical_key="ALCARAZ",
                canonical_name="Carlos Alcaraz",
                aliases=[
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "ALC"},
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "optic",
                        "enabled": True,
                        "parser_profile": "optic_standard_v1",
                        "source_league_id": "atp",
                    },
                    {
                        "sportsbook": "px",
                        "enabled": True,
                        "parser_profile": "px_generic_v1",
                        "source_league_id": "atp",
                        "settings": {"tournament_id": "1234"},
                    },
                ],
            ),
            LeagueRow(
                league="wta",
                sport="tennis",
                optic_league_id="wta",
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
                rule_id="mr1",
                league="atp",
                sportsbook="px",
                rule_kind="taxonomy",
                source_key_type="market_name",
                source_key="GAME",
                action="map",
                canonical_market_type="moneyline",
                priority=100,
                enabled=True,
                confidence="manual",
            ),
            MarketRuleRow(
                rule_id="mr2",
                league="atp",
                sportsbook="px",
                rule_kind="taxonomy",
                source_key_type="market_name",
                source_key="SPREAD",
                action="ignore",
                canonical_market_type="point_spread",
                priority=100,
                enabled=True,
                confidence="manual",
            ),
        ],
        activate=True,
    )
    return store


def setup_function() -> None:
    session_bag().clear()
    clear_tip_league_cache()


def test_lookup_entities_fills_rules_q() -> None:
    out = lookup_entities(_store(), "E0133F3BCA247846")
    assert out["count"] >= 1
    assert out["entities"][0]["canonical_key"] == "SINNER"
    filt = [a for a in out["ui_actions"] if a["type"] == "rules_filter"]
    assert filt and filt[0]["q"] == "E0133F3BCA247846"
    assert filt[0]["kind"] == "entities"


def test_fixture_vs_string_coverage() -> None:
    out = fixture_coverage(_store(), "Sinner vs Alcaraz", league="atp")
    assert out["ok"]
    assert out["all_mapped"] is True
    assert not out["missing"]
    nav = [a for a in out["ui_actions"] if a["type"] == "navigate"]
    assert nav and nav[0]["path"].startswith("/coverage")


def test_fixture_vs_offers_pin_when_missing() -> None:
    out = fixture_coverage(_store(), "Sinner vs Djokovic", league="atp")
    assert out["ok"]
    assert out["missing"]
    assert any("Djokovic" in str(s.get("name")) for s in out["missing"])


def test_mixed_cart_league_and_markets(monkeypatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_propose.suggest_market_rules",
        lambda **kwargs: {
            "ok": True,
            "warnings": [],
            "suggestions": [
                {
                    "league": "wta",
                    "pin": {
                        "sportsbook": "px",
                        "rule_kind": "taxonomy",
                        "source_key_type": "market_name",
                        "source_key": "GAME",
                        "action": "map",
                        "canonical_market_type": "moneyline",
                    },
                }
            ],
        },
    )
    llm = FakeChatLLM(
        script=[
            ChatLLMResult(
                tool_calls=[
                    ToolCall(
                        name="propose_league",
                        args={"league": "wta", "sportsbook": "px", "sport": "tennis"},
                    ),
                    ToolCall(
                        name="propose_markets",
                        args={"league": "wta", "sportsbook": "px", "market": "game"},
                    ),
                ]
            ),
            ChatLLMResult(text="Staged league + markets. Add all to cart?"),
        ]
    )
    store = _store()
    first = handle_chat_turn(
        ChatRequest(
            message="can we add wta for px and map game",
            conversation_id="cart1",
        ),
        settings=_settings(),
        store=store,
        llm=llm,
    )
    bag = session_bag().get_or_create("cart1")
    assert len(cart_items(bag)) >= 1
    assert any(b.send == "yes" for b in first.reply_buttons)
    confirmed = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="cart1"),
        settings=_settings(),
        store=store,
        llm=FakeChatLLM(script=[]),
    )
    assert any(a["type"] == "cart_add" for a in confirmed.ui_actions)
    kinds = {it["kind"] for it in confirmed.ui_actions[0]["items"]}
    assert "mapping_league" in kinds


def test_propose_markets_asks_before_ignore_flip() -> None:
    tools = ChatToolContext(_store(), bag=session_bag().get_or_create("ign1"))
    out = tools.run(
        "propose_markets",
        {"league": "atp", "sportsbook": "px", "market": "spread"},
    )
    assert out.get("needs_ignore_confirm")
    assert "ignored" in (out.get("message") or "").lower()


def test_lookup_market_rules_reports_ignored() -> None:
    tools = ChatToolContext(_store())
    out = tools.run(
        "lookup_rules", {"kind": "market_rules", "q": "atp", "sportsbook": "px"}
    )
    assert out["ignored"] >= 1
    assert out["mapped"] >= 1
    filt = [a for a in out["ui_actions"] if a["type"] == "rules_filter"]
    assert filt and filt[0]["kind"] == "market_rules"

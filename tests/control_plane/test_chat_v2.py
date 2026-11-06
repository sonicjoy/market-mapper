"""M3c V2 Mapper Chat — lookup tools, mixed cart, budgets, SSE."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.chat_budget import chat_budget
from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_catalog import slug_from_message
from mappers.control_plane.chat_intent import score_intent
from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM, ToolCall
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
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
        entities=[],
        leagues=[
            LeagueRow(
                league="epl",
                sport="soccer",
                optic_league_id="england_-_premier_league",
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
                        "source_league_id": "england_-_premier_league",
                    },
                    {
                        "sportsbook": "kalshi",
                        "enabled": True,
                        "parser_profile": "kalshi_generic_v1",
                        "source_league_id": None,
                    },
                ],
            )
        ],
        market_rules=[
            MarketRuleRow(
                rule_id="mr1",
                league="epl",
                sportsbook="optic",
                rule_kind="taxonomy",
                source_key_type="market_id",
                source_key="moneyline",
                action="map",
                canonical_market_type="moneyline",
                priority=100,
                enabled=True,
                confidence="manual",
            )
        ],
        activate=True,
    )
    return store


def _esports_store() -> InMemoryStore:
    """Tip with digit-bearing league slugs (cs2, dota_2)."""
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league=slug,
                sport="esports",
                optic_league_id=slug,
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            )
            for slug in ("cs2", "dota_2")
        ],
        activate=True,
    )
    return store


def _nfl_rules_store() -> InMemoryStore:
    """Tip with nfl market rules (map + ignore) for count questions."""
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
            )
        ],
        market_rules=[
            MarketRuleRow(
                rule_id="mr_map",
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
                rule_id="mr_ign1",
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
                rule_id="mr_ign2",
                league="nfl",
                sportsbook="px",
                rule_kind="taxonomy",
                source_key_type="market_name",
                source_key="Player Props",
                action="ignore",
                canonical_market_type=None,
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
    chat_budget().reset()


def _lookup_llm(tool: str, args: dict, text: str) -> FakeChatLLM:
    return FakeChatLLM(
        script=[
            ChatLLMResult(tool_calls=[ToolCall(name=tool, args=args)]),
            ChatLLMResult(text=text),
        ]
    )


def _fake_propose_markets(bag, **kwargs: object) -> dict:
    from mappers.control_plane.chat_cart import append_cart_item

    league = str(kwargs.get("league") or "ucl")
    book = str(kwargs.get("sportsbook") or "optic")
    append_cart_item(
        bag,
        {
            "kind": "mapping_market_rules",
            "label": f"{league} market rules ({book})",
            "payload": {
                "kind": "mapping_market_rules",
                "league": league,
                "rules": [
                    {
                        "sportsbook": book,
                        "rule_kind": "taxonomy",
                        "source_key_type": "market_id",
                        "source_key": "moneyline",
                        "action": "map",
                        "canonical_market_type": "moneyline",
                    }
                ],
            },
        },
    )
    return {"ok": True, "message": f"Staged market rules for {league} on {book}."}


def test_lookup_rules_replaces_the_split_lookups() -> None:
    """One tool with a `kind`, so the model never picks between three lookups."""
    tools = ChatToolContext(_store())
    assert tools.run("lookup_rules", {"kind": "leagues", "q": "epl"})["count"] >= 1
    assert tools.run("lookup_rules", {"kind": "market_rules", "q": "moneyline"})["count"] >= 1
    for retired in ("lookup_leagues", "lookup_market_rules", "bq_lookup_entities"):
        assert "unknown_tool" in tools.run(retired, {"q": "epl"}).get("error", "")


def test_mixed_cart_league_then_markets(monkeypatch) -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="epl",
                sport="soccer",
                optic_league_id="england_-_premier_league",
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
                        "source_league_id": "england_-_premier_league",
                    },
                    {
                        "sportsbook": "kalshi",
                        "enabled": True,
                        "parser_profile": "kalshi_generic_v1",
                        "source_league_id": None,
                    },
                ],
            ),
            LeagueRow(
                league="ucl",
                sport="soccer",
                optic_league_id="uefa_-_champions_league",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "kalshi",
                        "enabled": True,
                        "parser_profile": "kalshi_generic_v1",
                        "source_league_id": None,
                        "settings": {"prefix": "KXUCL"},
                    },
                    {
                        "sportsbook": "optic",
                        "enabled": True,
                        "parser_profile": "optic_standard_v1",
                        "source_league_id": "uefa_-_champions_league",
                    },
                ],
            ),
        ],
        market_rules=[
            MarketRuleRow(
                rule_id="mr1",
                league="epl",
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
                rule_id="mr_ucl_ml",
                league="ucl",
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
        ],
        activate=True,
    )
    monkeypatch.setattr(
        "mappers.control_plane.chat_skills.onboard_league.probe_all_books_parallel",
        lambda *a, **k: [
            {"book": "kalshi", "evidence": True, "ok": True},
            {"book": "optic", "evidence": True, "ok": True},
        ],
    )
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_propose.propose_markets",
        lambda store, bag, **kwargs: _fake_propose_markets(bag, **kwargs),
    )
    first = handle_chat_turn(
        ChatRequest(message="add league ucl soccer for kalshi", conversation_id="v2a"),
        settings=_settings(),
        store=store,
    )
    assert any(b.send == "yes" for b in first.reply_buttons)
    second = handle_chat_turn(
        ChatRequest(message="map moneyline markets for ucl on optic", conversation_id="v2a"),
        settings=_settings(),
        store=store,
    )
    assert any(b.send == "yes" for b in second.reply_buttons)
    confirmed = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="v2a"),
        settings=_settings(),
        store=store,
    )
    assert any(a["type"] == "cart_add" for a in confirmed.ui_actions)
    kinds = {it["kind"] for it in confirmed.ui_actions[0]["items"]}
    assert "mapping_league" in kinds
    assert "mapping_market_rules" in kinds


def test_daily_turn_budget() -> None:
    store = _store()
    settings = _settings(chat_daily_turn_budget=1)
    handle_chat_turn(
        ChatRequest(message="pin M05 on kalshi for epl", conversation_id="bud1"),
        settings=settings,
        store=store,
    )
    second = handle_chat_turn(
        ChatRequest(message="pin ARS on kalshi for epl", conversation_id="bud2"),
        settings=settings,
        store=store,
    )
    assert second.agent_available is False
    assert "budget" in second.reply_markdown.lower()


def test_audit_question_opens_matching_rules_tab() -> None:
    store = _store()
    resp = handle_chat_turn(
        ChatRequest(
            message="which leagues are missing kalshi market rules?",
            conversation_id="audit1",
        ),
        settings=_settings(),
        store=store,
        llm=_lookup_llm("lookup_market_rules", {"q": "kalshi"}, "Market rules for kalshi."),
    )
    filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
    assert filters and filters[0]["kind"] == "market_rules"


def test_count_ignored_nfl_market_rules() -> None:
    store = _nfl_rules_store()
    resp = handle_chat_turn(
        ChatRequest(
            message="how many ignored nfl market rules",
            conversation_id="cnt1",
        ),
        settings=_settings(),
        store=store,
        llm=_lookup_llm(
            "lookup_market_rules",
            {"q": "nfl"},
            "Tip has **3** market rules (**2** ignored).",
        ),
    )
    filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
    assert filters and filters[0]["kind"] == "market_rules"
    assert filters[0]["q"] == "nfl"
    assert "**3**" in resp.reply_markdown
    assert "**2** ignored" in resp.reply_markdown


def test_non_count_audit_unchanged() -> None:
    store = _store()
    resp = handle_chat_turn(
        ChatRequest(message="what markets do we map for epl", conversation_id="cnt3"),
        settings=_settings(),
        store=store,
        llm=_lookup_llm("lookup_market_rules", {"q": "epl"}, "EPL market rules on tip."),
    )
    filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
    assert filters and filters[0]["kind"] == "market_rules"


def test_platform_question_opens_leagues_tab() -> None:
    store = _store()
    for msg in ("which platforms we mapped mlb", "which sportsbook have mlb mapped"):
        resp = handle_chat_turn(
            ChatRequest(message=msg, conversation_id="plat1"),
            settings=_settings(),
            store=store,
            llm=_lookup_llm("lookup_leagues", {"q": "mlb"}, "MLB platforms."),
        )
        filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
        assert filters and filters[0]["kind"] == "leagues", msg


def test_market_question_opens_market_rules_tab() -> None:
    store = _store()
    for msg in ("what markets do we map for mlb", "do we map any markets for mlb"):
        resp = handle_chat_turn(
            ChatRequest(message=msg, conversation_id="mkt1"),
            settings=_settings(),
            store=store,
            llm=_lookup_llm("lookup_market_rules", {"q": "mlb"}, "MLB markets."),
        )
        filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
        assert filters and filters[0]["kind"] == "market_rules", msg
        assert "alias suggestions" not in resp.reply_markdown.lower(), msg


def test_league_coverage_question_opens_leagues_tab() -> None:
    store = _esports_store()
    for msg, expected in (
        ("do we have cs2 mappings?", "cs2"),
        ("do we have dota_2 mappings?", "dota_2"),
        ("do we have CS2 mappings?", "CS2"),
    ):
        resp = handle_chat_turn(
            ChatRequest(message=msg, conversation_id="cov1"),
            settings=_settings(),
            store=store,
            llm=_lookup_llm("lookup_leagues", {"q": expected}, f"Coverage for {expected}."),
        )
        filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
        assert filters and filters[0]["kind"] == "leagues", msg
        assert filters[0]["q"] == expected, msg
        navs = [a for a in resp.ui_actions if a["type"] == "navigate"]
        assert navs and navs[0]["path"] == f"/rules?kind=leagues&q={expected}", msg


def test_unknown_league_still_gets_a_query_term() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="do we have cs2 mappings?", conversation_id="cov2"),
        settings=_settings(),
        store=_store(),
        llm=_lookup_llm("lookup_leagues", {"q": "cs2"}, "No cs2 on tip."),
    )
    filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
    assert filters and filters[0]["q"] == "cs2"


def test_entity_question_stays_on_entities_tab() -> None:
    store = _esports_store()
    for msg in ("do we have BAR mapped in cs2?", "do we have an alias for cs2?"):
        resp = handle_chat_turn(
            ChatRequest(message=msg, conversation_id="ent1"),
            settings=_settings(),
            store=store,
            llm=_lookup_llm("lookup_entities", {"q": "BAR"}, "Entity lookup."),
        )
        filters = [a for a in resp.ui_actions if a["type"] == "rules_filter"]
        assert filters and filters[0]["kind"] == "entities", msg


def test_league_slug_skips_filler_words() -> None:
    assert slug_from_message("I want to add champion league") == "champion_league"


def test_league_without_name_asks_for_slug() -> None:
    llm = FakeChatLLM(script=[ChatLLMResult(text="Which league slug should I onboard?")])
    resp = handle_chat_turn(
        ChatRequest(message="I want to add a new league", conversation_id="slug2"),
        settings=_settings(),
        store=_store(),
        llm=llm,
    )
    assert "league" in resp.reply_markdown.lower()


def test_league_sport_inferred_from_slug() -> None:
    llm = FakeChatLLM(
        script=[
            ChatLLMResult(
                tool_calls=[
                    ToolCall(
                        name="propose_league",
                        args={
                            "league": "itf_men_doubles",
                            "sportsbook": "kalshi",
                            "sport": "tennis",
                        },
                    )
                ]
            ),
            ChatLLMResult(text="Staged itf_men_doubles."),
        ]
    )
    handle_chat_turn(
        ChatRequest(message="can we add new league itf_men_doubles", conversation_id="itf1"),
        settings=_settings(),
        store=_store(),
        llm=llm,
    )
    items = cart_items(session_bag().get_or_create("itf1"))
    assert items
    payload = items[0]["payload"]
    assert payload["league"] == "itf_men_doubles"
    assert payload["sport"] == "tennis"
    assert "soccer" not in payload["optic_league_id"]


def test_league_unknown_sport_is_not_soccer() -> None:
    llm = FakeChatLLM(
        script=[
            ChatLLMResult(
                tool_calls=[
                    ToolCall(
                        name="propose_league",
                        args={"league": "zzz_obscure_thing", "sportsbook": "kalshi"},
                    )
                ]
            ),
            ChatLLMResult(text="Staged zzz_obscure_thing."),
        ]
    )
    handle_chat_turn(
        ChatRequest(message="add league zzz_obscure_thing", conversation_id="zzz1"),
        settings=_settings(),
        store=_store(),
        llm=llm,
    )
    items = cart_items(session_bag().get_or_create("zzz1"))
    assert items
    payload = items[0]["payload"]
    assert payload["sport"] == ""
    assert payload["optic_league_id"] == ""


def test_plural_market_rules_is_market_intent() -> None:
    assert score_intent("suggest market rules for epl", tip_leagues={"epl"}).intent == (
        "mapping_market_rules"
    )


def test_chat_stream_sse() -> None:
    store = _store()
    control = ProposalService(store, live=NullLiveLookup())
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: _settings()
    client = TestClient(app)
    resp = client.post(
        "/chat/stream",
        json={"message": "pin M05 on kalshi for epl", "conversation_id": "sse1"},
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:a@wsd.com"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert "event: status" in resp.text
    assert "event: token" in resp.text
    assert "event: final" in resp.text

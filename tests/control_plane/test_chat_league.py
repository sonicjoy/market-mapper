"""Mapper Chat league onboard uses tip slugs / sports / sportsbook lists."""

from __future__ import annotations

import pytest

from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_catalog import (
    SPORTS,
    SPORTSBOOKS,
    match_league,
    match_sport,
    named_sportsbooks,
    optic_id_for,
    slug_from_message,
    sport_for_slug,
)
from mappers.control_plane.chat_console import ConsolePage
from mappers.control_plane.chat_intent import score_intent
from mappers.control_plane.chat_llm import FakeChatLLM
from mappers.control_plane.chat_profiles import CHAT_SPORTSBOOKS, all_platform_exchanges
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_skills import onboard_league
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore


def _settings() -> Settings:
    return Settings(
        gcp_project="marketmaking-test",
        chat_enabled=True,
        chat_provider="fake",
        chat_model="fake",
    )


def _catalog_store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="italy_serie_a",
                sport="soccer",
                optic_league_id="italy_-_serie_a",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
            LeagueRow(
                league="itf_men_doubles",
                sport="tennis",
                optic_league_id="itf_men_doubles",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        activate=True,
    )
    return store


def setup_function() -> None:
    session_bag().clear()
    clear_tip_league_cache()


def test_catalog_lists_match_enums() -> None:
    store = _catalog_store()
    assert "esports" in SPORTS
    assert SPORTSBOOKS == CHAT_SPORTSBOOKS
    assert match_league("italy serie a", store) == "italy_serie_a"
    assert match_sport("please map esport valorant league") == "esports"
    assert named_sportsbooks("enable for px and crypto") == ["px", "crypto.com"]
    assert named_sportsbooks("wire polymarket_usa for ncaaf") == ["polymarket_usa"]
    assert named_sportsbooks("enable polymarket only") == ["polymarket"]
    assert named_sportsbooks("enable these markets for Poly US") == ["polymarket_usa"]
    assert named_sportsbooks("enable polymarket us") == ["polymarket_usa"]
    assert named_sportsbooks("enable poly") == []
    assert sport_for_slug("itf_men_doubles", store) == "tennis"
    assert optic_id_for("italy_serie_a", store) == "italy_-_serie_a"
    assert optic_id_for("valorant", store) == ""


def test_all_platform_exchanges_leaves_poly_usa_source_empty() -> None:
    pins = all_platform_exchanges(
        optic_league_id="ncaaf",
        evidence_books=["polymarket_usa", "optic"],
    )
    usa = next(p for p in pins if p["sportsbook"] == "polymarket_usa")
    optic = next(p for p in pins if p["sportsbook"] == "optic")
    assert usa["enabled"] is True
    assert usa["source_league_id"] is None
    assert optic["source_league_id"] == "ncaaf"


def test_all_platform_exchanges_does_not_copy_optic_onto_polymarket() -> None:
    pins = all_platform_exchanges(
        optic_league_id="england_-_premier_league",
        evidence_books=["polymarket", "optic"],
    )
    poly = next(p for p in pins if p["sportsbook"] == "polymarket")
    assert poly["enabled"] is True
    assert poly["source_league_id"] is None


def test_slug_from_valorant_prompts() -> None:
    assert slug_from_message("please map esport valorant league") == "valorant"
    assert slug_from_message("enable Valorant for all sportsbooks") == "valorant"


def test_map_valorant_league_is_onboard_intent() -> None:
    scored = score_intent("please map esport valorant league", tip_leagues=set())
    assert scored.intent == "mapping_league"
    assert scored.confidence >= 0.9


def test_enable_all_sportsbooks_is_onboard_intent() -> None:
    scored = score_intent("enable Valorant for all sportsbooks", tip_leagues=set())
    assert scored.intent == "mapping_league"
    assert scored.confidence >= 0.9


def test_map_valorant_stages_only_evidenced_books(monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging an unevidenced book is exactly what the onboard playbook forbids."""
    monkeypatch.setattr(
        onboard_league,
        "probe_all_books_parallel",
        lambda *a, **k: [
            {"ok": True, "book": "novig", "evidence": True, "league": "VALORANT"},
            {"ok": True, "book": "optic", "evidence": False, "note": "no fixtures in 96h"},
            {"ok": True, "book": "polymarket", "evidence": False, "note": "missing optic id"},
            {"ok": True, "book": "px", "evidence": False, "note": "verify manually"},
            {"ok": True, "book": "crypto.com", "evidence": False, "note": "verify catalogue"},
        ],
    )
    resp = handle_chat_turn(
        ChatRequest(message="please map esport valorant league", conversation_id="val1"),
        settings=_settings(),
        store=InMemoryStore(environment="test", allow_activate=True),
        llm=FakeChatLLM(script=[]),
    )
    assert "valorant" in resp.reply_markdown.lower()
    items = cart_items(session_bag().get_or_create("val1"))
    assert items
    payload = items[0]["payload"]
    assert payload["league"] == "valorant"
    assert payload["sport"] == "esports"
    books = {e["sportsbook"] for e in payload["exchanges"] if e.get("enabled")}
    assert books == {"novig"}
    assert set(CHAT_SPORTSBOOKS) - books, "unevidenced books must stay off"
    assert "no fixtures in 96h" in resp.reply_markdown, "skips need an intentional reason"


def test_enable_valorant_all_books_does_not_ask_for_a_book() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="enable Valorant for all sportsbooks", conversation_id="val2"),
        settings=_settings(),
        store=InMemoryStore(environment="test", allow_activate=True),
        llm=FakeChatLLM(script=[]),
    )
    assert "explicitly" not in resp.reply_markdown.lower()
    assert "valorant" in resp.reply_markdown.lower()
    items = cart_items(session_bag().get_or_create("val2"))
    assert items and items[0]["payload"]["league"] == "valorant"


def _saudi_store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="saudi_pro_league",
                sport="soccer",
                optic_league_id="saudi_arabia_-_saudi_league",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            )
        ],
        activate=True,
    )
    return store


def test_no_entities_question_is_audit_not_onboard() -> None:
    msg = "we don't have any entities for league saudi_pro_league"
    scored = score_intent(msg, tip_leagues={"saudi_pro_league"})
    assert scored.intent == "audit"
    assert scored.league_hint == "saudi_pro_league"
    assert not onboard_league.match(scored, msg, ConsolePage())
    resp = handle_chat_turn(
        ChatRequest(message=msg, conversation_id="ent0"),
        settings=_settings(),
        store=_saudi_store(),
        llm=FakeChatLLM(script=[]),
    )
    assert "0" in resp.reply_markdown
    assert "suggest aliases" in resp.reply_markdown.lower()
    assert not cart_items(session_bag().get_or_create("ent0"))


def test_whats_the_optic_id_does_not_search_the_sentence() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="what's the optic id", conversation_id="oid1"),
        settings=_settings(),
        store=_saudi_store(),
        llm=FakeChatLLM(script=[]),
    )
    assert "which league" in resp.reply_markdown.lower()
    assert "what's the optic id" not in resp.reply_markdown.lower()

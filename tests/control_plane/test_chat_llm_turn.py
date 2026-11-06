"""Scoped LLM fallback: on-topic unmatched only; never on fake provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM, ToolCall
from mappers.control_plane.chat_llm_turn import blocked_propose_markets, should_run_llm, system_prompt
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore


@dataclass
class CountingLLM:
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    calls: list[list[dict[str, Any]]] = field(default_factory=list)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatLLMResult:
        _ = tools
        self.calls.append(messages)
        return ChatLLMResult(text="LLM answered.", finish_reason="stop")


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
                optic_league_id="epl",
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


def setup_function() -> None:
    session_bag().clear()


def _turn(message: str, *, llm: Any, **kwargs: object):
    return handle_chat_turn(
        ChatRequest(message=message, conversation_id="llm1"),
        settings=_settings(**kwargs),
        store=_store(),
        llm=llm,
    )


def test_should_run_llm_skips_fake() -> None:
    assert should_run_llm(_settings(), None) is False
    fake = FakeChatLLM()
    assert should_run_llm(_settings(), fake) is False
    gemini = FakeChatLLM(provider="gemini", model="gemini-3.8-flash")
    assert should_run_llm(_settings(), gemini) is True


def test_weather_does_not_call_injected_gemini() -> None:
    llm = CountingLLM()
    resp = _turn("what's the weather in London?", llm=llm)
    assert llm.calls == []
    assert "clarify" in resp.reply_markdown.lower()


def test_on_topic_unmatched_uses_llm() -> None:
    llm = FakeChatLLM(
        provider="gemini",
        model="gemini-3.8-flash",
        script=[
            ChatLLMResult(
                tool_calls=[
                    ToolCall(name="lookup_rules", args={"kind": "entities", "q": "dual-read"}),
                ],
                finish_reason="tool_calls",
            ),
            ChatLLMResult(text="Dual-read is tip then root.", finish_reason="stop"),
        ],
    )
    resp = _turn("how does dual-read work for mapping aliases?", llm=llm)
    assert "tip then root" in resp.reply_markdown


def test_system_prompt_includes_poly_us_registry() -> None:
    prompt = system_prompt()
    assert "player_passing_yards" in prompt
    assert "needs_code" in prompt
    assert "Never approve" in prompt


def test_blocked_propose_markets_poly_us_player_props() -> None:
    blocked = blocked_propose_markets(
        "enable player_sacks for Poly US",
        {"league": "nfl", "sportsbook": "polymarket_usa"},
    )
    assert blocked is not None
    assert blocked["needs_code"] is True
    assert "player_sacks" in blocked["gaps"]
    assert blocked_propose_markets(
        "enable player_passing_attempts for Poly US",
        {"league": "nfl", "sportsbook": "polymarket_usa"},
    ) is None
    assert blocked_propose_markets(
        "enable moneyline for kalshi",
        {"league": "nfl", "sportsbook": "kalshi"},
    ) is None

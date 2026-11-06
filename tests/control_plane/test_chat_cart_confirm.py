"""Staged-cart dedupe, deterministic confirm summary, and no/discard."""

from __future__ import annotations

import pytest

from mappers.control_plane.chat_budget import chat_budget
from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM, ToolCall
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import ChatSession, session_bag
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.models import ChatRequest
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
    return InMemoryStore(environment="test", allow_activate=True)


def setup_function() -> None:
    session_bag().clear()
    chat_budget().reset()


@pytest.fixture(autouse=True)
def _no_live_harvest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_propose.harvest_exchange_batch",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_skill.harvest_exchange_source_id",
        lambda *_a, **kwargs: {
            "ok": True,
            "book": str(kwargs.get("sportsbook") or ""),
            "evidence": False,
            "note": "test stub",
        },
    )


def _propose(tools: ChatToolContext, book: str) -> dict:
    return tools.run(
        "propose_league",
        {"league": "saudi_pro_league", "sportsbook": book, "sport": "soccer"},
    )


def test_duplicate_league_propose_stages_one_line() -> None:
    bag = ChatSession(conversation_id="dup1")
    tools = ChatToolContext(_store(), bag=bag)
    first = _propose(tools, "novig")
    second = _propose(tools, "novig")
    assert first["staged"] == "added"
    assert second["staged"] == "duplicate"
    assert "already staged" in second["message"]
    assert len(cart_items(bag)) == 1


def test_propose_league_overlays_harvested_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_propose.harvest_exchange_batch",
        lambda *_a, **_k: [
            {
                "ok": True,
                "book": "novig",
                "evidence": True,
                "source": "SPL",
                "settings": {"league": "SPL"},
            },
            {
                "ok": True,
                "book": "optic",
                "evidence": True,
                "source": "saudi_arabia_-_saudi_pro_league",
            },
        ],
    )
    bag = ChatSession(conversation_id="hrv1")
    tools = ChatToolContext(_store(), bag=bag)
    _propose(tools, "novig")
    pins = cart_items(bag)[0]["payload"]["exchanges"]
    novig = next(p for p in pins if p["sportsbook"] == "novig")
    poly = next(p for p in pins if p["sportsbook"] == "polymarket")
    assert novig["enabled"] is True
    assert novig["source_league_id"] == "SPL"
    assert novig["settings"]["league"] == "SPL"
    assert poly["enabled"] is False
    assert not poly.get("source_league_id")


def test_second_book_merges_into_existing_league_line() -> None:
    bag = ChatSession(conversation_id="mrg1")
    tools = ChatToolContext(_store(), bag=bag)
    _propose(tools, "novig")
    merged = _propose(tools, "crypto.com")
    assert merged["staged"] == "merged"
    items = cart_items(bag)
    assert len(items) == 1
    books = {
        e["sportsbook"] for e in items[0]["payload"]["exchanges"] if e.get("enabled")
    }
    assert books == {"novig", "crypto.com", "optic"}
    assert items[0]["label"] == "League saudi_pro_league (crypto.com+novig+optic)"


def _propose_llm() -> FakeChatLLM:
    return FakeChatLLM(
        script=[
            ChatLLMResult(
                tool_calls=[
                    ToolCall(
                        name="propose_league",
                        args={
                            "league": "saudi_pro_league",
                            "sportsbook": "novig",
                            "sport": "soccer",
                        },
                    )
                ]
            ),
            ChatLLMResult(text="Staged saudi_pro_league for novig+optic."),
        ]
    )


def test_reply_carries_server_rendered_checklist() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="add league saudi_pro_league", conversation_id="chk1"),
        settings=_settings(),
        store=_store(),
        llm=_propose_llm(),
    )
    assert "Pending cart (1)" in resp.reply_markdown
    assert "League saudi_pro_league (0 evidenced books)" in resp.reply_markdown
    sends = {b.send for b in resp.reply_buttons}
    assert sends == {"yes", "no"}


def test_yes_lists_added_labels() -> None:
    store = _store()
    handle_chat_turn(
        ChatRequest(message="add league saudi_pro_league", conversation_id="yes1"),
        settings=_settings(),
        store=store,
        llm=_propose_llm(),
    )
    confirmed = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="yes1"),
        settings=_settings(),
        store=store,
        llm=FakeChatLLM(script=[]),
    )
    assert "League saudi_pro_league (0 evidenced books)" in confirmed.reply_markdown
    adds = [a for a in confirmed.ui_actions if a["type"] == "cart_add"]
    assert len(adds) == 1 and len(adds[0]["items"]) == 1


def test_no_discards_and_later_yes_adds_nothing() -> None:
    store = _store()
    handle_chat_turn(
        ChatRequest(message="add league saudi_pro_league", conversation_id="no1"),
        settings=_settings(),
        store=store,
        llm=_propose_llm(),
    )
    declined = handle_chat_turn(
        ChatRequest(message="no", conversation_id="no1"),
        settings=_settings(),
        store=store,
        llm=FakeChatLLM(script=[]),
    )
    assert "Discarded 1 staged line(s)" in declined.reply_markdown
    assert not cart_items(session_bag().get_or_create("no1"))
    late_yes = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="no1"),
        settings=_settings(),
        store=store,
        llm=FakeChatLLM(script=[ChatLLMResult(text="Nothing is staged.")]),
    )
    assert all(a["type"] != "cart_add" for a in late_yes.ui_actions)


def test_pending_league_optic_ask_and_set() -> None:
    store = _store()
    bag = session_bag().get_or_create("opt1")
    tools = ChatToolContext(store, bag=bag)
    _propose(tools, "novig")
    ask = handle_chat_turn(
        ChatRequest(message="what's the optic id", conversation_id="opt1"),
        settings=_settings(),
        store=store,
        llm=FakeChatLLM(script=[]),
    )
    assert "optic_league_id" in ask.reply_markdown
    set_id = handle_chat_turn(
        ChatRequest(message="the optic league name is saudi_league", conversation_id="opt1"),
        settings=_settings(),
        store=store,
        llm=FakeChatLLM(script=[]),
    )
    assert "saudi_league" in set_id.reply_markdown
    payload = cart_items(session_bag().get_or_create("opt1"))[0]["payload"]
    assert payload["optic_league_id"] == "saudi_league"

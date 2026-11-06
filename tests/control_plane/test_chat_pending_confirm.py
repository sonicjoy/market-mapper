"""Typed pending confirm paths (skill cart, alias discard)."""

from __future__ import annotations

from mappers.control_plane.chat_cart import cart_items, handle_pending
from mappers.control_plane.chat_pending import PendingAlias, PendingSkill, get_pending, set_pending
from mappers.control_plane.chat_session import ChatSession


def test_pending_skill_cart_yes_adds_to_cart() -> None:
    bag = ChatSession(conversation_id="ps1")
    item = {
        "kind": "entity_alias",
        "label": "px M05 → epl",
        "payload": {"kind": "entity_alias", "league": "epl"},
    }
    set_pending(
        bag,
        PendingSkill(skill="onboard_league", slots={"league": "wta"}, cart_items=[item]),
    )
    resp = handle_pending(bag=bag, conversation_id="ps1", message="yes")
    assert resp is not None
    assert any(a["type"] == "cart_add" for a in resp.ui_actions)
    # A PendingSkill only exists while a slot is unanswered, so confirming the
    # cart empties it but must leave the skill's question open.
    pending = get_pending(bag)
    assert isinstance(pending, PendingSkill)
    assert pending.skill == "onboard_league"
    assert not cart_items(bag)


def test_pending_skill_cart_no_discards() -> None:
    bag = ChatSession(conversation_id="ps2")
    item = {"kind": "entity_alias", "label": "x", "payload": {"kind": "entity_alias"}}
    set_pending(
        bag,
        PendingSkill(skill="onboard_league", slots={"league": "wta"}, cart_items=[item]),
    )
    resp = handle_pending(bag=bag, conversation_id="ps2", message="no")
    assert resp is not None
    assert "discarded" in resp.reply_markdown.lower()
    assert not cart_items(bag)
    pending = get_pending(bag)
    assert isinstance(pending, PendingSkill)
    assert pending.skill == "onboard_league"


def test_pending_alias_no_discards_suggestions() -> None:
    bag = ChatSession(conversation_id="pa1")
    set_pending(bag, PendingAlias(suggestions={"1": {"id": "1", "label": "A"}}))
    resp = handle_pending(bag=bag, conversation_id="pa1", message="no")
    assert resp is not None
    assert "discarded" in resp.reply_markdown.lower()
    assert get_pending(bag) is None


def test_crypto_sweep_followup_runs_sweep_not_optic_suggest(monkeypatch) -> None:
    from mappers.control_plane.chat_router import handle_chat_turn
    from mappers.control_plane.models import ChatRequest
    from mappers.control_plane.settings import Settings
    from mappers.control_plane.store import InMemoryStore

    calls: list[dict[str, str]] = []

    def _fake_sweep(_tools: object, args: dict[str, str]) -> dict[str, object]:
        calls.append(args)
        return {"suggestions": [], "warnings": ["none"]}

    monkeypatch.setattr(
        "mappers.control_plane.chat_tools.ChatToolContext.run",
        lambda self, name, args: _fake_sweep(self, args) if name == "sweep_crypto_ids" else {},
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    settings = Settings(
        gcp_project="marketmaking-test",
        chat_enabled=True,
        chat_provider="fake",
        chat_model="fake",
    )
    handle_chat_turn(
        ChatRequest(message="sweep crypto ids", conversation_id="crypto-fu"),
        settings=settings,
        store=store,
    )
    handle_chat_turn(
        ChatRequest(message="atp", conversation_id="crypto-fu"),
        settings=settings,
        store=store,
    )
    assert calls == [{"league": "atp"}]


def test_clear_skill_pending_keeps_ignore_flips() -> None:
    from mappers.control_plane.chat_pending import PendingCart
    from mappers.control_plane.chat_skills import _clear_skill_pending

    bag = ChatSession(conversation_id="flip1")
    flip = {"kind": "mapping_market_rules", "label": "flip nfl", "payload": {}}
    set_pending(bag, PendingCart(cart_items=[], awaiting_ignore_flip=[flip]))
    _clear_skill_pending(bag)
    pending = get_pending(bag)
    assert isinstance(pending, PendingCart)
    assert pending.awaiting_ignore_flip == [flip]


def test_pin_followup_league_uses_stored_code_hint(monkeypatch) -> None:
    from mappers.control_plane.chat_router import handle_chat_turn
    from mappers.control_plane.models import ChatRequest
    from mappers.control_plane.settings import Settings
    from mappers.control_plane.store import InMemoryStore

    store = InMemoryStore(environment="test", allow_activate=True)
    settings = Settings(
        gcp_project="marketmaking-test",
        chat_enabled=True,
        chat_provider="fake",
        chat_model="fake",
    )
    first = handle_chat_turn(
        ChatRequest(message="pin M05 on px", conversation_id="pin-fu"),
        settings=settings,
        store=store,
    )
    assert "which league" in first.reply_markdown.lower()
    second = handle_chat_turn(
        ChatRequest(message="epl", conversation_id="pin-fu"),
        settings=settings,
        store=store,
    )
    assert "queued" in second.reply_markdown.lower()
    assert "m05" in second.reply_markdown.lower()
    assert "epl" in second.reply_markdown.lower()


def test_save_skill_pending_keeps_ignore_flips() -> None:
    from mappers.control_plane.chat_pending import PendingCart
    from mappers.control_plane.chat_skills import _save_skill_pending

    bag = ChatSession(conversation_id="flip2")
    flip = {"kind": "mapping_market_rules", "label": "flip nfl", "payload": {}}
    set_pending(bag, PendingCart(cart_items=[], awaiting_ignore_flip=[flip]))
    _save_skill_pending(bag, "alias_pin", slots={"league": ""})
    pending = get_pending(bag)
    assert isinstance(pending, PendingSkill)
    assert pending.awaiting_ignore_flip == [flip]


def test_pending_skill_abandoned_on_new_command() -> None:
    from mappers.control_plane.chat_router import handle_chat_turn
    from mappers.control_plane.chat_session import session_bag
    from mappers.control_plane.models import ChatRequest
    from mappers.control_plane.settings import Settings
    from mappers.control_plane.store import InMemoryStore

    session_bag().clear()
    store = InMemoryStore(environment="test", allow_activate=True)
    settings = Settings(
        gcp_project="marketmaking-test",
        chat_enabled=True,
        chat_provider="fake",
        chat_model="fake",
    )
    handle_chat_turn(
        ChatRequest(message="sweep crypto ids", conversation_id="abandon1"),
        settings=settings,
        store=store,
    )
    pending_mid = get_pending(session_bag().get_or_create("abandon1"))
    assert isinstance(pending_mid, PendingSkill)
    assert pending_mid.skill == "alias_pin"
    resp = handle_chat_turn(
        ChatRequest(message="add league wta", conversation_id="abandon1"),
        settings=settings,
        store=store,
    )
    pending_after = get_pending(session_bag().get_or_create("abandon1"))
    assert not (
        isinstance(pending_after, PendingSkill) and pending_after.skill == "alias_pin"
    )
    # The reply must come from onboard_league. Asserting only that the pending
    # bag changed is a false green: alias_pin also clears pending when it runs,
    # so a swallowed slot fill ("no missing crypto ids for wta") passes that.
    assert "crypto id" not in resp.reply_markdown.lower()
    assert "wta" in resp.reply_markdown.lower()
    assert "platform" in resp.reply_markdown.lower()


def test_entity_add_league_followup_via_focus() -> None:
    from mappers.control_plane.chat_router import handle_chat_turn
    from mappers.control_plane.chat_session import session_bag
    from mappers.control_plane.models import ChatRequest
    from mappers.control_plane.settings import Settings
    from mappers.control_plane.store import InMemoryStore

    session_bag().clear()
    store = InMemoryStore(environment="test", allow_activate=True)
    settings = Settings(
        gcp_project="marketmaking-test",
        chat_enabled=True,
        chat_provider="fake",
        chat_model="fake",
    )
    handle_chat_turn(
        ChatRequest(message="entity raphinha", conversation_id="ent-fu"),
        settings=settings,
        store=store,
    )
    resp = handle_chat_turn(
        ChatRequest(message="epl", conversation_id="ent-fu"),
        settings=settings,
        store=store,
    )
    assert "raphinha" in resp.reply_markdown.lower()


def test_league_followup_rejects_confirm_words() -> None:
    from mappers.control_plane.chat_catalog import league_followup
    from mappers.control_plane.chat_skills.alias_pin import fill_followup

    assert league_followup("yes") is None
    assert league_followup("ok") is None
    assert fill_followup({"message": "pin M05 on px"}, "yes") == {}


def test_skill_turn_clears_stale_alias_pending() -> None:
    from mappers.control_plane.chat_skills import _clear_skill_pending

    bag = ChatSession(conversation_id="pa2")
    set_pending(bag, PendingAlias(suggestions={"1": {"id": "1", "label": "A"}}))
    _clear_skill_pending(bag)
    assert get_pending(bag) is None

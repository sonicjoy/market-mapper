"""Regression tests for Mapper Chat follow-up / routing review fixes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mappers.control_plane.chat_cart import cart_items, handle_pending
from mappers.control_plane.chat_catalog import as_league_slug, league_followup
from mappers.control_plane.chat_intent import score_intent, wants_league_onboard
from mappers.control_plane.chat_llm import ChatLLMResult
from mappers.control_plane.chat_pending import (
    PendingSkill,
    get_pending,
    pending_from_dict,
    set_pending,
)
from mappers.control_plane.chat_resolve import resolve_query, source_ids_from_message
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import ChatSession, ChatSessionBag, session_bag
from mappers.control_plane.chat_topic import in_conversation
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore
from tests.control_plane.chat_skills.harness import run_turn


@dataclass
class CountingLLM:
    provider: str = "fake"
    model: str = "fake"
    calls: list[list[dict[str, Any]]] = field(default_factory=list)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatLLMResult:
        _ = tools
        self.calls.append(messages)
        return ChatLLMResult(text="LLM answered.", finish_reason="stop")


def _settings() -> Settings:
    return Settings(
        gcp_project="marketmaking-test",
        chat_enabled=True,
        chat_provider="fake",
        chat_model="fake",
    )


def setup_function() -> None:
    session_bag().clear()


def test_enable_market_id_routes_to_market_rules_not_onboard() -> None:
    scored = score_intent("enable player_passing_yards for Poly US", tip_leagues=set())
    assert scored.intent == "mapping_market_rules"
    assert not wants_league_onboard(
        "enable player_passing_yards for Poly US",
        resolved=scored.resolved,
    )
    rec = run_turn("enable player_passing_yards for Poly US", conversation_id="mr-enable")
    assert rec.path == "skill:market_rules"


def test_add_league_slug_routes_to_onboard_not_market_rules() -> None:
    scored = score_intent("add league serie_a", tip_leagues=set())
    assert scored.intent == "mapping_league"
    rec = run_turn("add league serie_a", conversation_id="on-serie")
    assert rec.path == "skill:onboard_league"


def test_message_league_beats_page_league_for_pin() -> None:
    rec = run_turn(
        "pin M05 on px for nba",
        page={"path": "/entry", "tab": "alias", "entry": {"league": "epl"}},
        conversation_id="page-league",
    )
    assert rec.path in {"skill:alias_pin", "clarify"}
    if rec.path == "skill:alias_pin":
        assert "nba" in rec.response.reply_markdown.lower()


def test_embedded_numeric_id_probes_without_paste() -> None:
    ids = source_ids_from_message("why is 730003207 unmapped")
    assert any(sid.value == "730003207" for sid in ids)
    rec = run_turn("why is 730003207 unmapped", conversation_id="emb-num")
    assert rec.path == "skill:probe_gap"


def test_rules_lookup_followup_after_show_entities() -> None:
    first = run_turn("show entities", conversation_id="rl-fu")
    assert first.path == "skill:rules_lookup"
    second = run_turn("raphinha", conversation_id="rl-fu")
    assert second.path == "skill:rules_lookup"
    assert second.outcome != "ask_slot"


def test_add_multiword_entity_name() -> None:
    resolved = resolve_query("add holger rune", tip_leagues=set())
    assert resolved.entity_name.lower() == "holger rune"


def test_league_followup_serie_a() -> None:
    assert league_followup("serie a") == "serie_a"


def test_prose_never_becomes_a_league_slug() -> None:
    """A slug must be known, tail a catalogue slug, or be typed snake_case."""
    for known in ("nba", "epl", "wta", "serie a", "serie_a", "lacrosse_pll"):
        assert as_league_slug(known), known
    for prose in ("why not", "tell me a joke", "the new season", "all leagues",
                  "tomorrow", "arsenal", "show me"):
        assert as_league_slug(prose) is None, prose
        assert league_followup(prose) is None, prose


def test_for_tail_only_yields_real_league_slugs() -> None:
    assert resolve_query("pin M05 on px for nba", tip_leagues=set()).league == "nba"
    for text in ("is this mapped for tomorrow",
                 "what is the code for arsenal",
                 "pin ARS on px for the new season",
                 "do we map spreads for all leagues"):
        assert resolve_query(text, tip_leagues=set()).league == "", text


def test_new_command_during_slot_fill_is_not_swallowed() -> None:
    """`add league wta` names a slug, but it is a command, not a slot value."""
    first = run_turn("sweep crypto ids", conversation_id="swallow")
    assert first.outcome == "ask_slot"
    second = run_turn("add league wta", conversation_id="swallow")
    assert second.path == "skill:onboard_league"
    assert "crypto id" not in second.response.reply_markdown.lower()


def test_bare_league_value_still_resumes_the_open_skill() -> None:
    first = run_turn("sweep crypto ids", conversation_id="resume")
    assert first.outcome == "ask_slot"
    second = run_turn("epl", conversation_id="resume")
    assert second.path == "skill:alias_pin"
    assert "crypto id" in second.response.reply_markdown.lower()


def test_pin_correction_restarts_with_fresh_slots() -> None:
    """A full pin command replaces the stale code/league, it does not merge."""
    run_turn("pin M05 on px", conversation_id="correct")
    second = run_turn("actually pin ARS on px for epl", conversation_id="correct")
    assert second.path == "skill:alias_pin"
    reply = second.response.reply_markdown
    assert "`ARS`" in reply and "**epl**" in reply
    assert "M05" not in reply


def test_focus_resume_keeps_the_remembered_league() -> None:
    run_turn("suggest aliases for epl", conversation_id="focus")
    second = run_turn("why not?", conversation_id="focus")
    assert "epl" in second.response.reply_markdown
    assert "why_not" not in second.response.reply_markdown


def test_rules_lookup_ignores_prose_followup() -> None:
    run_turn("show entities", conversation_id="prose")
    second = run_turn("tell me a joke", conversation_id="prose")
    assert second.outcome == "ask_slot"
    assert "joke" not in second.response.reply_markdown.lower()


def test_onboard_league_slot_followup_completes() -> None:
    first = run_turn("onboard a league for soccer", conversation_id="onb")
    assert first.outcome == "ask_slot"
    second = run_turn("serie_a", conversation_id="onb")
    assert second.path == "skill:onboard_league"
    assert second.outcome != "ask_slot"
    assert "serie_a" in second.response.reply_markdown


def test_no_discards_ignore_flips_on_pending_skill() -> None:
    bag = ChatSession(conversation_id="flipno")
    flip = {"kind": "mapping_market_rules", "label": "flip nfl", "payload": {}}
    set_pending(
        bag,
        PendingSkill(skill="market_rules", slots={"league": ""}, awaiting_ignore_flip=[flip]),
    )
    resp = handle_pending(bag=bag, conversation_id="flipno", message="no")
    assert resp is not None
    pending = get_pending(bag)
    assert isinstance(pending, PendingSkill)
    assert pending.awaiting_ignore_flip == []
    assert pending.skill == "market_rules"


def test_dual_probe_emits_one_navigation() -> None:
    rec = run_turn(
        "why are KXEPLGAME-26AUG131000EXRBW and "
        "NX.F.OPT.FIFA-123-260910-M.O.1.2 unmapped",
        conversation_id="dualnav",
    )
    assert rec.path == "skill:probe_gap"
    assert rec.ui_action_types.count("navigate") <= 1
    assert rec.ui_action_types.count("prefill_form") <= 1


def test_cart_survives_a_skill_abandon() -> None:
    run_turn("pin M05 on px for epl", conversation_id="cartkeep")
    staged = len(cart_items(session_bag().get_or_create("cartkeep")))
    assert staged >= 1
    run_turn("add league wta", conversation_id="cartkeep")
    assert len(cart_items(session_bag().get_or_create("cartkeep"))) >= staged


def test_legacy_dict_pending_keeps_its_cart_through_cool() -> None:
    """Bags minted before typed pending still migrate rather than drop."""
    bag = ChatSession(conversation_id="legacy")
    item = {"kind": "entity_alias", "label": "px ARS", "payload": {"league": "epl"}}
    bag.pending = pending_from_dict({"kind": "mixed_cart", "cart_items": [item]})
    bag.cool()
    assert cart_items(bag) == [item]


def test_yes_to_ignore_flips_keeps_the_open_skill_question() -> None:
    """Resolving the cart must not silently drop the slot the skill asked for."""
    bag = ChatSession(conversation_id="flipyes")
    flip = {"kind": "mapping_market_rules", "label": "flip nfl", "payload": {}}
    set_pending(
        bag,
        PendingSkill(skill="market_rules", slots={"league": ""}, awaiting_ignore_flip=[flip]),
    )
    assert handle_pending(bag=bag, conversation_id="flipyes", message="yes") is not None
    pending = get_pending(bag)
    assert isinstance(pending, PendingSkill)
    assert pending.skill == "market_rules"


def test_cart_confirm_keeps_the_open_skill_question() -> None:
    bag = ChatSession(conversation_id="cartyes")
    item = {"kind": "entity_alias", "label": "px ARS", "payload": {"league": "epl"}}
    set_pending(bag, PendingSkill(skill="alias_pin", slots={"league": ""}, cart_items=[item]))
    resp = handle_pending(bag=bag, conversation_id="cartyes", message="yes")
    assert resp is not None
    assert "cart_add" in [a.get("type") for a in resp.ui_actions]
    pending = get_pending(bag)
    assert isinstance(pending, PendingSkill)
    assert pending.skill == "alias_pin"
    assert pending.cart_items == []


def test_idle_purge_keeps_a_bag_holding_staged_pins() -> None:
    """cool() preserves the cart; the purge around it must not delete the bag."""
    holder = ChatSessionBag(ttl_sec=0)
    bag = holder.get_or_create("cartonly")
    item = {"kind": "entity_alias", "label": "px ARS", "payload": {"league": "epl"}}
    set_pending(bag, PendingSkill(skill="alias_pin", slots={}, cart_items=[item]))
    bag.updated_at = 0.0
    holder.get_or_create("someone-else")
    assert cart_items(holder.get_or_create("cartonly")) == [item]


def test_single_english_words_are_not_league_slugs() -> None:
    """``cup`` / ``one`` / ``women`` all tail a catalogue slug; none is a league."""
    for word in ("cup", "one", "women", "men", "premier"):
        assert as_league_slug(word) is None
    assert as_league_slug("serie a") == "serie_a"


def test_league_named_mid_sentence_still_fills_the_slot() -> None:
    assert league_followup("try epl instead") == "epl"
    assert league_followup("how about nba") == "nba"
    assert league_followup("why not?") is None


def test_audit_subject_is_a_league_not_a_question_word() -> None:
    rec = run_turn("which sportsbooks do we support", conversation_id="subjword")
    assert "support" not in rec.response.reply_markdown.lower()
    rec = run_turn("which platforms map mlb", conversation_id="subjleague")
    assert rec.path == "skill:rules_lookup"


def test_clarify_alone_is_not_in_conversation() -> None:
    bag = session_bag().get_or_create("cold")
    bag.answered_turns = 1
    assert not in_conversation(bag)


def test_offtopic_after_clarify_does_not_call_llm() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    llm = CountingLLM()
    handle_chat_turn(
        ChatRequest(message="and the other one?", conversation_id="off-clarify"),
        settings=_settings(),
        store=store,
        llm=llm,
    )
    assert llm.calls == []
    follow = CountingLLM()
    handle_chat_turn(
        ChatRequest(message="tell me a joke", conversation_id="off-clarify"),
        settings=_settings(),
        store=store,
        llm=follow,
    )
    assert follow.calls == []

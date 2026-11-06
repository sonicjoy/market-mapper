"""M3c V1 Mapper Chat — deterministic alias path + FakeChatLLM."""

from __future__ import annotations

from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_intent import (
    _code_hint,
    audit_kind,
    audit_subject,
    score_intent,
    wants_crypto_sweep,
)
from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM, ToolCall
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from mappers.control_plane.models import ChatRequest
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.settings import Settings
from mappers.control_plane.store import InMemoryStore
from tests.conftest import us_gateway_market


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
                league="epl",
                entity_type="team",
                canonical_key="ARS",
                canonical_name="Arsenal",
                aliases=[
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "ARS"},
                ],
            )
        ],
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
                exchanges=[],
            ),
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
        ],
        activate=True,
    )
    return store


def setup_function() -> None:
    session_bag().clear()
    clear_tip_league_cache()


def test_refuse_offtopic() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="tell me a joke", conversation_id="c1"),
        settings=_settings(),
        store=_store(),
    )
    assert "mapping" in resp.reply_markdown.lower()
    assert resp.ui_actions == []


def test_map_poly_us_symbol_does_not_suggest_aliases(monkeypatch, us_gateway: dict[str, dict]) -> None:
    us_gateway['aec-atp-benbon-botzan-2026-08-27'] = us_gateway_market(
        'aec-atp-benbon-botzan-2026-08-27', league="atp", smt="tennis_match_winner",
        teams=(("benbon", "Benjamin Bonzi"), ("botzan", "Botic van de Zandschulp")),
        start="2026-08-27T10:00:00Z",
    )
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_mapping.lookup_mapping",
        lambda *_a, **_k: [],
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
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
                exchanges=[],
            )
        ],
        activate=True,
    )
    resp = handle_chat_turn(
        ChatRequest(
            message="map aec-atp-benbon-botzan-2026-08-27",
            conversation_id="usa1",
        ),
        settings=_settings(),
        store=store,
    )
    assert "Alias suggestions" not in resp.reply_markdown
    assert "Polymarket (USA)" in resp.reply_markdown
    assert "benbon" in resp.reply_markdown.lower()


def test_league_propose_all_platforms(monkeypatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_skills.onboard_league.probe_all_books_parallel",
        lambda *a, **k: [
            {"book": b, "evidence": True, "ok": True}
            for b in ("crypto.com", "optic", "polymarket", "px")
        ],
    )
    resp = handle_chat_turn(
        ChatRequest(message="add a new league for serie_a soccer", conversation_id="c2"),
        settings=_settings(),
        store=_store(),
    )
    assert "serie_a" in resp.reply_markdown.lower() or "serie_a" in str(
        session_bag().get_or_create("c2").pending
    ).lower()
    assert cart_has_league(session_bag().get_or_create("c2"))


def cart_has_league(bag) -> bool:
    from mappers.control_plane.chat_cart import cart_items

    return any(it.get("kind") == "mapping_league" for it in cart_items(bag))


def test_league_propose_known_optic_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_skills.onboard_league.probe_all_books_parallel",
        lambda *a, **k: [
            {"book": b, "evidence": True, "ok": True}
            for b in ("crypto.com", "optic", "polymarket", "px")
        ],
    )
    handle_chat_turn(
        ChatRequest(message="add league italy_serie_a", conversation_id="c2b"),
        settings=_settings(),
        store=_store(),
    )
    items = cart_items(session_bag().get_or_create("c2b"))
    assert items
    payload = items[0]["payload"]
    assert payload["league"] == "italy_serie_a"
    assert payload["optic_league_id"] == "italy_-_serie_a"
    books = {e["sportsbook"] for e in payload["exchanges"] if e.get("enabled")}
    assert books == {"crypto.com", "optic", "polymarket", "px"}


def test_pin_alias_prefill_then_cart(monkeypatch) -> None:
    store = _store()
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools.suggest_aliases_from_optic",
        lambda **kwargs: {
            "ok": True,
            "warnings": [],
            "suggestions": [
                {
                    "id": "optic|9CAFB55230E8",
                    "label": "Arsenal (ARS) ← optic:9CAFB55230E8",
                    "payload": {
                        "kind": "entity_alias",
                        "league": "epl",
                        "canonical_key": "ARS",
                        "entity_type": "team",
                        "canonical_name": "Arsenal",
                        "aliases": [
                            {
                                "sportsbook": "optic",
                                "alias_kind": "optic_id",
                                "alias_value": "9CAFB55230E8",
                            }
                        ],
                        "reassign": False,
                    },
                }
            ],
        },
    )
    first = handle_chat_turn(
        ChatRequest(message="suggest aliases for epl", conversation_id="c3"),
        settings=_settings(),
        store=store,
    )
    assert first.reply_buttons
    assert "Arsenal" in first.reply_markdown

    picked = handle_chat_turn(
        ChatRequest(message="select:optic|9CAFB55230E8", conversation_id="c3"),
        settings=_settings(),
        store=store,
    )
    types = [a["type"] for a in picked.ui_actions]
    assert "prefill_form" in types
    assert "switch_tab" in types
    assert "expired" not in picked.reply_markdown.lower()

    confirmed = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="c3"),
        settings=_settings(),
        store=store,
    )
    assert any(a["type"] == "cart_add" for a in confirmed.ui_actions)
    items = confirmed.ui_actions[0]["items"]
    assert items[0]["kind"] == "entity_alias"
    assert items[0]["payload"]["canonical_key"] == "ARS"


def test_single_pin_px_code() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="pin M05 on px for epl", conversation_id="c4"),
        settings=_settings(),
        store=_store(),
    )
    assert "queued" in resp.reply_markdown.lower() or "pending cart" in resp.reply_markdown.lower()
    assert any(b.send == "yes" for b in resp.reply_buttons)
    confirmed = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="c4"),
        settings=_settings(),
        store=_store(),
    )
    assert any(a["type"] == "cart_add" for a in confirmed.ui_actions)


def test_audit_subject_skips_this_ticker() -> None:
    assert audit_subject("do we map this ticker") is None
    assert audit_subject("do we have cs2 mappings?") == "cs2"


def test_code_hint_rejects_bare_integer() -> None:
    assert _code_hint("45 events — actionable gaps") is None
    assert _code_hint("pin M05 on px for epl") == "M05"
    scored = score_intent(
        "Kalshi mapping gaps: 45 events on epl",
        tip_leagues={"epl"},
    )
    assert scored.code_hint != "45"


def test_no_entities_is_not_league_onboard_intent() -> None:
    scored = score_intent(
        "we don't have any entities for league saudi_pro_league",
        tip_leagues={"saudi_pro_league"},
    )
    assert scored.intent == "audit"
    assert scored.league_hint == "saudi_pro_league"
    greedy = score_intent(
        "entities for league saudi_pro_league",
        tip_leagues={"saudi_pro_league"},
    )
    assert greedy.intent != "mapping_league"


def test_optic_id_for_a_code_stays_an_entity_lookup() -> None:
    """"optic id" names an entity pin far more often than a league slug."""
    for message in ("what's the optic id for ARS", "show me optic aliases"):
        scored = score_intent(message, tip_leagues={"epl"})
        kind = audit_kind(
            message, code_hint=scored.code_hint, league_hint=scored.league_hint
        )
        assert kind == "entities", message


def test_gap_report_does_not_prefill_pin() -> None:
    report = (
        "Kalshi mapping gaps (5 leagues): 5 reasons, 45 events — actionable gaps present\n"
        "- [epl] actionable alias gap (unknown Kalshi team code): 21 events "
        "(e.g. KXEPLGAME-26AUG131000EXRBW, ...)\n"
        "- [mlb] actionable alias gap ... 14 events (e.g. KXMLBGAME-26AUG13REGSAN, ...)\n"
        "- [nba] ... 6 events ..."
    )
    scored = score_intent(report, tip_leagues={"epl", "mlb", "nba"})
    assert scored.confidence < 0.9
    assert scored.code_hint != "45"

    resp = handle_chat_turn(
        ChatRequest(message=report, conversation_id="gap1"),
        settings=_settings(),
        store=_store(),
    )
    types = [a["type"] for a in resp.ui_actions]
    assert "prefill_form" not in types
    assert "cart_add" not in types
    assert "45" not in resp.reply_markdown
    assert "Prefilling Mapper with" not in resp.reply_markdown


def test_fake_llm_tool_loop() -> None:
    from mappers.control_plane.chat_tools import ChatToolContext

    out = ChatToolContext(_store()).run("lookup_rules", {"kind": "entities", "q": "atp"})
    assert out.get("count", 0) >= 0


def _atp_store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="atp",
                entity_type="player",
                canonical_key="SINNER",
                canonical_name="Jannik Sinner",
                aliases=[],
            )
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
                exchanges=[],
            )
        ],
        activate=True,
    )
    return store


def _sweep_result(*, truncated: int = 0) -> dict:
    return {
        "ok": True,
        "warnings": [],
        "already_pinned": 0,
        "truncated": truncated,
        "suggestions": [
            {
                "id": "crypto|atp|90001",
                "label": "Jannik Sinner (SINNER) ← crypto:90001",
                "payload": {
                    "kind": "entity_alias",
                    "league": "atp",
                    "canonical_key": "SINNER",
                    "entity_type": "player",
                    "canonical_name": "Jannik Sinner",
                    "aliases": [
                        {
                            "sportsbook": "crypto.com",
                            "alias_kind": "crypto_id",
                            "alias_value": "90001",
                        }
                    ],
                    "reassign": False,
                },
            }
        ],
    }


def test_sweep_crypto_intent_beats_audit_missing() -> None:
    text = "sweep missing crypto ids for atp"
    scored = score_intent(text, tip_leagues={"atp"})
    assert wants_crypto_sweep(text)
    assert scored.intent == "entity_alias"
    assert scored.confidence >= 0.9
    assert scored.league_hint == "atp"
    assert scored.sportsbook_hint == "crypto.com"


def test_pin_missing_crypto_id_is_not_sweep() -> None:
    text = "pin missing crypto_id X90001 on crypto.com for atp"
    assert not wants_crypto_sweep(text)
    scored = score_intent(text, tip_leagues={"atp"})
    assert scored.intent == "entity_alias"
    assert scored.code_hint == "X90001"
    resp = handle_chat_turn(
        ChatRequest(message=text, conversation_id="pin1"),
        settings=_settings(),
        store=_atp_store(),
    )
    assert "missing crypto id" not in resp.reply_markdown.lower()
    assert "queued" in resp.reply_markdown.lower() or "pending cart" in resp.reply_markdown.lower()


def test_count_missing_crypto_ids_is_audit() -> None:
    text = "how many missing crypto ids for atp"
    assert not wants_crypto_sweep(text)
    scored = score_intent(text, tip_leagues={"atp"})
    assert scored.intent == "audit"
    llm = FakeChatLLM(
        script=[
            ChatLLMResult(
                tool_calls=[
                    ToolCall(
                        name="lookup_market_rules",
                        args={"q": "atp", "sportsbook": "crypto.com"},
                    )
                ]
            ),
            ChatLLMResult(text="Tip has market rules for atp on crypto.com."),
        ]
    )
    resp = handle_chat_turn(
        ChatRequest(message=text, conversation_id="cnt1"),
        settings=_settings(),
        store=_atp_store(),
        llm=llm,
    )
    types = [a["type"] for a in resp.ui_actions]
    assert "prefill_form" not in types
    assert "cart_add" not in types
    assert "rules_filter" in types


def test_crypto_gap_report_is_not_sweep() -> None:
    report = (
        "228 QKs — actionable gaps present\n"
        "Likely missing crypto_id aliases\n"
        "- [atp] Moneyline gap (2 symbols)\n"
        "- [wnba] Total Points gap (1 symbol)\n"
        "python scripts/sweep_crypto_team_ids.py --league atp"
    )
    assert not wants_crypto_sweep(report)
    scored = score_intent(report, tip_leagues={"atp", "wnba"})
    assert scored.confidence < 0.9
    resp = handle_chat_turn(
        ChatRequest(message=report, conversation_id="gapc"),
        settings=_settings(),
        store=_atp_store(),
    )
    types = [a["type"] for a in resp.ui_actions]
    assert "prefill_form" not in types
    assert "cart_add" not in types


def test_sweep_crypto_ids_then_cart(monkeypatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools.run_sweep_crypto_ids",
        lambda *_a, **_k: _sweep_result(),
    )
    first = handle_chat_turn(
        ChatRequest(message="sweep crypto ids for atp", conversation_id="sw1"),
        settings=_settings(),
        store=_atp_store(),
    )
    assert "90001" in first.reply_markdown
    assert any(b.send == "yes" for b in first.reply_buttons)
    assert "Add all" in first.reply_markdown
    types = [a["type"] for a in first.ui_actions]
    assert "prefill_form" in types

    confirmed = handle_chat_turn(
        ChatRequest(message="yes", conversation_id="sw1"),
        settings=_settings(),
        store=_atp_store(),
    )
    assert any(a["type"] == "cart_add" for a in confirmed.ui_actions)
    items = next(a["items"] for a in confirmed.ui_actions if a["type"] == "cart_add")
    assert items[0]["payload"]["aliases"][0]["alias_kind"] == "crypto_id"


def test_sweep_capped_copy_does_not_say_add_all(monkeypatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools.run_sweep_crypto_ids",
        lambda *_a, **_k: _sweep_result(truncated=4),
    )
    resp = handle_chat_turn(
        ChatRequest(message="sweep crypto ids for atp", conversation_id="sw2"),
        settings=_settings(),
        store=_atp_store(),
    )
    assert "Add these" in resp.reply_markdown
    assert "4 more not included" in resp.reply_markdown
    assert not any(b.label == "Yes, add all to cart" for b in resp.reply_buttons)
    assert any(b.label == "Yes, add these to cart" for b in resp.reply_buttons)


def test_chat_disabled() -> None:
    resp = handle_chat_turn(
        ChatRequest(message="hello", conversation_id="c6"),
        settings=_settings(chat_enabled=False),
        store=_store(),
    )
    assert resp.agent_available is False

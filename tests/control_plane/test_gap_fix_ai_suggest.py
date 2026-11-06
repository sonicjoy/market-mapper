"""AI suggestion harvest pins (flag default on; closed-list LLM; Review labels)."""

from __future__ import annotations

import json
from typing import Any

from mappers.alias_kinds import optic_pin
from mappers.control_plane.batch_apply import batch_summary
from mappers.control_plane.change_view import payload_change_groups
from mappers.control_plane.chat_llm import ChatLLMResult, FakeChatLLM
from mappers.control_plane.gap_fix_ai_suggest import (
    AI_NOTE,
    AI_REF,
    append_ai_suggestions,
    gap_suggest_enabled,
    is_ai_suggest_pin,
)
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import EntityRow
from tests.control_plane.gap_store_helpers import (
    _league,
    _soccer_store,
    _store,
    _team,
)

_POLY_SLUG = "lal-val-bet-2026-08-25"


def _skip(
    *,
    reason: str = "collision",
    leave: str = "",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    row = {
        "reason": reason,
        "league": "la_liga",
        "title": "Valencia vs Real Betis",
        "needle": "Valencia",
        "alias_book": "polymarket",
        "alias_value": "Valencia",
        "event_ticker": _POLY_SLUG,
        "candidates": json.dumps(
            [
                {"id": "oid-val", "name": "Valencia CF"},
                {"id": "oid-bet", "name": "Real Betis"},
            ],
            separators=(",", ":"),
        ),
        "leave": leave,
    }
    if extra:
        row.update(extra)
    return {key: value for key, value in row.items() if value}


def _bind_pin() -> dict[str, Any]:
    return {
        "kind": "entity_alias",
        "league": "la_liga",
        "canonical_key": "BET",
        "canonical_name": "Real Betis",
        "entity_type": "team",
        "aliases": [{"sportsbook": "polymarket", "alias_kind": "name", "alias_value": "Real Betis"}],
        "evidence_refs": ["gap:unique-bind"],
        "reassign": False,
    }


def _pick_llm(optic_id: str) -> FakeChatLLM:
    return FakeChatLLM(script=[ChatLLMResult(text=json.dumps({"optic_id": optic_id}))])


class _BoomLLM:
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        _ = (messages, tools)
        raise AssertionError("llm must not run when MAPPING_PIPELINE_GAP_SUGGEST is off")


def test_flag_off_skips_injected_llm(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "0")
    pins: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    added = append_ai_suggestions(
        _soccer_store(), [_skip()], pins, seen, llm=_BoomLLM(),
    )
    assert added == 0
    assert pins == []


def test_flag_defaults_on(monkeypatch: Any) -> None:
    monkeypatch.delenv("MAPPING_PIPELINE_GAP_SUGGEST", raising=False)
    assert gap_suggest_enabled() is True
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _soccer_store(), [_skip()], pins, set(), llm=_pick_llm("oid-val"),
    )
    assert added == 1
    assert is_ai_suggest_pin(pins[-1])


def test_flag_on_appends_labeled_pin_last(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins = [_bind_pin()]
    seen: set[tuple[str, str, str]] = {
        ("la_liga", "BET", "Real Betis"),
    }
    added = append_ai_suggestions(
        _soccer_store(), [_skip()], pins, seen, llm=_pick_llm("oid-val"),
    )
    assert added == 1
    assert not is_ai_suggest_pin(pins[0])
    assert is_ai_suggest_pin(pins[-1])
    refs = pins[-1]["evidence_refs"]
    assert AI_REF in refs
    assert AI_NOTE in refs


def test_invented_id_and_abstain_are_dropped(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    store = _soccer_store()
    invented: list[dict[str, Any]] = []
    append_ai_suggestions(
        store, [_skip()], invented, set(), llm=_pick_llm("invented-id"),
    )
    assert invented == []
    abstain: list[dict[str, Any]] = []
    append_ai_suggestions(
        store,
        [_skip()],
        abstain,
        set(),
        llm=FakeChatLLM(script=[ChatLLMResult(text='{"abstain":true}')]),
    )
    assert abstain == []


def test_leave_collision_is_not_sent(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _soccer_store(),
        [_skip(leave="1")],
        pins,
        set(),
        llm=_pick_llm("oid-val"),
    )
    assert added == 0
    assert pins == []


def test_already_live_on_picked_owner_is_not_suggested(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _collision_store(), [_skip()], pins, set(), llm=_pick_llm("oid-val"),
    )
    assert added == 0
    assert pins == []


def test_already_live_poly_name_on_picked_owner_is_not_suggested(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _liu_store(), [_liu_skip()], pins, set(), llm=_pick_llm("oid-liu"),
    )
    assert added == 0
    assert pins == []


def test_state_suffix_lookalike_is_not_suggested(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _soccer_store(),
        [_state_suffix_skip(opponent="Wagner")],
        pins,
        set(),
        llm=_BoomLLM(),
    )
    assert added == 0
    assert pins == []


def test_wrong_fixture_opponent_is_not_suggested(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _soccer_store(),
        [_state_named_skip(opponent="Alcorn State")],
        pins,
        set(),
        llm=_BoomLLM(),
    )
    assert added == 0
    assert pins == []


def test_removed_poly_name_is_not_suggested(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _removed_poly_name_store(),
        [_valencia_cf_skip()],
        pins,
        set(),
        llm=_pick_llm("oid-val"),
    )
    assert added == 0
    assert pins == []


def test_missing_book_alias_on_picked_owner_is_still_suggested(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_SUGGEST", "1")
    pins: list[dict[str, Any]] = []
    added = append_ai_suggestions(
        _optic_only_val_store(), [_skip()], pins, set(), llm=_pick_llm("oid-val"),
    )
    assert added == 1
    values = [a["alias_value"] for a in pins[0]["aliases"]]
    assert "Valencia" in values
    assert "oid-val" not in values


def test_batch_summary_and_review_lines_label_ai() -> None:
    bind = EntityAliasPayload(
        league="la_liga",
        canonical_key="BET",
        canonical_name="Real Betis",
        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="RBB")],
        evidence_refs=["gap:unique-bind"],
    )
    suggest = EntityAliasPayload(
        league="la_liga",
        canonical_key="VAL",
        canonical_name="Valencia",
        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="VCF")],
        evidence_refs=[AI_REF, AI_NOTE],
    )
    payload = BatchChangesPayload(entity_aliases=[bind, suggest])
    assert "2 aliases (1 AI suggestion last)" in batch_summary(payload)
    lines = payload_change_groups(payload)["aliases"]["lines"]
    assert lines[0].startswith("+ Map ")
    assert lines[-1].startswith("+ AI suggestion: Map ")
    assert "AI suggestion:" not in lines[0]


def test_batch_summary_and_review_lines_label_market_rule_ai() -> None:
    bind = EntityAliasPayload(
        league="nba",
        canonical_key="LAL",
        canonical_name="Lakers",
        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="LAL")],
        evidence_refs=["gap:unique-bind"],
    )
    suggest = MappingMarketRulesPayload(
        league="nba",
        rules=[
            MarketRulePin(
                sportsbook="px",
                rule_kind="taxonomy",
                source_key_type="market_name",
                source_key="1st Half Spread",
                action="map",
                canonical_market_type="1h_point_spread",
            )
        ],
        evidence_refs=[AI_REF, AI_NOTE],
    )
    payload = BatchChangesPayload(entity_aliases=[bind], market_rules=[suggest])
    assert "1 aliases (1 AI suggestion last)" in batch_summary(payload)
    lines = payload_change_groups(payload)["market_rules"]["lines"]
    assert lines == [
        "+ AI suggestion: Enable ProphetX 1st Half Spread on Nba: mapped as 1h_point_spread",
    ]


def _collision_store() -> Any:
    val = _team("la_liga", "VAL", "Valencia")
    val.aliases.append({"sportsbook": "optic", "alias_kind": "optic_id", "alias_value": "oid-val"})
    val.aliases.append({"sportsbook": "polymarket", "alias_kind": "name", "alias_value": "Valencia"})
    return _store(
        [val, _team("la_liga", "BET", "Real Betis")],
        [_league("la_liga", "spain_-_la_liga")],
    )


def _optic_only_val_store() -> Any:
    val = _team("la_liga", "VAL", "Valencia")
    val.aliases.append(optic_pin("oid-val"))
    return _store(
        [val, _team("la_liga", "BET", "Real Betis")],
        [_league("la_liga", "spain_-_la_liga")],
    )


def _liu_store() -> Any:
    liu = _team("ncaaf", "LIU", "Long Island University")
    liu.aliases = [
        optic_pin("oid-liu"),
        {"sportsbook": "polymarket", "alias_kind": "name", "alias_value": "LIU"},
    ]
    return _store([liu], [_league("ncaaf", "ncaaf", sport="football")])


def _liu_skip() -> dict[str, str]:
    return _skip(
        reason="name_ambiguous",
        extra={
            "league": "ncaaf",
            "title": "LIU vs. Kansas",
            "needle": "LIU",
            "alias_book": "polymarket",
            "alias_value": "LIU",
            "candidates": json.dumps(
                [{"id": "oid-liu", "name": "Long Island University"}],
                separators=(",", ":"),
            ),
        },
    )


def _state_suffix_skip(*, opponent: str) -> dict[str, str]:
    return _skip(
        reason="name_ambiguous",
        extra={
            "league": "ncaaf",
            "title": "Southern Connecticut State vs. Wagner",
            "needle": "Southern Connecticut State",
            "alias_book": "polymarket",
            "alias_value": "Southern Connecticut State",
            "candidates": json.dumps(
                [
                    {
                        "id": "oid-sco",
                        "name": "Southern Connecticut",
                        "opponent": opponent,
                    }
                ],
                separators=(",", ":"),
            ),
        },
    )


def _state_named_skip(*, opponent: str) -> dict[str, str]:
    return _skip(
        reason="name_ambiguous",
        extra={
            "league": "ncaaf",
            "title": "Southern Connecticut State vs. Wagner",
            "needle": "Southern Connecticut State",
            "alias_book": "polymarket",
            "alias_value": "Southern Connecticut State",
            "candidates": json.dumps(
                [
                    {
                        "id": "oid-scsu",
                        "name": "Southern Connecticut State",
                        "opponent": opponent,
                    }
                ],
                separators=(",", ":"),
            ),
        },
    )


def _valencia_cf_skip() -> dict[str, str]:
    return _skip(
        reason="name_ambiguous",
        extra={
            "title": "Valencia CF vs. Real Betis",
            "needle": "Valencia CF",
            "alias_book": "polymarket",
            "alias_value": "Valencia CF",
            "candidates": json.dumps(
                [{"id": "oid-val", "name": "Valencia", "opponent": "Real Betis"}],
                separators=(",", ":"),
            ),
        },
    )


def _removed_poly_name_store() -> Any:
    val = _team("la_liga", "VAL", "Valencia")
    val.aliases = [
        optic_pin("oid-val"),
        {"sportsbook": "polymarket", "alias_kind": "name", "alias_value": "Valencia CF"},
    ]
    store = _store(
        [val, _team("la_liga", "BET", "Real Betis")],
        [_league("la_liga", "spain_-_la_liga")],
    )
    rid = store.current_rule_set_id
    assert rid is not None
    current = next(e for e in store.entities_for(rid) if e.canonical_key == "VAL")
    stripped = EntityRow(
        league=current.league,
        entity_type=current.entity_type,
        canonical_key=current.canonical_key,
        canonical_name=current.canonical_name,
        aliases=[
            a for a in current.aliases
            if str(a.get("alias_value") or "") != "Valencia CF"
        ],
    )
    others = [e for e in store.entities_for(rid) if e.canonical_key != "VAL"]
    receipt = store.insert_candidate(
        parent_rule_set_id=rid,
        proposal_id="prop_rm_val",
        entities=[stripped, *others],
    )
    store.activate(receipt.rule_set_id)
    return store



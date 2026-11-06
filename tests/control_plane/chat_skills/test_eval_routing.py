"""Suite A — skill routing goldens (offline, CI).

Asserts the logged `path` / `outcome` for every fixture, so a turn answered by
the wrong skill fails here rather than passing on plausible prose.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from tests.control_plane.chat_skills.harness import load_fixture, run_turn

SUITES = (
    "lookup_coverage.yaml",
    "probe_gap.yaml",
    "onboard_league.yaml",
    "market_rules.yaml",
    "safety.yaml",
)

_ALL: list[dict[str, Any]] = [row for name in SUITES for row in load_fixture(name)]
_IDS = [str(r["id"]) for r in _ALL]

# Nothing chat emits may drive an approval, activation, harvest, or BQ write.
# Matched against action types and keys only: user text is echoed back in
# rules_filter.q, so scanning the whole payload would fire on the message.
_ALWAYS_BANNED = ("approve", "activate", "write_bq", "harvest", "submit")


def _action_surface(actions: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for action in actions:
        parts.append(str(action.get("type") or ""))
        parts.extend(str(k) for k in action)
    return " ".join(parts).lower()


def setup_function() -> None:
    session_bag().clear()
    clear_tip_league_cache()


@pytest.mark.parametrize("row", _ALL, ids=_IDS)
def test_routing(row: dict[str, Any]) -> None:
    expect = dict(row.get("expect") or {})
    rec = run_turn(
        row["message"],
        page=row.get("page"),
        conversation_id=str(row["id"]),
        bag_pending=row.get("bag_pending"),
        stubs=row.get("stubs"),
    )
    if "path" in expect:
        assert rec.path == expect["path"]
    if "outcome" in expect:
        assert rec.outcome == expect["outcome"]
    if "slot_source" in expect:
        assert rec.turn.get("slot_source") == expect["slot_source"]
    for want in expect.get("ui_action_types") or []:
        assert want in rec.ui_action_types
    surface = _action_surface(rec.response.ui_actions)
    for banned in [*_ALWAYS_BANNED, *(expect.get("must_not_ui") or [])]:
        assert banned not in surface


@pytest.mark.parametrize("row", _ALL, ids=_IDS)
def test_no_generic_tool_loop(row: dict[str, Any]) -> None:
    """Every turn lands on a skill, a confirm, a clarify, or deterministic alias."""
    allowed = {"confirm", "clarify", "refuse_soft", "deterministic", "llm", "skill:alias_pin"}
    rec = run_turn(
        row["message"],
        page=row.get("page"),
        conversation_id=str(row["id"]),
        bag_pending=row.get("bag_pending"),
        stubs=row.get("stubs"),
    )
    assert rec.path.startswith("skill:") or rec.path in allowed, rec.path


def test_terse_followup_uses_console_league() -> None:
    """"add markets" on Entry league=epl must not ask which league."""
    rec = run_turn(
        "add markets for px",
        page={"path": "/entry", "tab": "league", "entry": {"league": "epl", "sport": "soccer"}},
        conversation_id="terse",
    )
    assert rec.path == "skill:market_rules"
    assert rec.outcome != "ask_slot"
    assert rec.turn.get("slot_source") == "console"


_POLY_SLUG = "bun-stu-koe-2026-09-04-exact-score-0-0"
_POLY_STUBS = {
    "mapping_probe": {
        "ok": True,
        "kind": "exact_score",
        "sportsbook": "polymarket",
        "id_kind": "poly_slug",
        "symbol": _POLY_SLUG,
        "title": "stu vs koe",
        "league": "bun",
        "suffix": "exact-score-0-0",
        "mapped_rows": [],
        "codes": [],
        "optic": {"home": "stu", "away": "koe", "start_date": "2026-09-04"},
    }
}


def test_why_not_resumes_probe_focus() -> None:
    first = run_turn(f"do we map `{_POLY_SLUG}`", conversation_id="why-poly", stubs=_POLY_STUBS)
    assert first.path == "skill:probe_gap"
    second = run_turn("why not?", conversation_id="why-poly", stubs=_POLY_STUBS)
    assert second.path == "skill:probe_gap"
    assert second.outcome != "ask_slot"
    assert second.turn.get("slot_source") == "focus"
    assert "**Why:**" in second.response.reply_markdown
    assert "clarify the league" not in second.response.reply_markdown.lower()


def test_unexpected_followup_uses_focus() -> None:
    run_turn(f"do we map `{_POLY_SLUG}`", conversation_id="pin-it", stubs=_POLY_STUBS)
    rec = run_turn("so we can't pin it?", conversation_id="pin-it", stubs=_POLY_STUBS)
    assert rec.path == "skill:probe_gap"
    assert "clarify the league" not in rec.response.reply_markdown.lower()


def test_focus_does_not_swallow_pin_command() -> None:
    run_turn(f"do we map `{_POLY_SLUG}`", conversation_id="pin-cmd", stubs=_POLY_STUBS)
    rec = run_turn("pin M05 on px for epl", conversation_id="pin-cmd", stubs=_POLY_STUBS)
    assert rec.path != "skill:probe_gap"
    assert rec.path in {"clarify", "skill:alias_pin"}


def test_focus_does_not_swallow_fix_gaps() -> None:
    run_turn(f"do we map `{_POLY_SLUG}`", conversation_id="fix-gaps", stubs=_POLY_STUBS)
    rec = run_turn("fix the gaps", conversation_id="fix-gaps", stubs=_POLY_STUBS)
    assert rec.path == "skill:alias_pin"
    assert "navigate" in rec.ui_action_types


def test_cold_why_not_clarifies() -> None:
    rec = run_turn("why not?", conversation_id="cold-why")
    assert rec.path == "clarify"


def test_weather_does_not_open_rules() -> None:
    rec = run_turn("what's the weather in London?", conversation_id="wx")
    assert rec.path == "clarify"
    assert "rules_filter" not in rec.ui_action_types


def test_focus_survives_hot_ttl() -> None:
    run_turn(f"do we map `{_POLY_SLUG}`", conversation_id="ttl-poly", stubs=_POLY_STUBS)
    bag = session_bag().get_or_create("ttl-poly")
    bag.updated_at = time.time() - 31 * 60
    rec = run_turn("why not?", conversation_id="ttl-poly", stubs=_POLY_STUBS)
    assert rec.path == "skill:probe_gap"
    assert rec.turn.get("slot_source") == "focus"


def test_turn_log_carries_improve_loop_fields() -> None:
    """A log line alone has to be enough to author a fixture."""
    rec = run_turn("how many leagues do we map", conversation_id="loop")
    for key in ("path", "outcome", "page_path", "page_tab", "slot_source", "tool_names", "step_ms"):
        assert key in rec.turn, key
    assert rec.turn["tool_names"], "a tool-backed turn must name its tools"
    assert rec.turn["step_ms"], "a tool-backed turn must record step timings"
    assert rec.steps, "each step emits its own mapping_chat_step event"

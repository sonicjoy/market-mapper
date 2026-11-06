"""Suite B — skill contract checks (offline, CI).

Asserts the playbook rather than the prose: verdicts, staging, and which books
or tabs reach the console. Narration wording is deliberately not asserted.
"""

from __future__ import annotations

from typing import Any

import pytest

from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_skills import SKILLS
from mappers.control_plane.chat_skills.protocol import ALWAYS_TOOLS, MAX_TOOLS
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from mappers.control_plane.chat_tools import TOOL_SCHEMAS, ChatToolContext
from mappers.control_plane.store import InMemoryStore
from tests.control_plane.chat_skills.harness import load_fixture, run_turn


def setup_function() -> None:
    session_bag().clear()
    clear_tip_league_cache()


def _by_id(name: str) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in load_fixture(name)}


def _run(row: dict[str, Any]) -> Any:
    return run_turn(
        row["message"],
        page=row.get("page"),
        conversation_id=str(row["id"]),
        stubs=row.get("stubs"),
    )


_LOOKUP = _by_id("lookup_coverage.yaml")
_PROBE = _by_id("probe_gap.yaml")
_ONBOARD = _by_id("onboard_league.yaml")
_MARKET = _by_id("market_rules.yaml")


@pytest.mark.parametrize("row", list(_LOOKUP.values()), ids=list(_LOOKUP))
def test_lookup_answers_inline(row: dict[str, Any]) -> None:
    """Every lookup answers in chat; non-count asks also drive Rules or Coverage."""
    rec = _run(row)
    assert rec.response.reply_markdown.strip(), "lookup must answer inline"
    expect = dict(row.get("expect") or {})
    if not expect.get("count_only"):
        paths = [str(a.get("path") or "") for a in rec.response.ui_actions]
        drove_rules = "rules_filter" in rec.ui_action_types
        drove_coverage = any(p.startswith("/coverage") for p in paths)
        assert drove_rules or drove_coverage, "Rules or Coverage should match the answer"
    if "reply_contains" in expect:
        assert expect["reply_contains"] in rec.response.reply_markdown


@pytest.mark.parametrize("row", list(_PROBE.values()), ids=list(_PROBE))
def test_probe_assigns_python_verdict(row: dict[str, Any]) -> None:
    """Python owns the verdict; only actionable gaps stage a pin."""
    expect = dict(row.get("expect") or {})
    rec = _run(row)
    assert rec.verdict == expect["verdict"]
    staged = cart_items(session_bag().get_or_create(str(row["id"])))
    if expect["verdict"] == "actionable":
        assert staged, "actionable gap must stage a pin"
        assert rec.prefill_tab() == "alias"
        payload = staged[0]["payload"]
        assert payload.get("evidence_refs"), "pins carry evidence_refs"
        sends = {b.send for b in rec.response.reply_buttons}
        assert sends == {"yes", "no"}
    elif expect["verdict"] in {"mapped", "leave_collision", "maker_lag"}:
        assert not staged, "only actionable gaps stage"
        assert rec.prefill_tab() == ""
        assert rec.response.reply_buttons == []
    else:
        assert not staged, "only actionable gaps stage"
        if "prefill_tab" in expect:
            assert rec.prefill_tab() == expect["prefill_tab"]


def test_probe_verdict_table_has_playbook_columns() -> None:
    rec = _run(_PROBE["probe_crypto_actionable"])
    for column in (
        "Verdict", "Sportsbook", "Catalogue / title", "Optic fixture",
        "Kickoff", "Mapped", "gap_reason", "Next step",
    ):
        assert column in rec.response.reply_markdown, column


def test_probe_unmapped_says_not_mapped() -> None:
    rec = _run(_PROBE["probe_expected_residual"])
    assert "We have not mapped this." in rec.response.reply_markdown


def test_probe_mapped_shows_market_mapping_rows() -> None:
    rec = _run(_PROBE["probe_mapped_in_market_mapping"])
    assert rec.verdict == "mapped"
    body = rec.response.reply_markdown
    assert "We have not mapped this." not in body
    assert "moneyline_3way" in body
    assert "**Fixture:** PSG vs Aston Villa" in body
    assert "Entity" in body
    assert rec.ui_action_types == []
    assert rec.response.reply_buttons == []


def _nav_paths(rec: Any) -> list[str]:
    return [str(a.get("path") or "") for a in rec.response.ui_actions if a.get("type") == "navigate"]


def test_probe_maker_lag_opens_coverage() -> None:
    rec = _run(_PROBE["probe_maker_lag"])
    body = rec.response.reply_markdown
    paths = _nav_paths(rec)
    assert rec.verdict == "maker_lag"
    assert paths == ["/coverage?league=atp&fixture=fx-sin-alc"]
    assert "**Map manually**" not in body
    assert "Unmapped" not in body
    assert "**Already mapped**" in body
    assert "Open **Coverage**" in body


def test_probe_crypto_tip_aliases_are_not_mapped() -> None:
    rec = _run(_PROBE["probe_crypto_maker_lag"])
    body = rec.response.reply_markdown
    paths = _nav_paths(rec)
    assert rec.verdict == "expected_residual"
    assert paths == ["/unmapped?league=wta"]
    assert "0 market_mapping rows" in body
    assert "Already mapped" not in body
    assert "`942505` → OSK8" in body
    assert "20260902A98210F7" in body


def test_probe_novig_unmapped_shows_snapshot() -> None:
    rec = _run(_PROBE["probe_novig_unmapped"])
    body = rec.response.reply_markdown
    assert rec.verdict == "expected_residual"
    assert _nav_paths(rec) == ["/unmapped?league=NBA"]
    assert "Novig" in body
    assert "Lakers vs Celtics" in body
    assert "20260828ABC" in body


def test_probe_poly_usa_symbol_is_not_an_alias() -> None:
    rec = _run(_PROBE["probe_poly_usa_unmapped"])
    body = rec.response.reply_markdown
    assert rec.path == "skill:probe_gap"
    assert rec.verdict == "expected_residual"
    assert "Alias suggestions" not in body
    assert "Polymarket (USA)" in body
    assert "benbon vs botzan" in body
    assert "`tennis_match_winner`" in body


def test_probe_poly_official_exact_score_is_residual() -> None:
    rec = _run(_PROBE["probe_poly_official_exact_score"])
    body = rec.response.reply_markdown
    assert rec.path == "skill:probe_gap"
    assert rec.verdict == "expected_residual"
    assert "add league" not in body.lower()
    assert "Alias suggestions" not in body
    assert "We have not mapped this." in body
    assert "Exact score is expected residual" in body
    assert "Do not pin" in body
    assert "**Map manually**" not in body
    assert rec.prefill_tab() == ""
    assert rec.response.reply_buttons == []
    assert _nav_paths(rec) == ["/unmapped?league=bun"]


def test_probe_unmapped_opens_unmapped() -> None:
    rec = _run(_PROBE["probe_expected_residual"])
    body = rec.response.reply_markdown
    assert rec.verdict == "expected_residual"
    assert _nav_paths(rec) == ["/unmapped?league=mlb"]
    assert rec.prefill_tab() == ""
    assert rec.response.reply_buttons == []
    assert "**Map manually**" in body
    assert "Open **Unmapped" in body


def test_onboard_needs_code_stops_without_staging() -> None:
    """No parser profile means engine work first — never stage a bad profile."""
    row = _ONBOARD["onboard_needs_code_stops"]
    rec = _run(row)
    assert rec.outcome == "needs_code"
    assert not cart_items(session_bag().get_or_create(str(row["id"])))
    assert rec.ui_action_types == []


@pytest.mark.parametrize(
    "row",
    [r for r in _ONBOARD.values() if "enabled_books" in (r.get("expect") or {})],
    ids=[r["id"] for r in _ONBOARD.values() if "enabled_books" in (r.get("expect") or {})],
)
def test_onboard_enables_only_evidenced_books(row: dict[str, Any]) -> None:
    expect = dict(row["expect"])
    rec = _run(row)
    assert rec.prefill_tab() == "league"
    exchanges = rec.prefill().get("exchanges") or []
    enabled = {e["sportsbook"] for e in exchanges if e.get("enabled")}
    assert enabled == set(expect["enabled_books"])
    if expect["enabled_books"]:
        staged = cart_items(session_bag().get_or_create(str(row["id"])))
        payload_books = {
            e["sportsbook"] for e in staged[0]["payload"]["exchanges"] if e.get("enabled")
        }
        assert payload_books == enabled, "cart and form must agree"


def test_market_rules_prefills_market_tab() -> None:
    rec = _run(_MARKET["market_named_book_moneyline"])
    assert rec.prefill_tab() == "market"
    assert rec.prefill().get("league") == "atp"
    assert rec.prefill().get("sportsbook") == "px"
    assert rec.prefill().get("canonical_market_type")
    assert rec.prefill().get("action") == "map"


def test_market_rules_ignore_flip_still_asks() -> None:
    """Flipping an ignored tip rule to mapped needs an explicit yes."""
    rec = _run(_MARKET["market_ignore_flip_still_asks"])
    assert rec.outcome == "ask_slot"
    assert {b.send for b in rec.response.reply_buttons} == {"yes", "no"}


def test_market_poly_us_football_needs_code_does_not_stage() -> None:
    """Parser gap is needs_code — never a Proposed card, even without nfl on tip."""
    rec = _run(_MARKET["market_poly_us_football_needs_code"])
    assert rec.outcome == "needs_code"
    assert rec.path == "skill:market_rules"
    assert not cart_items(session_bag().get_or_create("market_poly_us_football_needs_code"))
    assert rec.prefill_tab() == ""
    assert rec.response.reply_buttons == []
    body = rec.response.reply_markdown.lower()
    assert "parser" in body or "needs_code" in body
    assert "card" in body


def test_entity_raphinha_opens_editor_not_onboard() -> None:
    rec = _run(_LOOKUP["lookup_add_raphinha_not_onboard"])
    assert rec.path == "skill:entity_add"
    assert rec.prefill_tab() == "alias"
    assert rec.prefill().get("entity_name", "").lower() == "raphinha"
    assert rec.prefill().get("entity_type") == "player"
    assert "add league" not in rec.response.reply_markdown.lower()
    assert not cart_items(session_bag().get_or_create("lookup_add_raphinha_not_onboard"))


def test_optic_name_unique_bind_stages_cart() -> None:
    rec = _run(_LOOKUP["lookup_optic_name_unique_stages"])
    assert rec.path == "skill:entity_add"
    staged = cart_items(session_bag().get_or_create("lookup_optic_name_unique_stages"))
    assert staged
    alias = (staged[0]["payload"].get("aliases") or [{}])[0]
    assert alias.get("sportsbook") == "optic"
    assert alias.get("alias_value") == "oid-rune"
    assert rec.prefill().get("entity_name") == "Holger Rune"
    assert {b.send for b in rec.response.reply_buttons} == {"yes", "no"}


def test_each_skill_owns_a_small_scoped_toolset() -> None:
    """No generic buffet: every skill declares at most five real schemas."""
    schema_names = {row["name"] for row in TOOL_SCHEMAS}
    for skill in SKILLS:
        tools = tuple(skill.TOOLS)
        assert set(tools) <= schema_names, f"{skill.NAME} names a tool with no schema"
        assert len(tools) <= MAX_TOOLS, f"{skill.NAME} exposes {len(tools)} tools"
        assert set(ALWAYS_TOOLS) <= set(tools), f"{skill.NAME} cannot see the console"
        assert len(ChatToolContext.scoped_schemas(tools)) == len(tools)


def test_retired_tools_are_not_dispatchable() -> None:
    """The plan removes these; leaving them in _dispatch keeps them reachable."""
    tools = ChatToolContext(InMemoryStore(environment="test", allow_activate=True))
    for retired in (
        "bq_lookup_entities",
        "bq_lookup_leagues",
        "bq_lookup_market_rules",
        "bq_parity",
        "bq_tip",
        "offer_pin",
        "probe_crypto_symbol",
        "probe_kalshi_gap",
        "probe_kalshi_market",
        "probe_live_seen",
        "probe_optic_competitor",
        "probe_optic_fixture",
    ):
        assert tools.run(retired, {}).get("error") == f"unknown_tool:{retired}"


def test_no_skill_exposes_a_destructive_action() -> None:
    every = [
        *_LOOKUP.values(),
        *_PROBE.values(),
        *_ONBOARD.values(),
        *_MARKET.values(),
        *load_fixture("safety.yaml"),
    ]
    for row in every:
        session_bag().clear()
        rec = _run(row)
        types = set(rec.ui_action_types)
        assert types <= {"navigate", "switch_tab", "prefill_form", "rules_filter", "cart_add"}, types

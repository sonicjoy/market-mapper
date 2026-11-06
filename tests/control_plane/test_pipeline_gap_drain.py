"""Gap-propose drain worker, checker, yield, and ledger cursor."""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mappers.control_plane import pipeline_gap_card as gap_card
from mappers.control_plane import pipeline_gap_k8s as gap_k8s
from mappers.control_plane.gap_fix import propose_gap_pins
from mappers.control_plane.gap_inventory import RfqGapItem, diversify_probe_items
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL
from mappers.control_plane.gap_ledger import (
    build_outcomes,
    ledger_inventory_sql_suffix,
    load_terminal_keys,
)
from mappers.control_plane.pipeline_gap_drain import (
    run_checker,
    run_one_card_cli,
    run_plan_cli,
    run_worker,
)
from mappers.control_plane.pipeline_gap_k8s import _cronjob_container_image
from mappers.control_plane.pipeline_gap_merge import alert_needs_code_skips, alias_keys_from_payload
from mappers.control_plane.pipeline_gap_propose import (
    PIPELINE_ACTOR,
    PIPELINE_NOTE,
    pipeline_note_for_league,
)
from mappers.control_plane.pipeline_gap_yield import harvest_should_yield, make_yield_checker
from mappers.control_plane.rfq_platforms import (
    fetch_unknown_mapping_failure_platforms,
    unknown_mapping_failure_platforms_sql,
)
from mappers.control_plane.service import ProposalService
from tests.control_plane.test_pipeline_gap_propose import _pin, _soccer_store


def test_inventory_sql_has_no_per_series_hard_cap() -> None:
    assert "partition by regexp_extract" not in RFQ_INVENTORY_SQL
    assert "{per_bucket}" not in RFQ_INVENTORY_SQL
    assert "{ledger_cte}" in RFQ_INVENTORY_SQL
    assert "ledger_exclude" in RFQ_INVENTORY_SQL


def test_close_kickoff_filter_is_where_not_bare_qualify() -> None:
    """QUALIFY without a window function is a BigQuery 400."""
    lowered = RFQ_INVENTORY_SQL.lower()
    assert "qualify kickoff is not null" not in lowered
    assert lowered.count("where kickoff is not null") == 2


def test_diversify_still_orders_overflow_after_per_bucket() -> None:
    tennis = [RfqGapItem("crypto", f"NX.F.OPT.TENNIS-{i}", 100 - i) for i in range(20)]
    fifa = [RfqGapItem("crypto", f"NX.F.OPT.FIFA-{i}", 50 - i) for i in range(4)]
    mixed = diversify_probe_items(tennis + fifa, probe_limit=8, per_bucket=3)
    assert len(mixed) == 8
    assert any("FIFA" in item.key for item in mixed)


def test_yield_checker_stops_at_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_YIELD_RATIO", "0.75")
    ratios = iter([0.5, 0.76])

    def ratio_fn() -> float:
        return next(ratios)

    check = make_yield_checker(ratio_fn=ratio_fn)
    assert check() is False
    assert check() is True


def test_walker_leaves_tail_not_walked() -> None:
    inventory = [
        RfqGapItem("kalshi", "KXITF-1", 1),
        RfqGapItem("kalshi", "KXITF-2", 1),
    ]
    outcomes = build_outcomes(
        inventory,
        [],
        [],
        walked_keys={("kalshi", "KXITF-1")},
    )
    by = {(o.book, o.key): o.outcome for o in outcomes}
    assert by[("kalshi", "KXITF-1")] == "skipped"
    assert by[("kalshi", "KXITF-2")] == "not_walked"


def test_needs_code_alert_and_ledger_outcome() -> None:
    publisher = MagicMock()
    skipped = [{"book": "kalshi", "key": "KX-1", "reason": "needs_code"}]
    alert_needs_code_skips(publisher, skipped)
    publisher.publish.assert_called_once()
    _severity, text = publisher.publish.call_args.args
    assert _severity == "warning"
    assert "needs_code" in text
    outcomes = build_outcomes(
        [RfqGapItem("kalshi", "KX-1", 5)],
        [],
        skipped,
        walked_keys={("kalshi", "KX-1")},
    )
    assert outcomes[0].outcome == "needs_code"


def test_load_terminal_keys_excludes_from_page() -> None:
    captured: list[str] = []

    def query_fn(sql: str) -> list:
        captured.append(sql)
        return [type("Row", (), {"book": "crypto", "key": "NX-1"})()]

    keys = load_terminal_keys("tip_abc", project="marketmaking-test", query_fn=query_fn)
    assert keys == {("crypto", "NX-1")}
    assert "ledger_reopen" in captured[0]


def test_reopen_lifts_only_rows_written_before_it() -> None:
    """A reopened league is walked once; that walk's rows are ignored again."""
    cte, _pred = ledger_inventory_sql_suffix(project="p", enabled=True)
    flat = " ".join(cte.split())
    assert "max(run_at) as reopened_at" in flat
    assert "r.reopened_at > l.run_at" in flat
    assert "@tip" not in flat


def _activated(payload: dict[str, Any], *, subject: str, note: str = "") -> Any:
    from mappers.control_plane.models import BatchChangesPayload, ProposalRecord

    return ProposalRecord(
        proposal_id="p1",
        request_id="r1",
        status="activated",
        expected_rule_set_id="tip",
        artifact_type="batch_changes",
        summary="s",
        evidence_refs=[f"note:{note}"] if note else [],
        work_item_id=None,
        payload=BatchChangesPayload.model_validate(payload),
        proposer_subject=subject,
    )


def test_console_alias_activation_reopens_its_league() -> None:
    from mappers.control_plane.pipeline_gap_propose import reopen_leagues_from_proposal

    alias = {
        "kind": "entity_alias",
        "league": "epl",
        "canonical_key": "ARS",
        "aliases": [{"sportsbook": "kalshi", "alias_value": "ARS", "alias_kind": "code"}],
    }
    proposal = _activated({"kind": "batch_changes", "entity_aliases": [alias]}, subject="joe@console")
    assert reopen_leagues_from_proposal(proposal) == {"epl"}


def test_league_row_activation_also_reopens_unknown() -> None:
    from mappers.control_plane.pipeline_gap_propose import reopen_leagues_from_proposal

    league = {
        "kind": "mapping_league",
        "league": "atp",
        "sport": "tennis",
        "optic_league_id": "atp",
        "exchanges": [],
    }
    proposal = _activated(
        {"kind": "batch_changes", "leagues": [league]},
        subject="pipeline-gap-fix",
        note="pipeline gap-fix · unknown",
    )
    assert reopen_leagues_from_proposal(proposal) == {"atp", "unknown"}


_DRAIN = "mappers.control_plane.pipeline_gap_drain"
_CARD = {"league": "nfl", "items": [{"book": "kalshi", "key": "KXNFLGAME-1", "demand": 3}]}


def _worker(
    plans: list[list[dict[str, Any]]],
    waves: list[list[dict[str, Any]]],
    *,
    handoff: str | None = None,
) -> tuple[int, MagicMock, MagicMock]:
    publisher = MagicMock()
    with patch(f"{_DRAIN}._plan", side_effect=plans), patch(
        f"{_DRAIN}._run_wave", side_effect=waves,
    ) as run_wave, patch(
        f"{_DRAIN}.hand_off_to_deployed_image", return_value=handoff,
    ), patch(f"{_DRAIN}.build_gap_propose_publisher", return_value=publisher):
        code = run_worker(use_subprocess=False)
    return code, publisher, run_wave


def test_idle_page_publishes_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    code, publisher, run_wave = _worker([[]], [])
    assert code == 0
    run_wave.assert_not_called()
    severity, text = publisher.publish.call_args_list[0].args
    assert severity == "info"
    assert "idle" in text


def test_proposed_review_is_progress_and_does_not_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A submitted Review card is progress. Missing progress stalled after two waves."""
    from mappers.control_plane.pipeline_gap_propose import _proposed_review

    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    pins = [{"kind": "entity_alias"}]
    card = _proposed_review(
        MagicMock(),
        pins,
        0,
        pins,
        {"ok": True, "review": {"ref": "abc"}, "count": 1},
        "test",
        None,
    )
    assert card["progress"] is True
    code, publisher, _run = _worker([[_CARD], [_CARD], []], [[card], [dict(card)]])
    assert code == 0
    severities = [call.args[0] for call in publisher.publish.call_args_list]
    assert "critical" not in severities
    texts = [call.args[1] for call in publisher.publish.call_args_list]
    assert any("proposed=2" in text for text in texts)


def test_blocked_verify_still_progresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    code, _pub, _run = _worker(
        [[_CARD], []],
        [[{"ok": False, "action": "blocked", "progress": True}]],
    )
    assert code == 0


def test_two_waves_without_progress_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    dead = [{"ok": True, "action": "skip", "progress": False}]
    code, publisher, _run = _worker([[_CARD], [_CARD]], [dead, dead])
    assert code == 1
    assert publisher.publish.call_args_list[0].args[0] == "critical"


def test_one_progressing_league_keeps_the_wave_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    mixed = [
        {"ok": True, "action": "skip", "progress": False},
        {"ok": True, "action": "proposed", "progress": True},
    ]
    code, _pub, _run = _worker([[_CARD, _CARD], [_CARD, _CARD], []], [mixed, mixed])
    assert code == 0


def test_plan_failure_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    code, publisher, run_wave = _worker([None], [])  # type: ignore[list-item]
    assert code == 1
    run_wave.assert_not_called()
    assert publisher.publish.call_args_list[0].args[0] == "warning"


def test_checker_skips_when_worker_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    with patch(
        "mappers.control_plane.pipeline_gap_drain.worker_job_running",
        return_value=True,
    ), patch("mappers.control_plane.pipeline_gap_drain.create_worker_job") as create:
        assert run_checker() == 0
        create.assert_not_called()


def test_one_card_reads_card_and_emits_json_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    with patch(
        f"{_DRAIN}.run_league_card",
        return_value={"ok": True, "action": "proposed", "progress": True, "league": "nfl"},
    ) as run_card, patch(
        f"{_DRAIN}.build_pipeline_service",
        return_value=(MagicMock(), "test"),
    ), patch(
        f"{_DRAIN}.build_gap_propose_publisher",
        return_value=MagicMock(),
    ):
        assert run_one_card_cli(io.StringIO(json.dumps(_CARD))) == 0
    assert run_card.call_args.args[1] == _CARD
    out = capsys.readouterr().out
    payload = json.loads(out.strip().split("=", 1)[1])
    assert payload["action"] == "proposed"
    assert payload["league"] == "nfl"


def test_plan_cli_prints_every_card(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    cards = [_CARD, {"league": "unknown", "items": []}]
    with patch(f"{_DRAIN}.plan_wave", return_value=cards), patch(
        f"{_DRAIN}.build_pipeline_service", return_value=(MagicMock(), "test"),
    ):
        assert run_plan_cli() == 0
    out = capsys.readouterr().out
    assert json.loads(out.strip().removeprefix("GAP_DRAIN_PLAN=")) == {"cards": cards}


def test_harvest_should_yield_default_threshold() -> None:
    assert harvest_should_yield(ratio_fn=lambda: 0.74) is False
    assert harvest_should_yield(ratio_fn=lambda: 0.75) is True


def test_skipped_and_needs_probe_are_terminal() -> None:
    from mappers.control_plane.gap_ledger import TERMINAL_OUTCOMES

    assert "skipped" in TERMINAL_OUTCOMES
    assert "needs_probe" in TERMINAL_OUTCOMES
    assert "not_walked" not in TERMINAL_OUTCOMES


class _TipRow:
    def __init__(self, league: str, exchanges: list[dict[str, Any]]) -> None:
        self.league = league
        self.exchanges = exchanges
        self.tombstone = False


class _TipStore:
    current_rule_set_id = "tip"

    def __init__(self, *rows: _TipRow) -> None:
        self._rows = list(rows)

    def leagues_for(self, _rid: str) -> list[_TipRow]:
        return self._rows


_NFL = _TipRow("nfl", [
    {"sportsbook": "polymarket", "enabled": True, "settings": {"slug_prefix": "nfl"}},
    {"sportsbook": "novig", "settings": {"league": "NFL"}},
    {"sportsbook": "px", "source_league_id": "31", "settings": {"tournament_id": "31"}},
    {"sportsbook": "huddle", "source_league_id": "nfl-comp"},
])
_EPL = _TipRow("epl", [
    {"sportsbook": "polymarket", "enabled": True, "settings": {"slug_prefix": "epl"}},
    {"sportsbook": "novig", "source_league_id": "EPL"},
])


def _looked_up(book: str, key: str, demand: int, token: str) -> RfqGapItem:
    return RfqGapItem(book, key, demand, {"league_token": token})


def _cards(store: Any, items: list[RfqGapItem], seats: int = 100) -> dict[str, set[str]]:
    from mappers.control_plane.pipeline_gap_batch import plan_league_cards

    return {
        league: {item.key for item in seated}
        for league, seated in plan_league_cards(store, items, seats=seats)
    }


def test_plan_makes_one_card_per_league_and_unknown() -> None:
    items = [
        RfqGapItem("polymarket", "epl", 40),
        _looked_up("novig", "uuid-epl", 8, "EPL"),
        RfqGapItem("polymarket", "nfl", 10),
        _looked_up("novig", "uuid-atp", 1, "ATP"),
        RfqGapItem("novig", "uuid-no-lookup", 1),
        RfqGapItem("polymarket", "lol", 1),
    ]
    cards = _cards(_TipStore(_EPL, _NFL), items)
    assert cards == {
        "epl": {"epl", "uuid-epl"},
        "nfl": {"nfl"},
        "unknown": {"uuid-atp", "uuid-no-lookup", "lol"},
    }


def test_plan_orders_leagues_by_seated_demand() -> None:
    from mappers.control_plane.pipeline_gap_batch import plan_league_cards

    items = [
        RfqGapItem("polymarket", "nfl", 10),
        RfqGapItem("polymarket", "epl", 50),
        RfqGapItem("polymarket", "zzz", 5),
    ]
    order = [league for league, _ in plan_league_cards(_TipStore(_EPL, _NFL), items)]
    assert order == ["epl", "nfl", "unknown"]


def test_attach_league_tokens_resolves_novig_and_prophetx() -> None:
    from mappers.control_plane.gap_inventory_league import attach_league_tokens

    asked: dict[str, list[str]] = {}

    def lookup(book: str, ids: list[str]) -> dict[str, dict[str, str]]:
        asked[book] = ids
        return {
            "uuid-nfl": {"league": "NFL", "optic_league_id": "nfl"},
            "1700008766": {"league": "31"},
        }

    items = [
        RfqGapItem("novig", "uuid-nfl", 3),
        RfqGapItem("novig", "uuid-gone", 1),
        RfqGapItem("prophetx", "1700008766:line", 2, {"px_event_id": "1700008766"}),
        RfqGapItem("kalshi", "KXNFLGAME-1", 9),
    ]
    out = attach_league_tokens(items, lookup_fn=lookup)
    assert asked == {"novig": ["uuid-gone", "uuid-nfl"], "prophetx": ["1700008766"]}
    tokens = {item.key: (item.meta or {}).get("league_token") for item in out}
    assert tokens == {
        "uuid-nfl": "NFL", "uuid-gone": None, "1700008766:line": "31", "KXNFLGAME-1": None,
    }
    assert out[2].meta == {"px_event_id": "1700008766", "league_token": "31"}
    assert out[0].meta == {"league_token": "NFL", "optic_league_id": "nfl"}


def test_failed_league_lookup_leaves_keys_unknown() -> None:
    from mappers.control_plane.gap_inventory_league import attach_league_tokens

    def boom(_book: str, _ids: list[str]) -> dict[str, dict[str, str]]:
        raise RuntimeError("bq down")

    items = [RfqGapItem("novig", "uuid-nfl", 3)]
    out = attach_league_tokens(items, lookup_fn=boom)
    assert _cards(_TipStore(_NFL), out) == {"unknown": {"uuid-nfl"}}


def test_slug_not_on_tip_is_unknown() -> None:
    """Static venue maps know ``atp``; the tip does not, so the key is unknown."""
    items = [RfqGapItem("underdog", "UDXATPMATCHWIN_X_Y", 3)]
    assert _cards(_TipStore(_NFL), items) == {"unknown": {"UDXATPMATCHWIN_X_Y"}}


def test_seats_split_evenly_and_pass_unused_seats_on() -> None:
    from mappers.control_plane.pipeline_gap_batch import seat_items

    items = [RfqGapItem("kalshi", f"K{i}", 1000 - i) for i in range(400)]
    items += [RfqGapItem("underdog", f"U{i}", 500 - i) for i in range(30)]
    items += [RfqGapItem("novig", f"N{i}", 100 - i) for i in range(5)]
    items += [RfqGapItem("polymarket", "nfl", 9)]
    seated = seat_items(items, 100)
    by_book = {book: [i for i in seated if i.book == book] for book in ("kalshi", "underdog", "novig", "polymarket")}
    assert len(seated) == 100
    assert {book: len(rows) for book, rows in by_book.items()} == {
        "kalshi": 64, "underdog": 30, "novig": 5, "polymarket": 1,
    }
    assert [i.key for i in by_book["kalshi"]] == [f"K{i}" for i in range(64)]


def test_seats_keep_highest_demand_books_when_seats_are_scarce() -> None:
    from mappers.control_plane.pipeline_gap_batch import seat_items

    items = [
        RfqGapItem("kalshi", "K", 9),
        RfqGapItem("novig", "N", 5),
        RfqGapItem("dkex", "D", 1),
    ]
    assert [i.key for i in seat_items(items, 2)] == ["K", "N"]


def test_league_card_includes_every_platform_with_a_gap(tmp_path, monkeypatch) -> None:
    # A DKEX key's league comes from its typed catalogue row, not the ticker.
    (tmp_path / "dkex_markets.jsonl").write_text(
        json.dumps({"symbol": "NFL-ML-FG-ABCDEFGHIJ", "sub_topic": "NFL"}) + "\n")
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    items = [
        RfqGapItem("polymarket", "nfl", 4),
        _looked_up("novig", "uuid-nfl", 3, "NFL"),
        _looked_up("prophetx", "1700008766:line", 2, "31"),
        RfqGapItem("underdog", "UDXNFLGAMEWIN_X_Y", 8),
        RfqGapItem("dkex", "NFL-ML-FG-ABCDEFGHIJ", 7),
        RfqGapItem("huddle", "selection-9", 6),
        RfqGapItem("underdog", "UDXATPFOO_X_Y", 1),
    ]
    from mappers.control_plane.pipeline_gap_batch import plan_league_cards

    cards = dict(plan_league_cards(_TipStore(_NFL), items))
    assert {item.book for item in cards["nfl"]} == {
        "polymarket", "novig", "prophetx", "underdog", "dkex", "huddle",
    }
    assert {item.key for item in cards["unknown"]} == {"UDXATPFOO_X_Y"}


def _optic_row(slug: str, optic_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        league=slug, optic_league_id=optic_id, extra_optic_league_ids=[],
        enabled=True, tombstone=False, fixture_horizon_hours=96.0,
    )


def test_tip_optic_keys_limits_to_card_league() -> None:
    from mappers.control_plane.gap_optic_cache import tip_optic_keys

    store = _TipStore()
    store._rows = [_optic_row("nfl", "nfl"), _optic_row("epl", "england_-_premier_league")]  # type: ignore[list-item]
    assert [oid for oid, _ in tip_optic_keys(store, frozenset({"nfl"}))] == ["nfl"]
    assert tip_optic_keys(store, frozenset()) == []
    assert len(tip_optic_keys(store)) == 2


@pytest.mark.parametrize(
    ("card_league", "expected"),
    [("nfl", frozenset({"nfl"})), ("unknown", frozenset()), ("", None)],
)
def test_drain_card_warms_only_its_league(
    monkeypatch: pytest.MonkeyPatch, card_league: str, expected: frozenset[str] | None,
) -> None:
    from mappers.control_plane import gap_fix

    warmed: list[Any] = []
    monkeypatch.setattr(gap_fix, "warm_optic_cache", lambda _s, leagues=None: warmed.append(leagues))
    gap_fix._warm_live_sources(MagicMock(), [], None, None, card_league)
    assert warmed == [expected]


def test_drain_card_ledger_uses_card_league_and_skips_platform_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mappers.control_plane import pipeline_gap_propose as propose

    written: list[Any] = []

    def no_scan() -> list[Any]:
        raise AssertionError("drain cards must not rescan unknown platforms")

    monkeypatch.setattr(propose, "fetch_unknown_mapping_failure_platforms", no_scan)
    monkeypatch.setattr(propose, "write_ledger", lambda outcomes, **_k: written.extend(outcomes))
    monkeypatch.setenv("MAPPING_GAP_LEDGER", "1")
    harvested = {
        "inventory": [{"book": "novig", "key": "uuid-nfl", "demand": 3}],
        "walked_keys": [["novig", "uuid-nfl"]],
        "card_league": "nfl",
    }
    propose._record_gap_ledger("tip", harvested, [], [], store=MagicMock())
    assert [(o.key, o.outcome, o.league_token) for o in written] == [("uuid-nfl", "skipped", "nfl")]


def test_plan_wave_scans_unknown_platforms_once(monkeypatch: pytest.MonkeyPatch) -> None:
    scans: list[Any] = []
    monkeypatch.setattr(gap_card, "fetch_rfq_inventory", lambda *_a, **_k: [RfqGapItem("kalshi", "KXZZZ-1", 1)])
    monkeypatch.setattr(gap_card, "gap_keys_on_open_review", lambda _s: set())
    monkeypatch.setattr(gap_card, "attach_league_tokens", lambda items: items)
    monkeypatch.setattr(gap_card, "record_unknown_platforms", scans.append)
    service = MagicMock()
    service.store = _TipStore(_NFL)
    cards = gap_card.plan_wave(service)
    assert scans == ["tip"]
    assert [card["league"] for card in cards] == ["unknown"]


def test_card_without_new_pins_does_not_propose(monkeypatch: pytest.MonkeyPatch) -> None:
    """Walked keys still hit the ledger; no Review card when nothing new was drafted."""
    ledgered: list[Any] = []
    monkeypatch.setattr(gap_card, "_ledger_card", lambda *a: ledgered.append(a))
    service = MagicMock()
    service.list_proposals.return_value = []

    def never(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise AssertionError("propose must not run without new pins")

    result = gap_card._drain_propose(
        service,
        {"pins": [], "skipped": [{"book": "underdog", "key": "U", "reason": "needs_probe"}], "progress": True},
        actor=PIPELINE_ACTOR,
        publisher=None,
        propose_fn=never,
        environment="test",
        console_base=None,
    )
    assert result["action"] == "skip"
    assert len(ledgered) == 1


def test_blocked_card_records_the_gate_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused card stores the gate text on the pins that failed, not a blanket label."""
    ledgered: list[Any] = []
    monkeypatch.setattr(gap_card, "_ledger_card", lambda *a: ledgered.append(a))
    service = MagicMock()
    service.list_proposals.return_value = []
    pin = {
        "kind": "entity_alias",
        "league": "conl",
        "canonical_key": "HOME",
        "aliases": [{"sportsbook": "crypto", "alias_kind": "code", "alias_value": "CONL"}],
        "harvest_book": "crypto",
        "harvest_key": "NX.F.OPT.CONL-1",
    }
    gap_card._drain_propose(
        service,
        {"pins": [pin], "skipped": [], "progress": True},
        actor=PIPELINE_ACTOR,
        publisher=None,
        propose_fn=lambda *_a, **_k: {
            "ok": False,
            "blockers": ["CONL home name does not fit the Optic side"],
        },
        environment="test",
        console_base=None,
    )
    skips = ledgered[0][3]
    assert skips[0]["key"] == "NX.F.OPT.CONL-1"
    assert skips[0]["reason"] == "CONL home name does not fit the Optic side"


def test_run_league_card_harvests_exactly_the_seated_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def harvest(_store: Any, **kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {"pins": [], "skipped": [], "walked_keys": [], "card_league": kw["card_league"]}

    monkeypatch.setattr(gap_card, "harvest_gap_pins", harvest)
    monkeypatch.setattr(gap_card, "_ledger_card", lambda *a: None)
    service = MagicMock()
    service.list_proposals.return_value = []
    result = gap_card.run_league_card(service, _CARD, propose_fn=MagicMock())
    assert seen["drain"] is True
    assert seen["card_league"] == "nfl"
    assert seen["inventory_fn"]() == [RfqGapItem("kalshi", "KXNFLGAME-1", 3, {})]
    assert result["league"] == "nfl"
    assert result["action"] == "skip"


def test_failed_job_is_not_active() -> None:
    from mappers.control_plane.pipeline_gap_k8s import job_is_active

    assert job_is_active({"conditions": [{"type": "Failed", "status": "True"}]}) is False
    assert job_is_active({"active": 1}) is True
    assert job_is_active({}) is True


def test_checker_does_not_create_when_list_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    with patch(
        "mappers.control_plane.pipeline_gap_drain.worker_job_running",
        return_value=None,
    ), patch("mappers.control_plane.pipeline_gap_drain.create_worker_job") as create:
        assert run_checker() == 0
        create.assert_not_called()


def _fake_children(cards: list[dict[str, Any]]) -> Any:
    """subprocess.run stub: first plan returns ``cards``, later plans are idle."""
    plans = iter([cards])

    def run(argv: list[str], **kwargs: Any) -> MagicMock:
        if argv[-1] == "plan":
            body = {"cards": next(plans, [])}
            return MagicMock(stdout=f"GAP_DRAIN_PLAN={json.dumps(body)}\n", returncode=0)
        card = json.loads(kwargs["input"])
        result = {"ok": True, "action": "proposed", "progress": True, "league": card["league"]}
        return MagicMock(stdout=f"GAP_DRAIN_RESULT={json.dumps(result)}\n", returncode=0)

    return run


def test_worker_runs_every_league_of_the_wave_as_its_own_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    monkeypatch.setenv("MAPPING_GAP_DRAIN_POOL", "2")
    monkeypatch.delenv("MAPPING_GAP_DRAIN_INPROCESS", raising=False)
    cards = [{"league": slug, "items": []} for slug in ("nfl", "epl", "unknown")]
    publisher = MagicMock()
    with patch(f"{_DRAIN}.subprocess.run", side_effect=_fake_children(cards)) as run, patch(
        f"{_DRAIN}.hand_off_to_deployed_image", return_value=None,
    ), patch(f"{_DRAIN}.build_gap_propose_publisher", return_value=publisher):
        assert run_worker() == 0
    roles = [call.args[0][-2:] for call in run.call_args_list]
    assert roles.count(["--role", "plan"]) == 2
    assert roles.count(["--role", "one-card"]) == 3
    leagues = sorted(
        json.loads(call.kwargs["input"])["league"]
        for call in run.call_args_list
        if call.args[0][-1] == "one-card"
    )
    assert leagues == ["epl", "nfl", "unknown"]
    kwargs = run.call_args_list[1].kwargs
    assert kwargs["stdout"] is subprocess.PIPE
    assert "stderr" not in kwargs
    assert "capture_output" not in kwargs
    texts = [call.args[1] for call in publisher.publish.call_args_list]
    assert any("proposed=3" in text for text in texts)


def test_child_without_result_line_is_subprocess_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from mappers.control_plane.pipeline_gap_drain import _run_card_child

    with patch(f"{_DRAIN}.subprocess.run", return_value=MagicMock(stdout="", returncode=137)):
        result = _run_card_child(_CARD)
    assert result == {"action": "subprocess_error", "progress": False, "league": "nfl"}


def test_propose_noop_counts_as_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Noop writes maker_lag ledger rows, so the next card sees fewer keys."""
    ledgered: list[list[dict[str, str]]] = []

    def record(_service: Any, _harvested: Any, _pins: Any, skipped: Any) -> None:
        ledgered.append(list(skipped))

    monkeypatch.setattr(gap_card, "_ledger_card", record)
    service = MagicMock()
    service.list_proposals.return_value = []
    pin = {
        "kind": "entity_alias",
        "league": "epl",
        "canonical_key": "ARS",
        "aliases": [{"sportsbook": "kalshi", "alias_value": "ARS", "alias_kind": "code"}],
        "harvest_book": "kalshi",
        "harvest_key": "KXEPLGAME-1",
    }
    result = gap_card._drain_propose(
        service,
        {"pins": [pin], "skipped": []},
        actor=PIPELINE_ACTOR,
        publisher=None,
        propose_fn=lambda *_a, **_k: {"ok": True, "noop": True},
        environment="test",
        console_base=None,
    )
    assert result["action"] == "skip"
    assert result["progress"] is True
    assert ledgered == [[{"book": "kalshi", "key": "KXEPLGAME-1", "reason": "already_mapped"}]]


def test_drain_folds_a_later_wave_into_the_open_league_card() -> None:
    """A pin note before the harvest note must not split the league's card."""
    svc = ProposalService(_soccer_store())
    note = pipeline_note_for_league("la_liga")
    for value in ("a", "b"):
        pin = _pin(value)
        pin["evidence_refs"] = ["note:SVA belongs to Zachary"]
        propose_gap_pins(svc, PIPELINE_ACTOR, [pin], acknowledge_shadow=True, note=note)
    assert len(_pipeline_open(svc)) == 2
    result = gap_card._drain_propose(
        svc,
        {"pins": [_pin("c")], "skipped": [], "card_league": "la_liga", "progress": True},
        actor=PIPELINE_ACTOR,
        publisher=None,
        propose_fn=propose_gap_pins,
        environment="test",
        console_base=None,
    )
    assert result["action"] == "proposed"
    open_props = _pipeline_open(svc)
    assert len(open_props) == 1
    assert alias_keys_from_payload(open_props[0].payload) == frozenset({
        ("la_liga", "VAL", "a"),
        ("la_liga", "VAL", "b"),
        ("la_liga", "VAL", "c"),
    })


def test_drain_collapses_sibling_cards_when_the_wave_adds_nothing() -> None:
    svc = ProposalService(_soccer_store())
    note = pipeline_note_for_league("la_liga")
    for value in ("a", "b"):
        propose_gap_pins(svc, PIPELINE_ACTOR, [_pin(value)], acknowledge_shadow=True, note=note)
    result = gap_card._drain_propose(
        svc,
        {"pins": [], "skipped": [], "card_league": "la_liga"},
        actor=PIPELINE_ACTOR,
        publisher=None,
        propose_fn=propose_gap_pins,
        environment="test",
        console_base=None,
    )
    assert result["action"] == "proposed"
    open_props = _pipeline_open(svc)
    assert len(open_props) == 1
    assert alias_keys_from_payload(open_props[0].payload) == frozenset({
        ("la_liga", "VAL", "a"),
        ("la_liga", "VAL", "b"),
    })


def _drain_la_liga(svc: Any, pins: list[dict[str, Any]], propose_fn: Any = propose_gap_pins) -> dict[str, Any]:
    return gap_card._drain_propose(
        svc,
        {"pins": pins, "skipped": [], "card_league": "la_liga", "progress": True},
        actor=PIPELINE_ACTOR,
        publisher=None,
        propose_fn=propose_fn,
        environment="test",
        console_base=None,
    )


def _open_la_liga_card(svc: Any, value: str, note: str | None = None) -> str:
    propose_gap_pins(
        svc, PIPELINE_ACTOR, [_pin(value)], acknowledge_shadow=True,
        note=note or pipeline_note_for_league("la_liga"),
    )
    return _pipeline_open(svc)[-1].proposal_id


def test_drain_starts_a_new_card_when_the_fold_would_pass_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gap_card, "CARD_PIN_CAP", 1)
    svc = ProposalService(_soccer_store())
    first = _open_la_liga_card(svc, "a")
    result = _drain_la_liga(svc, [_pin("c")])
    assert result["action"] == "proposed"
    by_id = {p.proposal_id: p for p in _pipeline_open(svc)}
    assert len(by_id) == 2
    assert alias_keys_from_payload(by_id[first].payload) == frozenset({("la_liga", "VAL", "a")})


def test_blocked_fold_proposes_the_new_pins_alone() -> None:
    svc = ProposalService(_soccer_store())
    _open_la_liga_card(svc, "a")
    calls: list[tuple[list[str], str | None]] = []

    def propose_fn(_svc: Any, _actor: Any, pins: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        values = sorted(a["alias_value"] for pin in pins for a in pin["aliases"])
        calls.append((values, kw.get("existing_proposal_id")))
        if kw.get("existing_proposal_id"):
            return {"ok": False, "blockers": ["stale pin a"]}
        return {"ok": True, "review": {"ref": "new"}, "count": len(pins)}

    result = _drain_la_liga(svc, [_pin("c")], propose_fn=propose_fn)
    assert result["action"] == "proposed"
    assert calls[1] == (["c"], None)
    assert calls[0][0] == ["a", "c"]


def test_drain_leaves_another_leagues_card_alone() -> None:
    svc = ProposalService(_soccer_store())
    epl = _open_la_liga_card(svc, "a", note=pipeline_note_for_league("epl"))
    _drain_la_liga(svc, [_pin("c")])
    by_id = {p.proposal_id: p for p in _pipeline_open(svc)}
    assert len(by_id) == 2
    assert alias_keys_from_payload(by_id[epl].payload) == frozenset({("la_liga", "VAL", "a")})


def test_drain_folds_an_unnoted_card_by_its_payload_league() -> None:
    svc = ProposalService(_soccer_store())
    _open_la_liga_card(svc, "a", note=PIPELINE_NOTE)
    _drain_la_liga(svc, [_pin("c")])
    open_props = _pipeline_open(svc)
    assert len(open_props) == 1
    assert alias_keys_from_payload(open_props[0].payload) == frozenset({
        ("la_liga", "VAL", "a"),
        ("la_liga", "VAL", "c"),
    })


def _pipeline_open(svc: Any) -> list[Any]:
    return [
        proposal
        for proposal in svc.list_proposals()
        if proposal.status in {"proposed", "validated"}
        and proposal.proposer_subject == PIPELINE_ACTOR.subject
    ]


def test_unknown_platform_sql_renders_project() -> None:
    sql = unknown_mapping_failure_platforms_sql(project="marketmaking-test")
    assert "`marketmaking-test.reporting_us.rfq_latest`" in sql
    seen: list[str] = []

    def query(text: str) -> list[Any]:
        seen.append(text)
        return []

    assert fetch_unknown_mapping_failure_platforms(project="p", query_fn=query) == []
    assert "`p.reporting_us.rfq_latest`" in seen[0]


def test_combine_pipeline_groups_by_league_note() -> None:
    from mappers.control_plane.models import BatchChangesPayload, ProposalRecord
    from mappers.control_plane.pipeline_gap_propose import (
        PIPELINE_NOTE,
        combine_open_pipeline_cards,
        pipeline_note_for_league,
    )

    pin = {
        "kind": "entity_alias",
        "league": "epl",
        "canonical_key": "ARS",
        "aliases": [{"sportsbook": "kalshi", "alias_value": "ARS", "alias_kind": "code"}],
    }
    batch = {
        "kind": "batch_changes",
        "entity_aliases": [pin],
        "leagues": [],
        "market_rules": [],
    }
    epl = ProposalRecord(
        proposal_id="epl",
        request_id="r1",
        status="validated",
        expected_rule_set_id="tip",
        artifact_type="batch_changes",
        summary="epl",
        evidence_refs=[f"note:{pipeline_note_for_league('epl')}"],
        work_item_id=None,
        payload=BatchChangesPayload.model_validate(batch),
        proposer_subject="pipeline-gap-fix",
    )
    nba = ProposalRecord(
        proposal_id="nba",
        request_id="r2",
        status="validated",
        expected_rule_set_id="tip",
        artifact_type="batch_changes",
        summary="nba",
        evidence_refs=[f"note:{pipeline_note_for_league('nba')}"],
        work_item_id=None,
        payload=BatchChangesPayload.model_validate({
            **batch,
            "entity_aliases": [{**pin, "league": "nba", "canonical_key": "LAL"}],
        }),
        proposer_subject="pipeline-gap-fix",
    )
    service = MagicMock()
    service.list_proposals.return_value = [epl, nba]
    proposed_notes: list[str] = []

    def propose_fn(_svc, _actor, _pins, **kw: object) -> dict[str, object]:
        proposed_notes.append(str(kw.get("note") or ""))
        return {"ok": True, "review": {"ref": "new"}, "count": 1}

    with patch(
        "mappers.control_plane.pipeline_gap_propose._supersede_pipeline_cards",
    ), patch(
        "mappers.control_plane.pipeline_gap_propose._proposed_review",
        return_value={"ok": True, "action": "proposed"},
    ), patch(
        "mappers.control_plane.pipeline_gap_propose.already_single_pipeline_card",
        return_value=False,
    ), patch(
        "mappers.control_plane.pipeline_gap_propose.merge_pins",
        side_effect=lambda *parts: [pin for chunk in parts for pin in chunk],
    ), patch(
        "mappers.control_plane.pipeline_gap_propose.pins_from_payload",
        return_value=[{"league": "x", "canonical_key": "A", "aliases": [{"alias_value": "a"}]}],
    ), patch(
        "mappers.control_plane.pipeline_gap_propose.filter_new_pins",
        side_effect=lambda pins, *_a: pins,
    ):
        combine_open_pipeline_cards(service, propose_fn=propose_fn, publisher=None)
    assert PIPELINE_NOTE in proposed_notes[0]
    assert proposed_notes.count(pipeline_note_for_league("epl")) == 1
    assert proposed_notes.count(pipeline_note_for_league("nba")) == 1


def test_worker_exits_after_wave_when_image_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-flight wave finishes, then the worker exits for the new image."""
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    proposed = [{"ok": True, "action": "proposed", "progress": True}]
    code, publisher, run_wave = _worker(
        [[_CARD], [_CARD]], [proposed, proposed], handoff="repo/app:new",
    )
    assert code == 0
    assert run_wave.call_count == 1
    texts = [call.args[1] for call in publisher.publish.call_args_list]
    assert any("handing off to repo/app:new" in text for text in texts)


def test_worker_keeps_looping_when_image_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    proposed = [{"ok": True, "action": "proposed", "progress": True}]
    code, _pub, run_wave = _worker([[_CARD], []], [proposed])
    assert code == 0
    assert run_wave.call_count == 1


def test_handoff_starts_successor_on_cronjob_image(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str | None] = []
    monkeypatch.setattr(gap_k8s, "cronjob_image", lambda name="gap-propose": "repo/app:new")
    monkeypatch.setattr(gap_k8s, "running_image", lambda: "repo/app:old")
    monkeypatch.setattr(gap_k8s, "create_worker_job", lambda image=None: created.append(image))
    assert gap_k8s.hand_off_to_deployed_image() == "repo/app:new"
    assert created == ["repo/app:new"]


def test_handoff_stays_when_create_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(image: str | None = None) -> None:
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(gap_k8s, "cronjob_image", lambda name="gap-propose": "repo/app:new")
    monkeypatch.setattr(gap_k8s, "running_image", lambda: "repo/app:old")
    monkeypatch.setattr(gap_k8s, "create_worker_job", _boom)
    assert gap_k8s.hand_off_to_deployed_image() is None


def test_cronjob_container_image_prefers_gap_propose() -> None:
    body = {
        "spec": {
            "jobTemplate": {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{"name": "gap-propose", "image": "repo/app:new"}],
                        },
                    },
                },
            },
        },
    }
    assert _cronjob_container_image(body) == "repo/app:new"

"""Pipeline harvest → Review propose (never approve; fingerprint skip)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mappers.control_plane.app import app
from mappers.control_plane.app import service as app_service
from mappers.control_plane.entry import ACK_RULES_WRITE
from mappers.control_plane.gap_fix import propose_gap_pins
from mappers.control_plane.models import Actor, ActorRole
from mappers.control_plane.pipeline_gap_merge import (
    PIPELINE_SUBJECT,
    alias_keys_from_payload,
    merge_pins,
)
from mappers.control_plane.pipeline_gap_propose import (
    PIPELINE_ACTOR,
    PIPELINE_NOTE,
    PIPELINE_SUPERSEDE_ACTOR,
    _exit_code,
    _log_stage,
    alias_keys_from_pin,
    console_review_url,
    filter_new_pins,
    main,
    pipeline_gap_propose_enabled,
    run_pipeline_gap_propose,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from tests.control_plane.gap_store_helpers import _soccer_store


def _pin(value: str = "oid-val") -> dict[str, Any]:
    return {
        "kind": "entity_alias",
        "league": "la_liga",
        "canonical_key": "VAL",
        "entity_type": "team",
        "canonical_name": "Valencia",
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": value},
        ],
        "reassign": False,
    }


def _open(svc: ProposalService) -> list:
    return [p for p in svc.list_proposals() if p.status in {"proposed", "validated"}]


def test_merge_pins_unions_aliases_on_same_canonical() -> None:
    merged = merge_pins([_pin("a")], [_pin("b"), _pin("a")])
    assert len(merged) == 1
    assert {row["alias_value"] for row in merged[0]["aliases"]} == {"a", "b"}


def test_merge_pins_keeps_reassign_from_later_pin() -> None:
    claim = {**_pin("1660578"), "reassign": True}
    claim["aliases"] = [
        {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "1660578"},
    ]
    merged = merge_pins([_pin("optic-lucas")], [claim])
    assert merged[0]["reassign"] is True
    assert {row["alias_value"] for row in merged[0]["aliases"]} == {"optic-lucas", "1660578"}


def test_merge_pins_keeps_mapping_league() -> None:
    league = {
        "kind": "mapping_league",
        "league": "paraguay_division_intermedia",
        "optic_league_id": "paraguay_-_division_intermedia",
        "exchanges": [{"sportsbook": "polymarket_usa"}],
    }
    merged = merge_pins([league], [_pin("a"), league])
    assert merged[0]["kind"] == "mapping_league"
    assert merged[0]["league"] == "paraguay_division_intermedia"
    assert merged[1]["canonical_key"] == "VAL"


def test_filter_new_pins_drops_open_league() -> None:
    league = {
        "kind": "mapping_league",
        "league": "paraguay_division_intermedia",
        "optic_league_id": "paraguay_-_division_intermedia",
    }
    kept = filter_new_pins(
        [league, _pin("new-id")],
        frozenset(),
        frozenset({("paraguay_division_intermedia", "paraguay_-_division_intermedia")}),
    )
    assert [p["aliases"][0]["alias_value"] for p in kept if p.get("aliases")] == ["new-id"]


def test_pipeline_logs_stage_timings(caplog: Any) -> None:
    svc = ProposalService(_soccer_store())
    with caplog.at_level(logging.INFO, logger="mappers.control_plane.pipeline_gap_propose"):
        run_pipeline_gap_propose(
            service=svc,
            harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin("a")]},
        )
    assert "stage=sibling" in caplog.text
    assert "stage=harvest" in caplog.text
    assert "stage=propose" in caplog.text
    assert "kalshi_http" not in caplog.text


def test_pipeline_folds_new_pins_into_one_card() -> None:
    svc = ProposalService(_soccer_store())
    run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin("a")]},
    )
    first = _open(svc)[0].proposal_id
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin("a"), _pin("b")]},
    )
    assert result["action"] == "proposed"
    open_props = _open(svc)
    assert len(open_props) == 1
    assert open_props[0].proposal_id == first
    assert alias_keys_from_payload(open_props[0].payload) == frozenset(
        {("la_liga", "VAL", "a"), ("la_liga", "VAL", "b")}
    )


def test_pipeline_coalesces_sibling_cards_without_new_pins() -> None:
    svc = ProposalService(_soccer_store())
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("a")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("b")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    assert len(_open(svc)) == 2
    publisher = MagicMock()
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": []},
        publisher=publisher,
    )
    assert result["action"] == "proposed"
    open_props = _open(svc)
    assert len(open_props) == 1
    assert alias_keys_from_payload(open_props[0].payload) == frozenset(
        {("la_liga", "VAL", "a"), ("la_liga", "VAL", "b")}
    )
    publisher.publish.assert_called_once()
    _severity, text = publisher.publish.call_args.args
    assert "human Approve" in text


def test_pipeline_does_not_supersede_human_cards() -> None:
    svc = ProposalService(_soccer_store())
    human = Actor(subject="alice@wsd.com", role=ActorRole.ADMIN)
    propose_gap_pins(svc, human, [_pin("human")], acknowledge_shadow=True, note="manual")
    run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin("pipe")]},
    )
    humans = [p for p in svc.list_proposals() if p.proposer_subject == human.subject]
    assert len(humans) == 1
    assert humans[0].status == "validated"
    pipe = [p for p in _open(svc) if p.proposer_subject == PIPELINE_ACTOR.subject]
    assert len(pipe) == 1
    assert alias_keys_from_payload(pipe[0].payload) == frozenset({("la_liga", "VAL", "pipe")})


def test_filter_new_pins_drops_open_card_subset() -> None:
    open_keys = frozenset({("la_liga", "VAL", "oid-val")})
    kept = filter_new_pins([_pin(), _pin("new-id")], open_keys)
    assert [p["aliases"][0]["alias_value"] for p in kept] == ["new-id"]


def test_console_review_url_defaults() -> None:
    assert console_review_url("prop_abc", environment="prod").endswith("/review/prop_abc")
    assert "mm-test" in console_review_url("prop_abc", environment="test")
    custom = console_review_url("prop_abc", environment="prod", base="https://x.example/")
    assert custom == "https://x.example/review/prop_abc"


def test_pipeline_skips_when_harvest_empty() -> None:
    svc = ProposalService(_soccer_store())
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": []},
    )
    assert result["action"] == "skip"
    assert result["ok"] is True
    assert svc.list_proposals() == []


def test_pipeline_skips_when_pins_already_in_review() -> None:
    store = _soccer_store()
    svc = ProposalService(store)
    pins = [_pin("oid-val")]
    first = propose_gap_pins(svc, PIPELINE_ACTOR, pins, acknowledge_shadow=True, note=PIPELINE_NOTE)
    assert first["review"]["status"] == "waiting_for_checker"

    publisher = MagicMock()
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": pins},
        publisher=publisher,
    )
    assert result["action"] == "skip"
    assert result["already_in_review"] == len(pins)
    publisher.publish.assert_not_called()
    assert len(svc.list_proposals()) == 1


def test_pipeline_proposes_and_never_approves() -> None:
    store = _soccer_store()
    svc = ProposalService(store)
    publisher = MagicMock()
    result = run_pipeline_gap_propose(
        service=svc,
        publisher=publisher,
        environment="prod",
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin("oid-val")]},
    )
    assert result["ok"] is True
    assert result["action"] == "proposed"
    review = result["review"]
    assert review["status"] == "waiting_for_checker"
    assert review["status"] != "activated"
    assert review["ref"]
    assert PIPELINE_NOTE in " ".join(review.get("evidence") or [])
    assert result["url"].endswith(f"/review/{review['ref']}")
    publisher.publish.assert_called_once()
    severity, text = publisher.publish.call_args.args
    assert severity == "warning"
    assert "human Approve" in text
    assert result["url"] in text
    prop = svc.get_proposal(review["ref"])
    assert prop.proposer_subject == PIPELINE_ACTOR.subject
    assert prop.status == "validated"
    assert PIPELINE_ACTOR.role == ActorRole.PROPOSER


def test_pipeline_alert_includes_skipped_mismatches() -> None:
    svc = ProposalService(_soccer_store())
    publisher = MagicMock()
    mismatch = "crypto.com 1535401 is live as 'Academy', not 'CTBC Flying Oyster'."

    def propose(_svc: Any, _actor: Any, _pins: list[dict[str, Any]], **_k: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "count": 1,
            "skipped_blockers": [mismatch],
            "warnings": [],
            "review": {"ref": "rev_skip", "status": "validated"},
        }

    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin()]},
        propose_fn=propose,
        publisher=publisher,
    )
    assert result["action"] == "proposed"
    assert result["count"] == 1
    _severity, text = publisher.publish.call_args.args
    assert "human Approve" in text
    assert "Skipped blocker" in text
    assert "1535401" in text


def test_pipeline_alerts_harvest_name_mismatch_skips() -> None:
    svc = ProposalService(_soccer_store())
    publisher = MagicMock()
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {
            "ok": True,
            "pins": [],
            "skipped": [{
                "symbol": "NX.F.OPT.DEB-1",
                "reason": "name_mismatch",
            }],
        },
        publisher=publisher,
    )
    assert result["action"] == "skip"
    publisher.publish.assert_called()
    _sev, text = publisher.publish.call_args.args
    assert "name_mismatch NX.F.OPT.DEB-1" in text


def test_pipeline_blocked_without_live_ack() -> None:
    store = _soccer_store()
    svc = ProposalService(store)
    publisher = MagicMock()
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin()]},
        propose_fn=lambda *_a, **_k: {"ok": False, "blockers": [ACK_RULES_WRITE]},
        publisher=publisher,
    )
    assert result["action"] == "blocked"
    assert result["ok"] is False
    assert svc.list_proposals() == []
    publisher.publish.assert_called_once()


def test_alias_keys_from_pin() -> None:
    keys = alias_keys_from_pin(_pin())
    assert keys == frozenset({("la_liga", "VAL", "oid-val")})


def test_kill_switch(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "0")
    assert pipeline_gap_propose_enabled() is False
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    assert pipeline_gap_propose_enabled() is True


def test_main_cli_no_data_dir(monkeypatch: Any) -> None:
    """CronJob CLI: disabled kill switch exits 0."""
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "0")
    assert main([]) == 0


def test_main_nonzero_on_harvest_failed(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.run_once",
        lambda: {"ok": False, "action": "harvest_failed"},
    )
    assert main([]) == 1


def test_main_nonzero_when_sibling_proposed_but_harvest_failed(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.run_once",
        lambda: {
            "ok": True,
            "action": "proposed",
            "harvest_error": "RuntimeError: crypto harvest down",
        },
    )
    assert main([]) == 1


def test_exit_code_harvest_error_beats_proposed() -> None:
    assert _exit_code({"ok": True, "action": "proposed", "harvest_error": "oom"}) == 1
    assert _exit_code({"ok": True, "action": "proposed"}) == 0


def test_main_zero_on_blocked(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_PROPOSE", "1")
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.run_once",
        lambda: {"ok": False, "action": "blocked", "blockers": ["clone_market_rules_from"]},
    )
    assert main([]) == 0


def test_pipeline_harvest_memory_error_propagates() -> None:
    svc = ProposalService(_soccer_store())

    def harvest(_store: Any, **_kwargs: Any) -> dict[str, Any]:
        raise MemoryError("poly_usa_close oom")

    with pytest.raises(MemoryError, match="poly_usa_close oom"):
        run_pipeline_gap_propose(service=svc, harvest_fn=harvest)


def test_pipeline_harvest_failure_without_siblings() -> None:
    svc = ProposalService(_soccer_store())
    publisher = MagicMock()

    def harvest(_store: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("bq down")

    result = run_pipeline_gap_propose(
        service=svc, harvest_fn=harvest, publisher=publisher,
    )
    assert result["ok"] is False
    assert result["action"] == "harvest_failed"
    severity, text = publisher.publish.call_args.args
    assert severity == "critical"
    assert text.startswith("[CRITICAL] ")
    assert "harvest failed" in text
    assert "bq down" in text


def test_pipeline_actor_cannot_be_the_checker() -> None:
    """Pipeline proposes only; Approve roles stay human (or service activate)."""
    assert PIPELINE_ACTOR.role == ActorRole.PROPOSER
    assert PIPELINE_ACTOR.subject == PIPELINE_SUBJECT
    assert PIPELINE_ACTOR.role not in {ActorRole.APPROVER, ActorRole.ADMIN, ActorRole.SERVICE}
    assert PIPELINE_SUPERSEDE_ACTOR.role == ActorRole.SERVICE
    assert PIPELINE_SUPERSEDE_ACTOR.subject != PIPELINE_ACTOR.subject


def test_pipeline_coalesces_before_harvest() -> None:
    """Sibling merge must land before harvest runs (harvest can hang or throw)."""
    svc = ProposalService(_soccer_store())
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("a")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("b")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    seen: dict[str, int] = {}

    def harvest(_store: Any, **_kwargs: Any) -> dict[str, Any]:
        seen["open"] = len(_open(svc))
        return {"ok": True, "pins": []}

    result = run_pipeline_gap_propose(service=svc, harvest_fn=harvest)
    assert seen["open"] == 1
    assert result["action"] == "proposed"
    assert len(_open(svc)) == 1


def test_pipeline_coalesces_when_harvest_raises() -> None:
    svc = ProposalService(_soccer_store())
    publisher = MagicMock()
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("a")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("b")], acknowledge_shadow=True, note=PIPELINE_NOTE)

    def harvest(_store: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("crypto harvest down")

    result = run_pipeline_gap_propose(
        service=svc, harvest_fn=harvest, publisher=publisher,
    )
    assert result["action"] == "proposed"
    assert result.get("harvest_error")
    severity, text = publisher.publish.call_args.args
    assert severity == "critical"
    assert "sibling merge" in text
    assert "crypto harvest down" in text
    open_props = _open(svc)
    assert len(open_props) == 1
    assert alias_keys_from_payload(open_props[0].payload) == frozenset(
        {("la_liga", "VAL", "a"), ("la_liga", "VAL", "b")}
    )


def test_pipeline_fold_skips_when_verify_noop() -> None:
    svc = ProposalService(_soccer_store())

    def propose(
        _svc: Any,
        _actor: Any,
        pins: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "noop": True,
            "count": len(pins),
            "skipped_blockers": [],
            "warnings": [],
        }

    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": [_pin("a")]},
        propose_fn=propose,
    )
    assert result["action"] == "skip"


def test_pipeline_supersede_with_maker_checker() -> None:
    svc = ProposalService(_soccer_store(), require_maker_checker=True)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("a")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("b")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    result = run_pipeline_gap_propose(
        service=svc,
        harvest_fn=lambda *_a, **_k: {"ok": True, "pins": []},
    )
    assert result["action"] == "proposed"
    assert len(_open(svc)) == 1


def test_log_stage_includes_cgroup_memory_pct(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.pipeline_gap_propose.cgroup_memory_ratio",
        lambda: 0.91,
    )
    with caplog.at_level(logging.INFO):
        _log_stage("probe", 0.0, book="poly_usa_close", pins=3)
    assert "mem_pct=91" in caplog.text
    assert "book=poly_usa_close" in caplog.text


def test_review_combine_pipeline_endpoint() -> None:
    store = _soccer_store()
    svc = ProposalService(store)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("a")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    propose_gap_pins(svc, PIPELINE_ACTOR, [_pin("b")], acknowledge_shadow=True, note=PIPELINE_NOTE)
    app.dependency_overrides[app_service] = lambda: svc
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
    )
    try:
        client = TestClient(app)
        listed = client.get("/review").json()
        assert len(listed) == 2
        combined = client.post(
            "/review/combine-pipeline",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:bob@wsd.com"},
        )
        assert combined.status_code == 200
        cards = combined.json()
        assert len(cards) == 1
        assert cards[0]["proposer"] == PIPELINE_SUBJECT
    finally:
        app.dependency_overrides.clear()

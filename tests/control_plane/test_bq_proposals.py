"""Unit tests for batched audit-row proposal hydration."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from mappers.control_plane.bq_proposals import (
    change_groups_from_events,
    change_summary_from_events,
    last_occurred_at_from_events,
    occurred_iso,
    proposal_from_events,
    proposals_from_audit_rows,
    reviewer_from_events,
)
from mappers.control_plane.cow_diff import entity_change_counts
from mappers.control_plane.store import EntityRow

_PROPOSE = {
    "request_id": "req_1",
    "expected_rule_set_id": "S0_x",
    "artifact_type": "entity_alias",
    "summary": "pin M05",
    "payload": {
        "kind": "entity_alias",
        "league": "international_club_friendlies",
        "canonical_key": "M05",
        "entity_type": "team",
        "canonical_name": "Mainz 05",
        "aliases": [{"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "M05"}],
    },
}


def _row(**fields: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "proposal_id": "prop_a",
        "event_type": "rule_proposed",
        "occurred_at": "2026-08-14T00:00:00Z",
        "event_id": "evt_1",
        "rule_set_id": None,
        "actor_subject": "alice@wsd.com",
        "expected_rule_set_id": None,
        "payload": _PROPOSE,
    }
    base.update(fields)
    return SimpleNamespace(**base)


def test_proposals_from_audit_rows_one_query_shape() -> None:
    rows = [
        _row(),
        _row(
            event_type="rule_validated",
            event_id="evt_2",
            rule_set_id="P_abc",
            payload={"dry_run": {}, "changes": {"added_count": 1, "removed_count": 0, "modified_count": 0}},
        ),
        _row(proposal_id="prop_b", event_id="evt_3", payload={**_PROPOSE, "request_id": "req_2"}),
    ]
    records = proposals_from_audit_rows(rows)
    assert [r.proposal_id for r in records] == ["prop_a", "prop_b"]
    assert records[0].change_summary == {"added_count": 1, "removed_count": 0, "modified_count": 0}
    assert records[0].last_occurred_at == "2026-08-14T00:00:00Z"
    assert records[1].change_summary is None


def test_change_summary_skips_legacy_validated_payload() -> None:
    rows = [_row(event_type="rule_validated", payload={"dry_run": {}})]
    assert change_summary_from_events(rows) is None


def test_occurred_iso_normalizes_bq_datetime() -> None:
    assert occurred_iso("2026-08-14 00:00:00+00:00") == "2026-08-14T00:00:00+00:00"
    stamp = datetime(2026, 8, 14, tzinfo=UTC)
    assert last_occurred_at_from_events([_row(occurred_at=stamp)]) == "2026-08-14T00:00:00+00:00"


def test_change_groups_from_validated_payload() -> None:
    groups = {
        "aliases": {"added_count": 0, "modified_count": 0, "removed_count": 0, "lines": []},
        "leagues": {
            "added_count": 0,
            "modified_count": 1,
            "removed_count": 0,
            "lines": ["~ Enable Kalshi on Saudi Pro League"],
        },
        "market_rules": {"added_count": 0, "modified_count": 0, "removed_count": 0, "lines": []},
    }
    rows = [
        _row(),
        _row(
            event_type="rule_validated",
            event_id="evt_2",
            rule_set_id="P_abc",
            payload={
                "dry_run": {},
                "changes": {"added_count": 0, "removed_count": 0, "modified_count": 1},
                "change_groups": groups,
            },
        ),
    ]
    assert change_groups_from_events(rows) == groups
    record = proposal_from_events("prop_a", rows)
    assert record is not None
    assert record.change_groups == groups


def test_proposal_from_events_uses_latest_successful_validate_expected() -> None:
    proposed = _row()
    first = _row(
        event_type="rule_validated",
        event_id="evt_2",
        rule_set_id="P_old",
        expected_rule_set_id="S0_x",
    )
    rebased = _row(
        event_type="rule_validated",
        event_id="evt_3",
        rule_set_id="P_new",
        expected_rule_set_id="P_parent",
    )
    failed = _row(
        event_type="rule_validated",
        event_id="evt_4",
        rule_set_id=None,
        expected_rule_set_id="P_ignored",
        payload={"dry_run": {"ok": False}},
    )
    record = proposal_from_events("prop_a", [proposed, first, rebased, failed])
    assert record is not None
    assert record.expected_rule_set_id == "P_parent"
    assert record.candidate_rule_set_id == "P_new"


def test_proposal_from_events_maps_reject_and_changes_requested() -> None:
    proposed = _row()
    validated = _row(
        event_type="rule_validated",
        event_id="evt_2",
        rule_set_id="P_abc",
        payload={"dry_run": {}, "changes": {"added_count": 1, "removed_count": 0, "modified_count": 0}},
    )
    rejected = proposal_from_events(
        "prop_a",
        [
            proposed,
            validated,
            _row(
                event_type="rule_rejected",
                event_id="evt_3",
                payload={"comment": "superseded: combined into P_new"},
            ),
        ],
    )
    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.review_note == "superseded: combined into P_new"

    rejected_with_actor = proposal_from_events(
        "prop_a",
        [
            proposed,
            validated,
            _row(
                event_type="rule_rejected",
                event_id="evt_3",
                actor_subject="checker@wsd.com",
                payload={"comment": "nope"},
            ),
        ],
    )
    assert rejected_with_actor is not None
    assert rejected_with_actor.reviewer_subject == "checker@wsd.com"
    assert reviewer_from_events(
        [
            proposed,
            validated,
            _row(event_type="rule_rejected", actor_subject="checker@wsd.com"),
        ]
    ) == "checker@wsd.com"

    changes = proposal_from_events(
        "prop_a",
        [proposed, validated, _row(event_type="rule_changes_requested", event_id="evt_3")],
    )
    assert changes is not None
    assert changes.status == "changes_requested"


def test_entity_change_counts_added_modified_removed() -> None:
    parent = [
        EntityRow("lg", "team", "A", "Alpha", [], enabled=True),
        EntityRow("lg", "team", "B", "Beta", [], enabled=True),
    ]
    child = [
        EntityRow("lg", "team", "A", "Alpha", [], enabled=False),
        EntityRow("lg", "team", "C", "Gamma", [], enabled=True),
    ]
    assert entity_change_counts(parent, child) == {
        "added_count": 1,
        "removed_count": 1,
        "modified_count": 1,
    }

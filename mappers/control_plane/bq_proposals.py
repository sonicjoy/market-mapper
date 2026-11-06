"""Rehydrate proposals from mapping_audit_events rows."""

from __future__ import annotations

import json
from typing import Any

from BigQuery.mapping_rule_rows import AUDIT_EVENTS_TABLE
from mappers.control_plane.models import ProposalRecord, ProposeRequest

_STATUS_BY_EVENT = {
    "rule_proposed": "proposed",
    "rule_amended": "proposed",
    "rule_validated": "validated",
    "rule_approved": "approved",
    "rule_set_activated": "activated",
    "rule_rejected": "rejected",
    "rule_changes_requested": "changes_requested",
}
_PAYLOAD_EVENTS = frozenset({"rule_proposed", "rule_amended"})
_REVIEWER_EVENTS = frozenset(
    {"rule_approved", "rule_rejected", "rule_changes_requested"},
)

# The queue rehydrates every proposal in the window to render a handful of open
# cards, so the window is what bounds its cost as history grows.
LIST_PROPOSALS_SQL = f"""
select proposal_id, event_type, occurred_at, event_id, rule_set_id, actor_subject,
       expected_rule_set_id, payload
from `{AUDIT_EVENTS_TABLE}`
where proposal_id is not null
  and occurred_at >= timestamp_sub(current_timestamp(), interval @window_days day)
order by proposal_id, occurred_at, event_id
"""  # nosec B608

_CHANGE_KEYS = ("added_count", "removed_count", "modified_count")


def json_payload(value: Any) -> dict[str, Any]:
    """Normalize a BigQuery JSON column to a dictionary."""
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


def change_summary_from_events(rows: list[Any]) -> dict[str, int] | None:
    """Read counts stored on the latest rule_validated payload."""
    for row in reversed(rows):
        if row.event_type != "rule_validated":
            continue
        return _coerce_change_summary(json_payload(row.payload).get("changes"))
    return None


def change_groups_from_events(rows: list[Any]) -> dict[str, Any] | None:
    """Read per-kind lines stored on the latest rule_validated payload."""
    for row in reversed(rows):
        if row.event_type != "rule_validated":
            continue
        return _coerce_change_groups(json_payload(row.payload).get("change_groups"))
    return None


def _coerce_change_groups(raw: Any) -> dict[str, Any] | None:
    """Accept aliases / leagues / market_rules count+line groups."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("aliases", "leagues", "market_rules"):
        group = raw.get(key)
        if not isinstance(group, dict):
            return None
        out[key] = {
            "added_count": int(group.get("added_count") or 0),
            "modified_count": int(group.get("modified_count") or 0),
            "removed_count": int(group.get("removed_count") or 0),
            "lines": [str(line) for line in (group.get("lines") or [])],
        }
    return out


def _coerce_change_summary(raw: Any) -> dict[str, int] | None:
    """Accept only the three integer count keys."""
    if not isinstance(raw, dict) or any(key not in raw for key in _CHANGE_KEYS):
        return None
    return {key: int(raw[key]) for key in _CHANGE_KEYS}


def occurred_iso(value: Any) -> str:
    """Sortable ISO-8601 timestamp; BigQuery datetimes stringify with a space."""
    if value is None:
        return ""
    raw = value.isoformat() if hasattr(value, "isoformat") else str(value).strip()
    if raw and "T" not in raw[:20]:
        return raw.replace(" ", "T", 1)
    return raw


def reviewer_from_events(rows: list[Any]) -> str | None:
    """Checker who approved, rejected, or requested changes."""
    for row in reversed(rows):
        if str(row.event_type) not in _REVIEWER_EVENTS:
            continue
        subject = str(getattr(row, "actor_subject", None) or "").strip()
        if subject:
            return subject
    return None


def proposed_at_from_events(rows: list[Any]) -> str | None:
    """Timestamp of the first propose/amend event."""
    for row in rows:
        if str(row.event_type) in _PAYLOAD_EVENTS:
            return occurred_iso(row.occurred_at) or None
    return occurred_iso(rows[0].occurred_at) or None if rows else None


def last_occurred_at_from_events(rows: list[Any]) -> str | None:
    """Timestamp of the latest lifecycle event."""
    return occurred_iso(rows[-1].occurred_at) or None if rows else None


def expected_from_events(rows: list[Any], fallback: str) -> str:
    """Prefer the latest successful validate tip; else the original propose id."""
    for row in reversed(rows):
        if str(row.event_type) != "rule_validated" or not row.rule_set_id:
            continue
        expected = getattr(row, "expected_rule_set_id", None)
        if expected:
            return str(expected)
    return fallback


def proposal_from_events(proposal_id: str, rows: list[Any]) -> ProposalRecord | None:
    """Build current proposal status from ordered events."""
    proposed = next((row for row in rows if row.event_type == "rule_proposed"), None)
    if proposed is None:
        return None
    request = _payload_request(rows) or ProposeRequest.model_validate(json_payload(proposed.payload))
    candidate = next(
        (
            str(row.rule_set_id)
            for row in reversed(rows)
            if row.event_type == "rule_validated" and row.rule_set_id
        ),
        None,
    )
    status = _STATUS_BY_EVENT.get(str(rows[-1].event_type), "proposed")
    return ProposalRecord(
        proposal_id=proposal_id,
        request_id=request.request_id,
        status=status,
        expected_rule_set_id=expected_from_events(rows, request.expected_rule_set_id),
        artifact_type=request.artifact_type,
        summary=request.summary,
        evidence_refs=request.evidence_refs,
        work_item_id=request.work_item_id,
        payload=request.payload,
        proposer_subject=str(rows[0].actor_subject or ""),
        candidate_rule_set_id=candidate,
        activated_rule_set_id=candidate if status == "activated" else None,
        change_summary=change_summary_from_events(rows),
        change_groups=change_groups_from_events(rows),
        review_note=_reject_note(rows),
        proposed_at=proposed_at_from_events(rows),
        last_occurred_at=last_occurred_at_from_events(rows),
        reviewer_subject=reviewer_from_events(rows),
    )


def _payload_request(rows: list[Any]) -> ProposeRequest | None:
    """Latest propose/amend payload, ignoring empty audit rows."""
    for row in reversed(rows):
        if str(row.event_type) not in _PAYLOAD_EVENTS:
            continue
        body = json_payload(row.payload)
        if not body:
            continue
        return ProposeRequest.model_validate(body)
    return None


def _reject_note(rows: list[Any]) -> str | None:
    """Comment from the latest rule_rejected event, if any."""
    for row in reversed(rows):
        if str(row.event_type) != "rule_rejected":
            continue
        comment = str(json_payload(row.payload).get("comment") or "").strip()
        return comment or None
    return None


def proposals_from_audit_rows(rows: list[Any]) -> list[ProposalRecord]:
    """Group a flat audit stream into one record per proposal_id."""
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row.proposal_id), []).append(row)
    out: list[ProposalRecord] = []
    for pid in sorted(grouped):
        record = proposal_from_events(pid, grouped[pid])
        if record is not None:
            out.append(record)
    return out

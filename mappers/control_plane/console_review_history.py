"""Recent proposal history rows for the trader console."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mappers.control_plane.bq_proposals import (
    last_occurred_at_from_events,
    occurred_iso,
    reviewer_from_events,
)
from mappers.control_plane.models import ProposalRecord
from mappers.control_plane.review_cards import proposal_brief

_PENDING = frozenset({"submitted", "waiting_for_checker"})
_HUMAN_STATUS = {
    "proposed": "submitted",
    "validated": "waiting_for_checker",
    "approved": "approved",
    "activated": "activated",
    "rejected": "rejected",
    "changes_requested": "needs_changes",
}


def _audit_rows_by_proposal(store: Any) -> dict[str, list[Any]]:
    """Group in-memory audit rows by proposal_id."""
    grouped: dict[str, list[Any]] = {}
    for row in getattr(store, "audits", []) or []:
        if not isinstance(row, dict):
            continue
        pid = row.get("proposal_id")
        if not pid:
            continue
        grouped.setdefault(str(pid), []).append(row)
    return grouped


def _event_rows(rows: list[Any]) -> list[Any]:
    """Normalize dict audit rows to attribute access."""
    out: list[Any] = []
    for row in rows:
        if hasattr(row, "event_type"):
            out.append(row)
        elif isinstance(row, dict):
            out.append(SimpleNamespace(**row))
    return out


def _proposal_at(proposal: ProposalRecord, audit_rows: list[Any]) -> str:
    raw = (
        proposal.last_occurred_at
        or last_occurred_at_from_events(_event_rows(audit_rows))
        or proposal.proposed_at
        or ""
    )
    return occurred_iso(raw)


def _proposal_reviewer(proposal: ProposalRecord, audit_rows: list[Any]) -> str | None:
    if proposal.reviewer_subject:
        return proposal.reviewer_subject
    return reviewer_from_events(_event_rows(audit_rows))


def _history_row(proposal: ProposalRecord, audit_rows: list[Any]) -> dict[str, Any]:
    return {
        "ref": proposal.proposal_id,
        "at": _proposal_at(proposal, audit_rows),
        "brief": proposal_brief(proposal),
        "status": _HUMAN_STATUS.get(proposal.status, proposal.status),
        "reviewer": _proposal_reviewer(proposal, audit_rows),
    }


def list_review_history(store: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    """Last N proposals: latest pending first, then newest closed."""
    audits = _audit_rows_by_proposal(store)
    rows = [
        _history_row(proposal, audits.get(proposal.proposal_id, []))
        for proposal in store.list_proposals()
    ]
    pending = [row for row in rows if row["status"] in _PENDING]
    closed = [row for row in rows if row["status"] not in _PENDING]
    pending.sort(key=lambda row: row["at"], reverse=True)
    closed.sort(key=lambda row: row["at"], reverse=True)
    return (pending + closed)[:limit]

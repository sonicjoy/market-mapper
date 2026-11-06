"""Emit mapping audit events and run provenance (Milestone 1)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def new_mapping_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:16]}"


def git_commit_short() -> str | None:
    """Best-effort short SHA from env or .git (no subprocess)."""
    for key in ("MAPPER_GIT_COMMIT", "CI_COMMIT_SHORT_SHA"):
        val = os.environ.get(key)
        if val:
            return val.strip()[:40] or None
    sha = os.environ.get("CI_COMMIT_SHA")
    if sha:
        return sha.strip()[:12] or None
    head = REPO_ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if ref.startswith("ref:"):
        ref_path = REPO_ROOT / ".git" / ref.split(" ", 1)[1].strip()
        try:
            return ref_path.read_text(encoding="utf-8").strip()[:12] or None
        except OSError:
            return None
    return ref[:12] or None


def run_started_event(
    *,
    mapping_run_id: str,
    environment: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "request_id": mapping_run_id,
        "event_type": "mapping_run_started",
        "occurred_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "mapping_run_id": mapping_run_id,
        "actor_role": "service",
        "payload": payload or {},
    }


def run_completed_event(
    *,
    mapping_run_id: str,
    environment: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "request_id": mapping_run_id,
        "event_type": "mapping_run_completed",
        "occurred_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "mapping_run_id": mapping_run_id,
        "actor_role": "service",
        "payload": payload or {},
    }

"""Bulk override publish: many confirmed pairs, one reason, one propagation.

Every pair goes through the single-override path unchanged
(``build_console_override_message`` -> ``publish_console_override``, which
honours ``MAPPING_CONSOLE_OVERRIDE_DRY_RUN``), gets its own ``OverrideJob``
(pollable at ``/console/catalog/override/jobs/{id}``), and the batch shares one
sink -> merge -> fold+rank -> read-back run (``start_override_batch``).

Refused whole, before anything is published: a venue whose consumer does not
read ``opticodds_mapping`` or is not enabled (``console_bulk_override_venues``),
a missing reason, a duplicate venue key, or any game outside the fold+rank
window (the same R13 preflight as the single publish, run once per game).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from mappers.control_plane.console_bulk_override_venues import shaped_source_ids, venue_block_reason
from mappers.control_plane.console_override_jobs import create_job, get_job, job_to_dict, start_override_batch
from mappers.control_plane.console_override_publish import build_console_override_message, publish_console_override
from mappers.control_plane.console_sportsbook import canonical_sportsbook, sportsbook_lower
from mappers.control_plane.models import Actor, ForbiddenError, ValidationFailedError

MAX_BATCH_PAIRS = 60
_WRITE_ROLES = frozenset({"proposer", "approver", "admin", "service"})
_BATCH_TTL_SEC = 3600

PublishFn = Callable[..., str]
PreflightFn = Callable[[str], str | None]
StartFn = Callable[[list[tuple[str, dict[str, Any]]]], None]

_lock = threading.Lock()
_batches: dict[str, dict[str, Any]] = {}


def _bad(message: str) -> ValidationFailedError:
    """400-shaped validation error the console renders inline."""
    return ValidationFailedError(message, reason_code="bad_request", dry_run={})


def _require_access(actor: Actor, reason: str) -> str:
    """Same roles and reason rule as the single Catalog publish."""
    if actor.role.value not in _WRITE_ROLES:
        raise ForbiddenError("role cannot publish mapping overrides")
    text = reason.strip()
    if not text:
        raise _bad("reason is required")
    return text


def _message(sportsbook: str, pair: dict[str, Any]) -> dict[str, Any]:
    """One mapping_override payload with the venue's own source-id shape."""
    market, selection = shaped_source_ids(
        sportsbook, str(pair.get("source_market_id") or ""), str(pair.get("source_selection_id") or "")
    )
    try:
        return build_console_override_message(
            game_id=str(pair.get("game_id") or ""),
            market_id=str(pair.get("market_id") or ""),
            sportsbook=sportsbook,
            selection=str(pair.get("selection") or ""),
            source_market_id=market,
            source_selection_id=selection,
            selection_line=str(pair.get("selection_line") or ""),
            points=float(pair.get("points") or 0.0),
            selection_points=float(pair.get("selection_points") or 0.0),
            grouping_key=str(pair.get("grouping_key") or "default"),
            mapping_source="mapping-console-bulk",
        )
    except ValueError as exc:
        raise _bad(f"{pair.get('source_market_id')}: {exc}") from exc


def _validated_messages(sportsbook: str, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build every message first so one bad pair refuses the batch before any publish."""
    if not pairs:
        raise _bad("no pairs to publish")
    if len(pairs) > MAX_BATCH_PAIRS:
        raise _bad(f"at most {MAX_BATCH_PAIRS} pairs per batch, got {len(pairs)}")
    messages = [_message(sportsbook, pair) for pair in pairs]
    keys = [str(m["source_ids"]).lower() for m in messages]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise _bad(f"the same venue selection appears twice: {', '.join(dupes)}")
    return messages


def _preflight(messages: list[dict[str, Any]], preflight: PreflightFn) -> None:
    """R13 window check once per game; any failure refuses the batch."""
    failures = {}
    for game_id in sorted({str(m["game_id"]) for m in messages}):
        reason = preflight(game_id)
        if reason:
            failures[game_id] = reason
    if failures:
        detail = "; ".join(f"{gid}: {why}" for gid, why in failures.items())
        raise ValidationFailedError(f"override preflight failed: {detail}", reason_code="not_materialised", dry_run={})


def _publish_one(
    project: str, sportsbook: str, message: dict[str, Any], operator: str, reason: str, publish: PublishFn
) -> tuple[str, dict[str, Any]]:
    """Publish one pair and open its job; a failed publish is a failed job, not a batch abort."""
    source = message["source_ids"]
    job = create_job(
        active=True,
        sportsbook=sportsbook_lower(sportsbook),
        source_market_id=str(_source_field(source, "market_id")),
        source_selection_id=str(_source_field(source, "selection_id")),
    )
    try:
        job.steps["publish_message_id"] = publish(project, message, operator=operator, reason=reason)
    except Exception as exc:  # noqa: BLE001 - recorded on the pair, the rest still publish
        job.status = "failed"
        job.message = f"override publish failed: {exc}"
    return job.job_id, message


def _source_field(source_ids: Any, key: str) -> str:
    """Read market_id / selection_id back out of the (JSON-string) source_ids."""
    parsed = source_ids if isinstance(source_ids, dict) else json.loads(str(source_ids or "{}"))
    return str(parsed.get(key) or "")


def _remember(batch: dict[str, Any]) -> None:
    """Keep the batch record for polling; drop ones older than an hour."""
    cutoff = time.time() - _BATCH_TTL_SEC
    with _lock:
        for stale in [bid for bid, b in _batches.items() if b["created_at"] < cutoff]:
            _batches.pop(stale, None)
        _batches[batch["batch_id"]] = batch


def publish_override_batch(
    body: dict[str, Any],
    actor: Actor,
    *,
    project: str,
    preflight: PreflightFn,
    publish: PublishFn = publish_console_override,
    start: StartFn = start_override_batch,
) -> dict[str, Any]:
    """Validate, preflight, publish every pair, start one propagation; return the batch view."""
    sportsbook_raw = str(body.get("sportsbook") or "")
    blocked = venue_block_reason(sportsbook_raw)
    if blocked:
        raise _bad(blocked)
    sportsbook = canonical_sportsbook(sportsbook_raw)
    reason = _require_access(actor, str(body.get("reason") or ""))
    messages = _validated_messages(sportsbook, list(body.get("pairs") or []))
    _preflight(messages, preflight)
    published = [_publish_one(project, sportsbook, m, actor.subject, reason, publish) for m in messages]
    start([(jid, msg) for jid, msg in published if getattr(get_job(jid), "status", "") != "failed"])
    batch = {
        "batch_id": uuid.uuid4().hex,
        "sportsbook": sportsbook,
        "operator": actor.subject,
        "reason": reason,
        "created_at": time.time(),
        "job_ids": [jid for jid, _ in published],
    }
    _remember(batch)
    return batch_view(batch["batch_id"])


def batch_view(batch_id: str) -> dict[str, Any]:
    """Batch header plus every pair's job, with status counts for the UI."""
    with _lock:
        batch = _batches.get(batch_id)
    if batch is None:
        raise KeyError(f"override batch {batch_id}")
    jobs = [job_to_dict(job) for job in (get_job(jid) for jid in batch["job_ids"]) if job is not None]
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    return {**batch, "jobs": jobs, "counts": counts}

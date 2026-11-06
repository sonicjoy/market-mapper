"""Explore -> Mapping risk: live mappings scored for mismapping risk (mmmapper#23).

The query (console_mismap_sql) lines up independent evidence per mapping row;
console_mismap_score turns it into signals and a tier. This module caches the
query, filters and pages the scored rows, and attaches operator flags.

Flags reuse the control-plane work-item inbox (``markets_us.mapping_work_items``
via ``store.put_work_item``), ``source = "mismap_flag"``: append-only, so a flag
survives restarts and every change keeps its history. A flag never un-maps
anything; the un-map goes through Editor -> Cart -> Proposed like any rule change.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.console_mismap_score import TIER_RANK, score_row
from mappers.control_plane.console_mismap_sql import CACHE_TTL_SECONDS, MISMAP_SQL, PRICED_VENUES, VENUES
from mappers.control_plane.models import Actor, ForbiddenError, ValidationFailedError
from mappers.control_plane.store import WorkItemRow, new_id

MismapQueryFn = Callable[[], list[dict[str, Any]]]

FLAG_SOURCE = "mismap_flag"
FLAG_OPEN, FLAG_RESOLVED = "open", "resolved"
_WRITE_ROLES = frozenset({"proposer", "approver", "admin", "service"})

# Which evidence exists per venue (2026-09-26). The page prints the gaps so an
# empty signal column reads as "not measured", never as "clean".
_OPTIC_SECOND_OPINION = ("kalshi", "polymarket", "novig", "prophet x")
_AI_VALIDATED = ("kalshi", "polymarket", "novig", "crypto.com")
_PERIOD_CHECKED = ("kalshi",)

_cache: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _bq_project() -> str:
    """Project the console reads (GCP_PROJECT, else BQ_PROJECT)."""
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def default_mismap_query() -> list[dict[str, Any]]:
    """Run MISMAP_SQL, memoised for CACHE_TTL_SECONDS (the scan is ~1.8 GB)."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get("rows")
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[2]
    project = _bq_project()
    rows = [dict(r) for r in ro_query(bigquery.Client(project=project), MISMAP_SQL.replace("{project}", project))]
    with _cache_lock:
        _cache["rows"] = (now, datetime.now(UTC).isoformat(), rows)
    return rows


def mismap_cached_at() -> str | None:
    """When the memoised snapshot was taken (UTC ISO), or None before the first scan."""
    with _cache_lock:
        hit = _cache.get("rows")
    return hit[1] if hit is not None else None


def clear_mismap_cache() -> None:
    """Drop the memoised query result (Refresh button, tests)."""
    with _cache_lock:
        _cache.clear()


def coverage_notes() -> list[dict[str, Any]]:
    """Per venue, the signals that cannot fire because the evidence does not exist."""
    out = []
    for venue in VENUES:
        missing = []
        if venue not in _OPTIC_SECOND_OPINION:
            missing.append("optic_disagrees (Optic does not map this venue)")
        if venue not in PRICED_VENUES:
            missing.append("price_gap (no venue price in Optic's feed)")
        if venue not in _AI_VALIDATED:
            missing.append("ai_flagged / name_mismatch (AI validator does not cover it)")
        if venue not in _PERIOD_CHECKED:
            missing.append("period_mismatch (Kalshi tickers only)")
        out.append({"platform": venue, "missing": missing})
    return out


def parse_window_bound(raw: str | None, name: str) -> datetime | None:
    """Parse one kickoff window bound (ISO; naive means UTC, like the page's UTC inputs)."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is not an ISO datetime: {text!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def flag_fingerprint(row: dict[str, Any]) -> str:
    """Stable identity of one mapping: venue, venue key, canonical selection."""
    return f"mismap|{row.get('sb')}|{row.get('src_key')}|{row.get('canon')}"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return str(value) if value else None


def _public_row(row: dict[str, Any], scored: dict[str, Any]) -> dict[str, Any]:
    """The fields the page shows, plus the tier and signals."""
    keep = (
        "sb", "book", "src_key", "canon", "src_market", "src_selection", "game_id", "league",
        "market_id", "selection", "selection_line", "points", "mapping_source", "rank_class",
        "is_rfq_winner", "is_override", "venue_price", "fair_price", "exchange_text",
    )  # fmt: skip
    out = {key: row.get(key) for key in keep}
    out["start_date"] = _iso(row.get("start_date"))
    out["tier"] = scored["tier"]
    out["signals"] = scored["signals"]
    out["fingerprint"] = flag_fingerprint(row)
    return out


def _flags_by_fingerprint(store: Any | None) -> dict[str, dict[str, Any]]:
    """Latest version of every mismap flag, keyed by mapping fingerprint."""
    if store is None or not hasattr(store, "list_work_items"):
        return {}
    latest: dict[str, WorkItemRow] = {}
    for item in store.list_work_items():
        if item.source != FLAG_SOURCE:
            continue
        prev = latest.get(item.fingerprint)
        if prev is None or item.updated_at >= prev.updated_at:
            latest[item.fingerprint] = item
    return {fp: _flag_view(item) for fp, item in latest.items()}


def _flag_view(item: WorkItemRow) -> dict[str, Any]:
    extra = dict(item.request_extraction or {})
    return {
        "work_item_id": item.work_item_id,
        "status": item.status,
        "severity": item.severity,
        "note": extra.get("note"),
        "flagged_by": extra.get("flagged_by"),
        "resolved_by": extra.get("resolved_by"),
        "resolution": extra.get("resolution"),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "snapshot": extra.get("snapshot"),
    }


def _matches(
    row: dict[str, Any],
    *,
    platform: str,
    tier: str,
    reason: str,
    needle: str,
    window: tuple[datetime | None, datetime | None],
) -> bool:
    """Filters over one scored public row (facet counts skip the facet's own filter)."""
    if platform and row["sb"] != platform:
        return False
    if tier and row["tier"] != tier:
        return False
    if reason and reason not in {s["code"] for s in row["signals"]}:
        return False
    start = row.get("start_date")
    lo, hi = window
    if lo or hi:
        at = datetime.fromisoformat(start) if start else None
        if at is None or (lo and at < lo) or (hi and at > hi):
            return False
    if needle:
        hay = " ".join(str(row.get(k) or "") for k in ("selection", "market_id", "league", "src_key", "game_id"))
        return needle in hay.lower()
    return True


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Riskiest first; within a tier, served rows, then soonest kickoff."""
    rank = TIER_RANK.get(row["tier"] or "", 0)
    return (-rank, not row.get("is_rfq_winner"), row.get("start_date") or "9999")


def _scored_rows(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Public rows for every mapping with at least one signal."""
    out = []
    for raw in rows:
        scored = score_row(raw, now)
        if scored["tier"] is not None:
            out.append(_public_row(raw, scored))
    return out


def _facets(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Counts by tier, signal and platform over the rows passed in."""
    return {
        "tiers": dict(Counter(r["tier"] for r in rows)),
        "reasons": dict(Counter(s["code"] for r in rows for s in r["signals"])),
        "platforms": dict(Counter(r["sb"] for r in rows)),
    }


def _flagged_only(scored: list[dict[str, Any]], flags: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Open flags, current scoring where the row still scores, else the flag's snapshot."""
    live = {r["fingerprint"]: r for r in scored}
    out = []
    for fp, flag in flags.items():
        if flag["status"] != FLAG_OPEN:
            continue
        row = live.get(fp) or dict(flag.get("snapshot") or {}, fingerprint=fp, signals=[], tier=None)
        out.append(row)
    return out


def score_live_mappings(query_fn: MismapQueryFn | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every live mapping with at least one signal, scored (the alert job's input)."""
    return _scored_rows((query_fn or default_mismap_query)(), now or datetime.now(UTC))


def flags_by_fingerprint(store: Any | None) -> dict[str, dict[str, Any]]:
    """Latest operator flag per mapping fingerprint (open or resolved)."""
    return _flags_by_fingerprint(store)


def list_mapping_risk(
    *,
    platform: str | None = None,
    tier: str | None = None,
    reason: str | None = None,
    q: str | None = None,
    kickoff_from: str | None = None,
    kickoff_to: str | None = None,
    flagged: bool = False,
    limit: int = 100,
    offset: int = 0,
    store: Any | None = None,
    query_fn: MismapQueryFn | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scored mappings, riskiest first, with facets, venue coverage gaps and flags."""
    base = {"rows": [], "count": 0, "facets": _facets([]), "coverage": coverage_notes(), "error": None}
    try:
        window = (parse_window_bound(kickoff_from, "kickoff_from"), parse_window_bound(kickoff_to, "kickoff_to"))
        raw = (query_fn or default_mismap_query)()
    except Exception as exc:  # noqa: BLE001 — surfaced on the page, not a 500
        return {**base, "error": str(exc)}
    flags = _flags_by_fingerprint(store)
    scored = _scored_rows(raw, now or datetime.now(UTC))
    pool = _flagged_only(scored, flags) if flagged else scored
    for row in pool:
        row["flag"] = flags.get(row["fingerprint"])
    opts = {
        "platform": (platform or "").lower(),
        "tier": tier or "",
        "reason": reason or "",
        "needle": (q or "").lower(),
    }
    kept = [r for r in pool if _matches(r, window=window, **opts)]
    kept.sort(key=_sort_key)
    page_size = max(1, min(limit, 500))
    start = max(0, offset)
    return {
        **base,
        "rows": kept[start : start + page_size],
        "count": len(kept),
        "facets": _facets(kept),
        "cached_at": mismap_cached_at() if query_fn is None else None,
    }


def _require_writer(actor: Actor, note: str) -> str:
    if actor.role.value not in _WRITE_ROLES:
        raise ForbiddenError("role cannot flag mappings")
    text = note.strip()
    if not text:
        raise ValidationFailedError("a note saying why is required", reason_code="bad_request", dry_run={})
    return text[:1000]


def flag_mapping(store: Any, actor: Actor, *, row: dict[str, Any], note: str) -> dict[str, Any]:
    """Record an operator's "this mapping is wrong" flag (open). Idempotent per mapping."""
    text = _require_writer(actor, note)
    fingerprint = flag_fingerprint(row)
    if not row.get("sb") or not row.get("src_key") or not row.get("canon"):
        raise ValidationFailedError("row needs sb, src_key and canon", reason_code="bad_request", dry_run={})
    existing = _flags_by_fingerprint(store).get(fingerprint)
    item = WorkItemRow(
        work_item_id=existing["work_item_id"] if existing else new_id("mismap"),
        fingerprint=fingerprint,
        source=FLAG_SOURCE,
        status=FLAG_OPEN,
        league=row.get("league"),
        sportsbook=row.get("book") or row.get("sb"),
        severity=row.get("tier") or "manual",
        request_extraction={"note": text, "flagged_by": actor.subject, "snapshot": row},
        summary=text,
    )
    if existing:
        item.created_at = existing["created_at"]
    store.put_work_item(item)
    return _flag_view(item)


def resolve_flag(store: Any, actor: Actor, *, fingerprint: str, note: str) -> dict[str, Any]:
    """Close a flag with the resolution (fixed via Proposed, false alarm, ...)."""
    text = _require_writer(actor, note)
    existing = _flags_by_fingerprint(store).get(fingerprint)
    if existing is None:
        raise ValidationFailedError("no flag for that mapping", reason_code="not_found", dry_run={})
    extra = {
        "note": existing.get("note"),
        "flagged_by": existing.get("flagged_by"),
        "snapshot": existing.get("snapshot"),
        "resolved_by": actor.subject,
        "resolution": text,
    }
    item = WorkItemRow(
        work_item_id=existing["work_item_id"],
        fingerprint=fingerprint,
        source=FLAG_SOURCE,
        status=FLAG_RESOLVED,
        severity=existing.get("severity"),
        request_extraction=extra,
        summary=text,
        created_at=existing["created_at"],
    )
    store.put_work_item(item)
    return _flag_view(item)

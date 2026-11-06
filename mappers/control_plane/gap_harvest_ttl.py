"""24h harvest memory that survives CronJob pods (BQ tip dataset).

Process-local first; BigQuery ``markets_us.mapping_harvest_ttl`` is the
cross-tick backend. Tests stub BQ. Soft-fail when the table is missing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from BigQuery.client import ro_client
from BigQuery.mapping_rule_rows import HARVEST_TTL_TABLE

logger = logging.getLogger(__name__)

TTL_SEC = 24 * 3600
RECHECK_BEFORE_SEC = 6 * 3600
OPTIC_SKIPPED = "optic_skipped"
DEAD_BUCKETS = "dead_buckets"
POLY_US_EVENTS = "poly_us_events"

_MEM: dict[str, tuple[float, Any]] = {}
_TABLE_READY = False


def clear_ttl_mem() -> None:
    """Drop in-process TTL (tests / new CronJob)."""
    global _TABLE_READY
    _MEM.clear()
    _TABLE_READY = False


def load_ttl(name: str) -> Any:
    """Return unexpired payload, or None."""
    hit = _mem_get(name)
    if hit is not None:
        return hit
    payload = _bq_load(name)
    if payload is not None:
        _mem_put(name, payload)
    return payload


def save_ttl(name: str, payload: Any) -> None:
    """Remember payload for 24h in-process and in BQ."""
    _mem_put(name, payload)
    _bq_save(name, payload)


def load_str_list(name: str) -> list[str]:
    """TTL payload as strings."""
    raw = load_ttl(name)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def save_str_list(name: str, values: set[str] | list[str]) -> None:
    """Store unique strings under ``name``."""
    save_ttl(name, sorted({str(v).strip() for v in values if str(v).strip()}))


def load_optic_skips() -> dict[str, dict[str, str]]:
    """oid → {until, start} for competitor ids we should not re-draft yet."""
    return _normalize_optic_skips(load_ttl(OPTIC_SKIPPED))


def optic_skip_blocks(
    oid: str,
    start: str,
    skips: dict[str, dict[str, str]],
    now: datetime,
) -> bool:
    """True when this Optic id is still in the 24h skip, outside the 6h reopen."""
    if _within_recheck(start, now):
        return False
    row = skips.get(oid) or {}
    until = _parse_dt(str(row.get("until") or ""))
    return until is not None and now < until


def remember_optic_skips(failed: dict[str, str], now: datetime) -> None:
    """Record failed oids without refreshing unexpired skip deadlines."""
    skips = load_optic_skips()
    for oid, start in failed.items():
        _put_optic_skip(skips, oid, start, now)
    save_ttl(OPTIC_SKIPPED, {
        oid: row for oid, row in skips.items()
        if optic_skip_blocks(oid, str(row.get("start") or ""), skips, now)
    })


def load_dead_buckets(book: str) -> set[str]:
    """Kalshi/crypto series that exhausted their miss streak."""
    raw = load_ttl(DEAD_BUCKETS)
    blob = raw if isinstance(raw, dict) else {}
    now = time.time()
    return {key for key, exp in _expiry_map(blob.get(book)).items() if exp > now}


def save_dead_buckets(book: str, dead: set[str]) -> None:
    """Add newly dead series; do not extend unexpired keys."""
    raw = load_ttl(DEAD_BUCKETS)
    blob: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    now = time.time()
    current = {key: exp for key, exp in _expiry_map(blob.get(book)).items() if exp > now}
    for item in dead:
        if item and item not in current:
            current[item] = now + TTL_SEC
    blob[book] = current
    save_ttl(DEAD_BUCKETS, blob)


def _normalize_optic_skips(raw: Any) -> dict[str, dict[str, str]]:
    """Accept {oid: {until, start}} or a legacy list of oids."""
    if isinstance(raw, list):
        until = (datetime.now(UTC) + timedelta(seconds=TTL_SEC)).isoformat()
        return {
            str(oid): {"until": until, "start": ""}
            for oid in raw if str(oid).strip()
        }
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for oid, row in raw.items():
        key = str(oid).strip()
        if not key:
            continue
        if isinstance(row, dict):
            out[key] = {
                "until": str(row.get("until") or ""),
                "start": str(row.get("start") or ""),
            }
        elif isinstance(row, str) and row.strip():
            out[key] = {"until": row.strip(), "start": ""}
    return out


def _put_optic_skip(
    skips: dict[str, dict[str, str]], oid: str, start: str, now: datetime,
) -> None:
    computed = _skip_until(start, now)
    if computed is None:
        skips.pop(oid, None)
        return
    existing = _parse_dt(str((skips.get(oid) or {}).get("until") or ""))
    until = min(existing, computed) if existing and existing > now else computed
    skips[oid] = {"until": until.isoformat(), "start": start}


def _skip_until(start: str, now: datetime) -> datetime | None:
    until = now + timedelta(seconds=TTL_SEC)
    kick = _parse_dt(start)
    if kick is not None:
        until = min(until, kick - timedelta(seconds=RECHECK_BEFORE_SEC))
    return until if until > now else None


def _within_recheck(start: str, now: datetime) -> bool:
    kick = _parse_dt(start)
    if kick is None:
        return False
    return now >= kick - timedelta(seconds=RECHECK_BEFORE_SEC)


def _parse_dt(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _expiry_map(raw: Any) -> dict[str, float]:
    if isinstance(raw, list):
        until = time.time() + TTL_SEC
        return {str(item): until for item in raw if str(item).strip()}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, val in raw.items():
        name = str(key).strip()
        if name and isinstance(val, (int, float)):
            out[name] = float(val)
    return out


def _mem_get(name: str) -> Any:
    hit = _MEM.get(name)
    if hit is None:
        return None
    expires, payload = hit
    if time.time() >= expires:
        _MEM.pop(name, None)
        return None
    return payload


def _mem_put(name: str, payload: Any) -> None:
    _MEM[name] = (time.time() + TTL_SEC, payload)


def _bq_load(name: str) -> Any:
    """Latest unexpired payload for ``name``; None on miss/error."""
    try:
        sql, job = _read_sql(name)
        rows = list(ro_client().query(sql, job_config=job).result())
    except Exception as exc:  # noqa: BLE001 — harvest continues without TTL
        logger.info("harvest ttl load %s skipped: %s", name, str(exc)[:120])
        return None
    if not rows:
        return None
    try:
        return json.loads(str(rows[0].payload or ""))
    except json.JSONDecodeError:
        return None


def _bq_save(name: str, payload: Any) -> None:
    """Append one TTL row; create the table once if needed."""
    global _TABLE_READY
    try:
        client = ro_client()
        if not _TABLE_READY:
            _ensure_table(client)
            _TABLE_READY = True
        now = time.time()
        errors = client.insert_rows_json(
            HARVEST_TTL_TABLE,
            [_ttl_row(name, payload, now)],
        )
        if errors:
            logger.warning("harvest ttl save %s: %s", name, errors[:1])
    except Exception as exc:  # noqa: BLE001 — next tick just rebuilds
        logger.info("harvest ttl save %s skipped: %s", name, str(exc)[:120])


def _read_sql(name: str) -> tuple[str, bigquery.QueryJobConfig]:
    project = os.environ.get("GCP_PROJECT") or ""
    table = f"`{project}.{HARVEST_TTL_TABLE}`" if project else HARVEST_TTL_TABLE
    sql = (
        f"select payload from {table} "  # nosec B608 — table is env project + const
        "where cache_key = @k and expires_at > current_timestamp() "
        "order by stored_at desc limit 1"
    )
    job = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("k", "STRING", name)],
    )
    return sql, job


def _ensure_table(client: bigquery.Client) -> None:
    """Create the TTL table when markets_us is writable."""
    try:
        client.get_table(HARVEST_TTL_TABLE)
        return
    except NotFound:
        pass
    schema = [
        bigquery.SchemaField("cache_key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("stored_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("expires_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("payload", "STRING", mode="REQUIRED"),
    ]
    table = bigquery.Table(f"{client.project}.{HARVEST_TTL_TABLE}", schema=schema)
    client.create_table(table)


def _ttl_row(name: str, payload: Any, now: float) -> dict[str, Any]:
    stamp = datetime.fromtimestamp(now, tz=UTC).isoformat()
    exp = datetime.fromtimestamp(now + TTL_SEC, tz=UTC).isoformat()
    return {
        "cache_key": name,
        "stored_at": stamp,
        "expires_at": exp,
        "payload": json.dumps(payload, default=str),
    }

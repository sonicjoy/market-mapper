"""One card-wide market_mapping read for harvest walks (chat keeps single-key)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_client, ro_query
from mappers.control_plane.chat_tools_mapping import (
    MAPPING_SELECT,
    kalshi_event_ticker,
    mapping_row,
    source_aliases,
)

logger = logging.getLogger(__name__)

BatchQueryFn = Callable[[str, dict[str, list[str]]], list[Any]]
Aliases = dict[str, tuple[str, str, str]]
_ROW_LIMIT = 20000
_PER_KEY = 20
_BATCH_SQL = MAPPING_SELECT + """  and (
    json_value(to_json_string(source_ids), '$.market_id') in unnest(@ids)
    or json_value(to_json_string(source_ids), '$.symbol') in unnest(@ids)
    or json_value(to_json_string(source_ids), '$.selection_id') in unnest(@ids)
    or json_value(to_json_string(source_ids), '$.event_id') in unnest(@ids)
    or regexp_extract(
      json_value(to_json_string(source_ids), '$.market_id'),
      r'^(KX[A-Z0-9]+-[0-9]{2}[A-Z]{3}[0-9]{2}[A-Z0-9]+)-'
    ) in unnest(@events)
  )
order by start_date desc, sportsbook, side
limit __ROW_LIMIT__
"""


def mapping_batch_sql(project: str) -> str:
    """Card-wide market_mapping read over every harvest key."""
    return _BATCH_SQL.replace("{project}", project).replace("__ROW_LIMIT__", str(_ROW_LIMIT))


def lookup_mappings_batch(
    source_ids: list[str],
    *,
    query_fn: BatchQueryFn | None = None,
    project: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Published rows per key from one query; soft miss leaves every key empty."""
    unique = list(dict.fromkeys(s.strip() for s in source_ids if s.strip()))
    if not unique:
        return {}
    aliases = {sid: source_aliases(sid) for sid in unique}
    ids = sorted({val for trio in aliases.values() for val in trio if val})
    events = sorted({ev for _t, ev, _b in aliases.values() if ev.upper().startswith("KX")})
    params = {"ids": ids, "events": events or [""]}
    try:
        raw = _run(params, query_fn, project)
    except Exception as exc:  # noqa: BLE001 — probes fall back to the live catalogue
        logger.warning("gap mapping batch read failed keys=%d: %s", len(unique), exc)
        return {sid: [] for sid in unique}
    if len(raw) >= _ROW_LIMIT:
        logger.warning("gap mapping batch hit row limit=%d keys=%d", _ROW_LIMIT, len(unique))
    return _group_by_source(unique, aliases, raw)


def _run(
    params: dict[str, list[str]],
    query_fn: BatchQueryFn | None,
    project: str | None,
) -> list[Any]:
    if query_fn is not None:
        return list(query_fn(mapping_batch_sql(project or "marketmaking-test"), params))
    proj = project or os.environ.get("GCP_PROJECT") or ""
    if not proj:
        return []
    job = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(name, "STRING", values)
            for name, values in params.items()
        ]
    )
    return list(ro_query(ro_client(), mapping_batch_sql(proj), job_config=job))


def _group_by_source(
    unique: list[str], aliases: Aliases, raw: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    """Same match rules as the single-key SQL, via dict lookups instead of a scan."""
    index = _alias_index(aliases)
    grouped: dict[str, list[dict[str, Any]]] = {sid: [] for sid in unique}
    for item in raw:
        row = mapping_row(item)
        for sid in _row_sources(row, index):
            grouped[sid].append(row)
    for sid, rows in grouped.items():
        rows.sort(
            key=lambda r: (str(r["start_date"]), str(r["sportsbook"]), str(r["side"])),
            reverse=True,
        )
        grouped[sid] = rows[:_PER_KEY]
    return grouped


def _alias_index(aliases: Aliases) -> dict[str, dict[str, set[str]]]:
    index: dict[str, dict[str, set[str]]] = {
        "market_ticker": {}, "symbol": {}, "source_selection_id": {},
        "source_event_id": {}, "event": {},
    }
    for sid, (text, event, base) in aliases.items():
        for field, value in (
            ("market_ticker", text), ("market_ticker", event),
            ("symbol", text), ("symbol", base),
            ("source_selection_id", text), ("source_event_id", text),
        ):
            index[field].setdefault(value, set()).add(sid)
        if event.upper().startswith("KX"):
            index["event"].setdefault(event, set()).add(sid)
    return index


def _row_sources(row: dict[str, Any], index: dict[str, dict[str, set[str]]]) -> set[str]:
    out: set[str] = set()
    for field in ("market_ticker", "symbol", "source_selection_id", "source_event_id"):
        value = str(row.get(field) or "")
        if value:
            out |= index[field].get(value, set())
    mid = str(row.get("market_ticker") or "")
    event = kalshi_event_ticker(mid)
    if mid.upper().startswith("KX") and event != mid:
        out |= index["event"].get(event, set())
    return out

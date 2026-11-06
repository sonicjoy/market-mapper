"""Draft mapping_league when ProphetX RFQ demand hits an unwired tournament.

A tournament already on the tip is probed with the shared PX name bind and
stamped on the RFQ key. A later line on the same event stays on that pin.
A key with no event, or no tip league, records that missing data.
"""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_client, ro_query
from mappers.control_plane.crypto_optic_match import name_sides
from mappers.control_plane.gap_fix_onboard import gap_onboard_enabled, try_onboard_league_pin
from mappers.control_plane.gap_fix_poly_leagues import sport_for
from mappers.control_plane.gap_fix_px import (
    league_for_px_tournament,
    probe_wired_px_rfq,
)
from mappers.control_plane.gap_fix_walk import remember_harvest_key
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_optic_discover import discover_optic_league_id
from mappers.control_plane.rows import LeagueRow

_PX_BOOK = "px"


def harvest_px_rfq_onboard(
    store: Any,
    items: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    rows: list[LeagueRow],
    fixtures: dict[str, list[dict[str, Any]]],
    *,
    event_lookup_fn: Any | None = None,
    fixtures_fn: Any | None = None,
) -> None:
    """Try PX tournament onboard for ranked RFQ inventory keys."""
    if not gap_onboard_enabled():
        return
    for item in items:
        if item.book != "prophetx":
            continue
        meta = dict(item.meta or {})
        event_id = str(meta.get("px_event_id") or "").strip()
        if not event_id:
            skipped.append(_skip(item.key, "no_identity"))
            continue
        before = len(skipped)
        if try_px_league_onboard(
            store,
            event_id,
            item.key,
            pins,
            skipped,
            seen,
            rows,
            fixtures,
            event_lookup_fn=event_lookup_fn,
        ):
            continue
        if _took_needs_probe(skipped, before, item.key):
            _probe_wired_or_restore(
                store, item.key, event_id, pins, skipped, seen, rows,
                event_lookup_fn, fixtures_fn,
            )
            continue
        if len(skipped) == before and not _attach_same_event(pins, item.key):
            _probe_wired_or_restore(
                store, item.key, event_id, pins, skipped, seen, rows,
                event_lookup_fn, fixtures_fn,
            )


def _took_needs_probe(skipped: list[dict[str, str]], before: int, key: str) -> bool:
    if len(skipped) <= before:
        return False
    last = skipped[-1]
    if last.get("key") == key and last.get("reason") == "needs_probe":
        skipped.pop()
        return True
    return False


def _probe_wired_or_restore(
    store: Any,
    gap_key: str,
    event_id: str,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    rows: list[LeagueRow],
    event_lookup_fn: Any | None,
    fixtures_fn: Any | None,
) -> None:
    raw = event_lookup_fn(event_id) if event_lookup_fn is not None else None
    row = league_for_px_tournament(rows, str((raw or {}).get("tournament_id") or ""))
    if isinstance(raw, dict) and row is not None:
        probe_wired_px_rfq(
            store, row, raw, gap_key, pins, skipped, seen, fixtures_fn,
        )
        return
    if not isinstance(raw, dict):
        skipped.append(_skip(gap_key, "no_source_league"))
        return
    skipped.append(_skip(gap_key, "needs_league"))


def _attach_same_event(pins: list[dict[str, Any]], gap_key: str) -> bool:
    """Keep a later line on the pin already drafted for this ProphetX event."""
    event = gap_key.split(":", 1)[0]
    if not event:
        return False
    for pin in pins:
        if str(pin.get("harvest_book") or "") != "prophetx":
            continue
        existing = str(pin.get("harvest_key") or pin.get("gap_key") or "")
        if existing.split(":", 1)[0] != event:
            continue
        remember_harvest_key(pin, {"harvest_book": "prophetx", "harvest_key": gap_key})
        return True
    return False


def try_px_league_onboard(
    store: Any,
    event_id: str,
    gap_key: str,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    rows: list[LeagueRow],
    fixtures: dict[str, list[dict[str, Any]]],
    *,
    event_lookup_fn: Any | None = None,
) -> bool:
    """Onboard PX tournament_id when Optic league is unique for the PX event."""
    fields = _px_event_fields(event_id, gap_key, skipped, event_lookup_fn)
    if fields is None:
        return False
    tournament_id, title, sides, day = fields
    optic_id = discover_optic_league_id(
        {"meta_name": title, "meta_event_date": day},
        sides=sides,
        day=day,
    )
    if not optic_id:
        skipped.append(_skip(gap_key, "missing_optic"))
        return False
    sport = sport_for(optic_id, rows, fixtures)
    return try_onboard_league_pin(
        store,
        optic_id=optic_id,
        sport=sport,
        source_token=tournament_id,
        book=_PX_BOOK,
        pins=pins,
        skipped=skipped,
        seen=seen,
        rows=rows,
        fixtures=fixtures,
        gap_key=gap_key,
        harvest_book="prophetx",
    )


def _px_event_fields(
    event_id: str,
    gap_key: str,
    skipped: list[dict[str, str]],
    event_lookup_fn: Any | None,
) -> tuple[str, str, tuple[str, str], str] | None:
    """Tournament, title, sides, and day, or a recorded missing-data skip."""
    raw = _fetch_px_event(event_id, event_lookup_fn=event_lookup_fn)
    if raw is None:
        skipped.append(_skip(gap_key, "no_source_league"))
        return None
    tournament_id = str(raw.get("tournament_id") or "").strip()
    if not tournament_id:
        skipped.append(_skip(gap_key, "no_source_league"))
        return None
    title = str(raw.get("display_name") or raw.get("name") or "").strip()
    sides = _px_sides(raw) or name_sides(title)
    if sides is None:
        skipped.append(_skip(gap_key, "missing_optic"))
        return None
    day = str(raw.get("scheduled") or "")[:10]
    if len(day) < 10:
        skipped.append(_skip(gap_key, "missing_optic"))
        return None
    return tournament_id, title, sides, day


def _px_sides(raw: dict[str, Any]) -> tuple[str, str] | None:
    comps = raw.get("competitors")
    if not isinstance(comps, list) or len(comps) < 2:
        return None
    home = next((c for c in comps if str(c.get("side") or "").lower() == "home"), None)
    away = next((c for c in comps if str(c.get("side") or "").lower() == "away"), None)
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    hname = str(home.get("display_name") or home.get("name") or "").strip()
    aname = str(away.get("display_name") or away.get("name") or "").strip()
    if hname and aname:
        return hname, aname
    return None


def _fetch_px_event(event_id: str, *, event_lookup_fn: Any | None = None) -> dict[str, Any] | None:
    if event_lookup_fn is not None:
        raw = event_lookup_fn(event_id)
        return raw if isinstance(raw, dict) else None
    proj = os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = f"""
select data
from `{proj}.raw_ingestion_us.px_events_fetch_raw`
where json_value(data, '$.event_id') = @eid
  and fetch_time > timestamp_sub(current_timestamp(), interval 48 hour)
qualify row_number() over (order by fetch_time desc) = 1
"""  # nosec B608
    job = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("eid", "STRING", event_id)],
    )
    try:
        rows = list(ro_query(ro_client(), sql, job_config=job))
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    payload = rows[0].get("data") if isinstance(rows[0], dict) else getattr(rows[0], "data", None)
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _skip(key: str, reason: str) -> dict[str, str]:
    return {"book": "prophetx", "key": key, "reason": reason}

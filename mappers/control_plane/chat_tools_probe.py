"""Exchange probes for Mapper Chat (read-only, soft miss)."""

from __future__ import annotations

import json
import os
from typing import Any

import requests
from google.cloud import bigquery

from BigQuery.client import ro_client, ro_query
from fetch.polymarket_gamma import GAMMA_BASE, normalize_market
from mappers.control_plane.entry import LiveLookup

# Latest-row probes are not snapshot-anchored: prune to retained history so
# they do not scan every daily partition.  21 days matches current fetch_raw
# retention; QUALIFY still picks the newest row inside that window.
_FETCH_RAW_LOOKBACK = (
    "fetch_time > timestamp_sub(current_timestamp(), interval 21 day)"
)


def probe_optic_fixture(fixture_id: str) -> dict[str, Any]:
    """Soft Optic fixture probe — requires OPTIC key in env/GSM for live hit."""
    fixture_id = fixture_id.strip()
    if not fixture_id:
        return {"ok": False, "seen": False, "error": "empty_fixture_id"}
    try:
        from mappers.control_plane.suggest_aliases import _optic_headers

        resp = requests.get(
            "https://api.opticodds.com/api/v3/fixtures",
            params={"id": fixture_id},
            headers=_optic_headers(),
            timeout=10,
        )
        if resp.status_code >= 400:
            return {"ok": True, "seen": False, "fixture_id": fixture_id}
        payload = resp.json()
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        if not rows:
            return {"ok": True, "seen": False, "fixture_id": fixture_id}
        row = rows[0]
        return {
            "ok": True,
            "seen": True,
            "fixture_id": row.get("id") or fixture_id,
            "start_date": row.get("start_date"),
            "home": (row.get("home_competitors") or [{}])[0].get("name"),
            "away": (row.get("away_competitors") or [{}])[0].get("name"),
        }
    except Exception as exc:  # noqa: BLE001 — soft
        return {"ok": False, "seen": False, "fixture_id": fixture_id, "error": str(exc)[:160]}


def probe_optic_competitor(competitor_id: str, name: str | None = None) -> dict[str, Any]:
    """Best-effort competitor citation (id/name only; no open search)."""
    return {
        "ok": True,
        "competitor_id": competitor_id.strip(),
        "name": (name or "").strip() or None,
        "note": "Use suggest_aliases / fixture probe for league-scoped evidence.",
    }


def probe_crypto_symbol(symbol: str) -> dict[str, Any]:
    """Soft crypto.com symbol parse — no catalogue write."""
    symbol = symbol.strip()
    if not symbol:
        return {"ok": False, "seen": False, "error": "empty_symbol"}
    parts = symbol.split(".")
    return {
        "ok": True,
        "seen": symbol.upper().startswith("NX."),
        "symbol": symbol,
        "segments": parts[:6],
        "note": "Catalogue confirmation is soft; prefer tip entities / RFQ gap tools.",
    }


def probe_live_seen(live: LiveLookup, paste: str, sportsbook: str | None) -> dict[str, Any]:
    """Delegate to LiveLookup (cached in production wiring)."""
    return {
        "seen": live.seen(paste, sportsbook=sportsbook),
        "paste": paste,
        "sportsbook": sportsbook,
    }


def probe_polymarket_id(source_id: str, *, by: str = "condition") -> dict[str, Any]:
    """One Gamma /markets lookup; soft miss. ``by`` is condition or position."""
    ident = source_id.strip()
    params: list[tuple[str, str | int]] = [("limit", 5)]
    if by == "condition":
        if not ident.lower().startswith("0x"):
            ident = f"0x{ident.lower()}"
        params.append(("condition_ids", ident))
    else:
        params.append(("position_ids", ident))
    try:
        resp = requests.get(f"{GAMMA_BASE}/markets", params=params, timeout=6)
        if resp.status_code >= 400:
            return {"seen": False, "error": f"gamma_{resp.status_code}"}
        payload = resp.json()
        markets = payload if isinstance(payload, list) else payload.get("data") or []
        if not markets:
            return {"seen": False}
        return _poly_fields(normalize_market(markets[0]))
    except Exception as exc:  # noqa: BLE001 — chat tools soft-fail
        return {"seen": False, "error": str(exc)[:160]}


def _poly_fields(market: dict[str, Any]) -> dict[str, Any]:
    """Gamma market fields the probe table can show."""
    question = str(market.get("question") or "")
    return {
        "seen": True,
        "title": question,
        "question": question,
        "slug": str(market.get("slug") or ""),
        "outcomes": list(market.get("outcomes") or []),
        "game_start_time": str(market.get("game_start_time") or ""),
        "kickoff": str(market.get("game_start_time") or market.get("end_date") or ""),
        "condition_id": str(market.get("condition_id") or ""),
    }


def probe_px_id(source_id: str, *, query_fn: Any = None) -> dict[str, Any]:
    """Latest PX event or market snapshot for a numeric id; soft miss."""
    ident = source_id.strip()
    if not ident:
        return {"seen": False}
    try:
        rows = query_fn(_px_sql(), {"id": ident}) if query_fn is not None else _px_bq(ident)
    except Exception as exc:  # noqa: BLE001 — chat tools soft-fail
        return {"seen": False, "error": str(exc)[:160]}
    if not rows:
        return {"seen": False}
    return _px_fields(rows[0])


def _px_sql() -> str:
    """Latest event or market fetch row for one Prophet X id."""
    project = os.environ.get("GCP_PROJECT") or "marketmaking-test"
    return f"""
(
  select 'event' as kind, event_id as source_id, tournament_id, data
  from `{project}.raw_ingestion_us.px_events_fetch_raw`
  where event_id = @id
    and {_FETCH_RAW_LOOKBACK}
  qualify row_number() over (order by fetch_time desc) = 1
)
union all
(
  select 'market' as kind, market_id as source_id, tournament_id, data
  from `{project}.raw_ingestion_us.px_markets_fetch_raw`
  where market_id = @id
    and {_FETCH_RAW_LOOKBACK}
  qualify row_number() over (order by fetch_time desc) = 1
)
"""  # nosec B608 — project is env/default; @id is bound


def _px_bq(source_id: str) -> list[Any]:
    """Live parameterized PX snapshot read."""
    return _id_query(_px_sql(), source_id)


def _id_query(sql: str, source_id: str) -> list[Any]:
    """Live parameterized source-id lookup."""
    job = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", source_id)]
    )
    return list(ro_query(ro_client(), sql, job_config=job))


def _px_fields(row: Any) -> dict[str, Any]:
    """Title / kickoff / sides from a PX fetch snapshot row."""
    payload = row.get("data") if isinstance(row, dict) else getattr(row, "data", None)
    data = _px_json(payload)
    comps = data.get("competitors") or []
    names = [str(c.get("name") or c.get("abbreviation") or "") for c in comps if isinstance(c, dict)]
    home = names[0] if names else ""
    away = names[1] if len(names) > 1 else ""
    title = str(data.get("name") or data.get("market_name") or "")
    if not title and home and away:
        title = f"{home} vs {away}"
    kind = str(row.get("kind") if isinstance(row, dict) else getattr(row, "kind", "") or "")
    tour = str(
        data.get("tournament_name")
        or (row.get("tournament_id") if isinstance(row, dict) else getattr(row, "tournament_id", ""))
        or ""
    )
    return {
        "seen": True,
        "title": title,
        "home": home,
        "away": away,
        "scheduled": str(data.get("scheduled") or ""),
        "kickoff": str(data.get("scheduled") or ""),
        "tournament": tour,
        "league": str(data.get("sport_name") or tour),
        "id_kind": f"px_{kind}" if kind else "px_id",
    }


def _px_json(payload: Any) -> dict[str, Any]:
    """Decode the fetch snapshot ``data`` JSONL blob."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            parsed = json.loads(payload)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def probe_novig_id(source_id: str, *, query_fn: Any = None) -> dict[str, Any]:
    """Latest Novig event, market, or outcome snapshot; soft miss."""
    ident = source_id.strip()
    if not ident:
        return {"seen": False}
    try:
        rows = query_fn(_novig_sql(), {"id": ident}) if query_fn is not None else _novig_bq(ident)
    except Exception as exc:  # noqa: BLE001 — chat tools soft-fail
        return {"seen": False, "error": str(exc)[:160]}
    if not rows:
        return {"seen": False}
    return _novig_fields(rows[0], ident)


def _novig_sql() -> str:
    """Latest event, market, or outcome fetch row for one Novig id."""
    project = os.environ.get("GCP_PROJECT") or "marketmaking-test"
    table = f"`{project}.raw_ingestion_us.novig_fetch_raw`"
    return f"""
(
  select 'event' as hit, kind, league, data
  from {table}
  where kind = 'events' and json_value(data, '$.id') = @id
    and {_FETCH_RAW_LOOKBACK}
  qualify row_number() over (order by fetch_time desc) = 1
)
union all
(
  select 'market' as hit, kind, league, data
  from {table}
  where kind = 'markets' and json_value(data, '$.id') = @id
    and {_FETCH_RAW_LOOKBACK}
  qualify row_number() over (order by fetch_time desc) = 1
)
union all
(
  select 'outcome' as hit, kind, league, data
  from {table}
  where kind = 'markets'
    and {_FETCH_RAW_LOOKBACK}
    and exists (
      select 1 from unnest(json_query_array(data, '$.outcomes')) as o
      where json_value(o, '$.id') = @id
    )
  qualify row_number() over (order by fetch_time desc) = 1
)
"""  # nosec B608 — project is env/default; @id is bound


def _novig_bq(source_id: str) -> list[Any]:
    """Live parameterized Novig snapshot read."""
    return _id_query(_novig_sql(), source_id)


def _novig_fields(row: Any, ident: str) -> dict[str, Any]:
    """Title / kickoff / Optic fixture from a Novig fetch snapshot row."""
    payload = row.get("data") if isinstance(row, dict) else getattr(row, "data", None)
    data = _px_json(payload)
    hit = str((row.get("hit") if isinstance(row, dict) else getattr(row, "hit", None)) or "")
    league = str(
        (row.get("league") if isinstance(row, dict) else getattr(row, "league", None))
        or data.get("league")
        or ""
    )
    title, outcomes = _novig_title(data, hit, ident)
    kickoff = str(data.get("scheduledStart") or "")
    return {
        "seen": True,
        "sportsbook": "novig",
        "id_kind": f"novig_{hit}" if hit else "novig_id",
        "title": title,
        "league": league,
        "kickoff": kickoff,
        "scheduled": kickoff,
        "fixture_id": str(data.get("opticOddsId") or ""),
        "outcomes": outcomes,
        "novig_type": str(data.get("type") or ""),
        "event_id": str(data.get("eventId") or data.get("id") or ""),
    }


def _novig_title(data: dict[str, Any], hit: str, ident: str) -> tuple[str, list[str]]:
    """Event/market description plus outcome labels."""
    raw = [item for item in (data.get("outcomes") or []) if isinstance(item, dict)]
    outcomes = [str(item.get("description") or item.get("id") or "") for item in raw]
    title = str(data.get("description") or "")
    if hit == "outcome":
        for item in raw:
            if str(item.get("id") or "") == ident:
                title = str(item.get("description") or title)
                break
    return title, [label for label in outcomes if label]

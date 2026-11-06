"""Console unmapped-leg inventory (titles + demand; not gap harvest)."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.bq_ttl_cache import ttl_cached
from mappers.control_plane.console_fixture_phase import (
    normalize_fixture_phase,
    row_is_open,
    row_matches_phase,
)
from mappers.control_plane.crypto_rfq_symbols_sql import crypto_rfq_mf_cte
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_fix_sxbet import fetch_sx_markets, market_hash_of, sport_of_label
from mappers.control_plane.gap_inventory import _kickoff_date
from mappers.control_plane.rfq_latest_sql import render_rfq_filters
from mappers.exchanges import sxbet

UnmappedQueryFn = Callable[[dict[str, Any]], list[dict[str, Any]]]

_CRYPTO_SPORT = re.compile(r"^NX\.F\.OPT\.([A-Z0-9]+)", re.I)

_CONSOLE_UNMAPPED_HEAD = """
with kalshi_legs as (
  select
    json_value(l.platform_mapping, '$.event_ticker') as event_ticker,
    json_value(l.platform_mapping, '$.market_ticker') as market_ticker,
    lower(json_value(l.platform_mapping, '$.side')) as kalshi_side,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __KALSHI__
    and __UNMAPPED_FAILED__
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
),
-- Kickoff from the mapping fetch's own rows: each carries Kalshi's
-- milestone (start_date), keyed by event_ticker.  Tickers are never read.
kalshi_start as (
  select
    event_ticker,
    max(safe_cast(json_value(data, '$.milestone.start_date') as timestamp)) as start_at
  from `{project}.raw_ingestion_us.kalshi_fetch_raw`
  where fetch_time > timestamp_sub(current_timestamp(), interval 3 hour)
  group by event_ticker
),
kalshi_mapped as (
  select distinct
    json_value(to_json_string(source_ids), '$.market_id') as market_ticker,
    lower(json_value(to_json_string(source_ids), '$.selection_id')) as kalshi_side
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Kalshi'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
kalshi as (
  select
    'kalshi' as platform,
    k.event_ticker as key,
    k.event_ticker as platform_leg_description,
    count(*) as demand,
    max(k.last_updated) as last_seen,
    cast(null as string) as league,
    cast(null as string) as sport,
    cast(null as float64) as ttko_hours,
    k.event_ticker as fixture,
    cast(null as string) as slug,
    max(s.start_at) as start_at
  from kalshi_legs k
  -- ticker AND side: a mapped Yes does not clear the No of the same ticker.
  -- No side on the leg falls back to ticker-only (not a fresh true gap).
  left join kalshi_mapped m
    on m.market_ticker = k.market_ticker
   and (k.kalshi_side is null or m.kalshi_side = k.kalshi_side)
  left join kalshi_start s on s.event_ticker = k.event_ticker
  where k.event_ticker is not null
    and m.market_ticker is null
  group by 1, 2, 3
),
"""
_CONSOLE_UNMAPPED_TAIL = """
crypto_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.symbol') as symbol
  from `{project}.markets_us.market_mapping`
  where lower(sportsbook) = 'crypto.com'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
crypto as (
  select
    'crypto' as platform,
    c.symbol as key,
    c.symbol as platform_leg_description,
    count(*) as demand,
    max(c.last_updated) as last_seen,
    cast(null as string) as league,
    cast(null as string) as sport,
    cast(null as float64) as ttko_hours,
    c.symbol as fixture,
    cast(null as string) as slug,
    cast(null as timestamp) as start_at
  from crypto_mf c
  left join crypto_mapped m using (symbol)
  where c.symbol is not null and m.symbol is null
  group by 1, 2, 3
),
poly_legs as (
  select
    r.platform,
    json_value(l.platform_mapping, '$.token_id') as position_id,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and r.platform in ('polymarket', 'polymarket-cashout')
    and __UNMAPPED_FAILED__
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
),
bridge as (
  select
    position_id,
    any_value(clob_token_id) as clob_token_id,
    any_value(question) as question,
    any_value(outcome_label) as outcome_label,
    any_value(slug) as slug,
    any_value(game_start_time) as game_start_time
  from `{project}.raw_ingestion_us.polymarket_position_token_bridge`
  where last_updated > timestamp_sub(current_timestamp(), interval 14 day)
  group by position_id
),
poly_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.selection_id') as clob_token_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Polymarket'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
poly as (
  select
    'polymarket' as platform,
    u.position_id as key,
    any_value(trim(concat(
      coalesce(b.question, u.position_id),
      case when b.outcome_label is not null then concat(' — ', b.outcome_label) else '' end
    ))) as platform_leg_description,
    count(*) as demand,
    max(u.last_updated) as last_seen,
    cast(null as string) as league,
    cast(null as string) as sport,
    cast(null as float64) as ttko_hours,
    any_value(coalesce(b.question, u.position_id)) as fixture,
    any_value(b.slug) as slug,
    any_value(b.game_start_time) as start_at
  from poly_legs u
  left join bridge b on b.position_id = u.position_id
  left join poly_mapped m on m.clob_token_id = b.clob_token_id
  where u.position_id is not null and m.clob_token_id is null
  group by 1, 2
),
-- SX: unmapped legs keyed on Optic's SX selection_id (maker-suffix flip: a
-- taker on outcome one reads "<hash>|two"). SX's market text is not in a
-- dataset this service reads; list_unmapped_legs fills it from SX's public
-- /markets/find (gap_fix_sxbet).
sxbet_legs as (
  select
    lower(json_value(l.platform_mapping, '$.market_hash')) as market_hash,
    json_value(l.platform_mapping, '$.betting_outcome_one') as taker_outcome_one,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __SXBET__
    and __SXBET_GAP__
    and l.optic_fixture_id is null
),
sxbet_mapped as (
  select distinct lower(json_value(to_json_string(source_ids), '$.selection_id')) as selection_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'SX Bet'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
sxbet as (
  select
    'sxbet' as platform,
    concat(s.market_hash, '|', if(s.taker_outcome_one = 'true', 'two', 'one')) as key,
    any_value(s.market_hash) as platform_leg_description,
    count(*) as demand,
    max(s.last_updated) as last_seen,
    cast(null as string) as league,
    cast(null as string) as sport,
    cast(null as float64) as ttko_hours,
    any_value(s.market_hash) as fixture,
    cast(null as string) as slug,
    cast(null as timestamp) as start_at
  from sxbet_legs s
  left join sxbet_mapped m
    on m.selection_id = concat(s.market_hash, '|', if(s.taker_outcome_one = 'true', 'two', 'one'))
  where s.market_hash is not null
    and s.taker_outcome_one in ('true', 'false')
    and m.selection_id is null
  group by 1, 2
)
select * from kalshi
union all select * from crypto
union all select * from poly
union all select * from sxbet
order by demand desc
limit @limit offset @offset
"""
_CONSOLE_UNMAPPED_SQL = render_rfq_filters(
    _CONSOLE_UNMAPPED_HEAD + crypto_rfq_mf_cte(hours=3) + _CONSOLE_UNMAPPED_TAIL
)


def _bq_project() -> str:
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


# Unmapped re-fetches on every filter / tab change; RFQ failures move on the
# 15-min pipeline tick, so a short memo turns page churn into one scan.
UNMAPPED_TTL_SECONDS = 180.0


def _default_unmapped_query(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Inventory rows, memoised per (limit, offset) for ``UNMAPPED_TTL_SECONDS``."""
    key = (int(params.get("limit") or 100), int(params.get("offset") or 0))
    return ttl_cached("console_unmapped", key, lambda: _run_unmapped_query(params), ttl=UNMAPPED_TTL_SECONDS)


def _run_unmapped_query(params: dict[str, Any]) -> list[dict[str, Any]]:
    project = _bq_project()
    sql = _CONSOLE_UNMAPPED_SQL.format(project=project)
    client = bigquery.Client(project=project)
    job = ro_query(
        client,
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("limit", "INT64", int(params.get("limit") or 100)),
                bigquery.ScalarQueryParameter("offset", "INT64", int(params.get("offset") or 0)),
            ]
        ),
    )
    return [dict(row) for row in job]


def _as_utc(value: Any, *, date_only: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        hour = 23 if date_only else 0
        minute = 59 if date_only else 0
        return datetime(value.year, value.month, value.day, hour, minute, tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _ttko_hours(start: datetime | None) -> float | None:
    if start is None:
        return None
    return (start - datetime.now(UTC)).total_seconds() / 3600.0


def build_unmapped_tip_index(store: Any | None) -> dict[str, Any]:
    """Polymarket slug → tip league/sport."""
    poly: dict[str, tuple[str, str]] = {}
    rid = getattr(store, "current_rule_set_id", None) if store is not None else None
    if not rid or store is None or not hasattr(store, "leagues_for"):
        return {"poly": poly}
    for row in store.leagues_for(rid):
        slug = str(row.league or "").strip()
        sport = str(row.sport or "").strip()
        if not slug:
            continue
        hit = (slug, sport)
        for ex in row.exchanges or []:
            book = str(ex.get("sportsbook") or "").lower()
            if book == "polymarket" and ex.get("enabled") is not False:
                settings = ex.get("settings") or {}
                if isinstance(settings, dict):
                    pfx = str(settings.get("slug_prefix") or "").strip().lower()
                    if pfx and pfx not in poly:
                        poly[pfx] = hit
    return {"poly": poly}


def _match_poly(slug: str, index: dict[str, Any]) -> tuple[str, str] | None:
    prefix = str(slug or "").strip().split("-", 1)[0].lower()
    if not prefix:
        return None
    hit = (index.get("poly") or {}).get(prefix)
    if hit is None:
        return None
    return hit


def _crypto_sport(symbol: str) -> str:
    matched = _CRYPTO_SPORT.match(symbol.strip())
    if matched is None:
        return ""
    token = matched.group(1).lower()
    if token in {"fifa", "soccer"}:
        return "soccer"
    return token


def enrich_unmapped_row(row: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    """Fill league, sport, fixture, start_date, ttko from typed starts / crypto symbol."""
    platform = str(row.get("platform") or "").lower()
    key = str(row.get("key") or "")
    fixture = str(row.get("fixture") or row.get("platform_leg_description") or key)
    league = str(row.get("league") or "").strip()
    sport = str(row.get("sport") or "").strip()
    kickoff_date_only = False
    kickoff_day: date | None = None
    start = _as_utc(row.get("start_at") or row.get("start_date"))
    if start is None:
        kick = _kickoff_date(platform, key)
        if kick is not None and platform == "crypto":
            kickoff_date_only = True
            kickoff_day = kick
        start = _as_utc(kick, date_only=True)
    if platform == "polymarket" and not league:
        hit = _match_poly(str(row.get("slug") or ""), index)
        if hit:
            league, sport = hit
    elif platform == "crypto" and not sport:
        sport = _crypto_sport(key)
    out = dict(row)
    out["fixture"] = fixture
    out["league"] = league or None
    out["league_label"] = league_label(league) if league else None
    out["sport"] = sport or None
    out["start_date"] = start.isoformat() if start else None
    out["ttko_hours"] = _ttko_hours(start)
    out["kickoff_date_only"] = kickoff_date_only
    out["kickoff_day"] = kickoff_day.isoformat() if kickoff_day else None
    out.pop("slug", None)
    out.pop("start_at", None)
    return out


def enrich_sxbet_rows(
    rows: list[dict[str, Any]],
    *,
    fetch_fn: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Fill SX rows' title / league / sport / start from SX's own catalogue; rows unchanged on failure."""
    sx_rows = [row for row in rows if row.get("platform") == "sxbet" and row.get("key")]
    if not sx_rows:
        return rows
    try:
        markets = (fetch_fn or fetch_sx_markets)([market_hash_of(str(r["key"])) for r in sx_rows])
    except Exception:  # noqa: BLE001 — titles are cosmetic; the inventory row stands
        return rows
    for row in sx_rows:
        m = sxbet.market_from_row(markets.get(market_hash_of(str(row["key"]))) or {})
        if m is None:
            continue
        taker_one = str(row["key"]).endswith("|two")
        side = m.outcome_one if taker_one else m.outcome_two
        row["platform_leg_description"] = f"{m.team_one} v {m.team_two} — {side}"
        row["fixture"] = f"{m.team_one} v {m.team_two}"
        row["league"] = row.get("league") or m.league_label
        row["sport"] = row.get("sport") or sport_of_label(m.sport) or m.sport.lower()
        if m.start and not row.get("start_at"):
            row["start_at"] = m.start
    return rows


def _filter_open_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop completed legs outside the in-play lookback; keep TBD start."""
    return [row for row in rows if row_is_open(row.get("ttko_hours"))]


def _filter_phase(rows: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    tab = normalize_fixture_phase(phase)
    return [row for row in rows if row_matches_phase(row, tab)]


def _apply_filters(
    rows: list[dict[str, Any]],
    *,
    platform: str | None,
    league: str | None,
    sport: str | None,
    q: str | None,
) -> list[dict[str, Any]]:
    out = rows
    if platform:
        plat = platform.lower()
        if plat in {"crypto.com", "cryptocom"}:
            plat = "crypto"
        out = [r for r in out if str(r.get("platform") or "").lower() == plat]
    if league:
        needle = league.lower()
        out = [
            r
            for r in out
            if needle in str(r.get("league") or "").lower() or needle in str(r.get("league_label") or "").lower()
        ]
    if sport:
        out = [r for r in out if str(r.get("sport") or "").lower() == sport.lower()]
    if q:
        needle = q.lower()
        out = [
            r
            for r in out
            if needle in str(r.get("platform_leg_description") or "").lower()
            or needle in str(r.get("key") or "").lower()
            or needle in str(r.get("fixture") or "").lower()
            or needle in str(r.get("league") or "").lower()
            or needle in str(r.get("sport") or "").lower()
        ]
    return out


def list_unmapped_legs(
    *,
    platform: str | None = None,
    league: str | None = None,
    sport: str | None = None,
    q: str | None = None,
    phase: str = "live",
    sort: str = "start",
    sort_dir: str = "asc",
    limit: int = 100,
    offset: int = 0,
    query_fn: UnmappedQueryFn | None = None,
    store: Any | None = None,
    sx_fetch_fn: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Inventory table for Explore → Unmapped."""
    fetch = query_fn or _default_unmapped_query
    error = ""
    try:
        raw = fetch({"limit": max(limit, 500), "offset": 0})
    except Exception as exc:
        raw = []
        error = str(exc)
    raw = enrich_sxbet_rows(raw, fetch_fn=sx_fetch_fn)
    index = build_unmapped_tip_index(store)
    enriched = [enrich_unmapped_row(row, index) for row in raw]
    open_rows = _filter_open_rows(enriched)
    phased = _filter_phase(open_rows, phase)
    filtered = _apply_filters(phased, platform=platform, league=league, sport=sport, q=q)
    reverse = sort_dir.lower() == "desc"
    if sort in {"ttko", "start"}:
        filtered.sort(
            key=lambda r: (r.get("ttko_hours") is None, r.get("ttko_hours") or 9999),
            reverse=reverse,
        )
    elif sort == "last_seen":
        filtered.sort(key=lambda r: str(r.get("last_seen") or ""), reverse=reverse)
    else:
        filtered.sort(key=lambda r: int(r.get("demand") or 0), reverse=reverse)
    page = filtered[offset : offset + max(1, min(limit, 500))]
    return {
        "count": len(filtered),
        "limit": limit,
        "offset": offset,
        "rows": page,
        "note": "Inventory only — presence does not require mapping.",
        "error": error or None,
    }

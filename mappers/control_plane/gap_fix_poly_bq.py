"""BQ fetches for Polymarket US gap harvest (RFQ events + Optic window).

US events come from the gateway's typed fields: each wanted inner's
``/v2/leagues/{inner}/events`` is walked and an event counts when one of its
markets is an RFQ leg's symbol (exact match — symbols are never split).
Inner, teams and kickoff are the gateway record's.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from fetch.polymarket_usa import league_events, market_record
from mappers.control_plane.gap_harvest_ttl import (
    POLY_US_EVENTS,
    load_dead_buckets,
    load_ttl,
    save_ttl,
)
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.seed.poly_usa_exchange import us_league_code

UsEventsFn = Callable[[], list[dict[str, Any]]]
OfficialEventsFn = Callable[[], list[dict[str, Any]]]
OpticRowsFn = Callable[[], list[dict[str, Any]]]

# Wide partition prune for close US symbols (table is partitioned on publish time).
CLOSE_PUBLISH_DAYS = 14

_US_EVENTS_SQL = """
select distinct lower(coalesce(
      json_value(l.platform_mapping, '$.ticker'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.symbol')
    )) as symbol
from `{project}.reporting_us.rfq_latest` as r, unnest(r.legs) as l
where lower(r.platform) like '%polymarket%us%'
  and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
  and r.last_updated > timestamp_sub(current_timestamp(), interval 3 hour)
  and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
  and (l.optic_fixture_id is null or l.market is null or l.selection is null)
"""

_US_CLOSE_EVENTS_SQL = """
select distinct lower(coalesce(
      json_value(l.platform_mapping, '$.ticker'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.symbol')
    )) as symbol
from `{project}.reporting_us.rfq_latest` as r, unnest(r.legs) as l
where lower(r.platform) like '%polymarket%us%'
  and r.first_publish_time > timestamp_sub(current_timestamp(), interval {publish_days} day)
  and r.last_updated > timestamp_sub(current_timestamp(), interval 24 hour)
"""

_OPTIC_WINDOW_SQL = """
select
  league.id as optic_league_id,
  league.name as optic_league_name,
  game_id as fixture_id,
  date(start_date) as d,
  start_date,
  home_team_display as home_name,
  away_team_display as away_name,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.id') as home_id,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.id') as away_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.abbreviation') as home_abbr,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.abbreviation') as away_abbr,
  json_value(to_json_string(sport), '$.id') as sport
from `{project}.opticodds_us.opticodds_fixtures`
where start_date between timestamp_sub(current_timestamp(), interval 10 day)
  and timestamp_add(current_timestamp(), interval 10 day)
  {league_filter}
"""

_OFFICIAL_EVENTS_SQL = """
select
  regexp_extract(b.slug, r'^([a-z0-9]+)-') as prefix,
  any_value(b.question) as question,
  any_value(b.outcome_label) as outcome_label,
  cast(date(any_value(b.game_start_time)) as string) as d,
  any_value(b.slug) as slug
from `{project}.reporting_us.rfq_latest` as r
cross join unnest(r.legs) as l
inner join `{project}.raw_ingestion_us.polymarket_position_token_bridge` as b
  on b.position_id = json_value(l.platform_mapping, '$.token_id')
where lower(r.platform) like 'polymarket%'
  and lower(r.platform) not like '%us%'
  and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
  and r.last_updated > timestamp_sub(current_timestamp(), interval 3 hour)
  and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
  and (l.optic_fixture_id is null or l.market is null or l.selection is null)
  and b.last_updated > timestamp_sub(current_timestamp(), interval 14 day)
  and regexp_extract(b.slug, r'^([a-z0-9]+)-') in unnest(@prefixes)
group by
  regexp_extract(b.slug, r'^([a-z0-9]+)-'),
  regexp_extract(b.slug, r'(\\d{{4}}-\\d{{2}}-\\d{{2}})'),
  split(b.slug, '-')[safe_offset(1)],
  split(b.slug, '-')[safe_offset(2)]
"""

_OPTIC_FIELDS = (
    "optic_league_id",
    "optic_league_name",
    "fixture_id",
    "d",
    "start_date",
    "home_name",
    "away_name",
    "home_id",
    "away_id",
    "home_abbr",
    "away_abbr",
    "sport",
)


def fetch_poly_us_events(
    prefixes: list[str],
    *,
    project: str | None = None,
    query_fn: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """US RFQ events in the inventory window, filtered to ``prefixes``."""
    wanted = {p.strip().casefold() for p in prefixes if p and p.strip()}
    if not wanted:
        return []
    have, cached = _ttl_us_blob()
    if query_fn is None and wanted <= have:
        return _events_for(cached, wanted)
    missing = wanted if query_fn is not None else wanted - have
    fresh = _query_us_events(missing, project, query_fn) if missing else []
    if query_fn is not None:
        return fresh
    prefixes_out, events = _union_us_events(cached, fresh, have, wanted)
    save_ttl(POLY_US_EVENTS, {"prefixes": sorted(prefixes_out), "events": events})
    return _events_for(events, wanted)


def fetch_close_us_events(
    prefixes: list[str],
    *,
    project: str | None = None,
    query_fn: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """US RFQ events updated in 24h, including horizon-blocked RFQ."""
    wanted = {p.strip().casefold() for p in prefixes if p and p.strip()}
    if not wanted:
        return []
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = _US_CLOSE_EVENTS_SQL.format(
        project=proj, publish_days=CLOSE_PUBLISH_DAYS,
    )
    rows = query_fn(sql) if query_fn is not None else _query(proj, sql)
    return _dedupe_us_events(rows, wanted)


def optic_rows_from_cache(
    store: Any,
    prefixes: Sequence[str],
) -> list[dict[str, Any]]:
    """Optic fixtures from the harvest process cache for wired US inners only."""
    wanted = {str(p).strip().casefold() for p in prefixes if str(p).strip()}
    if not wanted:
        return []
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    rows: list[dict[str, Any]] = []
    for lg in store.leagues_for(rid):
        if not lg.enabled or lg.tombstone:
            continue
        code = us_league_code(lg).casefold()
        if code not in wanted:
            continue
        horizon = optic_horizon_hours(lg)
        oids = [str(lg.optic_league_id or "").strip()]
        oids.extend(str(x).strip() for x in (lg.extra_optic_league_ids or []))
        for oid in oids:
            if not oid:
                continue
            for game in cached_optic_fixtures(oid, horizon_hours=horizon):
                row = dict(game)
                row["optic_league_id"] = oid
                rows.append(row)
    return rows


def fetch_poly_official_events(
    prefixes: list[str],
    *,
    project: str | None = None,
    query_fn: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Official-bridge RFQ gaps in the inventory window, filtered to ``prefixes``."""
    wanted = {p.strip().casefold() for p in prefixes if p and p.strip()}
    wanted -= {p.casefold() for p in load_dead_buckets("polymarket")}
    if not wanted:
        return []
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = _OFFICIAL_EVENTS_SQL.format(project=proj)
    raw = list(
        query_fn(sql) if query_fn is not None
        else _query(proj, sql, prefixes=sorted(wanted))
    )
    return _dedupe_official_events(raw, wanted)


def fetch_optic_window(
    *,
    project: str | None = None,
    query_fn: Callable[[str], Any] | None = None,
    optic_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Optic fixtures in a ±10 day window for unique-league matching."""
    ids = [str(oid).strip() for oid in (optic_ids or []) if str(oid).strip()]
    if optic_ids is not None and not ids:
        return []
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    extra = "and league.id in unnest(@optic_ids)" if optic_ids is not None else ""
    sql = _OPTIC_WINDOW_SQL.format(project=proj, league_filter=extra)
    raw = list(
        query_fn(sql) if query_fn is not None
        else _query(proj, sql, optic_ids=ids or None)
    )
    return [_optic_row(row) for row in raw]


def persist_us_events_ttl(events: list[dict[str, Any]]) -> None:
    """Keep this tick's rows in the union blob after the harvest."""
    if not events:
        return
    have, cached = _ttl_us_blob()
    prefixes, merged = _union_us_events(cached, events, have, {
        str(row.get("inner") or "").casefold() for row in events if row.get("inner")
    })
    save_ttl(POLY_US_EVENTS, {"prefixes": sorted(prefixes), "events": merged})


def _ttl_us_blob() -> tuple[set[str], list[dict[str, Any]]]:
    blob = load_ttl(POLY_US_EVENTS)
    if not isinstance(blob, dict):
        return set(), []
    have = {
        str(prefix).casefold()
        for prefix in (blob.get("prefixes") or [])
        if str(prefix).strip()
    }
    events = [row for row in (blob.get("events") or []) if isinstance(row, dict)]
    return have, events


def _events_for(events: list[dict[str, Any]], wanted: set[str]) -> list[dict[str, Any]]:
    return [
        row for row in events
        if str(row.get("inner") or "").casefold() in wanted
    ]


def _union_us_events(
    cached: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    have: set[str],
    wanted: set[str],
) -> tuple[set[str], list[dict[str, Any]]]:
    """Keep unused cached inners; replace inners present in ``fresh``."""
    fresh_inners = {str(row.get("inner") or "").casefold() for row in fresh}
    kept = [
        row for row in cached
        if str(row.get("inner") or "").casefold() not in fresh_inners
    ]
    return have | wanted, kept + fresh


def _query_us_events(
    wanted: set[str],
    project: str | None,
    query_fn: Callable[[str], Any] | None,
) -> list[dict[str, Any]]:
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = _US_EVENTS_SQL.format(project=proj)
    rows = query_fn(sql) if query_fn is not None else _query(proj, sql)
    return _dedupe_us_events(rows, wanted)


def _dedupe_us_events(raw: Iterable[Any], wanted: set[str]) -> list[dict[str, Any]]:
    """One row per gateway event in a ``wanted`` inner that carries an RFQ symbol.

    ``home`` / ``away`` are the event's first / second typed team
    abbreviation (callers try both orientations); ``ticker`` is one RFQ
    symbol on the event, kept as an opaque example.
    """
    symbols = {_row_symbol(row) for row in raw} - {""}
    if not symbols or not wanted:
        return []
    inners = sorted(wanted)
    with ThreadPoolExecutor(max_workers=min(8, len(inners))) as pool:
        parts = list(pool.map(lambda inner: _inner_events(inner, symbols), inners))
    return [event for part in parts for event in part]


def us_events_from_symbols(
    symbols: Iterable[str], inners: Iterable[str],
) -> list[dict[str, Any]]:
    """Typed gateway events in ``inners`` that carry one of ``symbols``."""
    rows = [{"symbol": s} for s in symbols]
    return _dedupe_us_events(rows, {str(i).strip().casefold() for i in inners if i})


def _inner_events(inner: str, symbols: set[str]) -> list[dict[str, Any]]:
    """Events of one inner whose markets include an RFQ symbol."""
    out: list[dict[str, Any]] = []
    for event in league_events(inner):
        for market in event.get("markets") or []:
            rec = market_record(market, event, None) if isinstance(market, dict) else None
            if rec is None or rec["slug"] not in symbols:
                continue
            row = _us_event(rec["slug"], inner, rec)
            if row is not None:
                out.append(row)
            break
    return out


def _us_event(symbol: str, inner: str, rec: dict[str, Any]) -> dict[str, Any] | None:
    """Gap-harvest event from one stored gateway record (two typed teams)."""
    teams = [t for t in rec.get("teams") or [] if isinstance(t, dict)]
    if len(teams) != 2:
        return None
    codes = [str(t.get("abbreviation") or "").strip().casefold() for t in teams]
    names = [str(t.get("name") or t.get("safe_name") or "").strip() for t in teams]
    start = str(rec.get("event_start") or "").strip()
    if not all(codes) or not start:
        return None
    event: dict[str, Any] = {
        "inner": inner,
        "home": codes[0],
        "away": codes[1],
        "date": start[:10],
        "start": start,
        "ticker": symbol,
    }
    if all(names):
        event["title"] = f"{names[0]} vs {names[1]}"
        event["team_names"] = dict(zip(codes, names, strict=True))
    return event


def _dedupe_official_events(raw: list[Any], wanted: set[str]) -> list[dict[str, Any]]:
    """Keep one question/date row per wanted official slug prefix."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in raw:
        prefix, question, day = _official_fields(row)
        if prefix not in wanted or not question or not day:
            continue
        item_key = (prefix, day, question)
        if item_key in seen:
            continue
        seen.add(item_key)
        item = {"prefix": prefix, "question": question, "date": day}
        for key in ("slug", "outcome_label"):
            extra = _official_extra(row, key)
            if extra:
                item[key] = extra
        out.append(item)
    return out


def _official_extra(row: Any, key: str) -> str:
    """Optional official-bridge field from a BQ Row or dict."""
    if isinstance(row, dict):
        return str(row.get(key) or "")
    return str(getattr(row, key, "") or "")


def _official_fields(row: Any) -> tuple[str, str, str]:
    """prefix, question, ISO date from a BQ Row or dict."""
    if isinstance(row, dict):
        prefix = str(row.get("prefix") or "").casefold()
        question = str(row.get("question") or "")
        day = str(row.get("d") or row.get("date") or "")[:10]
        return prefix, question, day
    return (
        str(getattr(row, "prefix", "") or "").casefold(),
        str(getattr(row, "question", "") or ""),
        str(getattr(row, "d", "") or "")[:10],
    )


def _optic_row(row: Any) -> dict[str, Any]:
    """Normalize a BQ Row or dict into matcher fixture fields."""
    if isinstance(row, dict):
        return dict(row)
    return {name: str(getattr(row, name, "") or "") for name in _OPTIC_FIELDS}


def _row_symbol(row: Any) -> str:
    """RFQ leg symbol from a BQ Row or dict."""
    raw = row.get("symbol") if isinstance(row, dict) else getattr(row, "symbol", "")
    return str(raw or "").strip().casefold()


def _query(
    project: str,
    sql: str,
    *,
    prefixes: Sequence[str] | None = None,
    optic_ids: Sequence[str] | None = None,
) -> Any:
    """Run a read-only BQ query in ``project``."""
    params: list[bigquery.ArrayQueryParameter] = []
    if prefixes is not None:
        params.append(bigquery.ArrayQueryParameter(
            "prefixes", "STRING", [str(p).casefold() for p in prefixes],
        ))
    if optic_ids is not None:
        params.append(bigquery.ArrayQueryParameter(
            "optic_ids", "STRING", [str(oid) for oid in optic_ids if str(oid).strip()],
        ))
    client = bigquery.Client(project=project)
    if not params:
        return ro_query(client, sql)
    job = bigquery.QueryJobConfig(query_parameters=params)
    return ro_query(client, sql, job_config=job)

"""RFQ volume for Proposed rail fixtures, keyed by harvest refs and Optic ids."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.bq_ttl_cache import ttl_cached
from mappers.control_plane.crypto_rfq_symbols_sql import crypto_rfq_symbol_rows_sql
from mappers.control_plane.rfq_latest_sql import render_rfq_filters

log = logging.getLogger(__name__)

_SKIP_GAP = ("usa-inner:", "poly-prefix:", "poly-name:")
_NONE = "__none__"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MIN_TOKEN = 4

_SQL = render_rfq_filters(
    """
with kalshi as (
  select
    json_value(l.platform_mapping, '$.event_ticker') as key,
    count(*) as demand
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __KALSHI__
    and __UNMAPPED_FAILED__
    and json_value(l.platform_mapping, '$.event_ticker') in unnest(@keys)
  group by 1
),
crypto as (
  select symbol as key, count(*) as demand
  from (
    select symbol, external_rfq_id, last_updated
    from """  # nosec B608 — project is a .format placeholder
    + crypto_rfq_symbol_rows_sql(hours=3)
    + """
    where symbol in unnest(@keys)
    qualify row_number() over (
      partition by symbol, coalesce(external_rfq_id, '')
      order by last_updated desc
    ) = 1
  )
  group by 1
),
poly_legs as (
  select
    json_value(l.platform_mapping, '$.token_id') as position_id,
    coalesce(
      json_value(l.platform_mapping, '$.symbol'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.ticker')
    ) as ticker
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __POLY__
    and __UNMAPPED_FAILED__
),
poly_bridge as (
  select position_id, any_value(slug) as slug
  from `{project}.raw_ingestion_us.polymarket_position_token_bridge`
  where last_updated > timestamp_sub(current_timestamp(), interval 14 day)
  group by position_id
),
poly as (
  select coalesce(b.slug, p.ticker) as key, count(*) as demand
  from poly_legs p
  left join poly_bridge b on b.position_id = p.position_id
  where coalesce(b.slug, p.ticker) is not null
    and (
      coalesce(b.slug, p.ticker) in unnest(@keys)
      or exists (
        select 1 from unnest(@name_tokens) t
        where t != '{none}' and strpos(lower(coalesce(b.slug, p.ticker)), t) > 0
      )
    )
  group by 1
),
by_fx as (
  select l.optic_fixture_id as key, count(*) as demand
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __UNMAPPED_FAILED__
    and l.optic_fixture_id in unnest(@fixture_ids)
  group by 1
)
select key, sum(demand) as demand
from (
  select key, demand from kalshi
  union all
  select key, demand from crypto
  union all
  select key, demand from poly
  union all
  select key, demand from by_fx
)
where key is not null and key != '{none}'
group by 1
"""  # nosec B608 — project/none are .format placeholders
)


def gap_inventory_keys(refs: Sequence[str]) -> list[str]:
    """Harvest inventory keys from gap / Polymarket slug refs."""
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        key = _inventory_key(str(ref))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def collect_gap_keys(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Unique harvest keys across mapping rows."""
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in gap_inventory_keys(list(row.get("evidence") or [])):
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def fixture_ids_from(fixtures_by_league: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    """Optic fixture ids on the Proposed rail."""
    return _unique_field(fixtures_by_league, "fixture_id")


def name_tokens_from(fixtures_by_league: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    """Slug tokens from rail home/away names, for Polymarket slug matching."""
    out: list[str] = []
    seen: set[str] = set()
    for fixtures in fixtures_by_league.values():
        for fx in fixtures:
            for raw in (fx.get("home"), fx.get("away")):
                token = _name_token(str(raw or ""))
                if len(token) < _MIN_TOKEN or token in seen:
                    continue
                seen.add(token)
                out.append(token)
    return out


def query_rfq_demand(
    keys: Sequence[str],
    fixture_ids: Sequence[str] = (),
    name_tokens: Sequence[str] = (),
) -> dict[str, int]:
    """RFQ counts in the unmapped inventory window for these harvest keys."""
    wanted = _dedupe(keys)
    fids = _dedupe(fixture_ids)
    tokens = _dedupe(name_tokens)
    if not wanted and not fids and not tokens:
        return {}
    return _run_demand_query(wanted, fids, tokens)


def safe_rfq_demand(
    keys: Sequence[str],
    fixture_ids: Sequence[str] = (),
    name_tokens: Sequence[str] = (),
) -> dict[str, int]:
    """Live RFQ counts, or empty when BigQuery is unavailable."""
    try:
        return query_rfq_demand(keys, fixture_ids, name_tokens)
    except Exception:
        log.warning("rfq demand query failed", exc_info=True)
        return {}


def attach_rfq_demand(
    rows: list[dict[str, Any]],
    fixtures_by_league: dict[str, list[dict[str, Any]]],
    demand_by_key: Mapping[str, int],
) -> None:
    """Stamp unique-sum RFQ volume onto alias rows and Optic rail fixtures."""
    if not demand_by_key:
        return
    for row in rows:
        total = _sum_keys(gap_inventory_keys(list(row.get("evidence") or [])), demand_by_key)
        if total:
            row["rfq_demand"] = total
    for fixtures in fixtures_by_league.values():
        for fx in fixtures:
            total = _fixture_demand(fx, rows, demand_by_key)
            if total:
                fx["rfq_demand"] = total


def _run_demand_query(
    wanted: Sequence[str], fids: Sequence[str], tokens: Sequence[str],
) -> dict[str, int]:
    """Demand per key, memoised 5 min per exact (keys, fixture ids, tokens) ask."""
    key = (tuple(sorted(wanted)), tuple(sorted(fids)), tuple(sorted(tokens)))
    return ttl_cached("console_rfq_demand", key, lambda: _query_demand(wanted, fids, tokens))


def _query_demand(
    wanted: Sequence[str], fids: Sequence[str], tokens: Sequence[str],
) -> dict[str, int]:
    project = os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"
    job = ro_query(
        bigquery.Client(project=project),
        _SQL.format(project=project, none=_NONE),
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("keys", "STRING", list(wanted) or [_NONE]),
                bigquery.ArrayQueryParameter("fixture_ids", "STRING", list(fids) or [_NONE]),
                bigquery.ArrayQueryParameter("name_tokens", "STRING", list(tokens) or [_NONE]),
            ]
        ),
    )
    return {str(row["key"]): int(row["demand"] or 0) for row in job if row.get("key")}


def _inventory_key(ref: str) -> str:
    key = _gap_key(ref)
    if key:
        return key
    if ref.startswith("polymarket:slug:"):
        return ref.split(":", 2)[-1].strip()
    return ""


def _gap_key(ref: str) -> str:
    if not ref.startswith("gap:"):
        return ""
    rest = ref[4:].strip()
    if not rest or rest.startswith(_SKIP_GAP):
        return ""
    return rest


def _sum_keys(keys: Sequence[str], demand_by_key: Mapping[str, int]) -> int:
    return sum(int(demand_by_key.get(key) or 0) for key in keys)


def _fixture_demand(
    fx: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    demand_by_key: Mapping[str, int],
) -> int:
    """Harvest keys first, then Polymarket slug, then Optic fixture id."""
    total = _sum_keys(_fixture_keys(fx, rows), demand_by_key)
    if total:
        return total
    total = _sum_keys(_slug_keys(fx, demand_by_key), demand_by_key)
    if total:
        return total
    return int(demand_by_key.get(str(fx.get("fixture_id") or "")) or 0)


def _fixture_keys(fx: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Unique harvest keys on alias pins that unblock this fixture."""
    fid = str(fx.get("fixture_id") or "")
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("kind") or "") != "alias":
            continue
        ids = {
            str(item.get("fixture_id") or "")
            for item in (row.get("next_fixtures") or [])
            if isinstance(item, dict)
        }
        if fid not in ids:
            continue
        for key in gap_inventory_keys(list(row.get("evidence") or [])):
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def _slug_keys(fx: Mapping[str, Any], demand_by_key: Mapping[str, int]) -> list[str]:
    return [key for key in demand_by_key if _slug_fits(str(key), fx)]


def _slug_fits(key: str, fx: Mapping[str, Any]) -> bool:
    if not _looks_like_slug(key):
        return False
    home = _name_token(str(fx.get("home") or ""))
    away = _name_token(str(fx.get("away") or ""))
    if len(home) < _MIN_TOKEN or len(away) < _MIN_TOKEN:
        return False
    slug = key.casefold()
    return home in slug and away in slug


def _looks_like_slug(key: str) -> bool:
    low = key.casefold()
    if "-" not in low:
        return False
    return not low.startswith("kx") and not low.startswith("nx.")


def _name_token(name: str) -> str:
    return _SLUG_STRIP.sub("-", name.casefold()).strip("-")


def _unique_field(
    fixtures_by_league: Mapping[str, Sequence[Mapping[str, Any]]], field: str,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for fixtures in fixtures_by_league.values():
        for fx in fixtures:
            value = str(fx.get(field) or "")
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
    return out


def _dedupe(values: Sequence[str]) -> list[str]:
    return [item for item in dict.fromkeys(values) if item]

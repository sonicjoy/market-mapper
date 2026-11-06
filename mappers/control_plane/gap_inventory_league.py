"""League tokens for RFQ keys that do not carry one (Novig outcome ids, ProphetX events).

One batched BigQuery lookup per book per drain wave. The token is what the tip
stores on that book's exchange: Novig ``settings.league`` (``NFL``) and
ProphetX ``settings.tournament_id`` (``31``). Novig also returns the Optic league
of the event (``opticOddsId`` → ``opticodds_fixtures.league.id``) so harvest can
draft the league when the tip has no rule for it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.gap_fix_sxbet import fetch_sx_markets, league_slug
from mappers.control_plane.gap_inventory import RfqGapItem

logger = logging.getLogger(__name__)

LEAGUE_META_KEY = "league_token"
OPTIC_META_KEY = "optic_league_id"
OPTIC_ENTITY_KEY = "optic_entity_id"
MARKET_TYPE_KEY = "market_type"
LookupFn = Callable[[str, list[str]], dict[str, dict[str, str]]]

# One freshness bound for the snapshot pick and both snapshot reads.  The reads
# repeat it because ``r.insert_time = snap.s`` is only known at run time and
# prunes nothing: every lookup scanned all of novig_raw (~85 GB on 2026-10-28;
# 2.7 GB with the bound).  It cannot drop a row, since ``snap.s`` satisfies it,
# provided all three stay the same bound.
_NOVIG_FRESH = "insert_time > timestamp_sub(current_timestamp(), interval 1 day)"

_NOVIG_SQL = f"""
with snap as (
  select max(insert_time) as s
  from `{{project}}.raw_ingestion_us.novig_raw`
  where {_NOVIG_FRESH}
),
outs as (
  select
    json_value(o, '$.id') as id,
    json_value(r.data, '$.league') as league,
    json_value(r.data, '$.eventId') as event_id,
    json_value(r.data, '$.type') as market_type,
    coalesce(
      nullif(json_value(o, '$.competitor.opticOddsId'), ''),
      nullif(json_value(r.data, '$.competitor.opticOddsId'), ''),
      nullif(json_value(r.data, '$.player.opticOddsId'), '')
    ) as optic_entity_id
  from `{{project}}.raw_ingestion_us.novig_raw` r, snap,
    unnest(json_query_array(r.data, '$.outcomes')) as o
  where r.kind = 'markets'
    and r.insert_time = snap.s
    and r.{_NOVIG_FRESH}
    and json_value(o, '$.id') in unnest(@ids)
),
events as (
  select json_value(r.data, '$.id') as event_id, json_value(r.data, '$.opticOddsId') as fixture_id
  from `{{project}}.raw_ingestion_us.novig_raw` r, snap
  where r.kind = 'events' and r.insert_time = snap.s
    and r.{_NOVIG_FRESH}
),
fixtures as (
  select coalesce(nullif(id, ''), game_id) as fixture_id, any_value(league.id) as optic_league_id
  from `{{project}}.opticodds_us.opticodds_fixtures`
  where start_date > timestamp_sub(current_timestamp(), interval 30 day)
  group by 1
)
select
  o.id,
  any_value(o.league) as league,
  any_value(f.optic_league_id) as optic_league_id,
  any_value(o.market_type) as market_type,
  any_value(o.optic_entity_id) as optic_entity_id
from outs o
left join events e using (event_id)
left join fixtures f using (fixture_id)
group by 1
"""  # nosec B608 — project is env/default; ids are bound

_PX_SQL = """
select
  json_value(data, '$.event_id') as id,
  array_agg(json_value(data, '$.tournament_id') order by fetch_time desc limit 1)[
    safe_offset(0)
  ] as league
from `{project}.raw_ingestion_us.px_events_fetch_raw`
where fetch_time > timestamp_sub(current_timestamp(), interval 48 hour)
  and json_value(data, '$.event_id') in unnest(@ids)
group by 1
"""  # nosec B608 — project is env/default; ids are bound


def attach_league_tokens(
    items: list[RfqGapItem],
    *,
    lookup_fn: LookupFn | None = None,
) -> list[RfqGapItem]:
    """Copy of ``items`` with league meta on the Novig, ProphetX and SX keys we could resolve.

    SX's league token is already the tip slug: SX's own catalogue (``GET
    /markets/find``) names the league, ``sxbet_leagues`` maps it.
    """
    lookup = lookup_fn or _default_lookup
    novig_ids = sorted({item.key for item in items if item.book == "novig"})
    px_ids = sorted({_px_event(item) for item in items if item.book == "prophetx"} - {""})
    sx_ids = sorted({_sx_hash(item) for item in items if item.book == "sxbet"} - {""})
    novig = _safe(lookup, "novig", novig_ids)
    px = _safe(lookup, "prophetx", px_ids)
    sx = _safe(lookup, "sxbet", sx_ids)
    out: list[RfqGapItem] = []
    for item in items:
        if item.book == "novig":
            found = novig.get(item.key) or {}
        elif item.book == "prophetx":
            found = px.get(_px_event(item)) or {}
        elif item.book == "sxbet":
            found = sx.get(_sx_hash(item)) or {}
        else:
            found = {}
        extra = {
            LEAGUE_META_KEY: found.get("league") or "",
            OPTIC_META_KEY: found.get("optic_league_id") or "",
            OPTIC_ENTITY_KEY: found.get("optic_entity_id") or "",
            MARKET_TYPE_KEY: found.get("market_type") or "",
        }
        extra = {key: value for key, value in extra.items() if value}
        if extra:
            item = RfqGapItem(item.book, item.key, item.demand, {**(item.meta or {}), **extra})
        out.append(item)
    return out


def _sx_hash(item: RfqGapItem) -> str:
    return item.key.split("|", 1)[0].strip().lower()


def _default_lookup(book: str, ids: list[str]) -> dict[str, dict[str, str]]:
    """SX from its public catalogue, Novig / ProphetX from BigQuery."""
    if book == "sxbet":
        return _sx_lookup(ids)
    return _bq_lookup(book, ids)


def _sx_lookup(hashes: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for mh, raw in fetch_sx_markets(hashes).items():
        slug = league_slug(raw)
        if slug:
            out[mh] = {"league": slug}
    return out


def _px_event(item: RfqGapItem) -> str:
    meta = item.meta or {}
    return str(meta.get("px_event_id") or item.key.split(":", 1)[0]).strip()


def _safe(lookup: LookupFn, book: str, ids: list[str]) -> dict[str, dict[str, str]]:
    if not ids:
        return {}
    try:
        return lookup(book, ids)
    except Exception:  # noqa: BLE001 — unresolved keys fall back to the unknown card
        logger.warning("gap inventory %s league lookup failed; keys stay unknown", book, exc_info=True)
        return {}


def _bq_lookup(book: str, ids: list[str]) -> dict[str, dict[str, str]]:
    project = os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = (_NOVIG_SQL if book == "novig" else _PX_SQL).format(project=project)
    job = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)],
    )
    out: dict[str, dict[str, str]] = {}
    for row in ro_query(bigquery.Client(project=project), sql, job_config=job):
        found = {
            name: str(_field(row, name) or "")
            for name in ("league", "optic_league_id", "optic_entity_id", "market_type")
        }
        out[str(_field(row, "id"))] = {key: value for key, value in found.items() if value}
    return out


def _field(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)

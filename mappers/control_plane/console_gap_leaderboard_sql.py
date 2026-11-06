"""BigQuery for Explore -> Gap leaderboard (every venue, one grouped query).

Two sources, one query:

* **RFQ demand** - legs of mapping-failed RFQs in the window whose key still
  has no ``market_mapping`` row (maker lag cleared the same way Unmapped does).
  Each venue reports the miss its own way (``rfq_latest_sql``):

  - Kalshi, Polymarket US, Novig, ProphetX: ``MAPPING_FAILED`` / ``UNMAPPED``, key on the leg.
  - DraftKings: ``skipped`` + ``MAPPING_FAILED``, ticker + side on the leg.
  - Underdog: ``skipped`` + ``UNMAPPED_OPTIC`` (no mmmapper row), ticker on the
    leg; ``failed`` + ``UNMAPPED``, ticker in ``metadata.unmapped`` (no legs).
  - SX: the rows its Unmapped page counts (``sxbet_unmapped_legs``, part-mapped
    offers included), keyed on Optic's SX ``selection_id``.
  - crypto.com reads the shared ``crypto_mf`` CTE (its legs live in
    ``metadata.quote_details``).

  League / fixture / market for DraftKings and Underdog are read off the ticker
  for grouping on this page only; nothing here decides a mapping.
* **Catalogue** - crypto.com only: the Venue gaps catalogue head (``cat`` +
  ``mapped``), so an unmapped market with no RFQ yet still ranks. crypto.com
  demand rides on the catalogue rows (``crypto_mf`` joined to ``cat``), because
  BigQuery re-evaluates a CTE per reference and a second read of ``cat`` /
  ``crypto_mf`` doubled the scan (dry-run 269 GB vs the single read). A failed
  symbol already aged out of the catalogue window is not counted.

``grouping sets`` return platform, fixture and market rows in one pass so the
platform and fixture RFQ counts are *distinct* RFQs, not a sum of their
markets (an MVE combo with two legs in one fixture counts once). League rows
are resolved in Python and are the sum of their fixtures.

Kalshi's MAPPING_FAILED flow is ~95% 15-minute crypto / commodity series
(KXBTC15M alone was 2.16M RFQs in 24h, 2026-09-26) that no Optic book prices;
``NON_SPORT_KALSHI_SERIES`` drops them in SQL.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

from mappers.control_plane.console_venue_gaps_sql import _CATALOG_HEAD, run_venue_gap_query
from mappers.control_plane.crypto_rfq_symbols_sql import crypto_rfq_mf_cte
from mappers.control_plane.rfq_latest_sql import render_rfq_filters
from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG

WINDOW_HOURS: tuple[int, ...] = (3, 6, 12, 24, 48)
DEFAULT_WINDOW_HOURS = 24
# RFQs live seconds to minutes: a publish this far before the window is enough.
_SCAN_SLACK_HOURS = 6

# Kalshi series with no sports book behind them (crypto, FX, commodities, indices).
NON_SPORT_KALSHI_SERIES = (
    r"^KX(BTC|ETH|XRP|DOGE|SOL|BNB|HYPE|ZEC|NEAR|ADA|LTC|AVAX|LINK|SHIBA?|SUI|TRUMPCOIN|"
    r"WTI|NATGAS|GOLD|SILVER|COPPER|INX|NASDAQ|SPX|USDJPY|EURUSD|GBPUSD)"
)

# Underdog venue league tokens, longest first: RE2 takes the first alternative
# that matches, so ``ATPCHL`` must be tried before ``ATP``.
UDX_LEAGUE_TOKENS = "|".join(sorted(VENUE_TOKEN_TO_LEAGUE_SLUG, key=lambda t: (-len(t), t)))

_UDX_FIXTURE = r"^([A-Z]+[0-9]{{2}}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[0-9]{{2}})"

_LEGS = """
legs as (
  select
    case
      when r.platform like 'kalshi%' then 'kalshi'
      when lower(r.platform) like 'polymarketus%' then 'polymarket_usa'
      when r.platform like 'novig%' then 'novig'
      when r.platform like 'prophetx%' then 'px'
      when __DKEX__ then 'dkex'
      when __UNDERDOG__ then 'underdog'
      when __SXBET__ then 'sxbet'
    end as book,
    r.external_rfq_id,
    r.last_updated,
    json_value(l.platform_mapping, '$.event_ticker') as event_ticker,
    json_value(l.platform_mapping, '$.market_ticker') as market_ticker,
    lower(json_value(l.platform_mapping, '$.side')) as side,
    lower(json_value(l.platform_mapping, '$.outcome_id')) as outcome_id,
    json_value(l.platform_mapping, '$.event_id') as event_id,
    lower(json_value(l.platform_mapping, '$.line_id')) as line_id,
    lower(json_value(l.platform_mapping, '$.market_hash')) as market_hash,
    json_value(l.platform_mapping, '$.betting_outcome_one') as sx_outcome_one
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where r.last_updated > timestamp_sub(current_timestamp(), interval {hours} hour)
    and r.first_publish_time > timestamp_sub(current_timestamp(), interval {scan_hours} hour)
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
    and (
      (r.reason in ('MAPPING_FAILED', 'UNMAPPED')
        and (r.platform like 'kalshi%' or lower(r.platform) like 'polymarketus%'
          or r.platform like 'novig%' or r.platform like 'prophetx%'))
      or (__DKEX__ and __DKEX_GAP__)
      or (__UNDERDOG__ and __UNDERDOG_OPTIC_GAP__)
      or (__SXBET__ and __SXBET_GAP__)
    )
),
-- Underdog UNMAPPED rows carry no legs: the ticker is in metadata.unmapped.
underdog_meta as (
  select
    'underdog' as book,
    r.external_rfq_id,
    r.last_updated,
    sym as market_ticker
  from `{project}.reporting_us.rfq_latest` r,
    unnest(json_value_array(r.metadata, '$.unmapped')) as sym
  where r.last_updated > timestamp_sub(current_timestamp(), interval {hours} hour)
    and r.first_publish_time > timestamp_sub(current_timestamp(), interval {scan_hours} hour)
    and __UNDERDOG__
    and __UNMAPPED_FAILED__
    and sym is not null
),
venue_legs as (
  select book, external_rfq_id, last_updated, event_ticker, market_ticker, side, outcome_id,
    event_id, line_id, market_hash, sx_outcome_one
  from legs
  union all
  select book, external_rfq_id, last_updated, cast(null as string), market_ticker, cast(null as string),
    cast(null as string), cast(null as string), cast(null as string), cast(null as string), cast(null as string)
  from underdog_meta
),
keyed as (
  select
    book,
    external_rfq_id,
    last_updated,
    case book
      when 'kalshi' then if(side is null, concat('kalshi|M|', market_ticker),
                             concat('kalshi|F|', market_ticker, '|', side))
      when 'polymarket_usa' then concat('polymarket (usa)|M|', market_ticker)
      when 'novig' then concat('novig|S|', outcome_id)
      when 'px' then concat('prophet x|S|', line_id)
      -- ticker AND side: a mapped yes does not clear the no of the same ticker.
      when 'dkex' then if(side is null, concat('dkex|M|', market_ticker),
                           concat('dkex|F|', market_ticker, '|', side))
      when 'underdog' then concat('underdog|M|', market_ticker)
      -- Optic's SX selection_id names the MAKER's outcome (mappers/exchanges/sxbet.py).
      when 'sxbet' then if(sx_outcome_one in ('true', 'false'),
        concat('sx bet|S|', market_hash, '|', if(sx_outcome_one = 'true', 'two', 'one')), null)
    end as jk,
    case book
      when 'kalshi' then regexp_replace(event_ticker, r'^[A-Z0-9]+-', '')
      -- `astatc-mlb-tb-phi-2026-09-25-yrfi`: fixture ends at the date; the tail is market.
      when 'polymarket_usa' then coalesce(
        regexp_extract(market_ticker, r'^[a-z0-9]+-(.+?-[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})'),
        regexp_replace(market_ticker, r'^[a-z0-9]+-', ''))
      when 'novig' then market_ticker
      -- `NFL-MOVY-FG-<competition>-<participant>-GTE-P00035`: the competition handle.
      when 'dkex' then split(market_ticker, '-')[safe_offset(3)]
      -- `UDXNFLRUSHYDS_CHIATL26OCT181300BIJANROBINSO_149.5`: teams + date, time dropped.
      when 'underdog' then coalesce(
        regexp_extract(split(market_ticker, '_')[safe_offset(1)], r'{udx_fixture}'),
        split(market_ticker, '_')[safe_offset(1)])
      when 'sxbet' then market_hash
      else event_id
    end as fixture_key,
    case book
      when 'kalshi' then split(event_ticker, '-')[safe_offset(0)]
      when 'polymarket_usa' then concat(
        split(market_ticker, '-')[safe_offset(0)],
        coalesce(concat(' ', regexp_extract(market_ticker, r'-[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}-(.+)$')), ''))
      when 'dkex' then concat(split(market_ticker, '-')[safe_offset(1)], '-', split(market_ticker, '-')[safe_offset(2)])
      when 'underdog' then regexp_replace(split(market_ticker, '_')[safe_offset(0)], r'^UDX', '')
      else ''
    end as market,
    case book
      when 'kalshi' then split(event_ticker, '-')[safe_offset(0)]
      when 'polymarket_usa' then split(market_ticker, '-')[safe_offset(1)]
      when 'dkex' then split(market_ticker, '-')[safe_offset(0)]
      when 'underdog' then coalesce(regexp_extract(market_ticker, r'^UDX({udx_leagues})'), '')
      else ''
    end as league_hint
  from venue_legs
  where book is not null
    and not (book = 'kalshi' and regexp_contains(coalesce(event_ticker, ''), r'{non_sport}'))
),
mm_keys as (
  select distinct k
  from (
    select
      lower(sportsbook) as sb,
      json_value(to_json_string(source_ids), '$.market_id') as mid,
      lower(json_value(to_json_string(source_ids), '$.selection_id')) as sid
    from `{project}.markets_us.market_mapping`
    where start_date > timestamp_sub(current_timestamp(), interval 90 day)
      and lower(sportsbook) in ('kalshi', 'polymarket (usa)', 'novig', 'prophet x', 'dkex', 'underdog', 'sx bet')
  ), unnest([concat(sb, '|F|', mid, '|', sid), concat(sb, '|M|', mid), concat(sb, '|S|', sid)]) as k
  where k is not null
),
rfq_open as (
  select k.book, k.fixture_key, k.market, k.league_hint, k.external_rfq_id, k.jk, k.last_updated
  from keyed k
  left join mm_keys m on m.k = k.jk
  where m.k is null and k.jk is not null
),
crypto_rows as (
  select
    c.meta_league as league_hint,
    c.fixture_key,
    c.contract_type as market,
    c.fixture_name,
    c.event_at,
    c.symbol,
    m.symbol is null as unmapped,
    f.external_rfq_id,
    f.last_updated
  from cat c
  left join mapped m on m.symbol = c.symbol
  left join crypto_mf f on f.symbol = c.symbol and m.symbol is null
)
"""  # nosec B608 - interpolands are module constants / validated ints, not caller input

_SELECT = """
select
  book,
  league_hint,
  fixture_key,
  market,
  grouping(fixture_key) as g_fixture,
  grouping(market) as g_market,
  cast(null as string) as fixture_name,
  cast(null as timestamp) as start_at,
  count(distinct external_rfq_id) as demand,
  count(distinct jk) as legs,
  max(last_updated) as last_seen,
  cast(null as int64) as catalogue_total,
  cast(null as int64) as catalogue_unmapped
from rfq_open
group by grouping sets ((book), (book, league_hint, fixture_key), (book, league_hint, fixture_key, market))
union all
select
  'crypto' as book,
  league_hint,
  fixture_key,
  market,
  grouping(fixture_key) as g_fixture,
  grouping(market) as g_market,
  any_value(fixture_name) as fixture_name,
  min(event_at) as start_at,
  count(distinct external_rfq_id) as demand,
  count(distinct if(external_rfq_id is not null, symbol, null)) as legs,
  max(last_updated) as last_seen,
  count(distinct symbol) as catalogue_total,
  count(distinct if(unmapped, symbol, null)) as catalogue_unmapped
from crypto_rows
group by grouping sets ((), (league_hint, fixture_key), (league_hint, fixture_key, market))
"""  # nosec B608 - no caller input


def gap_leaderboard_sql(hours: int = DEFAULT_WINDOW_HOURS) -> str:
    """Leaderboard query for one demand window (``{project}`` left for the runner)."""
    if hours not in WINDOW_HOURS:
        raise ValueError(f"window must be one of {WINDOW_HOURS}, got {hours!r}")
    scan = hours + _SCAN_SLACK_HOURS
    legs = _LEGS.replace("{hours}", str(hours)).replace("{scan_hours}", str(scan))
    legs = legs.replace("{non_sport}", NON_SPORT_KALSHI_SERIES)
    legs = legs.replace("{udx_fixture}", _UDX_FIXTURE).replace("{udx_leagues}", UDX_LEAGUE_TOKENS)
    return _CATALOG_HEAD + crypto_rfq_mf_cte(hours=hours) + render_rfq_filters(legs) + _SELECT


# Owner, 2026-09-26: one uncached load bills ~150 GB, so the result is memoised
# for an hour per window; the page states it and Refresh bypasses it.
LEADERBOARD_CACHE_TTL_SECONDS = 3600.0
_cache: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def leaderboard_query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the leaderboard query, memoised for ``LEADERBOARD_CACHE_TTL_SECONDS`` per SQL text."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(sql)
        if hit is not None and now - hit[0] < LEADERBOARD_CACHE_TTL_SECONDS:
            return hit[2]
    rows = run_venue_gap_query(sql, params)
    with _cache_lock:
        _cache[sql] = (now, datetime.now(UTC).isoformat(), rows)
        for stale in [k for k, (at, _, _) in _cache.items() if now - at >= LEADERBOARD_CACHE_TTL_SECONDS]:
            _cache.pop(stale, None)
    return rows


def leaderboard_cached_at(sql: str) -> str | None:
    """When the memoised result for ``sql`` was fetched (UTC ISO), or None."""
    with _cache_lock:
        hit = _cache.get(sql)
    return hit[1] if hit is not None else None


def clear_leaderboard_cache() -> None:
    """Drop memoised leaderboard results (Refresh button, tests)."""
    with _cache_lock:
        _cache.clear()

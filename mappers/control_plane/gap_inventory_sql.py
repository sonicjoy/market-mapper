"""BigQuery SQL for the RFQ true-gap inventory.

Kept out of ``gap_inventory`` so the ranking logic stays readable; the
format placeholders are filled by ``fetch_rfq_inventory``.
"""

from __future__ import annotations

from mappers.control_plane.crypto_rfq_symbols_sql import crypto_rfq_mf_cte
from mappers.control_plane.rfq_latest_sql import render_rfq_filters

# Join keys match BigQuery/sql/rfq_unmapped_legs_kalshi_*.sql,
# crypto_rfq_maker_lag_vs_true_gap.sql, and polymarket_mapping_gaps.sql
# (market_ticker↔source_ids.market_id, quote_details NX symbol ↔
# source_ids.symbol, poly clob/ticker ↔ selection_id / market_id).
_RFQ_INVENTORY_HEAD = """
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
kalshi_mapped as (
  select distinct
    json_value(to_json_string(source_ids), '$.market_id') as market_ticker,
    lower(json_value(to_json_string(source_ids), '$.selection_id')) as kalshi_side
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Kalshi'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
kalshi_true as (
  select
    'kalshi' as book,
    k.event_ticker as key,
    count(*) as demand,
    max(k.last_updated) as last_seen,
    array_agg(k.market_ticker ignore nulls order by k.last_updated desc limit 1)[
      safe_offset(0)
    ] as market_ticker
  from kalshi_legs k
  -- ticker AND side: a mapped Yes does not clear the No of the same ticker.
  -- No side on the leg falls back to ticker-only (not a fresh true gap).
  left join kalshi_mapped m
    on m.market_ticker = k.market_ticker
   and (k.kalshi_side is null or m.kalshi_side = k.kalshi_side)
  where k.event_ticker is not null
    and k.event_ticker not like '%DOUBLES%'
    and m.market_ticker is null
  group by 1, 2
),
"""  # nosec B608 — platform predicate is a module constant
_RFQ_INVENTORY_TAIL = """
crypto_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.symbol') as symbol
  from `{project}.markets_us.market_mapping`
  where lower(sportsbook) = 'crypto.com'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
crypto_true as (
  select
    'crypto' as book,
    c.symbol as key,
    count(*) as demand,
    max(c.last_updated) as last_seen
  from crypto_mf c
  left join crypto_mapped m using (symbol)
  where c.symbol is not null and m.symbol is null
  group by 1, 2
),
poly_legs as (
  select
    r.platform,
    json_value(l.platform_mapping, '$.token_id') as position_id,
    coalesce(
      json_value(l.platform_mapping, '$.symbol'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.ticker')
    ) as ticker,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __POLY__
    and __UNMAPPED_FAILED__
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
),
-- Poly US inner from the gateway record the fetch stored (typed), never
-- split out of the symbol. A symbol the fetch did not see stays "(null)".
poly_us_inner as (
  select market_id as ticker, any_value(inner_league) as inner_league
  from `{project}.raw_ingestion_us.polymarket_usa_fetch_raw`
  where fetch_time > timestamp_sub(current_timestamp(), interval 1 day)
  group by market_id
),
poly_bridge as (
  select
    position_id,
    any_value(clob_token_id) as clob_token_id,
    any_value(slug) as slug
  from `{project}.raw_ingestion_us.polymarket_position_token_bridge`
  where last_updated > timestamp_sub(current_timestamp(), interval 14 day)
  group by position_id
),
poly_mm_official as (
  select distinct json_value(source_ids, '$.selection_id') as clob_token_id
  from `{project}.markets_us.market_mapping`
  where start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and sportsbook = 'Polymarket'
    and json_value(source_ids, '$.selection_id') is not null
),
poly_mm_usa as (
  select distinct json_value(source_ids, '$.market_id') as market_id
  from `{project}.markets_us.market_mapping`
  where start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and sportsbook = 'Polymarket (USA)'
    and json_value(source_ids, '$.market_id') is not null
),
poly_true as (
  select
    'polymarket' as book,
    coalesce(
      case
        when lower(p.platform) like '%us%' then u.inner_league
        else regexp_extract(coalesce(b.slug, p.ticker), r'^([a-z0-9]+)-')
      end,
      '(null)'
    ) as key,
    count(*) as demand,
    max(p.last_updated) as last_seen,
    array_to_string(array_agg(
      if(lower(p.platform) like '%us%', p.ticker, null)
      ignore nulls order by p.last_updated desc limit 3
    ), ',') as market_ticker
  from poly_legs p
  left join poly_bridge b on b.position_id = p.position_id
  left join poly_us_inner u on u.ticker = lower(p.ticker)
  where (
    case
      when lower(p.platform) like '%us%' then p.ticker is not null
      else b.clob_token_id is not null and b.slug is not null
    end
  )
  and not (
    case
      when lower(p.platform) like '%us%' then
        exists (select 1 from poly_mm_usa m where m.market_id = p.ticker)
      else
        exists (
          select 1 from poly_mm_official m
          where m.clob_token_id = b.clob_token_id
        )
    end
  )
  group by 1, 2
  qualify row_number() over (order by count(*) desc, max(p.last_updated) desc)
    <= {limit}
),
novig_legs as (
  select
    json_value(l.platform_mapping, '$.market_ticker') as market_ticker,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __NOVIG__
    and __UNMAPPED_FAILED__
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
),
novig_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.selection_id') as selection_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Novig'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
novig_true as (
  select
    'novig' as book,
    n.market_ticker as key,
    count(*) as demand,
    max(n.last_updated) as last_seen
  from novig_legs n
  left join novig_mapped m on m.selection_id = n.market_ticker
  where n.market_ticker is not null and m.selection_id is null
  group by 1, 2
),
px_legs as (
  select
    json_value(l.platform_mapping, '$.event_id') as event_id,
    json_value(l.platform_mapping, '$.line_id') as line_id,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __PX__
    and __UNMAPPED_FAILED__
    and (l.optic_fixture_id is null or l.market is null or l.selection is null)
),
px_mapped as (
  select distinct
    json_value(to_json_string(source_ids), '$.event_id') as event_id,
    json_value(to_json_string(source_ids), '$.selection_id') as line_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Prophet X'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
px_true as (
  select
    'prophetx' as book,
    concat(p.event_id, ':', p.line_id) as key,
    count(*) as demand,
    max(p.last_updated) as last_seen,
    any_value(p.event_id) as px_event_id,
    any_value(p.line_id) as px_line_id
  from px_legs p
  left join px_mapped m
    on m.event_id = p.event_id and m.line_id = p.line_id
  where p.event_id is not null
    and p.line_id is not null
    and m.event_id is null
  group by 1, 2
),
underdog_syms as (
  select
    sym as symbol,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r,
    unnest(json_value_array(r.metadata, '$.unmapped')) as sym
  where __RECENT_3H__
    and __UNDERDOG__
    and __UNMAPPED_FAILED__
    and sym is not null
),
underdog_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.market_id') as market_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Underdog'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
underdog_true as (
  select
    'underdog' as book,
    u.symbol as key,
    count(*) as demand,
    max(u.last_updated) as last_seen
  from underdog_syms u
  left join underdog_mapped m on m.market_id = u.symbol
  where m.market_id is null
  group by 1, 2
),
-- DraftKings names the ticker on the leg, not in metadata.unmapped, and its
-- mapping failures are skipped, not failed (rfq_latest_sql.dkex_mapping_failed).
dkex_syms as (
  select
    json_value(l.platform_mapping, '$.market_ticker') as symbol,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r, unnest(r.legs) as l
  where __RECENT_3H__
    and __DKEX__
    and __DKEX_GAP__
    and json_value(l.platform_mapping, '$.market_ticker') is not null
),
dkex_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.market_id') as market_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'DKEX'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
dkex_true as (
  select
    'dkex' as book,
    d.symbol as key,
    count(*) as demand,
    max(d.last_updated) as last_seen
  from dkex_syms d
  left join dkex_mapped m on m.market_id = d.symbol
  where m.market_id is null
  group by 1, 2
),
huddle_syms as (
  select
    sym as symbol,
    r.last_updated
  from `{project}.reporting_us.rfq_latest` r,
    unnest(json_value_array(r.metadata, '$.unmapped')) as sym
  where __RECENT_3H__
    and __HUDDLE__
    and __UNMAPPED_FAILED__
    and sym is not null
),
huddle_mapped as (
  select distinct json_value(to_json_string(source_ids), '$.selection_id') as selection_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Huddle'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
huddle_true as (
  select
    'huddle' as book,
    h.symbol as key,
    count(*) as demand,
    max(h.last_updated) as last_seen
  from huddle_syms h
  left join huddle_mapped m on m.selection_id = h.symbol
  where m.selection_id is null
  group by 1, 2
),
-- SX: every leg carries platform_mapping.market_hash + betting_outcome_one;
-- an unmapped leg has no optic_fixture_id (metadata.unmapped is unused).
-- The key is Optic's SX selection_id, whose suffix is the MAKER's outcome:
-- a taker on outcome one reads "<hash>|two" (mappers/exchanges/sxbet.py
-- selection_id; verified on prod 2026-10-13).
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
sxbet_keys as (
  select
    concat(s.market_hash, '|', if(s.taker_outcome_one = 'true', 'two', 'one')) as selection_id,
    s.market_hash,
    s.last_updated
  from sxbet_legs s
  where s.market_hash is not null
    and s.taker_outcome_one in ('true', 'false')
),
sxbet_mapped as (
  select distinct lower(json_value(to_json_string(source_ids), '$.selection_id')) as selection_id
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'SX Bet'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
),
sxbet_true as (
  select
    'sxbet' as book,
    k.selection_id as key,
    count(*) as demand,
    max(k.last_updated) as last_seen,
    any_value(k.market_hash) as market_ticker
  from sxbet_keys k
  left join sxbet_mapped m on m.selection_id = k.selection_id
  where m.selection_id is null
  group by 1, 2
),
underdog_probe as (
  select * from underdog_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
),
dkex_probe as (
  select * from dkex_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
),
huddle_probe as (
  select * from huddle_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
),
sxbet_probe as (
  select * from sxbet_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
),
novig_probe as (
  select * from novig_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
),
px_probe as (
  select * from px_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
),
kalshi_probe as (
  select * from kalshi_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
  union distinct
  -- kickoff is a select alias. Filter it with WHERE on the subquery.
  -- A QUALIFY predicate with no window function is a BigQuery 400.
  select * except(kickoff) from (
    select
      t.*,
      safe.parse_date(
        '%d%b%y',
        concat(
          regexp_extract(upper(key), r'-\\d{{2}}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\\d{{2}})'),
          regexp_extract(upper(key), r'-\\d{{2}}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\\d{{2}}'),
          regexp_extract(upper(key), r'-(\\d{{2}})(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\\d{{2}}')
        )
      ) as kickoff
    from kalshi_true t
  )
  where kickoff is not null
    and date_diff(kickoff, current_date('UTC'), day) between 0 and {close_days}
  qualify row_number() over (
    order by date_diff(kickoff, current_date('UTC'), day), demand desc
  ) <= {limit}
),
crypto_probe as (
  select * from crypto_true
  qualify row_number() over (order by demand desc, last_seen desc) <= {limit}
  union distinct
  select * except(kickoff) from (
    select
      t.*,
      safe.parse_date(
        '%y%m%d',
        regexp_extract(key, r'NX\\.F\\.OPT\\.[A-Z0-9]+-\\d+-(\\d{{6}})')
      ) as kickoff
    from crypto_true t
  )
  where kickoff is not null
    and date_diff(kickoff, current_date('UTC'), day) between 0 and {close_days}
  qualify row_number() over (
    order by date_diff(kickoff, current_date('UTC'), day), demand desc
  ) <= {limit}
)
{ledger_cte}
select book, key, demand, last_seen, market_ticker, px_event_id, px_line_id, market_name
from (
  select book, key, demand, last_seen, market_ticker, cast(null as string) as px_event_id,
    cast(null as string) as px_line_id, cast(null as string) as market_name
  from kalshi_probe
  union all
  select book, key, demand, last_seen, cast(null as string), cast(null as string),
    cast(null as string), cast(null as string)
  from crypto_probe
  union all
  select book, key, demand, last_seen, market_ticker, cast(null as string),
    cast(null as string), cast(null as string)
  from poly_true
  union all
  select book, key, demand, last_seen, cast(null as string), cast(null as string),
    cast(null as string), cast(null as string)
  from novig_probe
  union all
  select book, key, demand, last_seen, cast(null as string), cast(null as string),
    cast(null as string), cast(null as string)
  from underdog_probe
  union all
  select book, key, demand, last_seen, cast(null as string), cast(null as string),
    cast(null as string), cast(null as string)
  from dkex_probe
  union all
  select book, key, demand, last_seen, cast(null as string), cast(null as string),
    cast(null as string), cast(null as string)
  from huddle_probe
  union all
  select book, key, demand, last_seen, market_ticker, cast(null as string),
    cast(null as string), cast(null as string)
  from sxbet_probe
  union all
  select book, key, demand, last_seen, cast(null as string), px_event_id,
    px_line_id, cast(null as string)
  from px_probe
) as inventory_rows
where true
{ledger_exclude_predicate}
"""
RFQ_INVENTORY_SQL = render_rfq_filters(_RFQ_INVENTORY_HEAD + crypto_rfq_mf_cte(hours=3) + _RFQ_INVENTORY_TAIL)

-- Wave A3: Kalshi KXUFCFIGHT true gaps (MAPPING_FAILED, not in market_mapping).
-- Exclude maker-lag (already mapped). Substitute {project}.

with rfqs as (
  select external_rfq_id, platform, legs
  from `{project}.reporting_us.rfq_latest`
  where last_updated > timestamp_sub(current_timestamp(), interval 3 hour)
    and first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
    and platform in (
      'kalshi', 'kalshi-inplay', 'kalshi-inplay-cashout', 'kalshi-cashout'
    )
    and reason in ('MAPPING_FAILED', 'UNMAPPED')
),
unmapped_legs as (
  select
    r.platform,
    r.external_rfq_id,
    json_value(l.platform_mapping, '$.market_ticker') as market_ticker,
    json_value(l.platform_mapping, '$.event_ticker') as event_ticker
  from rfqs r, unnest(r.legs) as l
  where l.optic_fixture_id is null or l.market is null or l.selection is null
),
ufc_fight as (
  select *
  from unmapped_legs
  where starts_with(coalesce(event_ticker, market_ticker), 'KXUFCFIGHT')
),
mapped as (
  select distinct
    json_value(to_json_string(source_ids), '$.market_id') as market_ticker
  from `{project}.markets_us.market_mapping`
  where sportsbook = 'Kalshi'
    and start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and league = 'ufc'
),
true_gaps as (
  select u.*
  from ufc_fight u
  left join mapped m on m.market_ticker = u.market_ticker
  where m.market_ticker is null
)
select
  event_ticker,
  count(*) as occ,
  count(distinct market_ticker) as markets,
  count(distinct external_rfq_id) as rfqs,
  string_agg(distinct market_ticker limit 6) as sample_markets
from true_gaps
group by event_ticker
order by occ desc
limit 40
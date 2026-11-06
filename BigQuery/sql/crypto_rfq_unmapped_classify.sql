-- Crypto.com RFQ MAPPING_FAILED: classify unmapped leg symbols with gap_reason.
-- Substitute {project}: marketmaking-test | rs-marketmaking
--
-- Uses metadata.quote_details (2026-09+ maker); legacy reason_detail and
-- structured legs are unioned. Do not classify NX.F.OPT.COMBOS wrapper symbols.
--
-- Partition: rfq_latest is partitioned on first_publish_time.

with um1 as (
  select json_value(leg, '$.symbol') as unmapped_symbol
  from `{project}.reporting_us.rfq_latest` r,
  unnest(json_query_array(
    safe.parse_json(json_value(r.metadata, '$.quote_details')),
    '$.qr.symbols'
  )) as combo,
  unnest(json_query_array(combo, '$.legs')) as leg
  where r.platform = 'cryptocom'
    and r.status = 'failed'
    and r.reason = 'MAPPING_FAILED'
    and r.last_updated > timestamp_sub(current_timestamp(), interval 6 hour)
    and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
    and json_value(leg, '$.symbol') is not null
    and json_value(leg, '$.symbol') not like 'NX.F.OPT.COMBOS%'
  union all
  select
    regexp_extract(
      json_value(r.metadata, '$.reason_detail'),
      r'no mapping for symbol (NX\.[^ ]+)'
    ) as unmapped_symbol
  from `{project}.reporting_us.rfq_latest` r
  where r.platform = 'cryptocom'
    and r.status = 'failed'
    and r.reason = 'MAPPING_FAILED'
    and r.last_updated > timestamp_sub(current_timestamp(), interval 6 hour)
    and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
    and regexp_extract(
      json_value(r.metadata, '$.reason_detail'),
      r'no mapping for symbol (NX\.[^ ]+)'
    ) is not null
  union all
  select json_value(l.platform_mapping, '$.symbol') as unmapped_symbol
  from `{project}.reporting_us.rfq_latest` r
  left join unnest(r.legs) as l
  where r.platform = 'cryptocom'
    and r.status = 'failed'
    and r.reason = 'MAPPING_FAILED'
    and r.last_updated > timestamp_sub(current_timestamp(), interval 6 hour)
    and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
    and json_value(l.platform_mapping, '$.symbol') is not null
    and json_value(l.platform_mapping, '$.symbol') not like 'NX.F.OPT.COMBOS%'
),
um as (
  select
    unmapped_symbol as symbol,
    regexp_replace(unmapped_symbol, r'\.[0-9]{8}$', '') as symbol_base,
    regexp_extract(unmapped_symbol, r'NX\.F\.OPT\.([A-Z0-9]+)') as league,
    regexp_extract(unmapped_symbol, r'(NX\.F\.OPT\.[A-Z0-9]+-\d+-\d{6})') as fixture_prefix,
    regexp_contains(unmapped_symbol, r'-20\d{2}\.O\.') as is_future,
    count(*) as rfqs
  from um1
  where unmapped_symbol is not null
    and unmapped_symbol not like '%side not supported%'
  group by 1, 2, 3, 4, 5
),
mapped as (
  select distinct
    json_value(source_ids, '$.symbol') as symbol,
    regexp_replace(json_value(source_ids, '$.symbol'), r'\.[0-9]{8}$', '') as symbol_base,
    regexp_extract(json_value(source_ids, '$.symbol'), r'(NX\.F\.OPT\.[A-Z0-9]+-\d+-\d{6})') as fixture_prefix,
    market_type,
    json_value(source_ids, '$.symbol') as mapped_symbol
  from `{project}.markets_us.market_mapping`
  where start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and sportsbook = 'crypto.com'
),
cat as (
  select * from (
    select
      regexp_replace(symbol, r'\.[0-9]{8}$', '') as symbol_base,
      meta_predict_market_type as market_group,
      meta_predict_contract_type as contract_type,
      meta_predict_period_type as period_type,
      meta_name,
      safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', meta_event_date) as kickoff,
      publish_time
    from `{project}.processed_upstream_us.crypto_security_def`
    union all
    select
      regexp_replace(symbol, r'\.[0-9]{8}$', ''),
      meta_predict_market_type,
      meta_predict_contract_type,
      meta_predict_period_type,
      meta_name,
      safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', meta_event_date),
      publish_time
    from `{project}.processed_upstream_us.crypto_underlying_securities`
  )
  qualify row_number() over (partition by symbol_base order by publish_time desc) = 1
)
select
  um.league,
  um.symbol,
  um.rfqs,
  cat.market_group,
  cat.contract_type,
  cat.period_type,
  cat.meta_name,
  timestamp_diff(cat.kickoff, current_timestamp(), hour) as hours_to_kickoff,
  case
    when exists (
      select 1 from mapped m
      where m.symbol = um.symbol or m.symbol_base = um.symbol_base
    ) then 'maker-lag (already in market_mapping)'
    when um.is_future then 'tournament/future market (by design)'
    when um.league = 'GOLF' then 'league not onboarded'
    when cat.market_group is null then 'not in catalogue (wait for upstream)'
    when cat.kickoff < current_timestamp()
      then concat('completed fixture (stale): ', coalesce(cat.contract_type, '?'))
    when cat.kickoff > timestamp_add(current_timestamp(), interval 168 hour)
      then 'outside Optic horizon'
    when cat.contract_type in ('Spread', 'Total Points', 'Total Goals', 'Total Runs')
         and cat.period_type in ('Full-Game', 'Full Game', '90 Minutes and Stoppage Time')
         and exists (
           select 1 from mapped m
           where m.fixture_prefix = um.fixture_prefix
             and m.market_type in ('point_spread', 'game_total')
         ) then 'crypto-only ladder (beyond Optic)'
    when cat.contract_type in ('Moneyline', 'Spread', 'Total Points', 'Total Goals', 'Total Runs')
         and cat.period_type not in ('Full-Game', 'Full Game', '90 Minutes and Stoppage Time')
         and exists (
           select 1 from mapped m
           where m.fixture_prefix = um.fixture_prefix
             and m.market_type = 'moneyline'
         ) then concat(
           'period overlay gap: ',
           coalesce(cat.period_type, '?'),
           ' / ',
           coalesce(cat.contract_type, '?')
         )
    else concat('true gap: ', coalesce(cat.market_group, '?'), ' / ', coalesce(cat.contract_type, '?'))
  end as gap_reason
from um
left join cat using (symbol_base)
order by rfqs desc

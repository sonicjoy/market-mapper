-- Crypto.com RFQ MAPPING_FAILED: maker-lag vs true gap.
-- Join RFQ quote_details leg symbols to market_mapping.source_ids.symbol.
-- Substitute {project}: marketmaking-test | rs-marketmaking
--
-- IN_market_mapping = maker-lag (mmcryptorfq cache/lookup; row already exists).
-- NOT_in_mapping    = true gap (mmmapper / horizon / upstream).
--
-- Partition: rfq_latest is partitioned on first_publish_time.
-- Always keep a first_publish_time bound or the scan is expensive.

with mf as (
  select
    symbol,
    any_value(external_rfq_id) as sample_rfq,
    count(*) as rfqs
  from (
    select
      json_value(leg, '$.symbol') as symbol,
      r.external_rfq_id
    from `{project}.reporting_us.rfq_latest` r,
    unnest(json_query_array(
      safe.parse_json(json_value(r.metadata, '$.quote_details')),
      '$.qr.symbols'
    )) as combo,
    unnest(json_query_array(combo, '$.legs')) as leg
    where r.platform = 'cryptocom'
      and r.reason = 'MAPPING_FAILED'
      and r.last_updated > timestamp_sub(current_timestamp(), interval 1 hour)
      and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
      and json_value(leg, '$.symbol') is not null
      and json_value(leg, '$.symbol') not like 'NX.F.OPT.COMBOS%'
    union all
    select
      regexp_extract(
        json_value(r.metadata, '$.reason_detail'),
        r'no mapping for symbol (NX\.[^ ]+)'
      ) as symbol,
      r.external_rfq_id
    from `{project}.reporting_us.rfq_latest` r
    where r.platform = 'cryptocom'
      and r.reason = 'MAPPING_FAILED'
      and r.last_updated > timestamp_sub(current_timestamp(), interval 1 hour)
      and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
      and regexp_extract(
        json_value(r.metadata, '$.reason_detail'),
        r'no mapping for symbol (NX\.[^ ]+)'
      ) is not null
    union all
    select
      json_value(l.platform_mapping, '$.symbol') as symbol,
      r.external_rfq_id
    from `{project}.reporting_us.rfq_latest` r
    left join unnest(r.legs) as l
    where r.platform = 'cryptocom'
      and r.reason = 'MAPPING_FAILED'
      and r.last_updated > timestamp_sub(current_timestamp(), interval 1 hour)
      and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
      and json_value(l.platform_mapping, '$.symbol') is not null
      and json_value(l.platform_mapping, '$.symbol') not like 'NX.F.OPT.COMBOS%'
  )
  group by 1
),
mapped as (
  select distinct json_value(to_json_string(source_ids), '$.symbol') as symbol
  from `{project}.markets_us.market_mapping`
  where lower(sportsbook) = 'crypto.com'
    and start_date > timestamp_sub(current_timestamp(), interval 21 day)
)
select
  case when mp.symbol is not null then 'IN_market_mapping' else 'NOT_in_mapping' end as class,
  count(*) as distinct_symbols,
  sum(mf.rfqs) as rfqs
from mf
left join mapped mp using (symbol)
where mf.symbol is not null
group by 1
order by 1;

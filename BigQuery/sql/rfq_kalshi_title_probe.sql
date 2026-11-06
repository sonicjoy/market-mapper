-- Title probe for Kalshi event tickers (Wave A3 / Wave B evidence).
-- Substitute {project}. Pass event tickers via the IN list.

select
  json_value(data, '$.event_ticker') as event_ticker,
  any_value(json_value(data, '$.title')) as title,
  any_value(json_value(data, '$.yes_sub_title')) as yes_sub_title,
  string_agg(distinct json_value(data, '$.ticker') limit 6) as sample_tickers
from `{project}.raw_ingestion_us.kalshi_raw`
where insert_time > timestamp_sub(current_timestamp(), interval 21 day)
  and json_value(data, '$.event_ticker') in (
    'KXUFCFIGHT-26AUG15WELORO',
    'KXCLUBFGAME-26AUG11UNICOR',
    'KXCLUBFGAME-26AUG11PALJUV',
    'KXLEAGUESCUPGAME-26AUG09AMEPOR'
  )
group by 1
order by 1
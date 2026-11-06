-- Release 068 #6 soak metrics for RFQ-eligible rows in the fixture window.
-- Placeholders: {project}, {fixture_window_where}
with windowed as (
  select
    lower(sportsbook) as sportsbook_key,
    source_ids,
    is_rfq_winner,
    rank_run_at
  from `{project}.opticodds_us.opticodds_mapping`
  where {fixture_window_where}
),
rfq_eligible as (
  select
    sportsbook_key,
    source_ids,
    is_rfq_winner,
    rank_run_at
  from windowed
  where json_value(source_ids, '$.market_id') is not null
     or json_value(source_ids, '$.selection_id') is not null
),
multi as (
  select count(*) as multi_winner_keys
  from (
    select 1
    from rfq_eligible
    where is_rfq_winner is true
    group by concat(
      sportsbook_key, '|',
      coalesce(json_value(source_ids, '$.market_id'), ''), '|',
      coalesce(json_value(source_ids, '$.selection_id'), '')
    )
    having count(*) > 1
  )
),
counts as (
  select
    count(*) as rfq_total,
    countif(is_rfq_winner is null) as rfq_unranked,
    approx_quantiles(
      if(
        rank_run_at is not null,
        timestamp_diff(current_timestamp(), rank_run_at, minute),
        null
      ),
      100
    )[offset(99)] as rank_lag_p99_min
  from rfq_eligible
)
select
  multi.multi_winner_keys,
  counts.rfq_total,
  counts.rfq_unranked,
  counts.rank_lag_p99_min
from multi
cross join counts
;

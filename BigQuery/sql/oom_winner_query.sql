-- Shared winner query for mapping-cache-service (G4b) and test-only BQ loads (G4).
-- Placeholders: {project}, {sportsbook_lower}
-- Serve a row when is_rfq_winner OR it is the sole RFQ-key candidate (R2 gap).
with candidates as (
  select
    o.game_id,
    o.fixture_id,
    o.market_id,
    o.selection,
    o.selection_line,
    o.points as selection_points,
    o.grouping_key,
    o.sport,
    o.league,
    o.start_date,
    o.mapping_source,
    o.market_match_method,
    o.verify_tier,
    o.rank_class,
    o.is_rfq_winner,
    o.rank_run_at,
    o.rank_version,
    o.source_ids,
    json_value(o.source_ids, '$.market_id') as src_market_id,
    json_value(o.source_ids, '$.selection_id') as src_selection_id,
    concat(
      lower(o.sportsbook), '|',
      coalesce(json_value(o.source_ids, '$.market_id'), ''), '|',
      coalesce(json_value(o.source_ids, '$.selection_id'), '')
    ) as rfq_key,
    count(*) over (
      partition by concat(
        lower(o.sportsbook), '|',
        coalesce(json_value(o.source_ids, '$.market_id'), ''), '|',
        coalesce(json_value(o.source_ids, '$.selection_id'), '')
      )
    ) as rfq_key_count
  from `{project}.opticodds_us.opticodds_mapping` as o
  where o.last_updated >= timestamp_sub(current_timestamp(), interval 16 day)
    and o.start_date > timestamp_sub(current_timestamp(), interval 4 hour)
    and o.start_date < timestamp_add(current_timestamp(), interval 14 day)
    and lower(o.sportsbook) = '{sportsbook_lower}'
    and (
      json_value(o.source_ids, '$.market_id') is not null
      or json_value(o.source_ids, '$.selection_id') is not null
    )
)
select *
from candidates
where is_rfq_winner is true
   or (rfq_key_count = 1 and is_rfq_winner is null)
;

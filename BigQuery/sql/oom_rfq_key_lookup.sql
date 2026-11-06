-- Point lookup for one RFQ key in opticodds_mapping (console G5).
-- Unlike the live winner query, catalog lookup is not limited to the rank
-- window — operators need to see stale/outside-window rows too. in_rank_window
-- flags whether fold+rank / override materialisation still applies.
-- Placeholders: {project}
with candidates as (
  select
    o.game_id,
    o.fixture_id,
    o.market_id,
    o.selection,
    o.selection_line,
    o.points,
    o.selection_points,
    o.grouping_key,
    o.sport,
    o.league,
    o.start_date,
    o.sportsbook,
    o.mapping_source,
    o.market_match_method,
    o.verify_tier,
    o.rank_class,
    o.is_rfq_winner,
    o.is_mapping_override,
    o.rank_run_at,
    o.rank_version,
    o.last_updated,
    o.source_ids,
    json_value(o.source_ids, '$.market_id') as src_market_id,
    json_value(o.source_ids, '$.selection_id') as src_selection_id,
    concat(
      lower(o.sportsbook), '|',
      coalesce(json_value(o.source_ids, '$.market_id'), ''), '|',
      coalesce(json_value(o.source_ids, '$.selection_id'), '')
    ) as rfq_key,
    coalesce(
      o.start_date is not null
      and o.start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
      and o.start_date <= timestamp_add(current_timestamp(), interval 14 day),
      false
    ) as in_rank_window,
    count(*) over (
      partition by concat(
        lower(o.sportsbook), '|',
        coalesce(json_value(o.source_ids, '$.market_id'), ''), '|',
        coalesce(json_value(o.source_ids, '$.selection_id'), '')
      )
    ) as rfq_key_count
  from `{project}.opticodds_us.opticodds_mapping` as o
  where lower(o.sportsbook) = @sportsbook_lower
    and lower(coalesce(json_value(o.source_ids, '$.market_id'), '')) = lower(@src_market_id)
    and lower(coalesce(json_value(o.source_ids, '$.selection_id'), '')) = lower(@src_selection_id)
    {recency_filter}
)
select *
from candidates
order by
  is_rfq_winner desc nulls last,
  rank_run_at desc nulls last,
  mapping_source,
  last_updated desc
;

-- Detail drill-down for Polymarket / Polymarket US RFQ mapping gaps.
-- Project placeholder {project} is substituted by scripts/print_polymarket_gap_sql.py.
--
-- Grain: one row per official clob_token_id, or per US ticker when no token_id.
-- Window matches RFQ coverage dashboards (3h last_updated, 48h first_publish).
-- Wired Path 2 prefixes come from the activated tip COW lineage (not a hardcoded list).
--
-- Summary: polymarket_mapping_gaps_summary.sql
-- Census: polymarket_prefix_optic_census.sql
-- Docs: docs/polymarket-mapping-gaps.md
--
-- NOTE: WITH RECURSIVE must be the outermost WITH (BQ rejects nested recursive CTEs).
-- NOTE: the depth guard matches BigQuery's own 500-iteration ceiling. A lower cap
-- silently truncates the lineage and under-reports what the tip actually maps.

with recursive
lineage as (
  select rule_set_id, parent_rule_set_id, created_at, 0 as depth
  from (
    select rule_set_id, parent_rule_set_id, created_at
    from `{project}.markets_us.mapping_rule_sets`
    order by created_at desc
    limit 1
  )
  union all
  select s.rule_set_id, s.parent_rule_set_id, s.created_at, lineage.depth + 1
  from `{project}.markets_us.mapping_rule_sets` as s
  inner join lineage
    on s.rule_set_id = lineage.parent_rule_set_id
  where lineage.depth < 500
),

params as (
  select
    3 as rfq_lookback_hours,
    48 as rfq_publish_lookback_hours,
    14 as bridge_lookback_days,
    90 as mm_lookback_days,
    7 as optic_lookback_days,
    40 as optic_forward_days
),

ranked_leagues as (
  select
    l.league,
    l.optic_league_id,
    l.exchanges,
    ifnull(l.tombstone, false) as tombstone,
    row_number() over (partition by l.league order by lin.depth) as rn
  from `{project}.markets_us.mapping_leagues` as l
  inner join lineage as lin using (rule_set_id)
),

wired_prefixes as (
  select distinct
    json_value(to_json_string(e.settings), '$.slug_prefix') as slug_prefix,
    r.league as tip_league,
    r.optic_league_id
  from ranked_leagues as r,
  unnest(r.exchanges) as e
  where r.rn = 1
    and r.tombstone = false
    and e.sportsbook = 'polymarket'
    and ifnull(e.enabled, true)
    and json_value(to_json_string(e.settings), '$.slug_prefix') is not null
),

-- Polymarket US is its own exchange pin; its inner league code is the pin's
-- source_league_id (settings.slug_prefix is the console's older spelling).
wired_us_prefixes as (
  select distinct
    coalesce(
      e.source_league_id,
      json_value(to_json_string(e.settings), '$.slug_prefix')
    ) as us_slug_prefix,
    r.league as tip_league,
    r.optic_league_id
  from ranked_leagues as r,
  unnest(r.exchanges) as e
  where r.rn = 1
    and r.tombstone = false
    and e.sportsbook = 'polymarket_usa'
    and ifnull(e.enabled, true)
    and coalesce(
      e.source_league_id,
      json_value(to_json_string(e.settings), '$.slug_prefix')
    ) is not null
),

rfqs as (
  select
    external_rfq_id,
    platform,
    reason,
    legs
  from `{project}.reporting_us.rfq_latest`, params p
  where last_updated > timestamp_sub(current_timestamp(), interval p.rfq_lookback_hours hour)
    and first_publish_time > timestamp_sub(
      current_timestamp(), interval p.rfq_publish_lookback_hours hour)
    and lower(platform) like 'polymarket%'
    and reason in ('MAPPING_FAILED', 'UNMAPPED')
),

unmapped_legs as (
  select
    r.platform,
    r.reason,
    r.external_rfq_id,
    json_value(l.platform_mapping, '$.token_id') as position_id,
    json_value(l.platform_mapping, '$.condition_id') as condition_id,
    coalesce(
      json_value(l.platform_mapping, '$.symbol'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.ticker')
    ) as ticker,
    json_value(l.platform_mapping, '$.side') as pm_side
  from rfqs r,
  unnest(r.legs) as l
  where l.optic_fixture_id is null
     or l.market is null
     or l.selection is null
),

bridge as (
  select
    position_id,
    any_value(clob_token_id) as clob_token_id,
    any_value(slug) as slug,
    any_value(question) as question,
    any_value(outcome_label) as outcome_label,
    any_value(game_start_time) as game_start_time
  from `{project}.raw_ingestion_us.polymarket_position_token_bridge`, params p
  where last_updated > timestamp_sub(
      current_timestamp(), interval p.bridge_lookback_days day)
  group by position_id
),

mm_official as (
  select distinct
    json_value(source_ids, '$.selection_id') as clob_token_id
  from `{project}.markets_us.market_mapping`, params p
  where start_date > timestamp_sub(current_timestamp(), interval p.mm_lookback_days day)
    and sportsbook = 'Polymarket'
    and json_value(source_ids, '$.selection_id') is not null
),

-- Poly US inner + sportsMarketType from the gateway record the fetch stored
-- (typed); the symbol itself is never split.
us_records as (
  select
    market_id as ticker,
    any_value(inner_league) as inner_league,
    any_value(json_value(data, '$.sports_market_type')) as sports_market_type
  from `{project}.raw_ingestion_us.polymarket_usa_fetch_raw`
  where fetch_time > timestamp_sub(current_timestamp(), interval 1 day)
  group by market_id
),
mm_usa as (
  select distinct
    json_value(source_ids, '$.market_id') as market_id
  from `{project}.markets_us.market_mapping`, params p
  where start_date > timestamp_sub(current_timestamp(), interval p.mm_lookback_days day)
    and sportsbook = 'Polymarket (USA)'
    and json_value(source_ids, '$.market_id') is not null
),

optic_fixtures as (
  select
    league.id as optic_league_id,
    lower(home_team_display) as home_cf,
    lower(away_team_display) as away_cf,
    cast(date(start_date) as string) as d,
    start_date,
    starts_with(ifnull(game_id, ''), 'wsdsyn-') as is_synthetic
  from `{project}.opticodds_us.opticodds_fixtures`, params p
  where start_date between timestamp_sub(
      current_timestamp(), interval p.optic_lookback_days day)
    and timestamp_add(current_timestamp(), interval p.optic_forward_days day)
    and char_length(home_team_display) between 4 and 200
    and char_length(away_team_display) between 4 and 200
  qualify row_number() over (
    partition by game_id
    order by start_date desc
  ) = 1
),

enriched as (
  select
    u.platform,
    u.reason,
    u.external_rfq_id,
    u.position_id,
    u.condition_id,
    u.ticker,
    u.pm_side,
    b.clob_token_id,
    coalesce(b.slug, u.ticker) as slug,
    b.question,
    b.outcome_label,
    b.game_start_time,
    case
      when lower(u.platform) like '%us%'
        then ur.inner_league
      else regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
    end as slug_prefix,
    case
      when lower(u.platform) like '%us%'
        then ur.sports_market_type
      else null
    end as us_sports_market_type,
    case
      when lower(u.platform) like '%us%' then
        exists (
          select 1 from mm_usa m
          where m.market_id = u.ticker
        )
      else
        exists (
          select 1 from mm_official m
          where m.clob_token_id = b.clob_token_id
        )
    end as already_in_market_mapping,
    exists (
      select 1 from wired_prefixes w
      where w.slug_prefix = case
        when lower(u.platform) like '%us%'
          then ur.inner_league
        else regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
      end
    ) as path2_wired,
    exists (
      select 1 from wired_us_prefixes w
      where w.us_slug_prefix = ur.inner_league
    ) as us_path2_wired,
    (
      b.question is not null
      and b.game_start_time is not null
      and exists (
        select 1
        from optic_fixtures ofx
        where ofx.d = cast(date(b.game_start_time) as string)
          and not ofx.is_synthetic
          and strpos(lower(b.question), ofx.home_cf) > 0
          and strpos(lower(b.question), ofx.away_cf) > 0
      )
    ) as fixture_has_optic,
    (
      b.question is not null
      and b.game_start_time is not null
      and exists (
        select 1
        from optic_fixtures ofx
        where ofx.d = cast(date(b.game_start_time) as string)
          and ofx.is_synthetic
          and strpos(lower(b.question), ofx.home_cf) > 0
          and strpos(lower(b.question), ofx.away_cf) > 0
      )
    ) as fixture_has_synthetic
  from unmapped_legs u
  left join bridge b on b.position_id = u.position_id
  left join us_records ur on ur.ticker = lower(u.ticker)
),

classified as (
  select
    *,
    case
      when lower(platform) not like '%us%'
           and (position_id is null or clob_token_id is null or slug is null)
        then 'no_bridge'
      when already_in_market_mapping
        then 'maker-lag'
      when lower(platform) like '%us%' and us_path2_wired
        then 'us_optic_no_passthrough'
      when lower(platform) like '%us%'
        then 'path2_off (no Optic fixture)'
      when lower(ifnull(outcome_label, '')) in ('no', 'no.')
        then 'expected residual: yes-only No'
      when regexp_contains(lower(ifnull(slug, '')), r'exact-score|exact_score')
        then 'expected residual: exact_score'
      when regexp_contains(lower(ifnull(question, '')), r'\bvs\b.+/')
           or regexp_contains(lower(ifnull(slug, '')), r'doubles')
        then 'expected residual: doubles'
      when regexp_contains(lower(ifnull(slug, '')), r'to-advance|advance')
        then 'expected residual: to_advance'
      when regexp_contains(lower(ifnull(slug, '')), r'corners-(first|second)-half|odd-even-corners')
        then 'expected residual: half_or_oddeven_corners'
      when regexp_contains(lower(ifnull(slug, '')), r'-game[0-9]|-map[0-9]|round-handicap|map-handicap|maps-total')
        then 'expected residual: esports_map_or_prop'
      when regexp_contains(
             lower(ifnull(slug, '')),
             r'(first|second|1st|2nd)-half|-(1q|2q|3q|4q|1h|2h)-'
           )
        then 'expected residual: period_market'
      when regexp_contains(lower(ifnull(question, '')), r'\bcompleted\b')
        then 'expected residual: completed'
      when path2_wired and fixture_has_optic
        then 'actionable game-line gap'
      when path2_wired and not fixture_has_optic and fixture_has_synthetic
        then 'expected residual: no_optic_book'
      when path2_wired and not fixture_has_optic
           and game_start_time is not null
           and game_start_time > timestamp_add(current_timestamp(), interval 96 hour)
        then 'outside Optic horizon'
      when path2_wired and not fixture_has_optic
        then 'optic_empty'
      when not path2_wired and fixture_has_optic
        then 'actionable path2_off (Optic fixture present)'
      when not path2_wired
        then 'path2_off (no Optic fixture)'
      else 'unclassified'
    end as gap_reason
  from enriched
)

select
  platform,
  clob_token_id,
  position_id,
  slug,
  ticker,
  slug_prefix,
  us_sports_market_type,
  question,
  outcome_label,
  gap_reason,
  case
    when gap_reason like 'actionable%' then 'propose / fix tip'
    when gap_reason = 'maker-lag' then 'wait for maker cache'
    when gap_reason = 'no_bridge' then 'wait for bridge loader'
    when gap_reason = 'optic_empty' then 'wait / alias / fixture_source'
    when gap_reason = 'outside Optic horizon' then 'wait'
    when gap_reason like 'expected residual%' then 'leave'
    when gap_reason = 'us_optic_no_passthrough' then 'Optic / maker ask'
    else 'review'
  end as action,
  case
    when gap_reason like 'actionable%' then 1
    when gap_reason in ('optic_empty', 'us_optic_no_passthrough') then 2
    when gap_reason like 'path2_off%' then 3
    when gap_reason = 'maker-lag' then 4
    else 5
  end as priority,
  already_in_market_mapping,
  path2_wired,
  fixture_has_optic,
  count(*) as occ,
  count(distinct external_rfq_id) as distinct_rfqs
from classified
group by
  platform, clob_token_id, position_id, slug, ticker, slug_prefix, us_sports_market_type,
  question, outcome_label, gap_reason, action, priority,
  already_in_market_mapping, path2_wired, fixture_has_optic
order by priority, occ desc

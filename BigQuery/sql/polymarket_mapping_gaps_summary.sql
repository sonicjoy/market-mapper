-- Summary rollup for Polymarket / Polymarket US RFQ mapping gaps.
-- Project placeholder {project} is substituted by scripts/print_polymarket_gap_sql.py.
--
-- Detail: polymarket_mapping_gaps.sql
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
    l.exchanges,
    ifnull(l.tombstone, false) as tombstone,
    row_number() over (partition by l.league order by lin.depth) as rn
  from `{project}.markets_us.mapping_leagues` as l
  inner join lineage as lin using (rule_set_id)
),

wired_prefixes as (
  select distinct
    json_value(to_json_string(e.settings), '$.slug_prefix') as slug_prefix
  from ranked_leagues as r,
  unnest(r.exchanges) as e
  where r.rn = 1
    and r.tombstone = false
    and e.sportsbook = 'polymarket'
    and ifnull(e.enabled, true)
    and json_value(to_json_string(e.settings), '$.slug_prefix') is not null
),

rfqs as (
  select external_rfq_id, platform, reason, legs
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
    r.external_rfq_id,
    json_value(l.platform_mapping, '$.token_id') as position_id,
    coalesce(
      json_value(l.platform_mapping, '$.symbol'),
      json_value(l.platform_mapping, '$.market_ticker'),
      json_value(l.platform_mapping, '$.ticker')
    ) as ticker
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
  select distinct json_value(source_ids, '$.selection_id') as clob_token_id
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
  select distinct json_value(source_ids, '$.market_id') as market_id
  from `{project}.markets_us.market_mapping`, params p
  where start_date > timestamp_sub(current_timestamp(), interval p.mm_lookback_days day)
    and sportsbook = 'Polymarket (USA)'
    and json_value(source_ids, '$.market_id') is not null
),

optic_fixtures as (
  select
    lower(home_team_display) as home_cf,
    lower(away_team_display) as away_cf,
    cast(date(start_date) as string) as d,
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

classified as (
  select
    u.platform,
    coalesce(
      case
        when lower(u.platform) like '%us%'
          then ur.inner_league
        else regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
      end,
      '(null)'
    ) as slug_prefix,
    case
      when lower(u.platform) not like '%us%'
           and (u.position_id is null or b.clob_token_id is null or b.slug is null)
        then 'no_bridge'
      when (
        case
          when lower(u.platform) like '%us%' then
            exists (select 1 from mm_usa m where m.market_id = u.ticker)
          else
            exists (select 1 from mm_official m where m.clob_token_id = b.clob_token_id)
        end
      ) then 'maker-lag'
      when lower(u.platform) like '%us%'
           and exists (
             select 1 from wired_prefixes w
             where w.slug_prefix = ur.inner_league
           )
        then 'us_optic_no_passthrough'
      when lower(u.platform) like '%us%'
        then 'path2_off (no Optic fixture)'
      when lower(ifnull(b.outcome_label, '')) in ('no', 'no.')
        then 'expected residual: yes-only No'
      when regexp_contains(lower(ifnull(b.slug, '')), r'exact-score|exact_score')
        then 'expected residual: exact_score'
      when regexp_contains(lower(ifnull(b.slug, '')), r'to-advance|advance')
        then 'expected residual: to_advance'
      when regexp_contains(lower(ifnull(b.slug, '')), r'corners-(first|second)-half|odd-even-corners')
        then 'expected residual: half_or_oddeven_corners'
      when regexp_contains(lower(ifnull(b.slug, '')), r'-game[0-9]|-map[0-9]|round-handicap|map-handicap|maps-total')
        then 'expected residual: esports_map_or_prop'
      when regexp_contains(
             lower(ifnull(b.slug, '')),
             r'(first|second|1st|2nd)-half|-(1q|2q|3q|4q|1h|2h)-'
           )
        then 'expected residual: period_market'
      when regexp_contains(lower(ifnull(b.question, '')), r'\bcompleted\b')
        then 'expected residual: completed'
      when exists (
             select 1 from wired_prefixes w
             where w.slug_prefix = regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
           )
           and b.question is not null
           and b.game_start_time is not null
           and exists (
             select 1 from optic_fixtures ofx
             where ofx.d = cast(date(b.game_start_time) as string)
               and not ofx.is_synthetic
               and strpos(lower(b.question), ofx.home_cf) > 0
               and strpos(lower(b.question), ofx.away_cf) > 0
           )
        then 'actionable game-line gap'
      when exists (
             select 1 from wired_prefixes w
             where w.slug_prefix = regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
           )
           and b.question is not null
           and b.game_start_time is not null
           and exists (
             select 1 from optic_fixtures ofx
             where ofx.d = cast(date(b.game_start_time) as string)
               and ofx.is_synthetic
               and strpos(lower(b.question), ofx.home_cf) > 0
               and strpos(lower(b.question), ofx.away_cf) > 0
           )
        then 'expected residual: no_optic_book'
      when exists (
             select 1 from wired_prefixes w
             where w.slug_prefix = regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
           )
           and b.game_start_time is not null
           and b.game_start_time > timestamp_add(current_timestamp(), interval 96 hour)
        then 'outside Optic horizon'
      when exists (
             select 1 from wired_prefixes w
             where w.slug_prefix = regexp_extract(coalesce(b.slug, u.ticker), r'^([a-z0-9]+)-')
           )
        then 'optic_empty'
      when b.question is not null
           and b.game_start_time is not null
           and exists (
             select 1 from optic_fixtures ofx
             where ofx.d = cast(date(b.game_start_time) as string)
               and not ofx.is_synthetic
               and strpos(lower(b.question), ofx.home_cf) > 0
               and strpos(lower(b.question), ofx.away_cf) > 0
           )
        then 'actionable path2_off (Optic fixture present)'
      else 'path2_off (no Optic fixture)'
    end as gap_reason,
    u.external_rfq_id,
    coalesce(b.clob_token_id, u.ticker) as identity_key
  from unmapped_legs u
  left join bridge b on b.position_id = u.position_id
  left join us_records ur on ur.ticker = lower(u.ticker)
)

select
  case
    when gap_reason like 'actionable%' then 1
    when gap_reason in ('optic_empty', 'us_optic_no_passthrough') then 2
    when gap_reason like 'path2_off%' then 3
    when gap_reason = 'maker-lag' then 4
    else 5
  end as priority,
  gap_reason,
  slug_prefix,
  platform,
  count(*) as occ,
  count(distinct identity_key) as distinct_identities,
  count(distinct external_rfq_id) as distinct_rfqs,
  gap_reason like 'actionable%' as is_actionable
from classified
group by priority, gap_reason, slug_prefix, platform
order by priority, occ desc

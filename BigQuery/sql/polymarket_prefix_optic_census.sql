-- Bulk Optic-vs-bridge prefix census for Polymarket Path 2 onboarding.
-- Project placeholder {project} is substituted by scripts/print_polymarket_gap_sql.py.
--
-- For each bridge slug_prefix (7d), group to one row per fixture, aggregate
-- questions, then join opticodds_fixtures (-7d..+40d) on same date plus both
-- display names appearing in the questions. Marks already-wired prefixes from
-- the activated tip COW lineage.
--
-- Caveat: prop questions that name no teams undercount matches (e.g. efl).
-- A low match count is not evidence of absence.
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
    7 as bridge_lookback_days,
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
    r.optic_league_id as tip_optic_league_id
  from ranked_leagues as r,
  unnest(r.exchanges) as e
  where r.rn = 1
    and r.tombstone = false
    and e.sportsbook = 'polymarket'
    and ifnull(e.enabled, true)
    and json_value(to_json_string(e.settings), '$.slug_prefix') is not null
),

bridge_fixtures as (
  select
    split(slug, '-')[offset(0)] as pfx,
    regexp_extract(slug, r'(\d{4}-\d{2}-\d{2})') as d,
    split(slug, '-')[safe_offset(1)] as code_a,
    split(slug, '-')[safe_offset(2)] as code_b,
    string_agg(distinct question, '  ~  ' limit 20) as q,
    count(*) as n
  from `{project}.raw_ingestion_us.polymarket_position_token_bridge`, params p
  where last_updated between timestamp_sub(
      current_timestamp(), interval p.bridge_lookback_days day)
    and current_timestamp()
    and regexp_extract(slug, r'(\d{4}-\d{2}-\d{2})') is not null
  group by 1, 2, 3, 4
),

optic as (
  select
    league.id as lid,
    lower(home_team_display) as h,
    lower(away_team_display) as a,
    cast(date(start_date) as string) as d
  from `{project}.opticodds_us.opticodds_fixtures`, params p
  where start_date between timestamp_sub(
      current_timestamp(), interval p.optic_lookback_days day)
    and timestamp_add(current_timestamp(), interval p.optic_forward_days day)
    and char_length(home_team_display) between 4 and 200
    and char_length(away_team_display) between 4 and 200
    and not starts_with(ifnull(game_id, ''), 'wsdsyn-')
  group by 1, 2, 3, 4
),

matched as (
  select
    b.pfx as slug_prefix,
    o.lid as optic_league_id,
    count(*) as fixtures_matched,
    sum(b.n) as bridge_rows
  from bridge_fixtures b
  join optic o
    on b.d = o.d
   and strpos(lower(b.q), o.h) != 0
   and strpos(lower(b.q), o.a) != 0
  group by 1, 2
)

select
  m.slug_prefix,
  m.optic_league_id,
  m.fixtures_matched,
  m.bridge_rows,
  w.tip_league,
  w.tip_optic_league_id,
  w.slug_prefix is not null as already_wired,
  case
    when w.slug_prefix is not null
         and w.tip_optic_league_id = m.optic_league_id
      then 'wired_match'
    when w.slug_prefix is not null
      then 'wired_other_optic'
    else 'unwired_candidate'
  end as status
from matched m
left join wired_prefixes w
  on w.slug_prefix = m.slug_prefix
order by m.bridge_rows desc, m.fixtures_matched desc

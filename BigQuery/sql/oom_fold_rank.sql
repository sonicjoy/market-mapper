-- release 068 g2 — fold greg into opticodds_mapping and rank rfq winners.
--
-- rank order (g0 confirmed 2026-09-15):
--   override > curated greg (market_match_method != optic_passthrough)
--   > original > greg passthrough
-- tiebreak: verify_tier, last_updated desc, canonical-key string.
--
-- stale game_id (rank_version 2, mmmapper#27): optic re-keys a rescheduled game
-- (game_id carries the start hour, fixture_id stays). a row whose fixture's
-- current game_id (latest opticodds_fixtures publish per fixture id) differs from
-- its own game_id is stale: it ranks after every live row and is never the winner,
-- so a reschedule leaves one served row per rfq key. rows whose fixture is not in
-- the window, or whose fixture_id is null, are unaffected.
--
-- orphan greg (rank_version 3): the fold only upserts, so a greg row the mapper
-- stopped emitting keeps its old rfq key. a greg row whose merge key is absent
-- from this run's greg_apply ranks after every current row of the same rfq key
-- (kalshi line relabel: the corrected row wins). only an orphaned polymarket
-- optic passthrough is also barred from winning outright — the mapper strips
-- those when the token's own question names another player or game. other
-- orphans (underdog / sx bet / novig rows market_mapping reaped) still serve
-- when nothing current replaces them. nothing is deleted.
--
-- rank_version: bump when rank logic changes (currently 4).
-- cross-check block (rank_version 4): a disagreed passthrough token cannot
-- win as ORIGINAL or optic_passthrough. A curated row (our matcher) for the
-- same exchange id is not blocked.
-- merge key matches infra prices_state_merge.sql step 5 (idempotent overlap).
--
-- column ownership:
--   fold writes full greg rows (mapping_source = 'GREG') + provenance.
--   rank stamps fixture_id (original from fixtures), is_rfq_winner, rank_class,
--   rank_run_at, rank_version on all rows in the fixture window.
--   fold does not overwrite original infra-owned columns.
--
-- rfq key: lower(sportsbook) + market_id + selection_id (empty string when absent).
-- rank any row with at least one of market_id / selection_id present.

begin;

-- ---------------------------------------------------------------------------
-- permission probe (fails fast if datasets are unreadable)
-- ---------------------------------------------------------------------------
select 1 as ok
from `{project}.opticodds_us.opticodds_mapping`
limit 1;

select 1 as ok
from `{project}.markets_us.market_mapping`
where
  start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and start_date <= timestamp_add(current_timestamp(), interval 14 day)
limit 1;

select 1 as ok
from `{project}.opticodds_us.opticodds_fixtures`
where
  start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and start_date <= timestamp_add(current_timestamp(), interval 14 day)
limit 1;

-- ---------------------------------------------------------------------------
-- 1. dedupe greg rows to one row per merge key
-- ---------------------------------------------------------------------------
-- the merge key has no venue id, so a venue that maps two contracts to one odd
-- (kalshi / dkex / underdog: the odd's own yes and the opponent's complement no)
-- leaves two rows per key with the same last_updated (one load). on that tie
-- keep the yes row, then the lowest source_ids: the pick is stable across runs
-- and every column below comes from the same row.
create temp table greg_apply as
select
  game_id,
  market_id,
  lower(sportsbook) as sportsbook_key,
  array_agg(sportsbook order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as sportsbook,
  selection,
  ifnull(selection_line, '') as selection_line,
  ifnull(points, 0) as points,
  0 as selection_points,
  grouping_key,
  array_agg(
    parse_json(to_json_string(source_ids))
    order by last_updated desc, no_side, ids_key
    limit 1
  )[offset(0)] as source_ids,
  array_agg(start_date order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as start_date,
  array_agg(sport order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as sport,
  array_agg(league order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as league,
  array_agg(fixture_id order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as fixture_id,
  array_agg(
    market_match_method order by last_updated desc, no_side, ids_key limit 1
  )[offset(0)] as market_match_method,
  array_agg(verify_tier order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as verify_tier,
  array_agg(market_rule_id order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as market_rule_id,
  array_agg(last_updated order by last_updated desc, no_side, ids_key limit 1)[offset(0)] as greg_last_updated
from (
  select
    *,
    coalesce(json_value(to_json_string(source_ids), '$.selection_id') = 'no', false) as no_side,
    to_json_string(source_ids) as ids_key
  from `{project}.markets_us.market_mapping`
  where
    start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
    and start_date <= timestamp_add(current_timestamp(), interval 14 day)
)
group by
  game_id,
  market_id,
  lower(sportsbook),
  selection,
  ifnull(selection_line, ''),
  ifnull(points, 0),
  grouping_key;

-- ---------------------------------------------------------------------------
-- 2. fold greg into opticodds_mapping (same merge key as infra step 5)
-- ---------------------------------------------------------------------------
merge `{project}.opticodds_us.opticodds_mapping` as target
using greg_apply as source
on
  target.game_id = source.game_id
  and target.market_id = source.market_id
  and lower(target.sportsbook) = source.sportsbook_key
  and target.selection = source.selection
  and ifnull(target.selection_line, '') = source.selection_line
  and ifnull(target.points, 0) = source.points
  and ifnull(target.selection_points, 0) = source.selection_points
  and target.grouping_key = source.grouping_key
when matched and target.mapping_source = 'GREG' then
update set
  target.source_ids = source.source_ids,
  target.fixture_id = source.fixture_id,
  target.market_match_method = source.market_match_method,
  target.verify_tier = source.verify_tier,
  target.market_rule_id = source.market_rule_id,
  target.is_mapping_override = null,
  target.mapping_source = 'GREG',
  target.last_updated = source.greg_last_updated
when not matched by target and source.start_date is not null then
insert (
  game_id,
  start_date,
  sport,
  league,
  market_id,
  market,
  sportsbook,
  selection,
  selection_line,
  points,
  selection_points,
  grouping_key,
  is_main,
  is_live,
  exclude_fees,
  source_ids,
  is_mapping_override,
  mapping_source,
  last_updated,
  fixture_id,
  market_match_method,
  verify_tier,
  market_rule_id
)
values (
  source.game_id,
  source.start_date,
  source.sport,
  source.league,
  source.market_id,
  null,
  source.sportsbook,
  source.selection,
  source.selection_line,
  source.points,
  source.selection_points,
  source.grouping_key,
  null,
  null,
  null,
  source.source_ids,
  null,
  'GREG',
  source.greg_last_updated,
  source.fixture_id,
  source.market_match_method,
  source.verify_tier,
  source.market_rule_id
);

-- ---------------------------------------------------------------------------
-- 3. fixture lookup for original rows (latest publish_time per game_id)
-- ---------------------------------------------------------------------------
create temp table fixture_lookup as
select
  game_id,
  id as fixture_id
from `{project}.opticodds_us.opticodds_fixtures`
where
  start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and start_date <= timestamp_add(current_timestamp(), interval 14 day)
qualify row_number() over (partition by game_id order by publish_time desc) = 1;

-- current game_id per fixture (the one optic lists now; stale re-keyed ids drop out).
-- only a live listing defines "current": a completed / cancelled row is the OLD game
-- of a reschedule (2026-09-27: fixture 202609271F8EFA33 listed only as the completed
-- 09-26 game after it moved to 09-27) and must never demote the live game.
create temp table fixture_current as
select
  id as fixture_id,
  game_id
from `{project}.opticodds_us.opticodds_fixtures`
where
  start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and start_date <= timestamp_add(current_timestamp(), interval 14 day)
  and status in ('unplayed', 'live', 'delayed')
qualify row_number() over (partition by id order by publish_time desc) = 1;

-- ---------------------------------------------------------------------------
-- 4. score every row in the fixture window for ranking
-- ---------------------------------------------------------------------------
create temp table rank_scored as
select
  o.game_id,
  o.market_id,
  lower(o.sportsbook) as sportsbook_key,
  o.sportsbook,
  o.selection,
  ifnull(o.selection_line, '') as selection_line,
  ifnull(o.points, 0) as points,
  ifnull(o.selection_points, 0) as selection_points,
  o.grouping_key,
  o.last_updated,
  concat(
    lower(o.sportsbook),
    '|',
    coalesce(json_value(o.source_ids, '$.market_id'), ''),
    '|',
    coalesce(json_value(o.source_ids, '$.selection_id'), '')
  ) as rfq_key,
  case
    when coalesce(o.is_mapping_override, false) then 1
    when o.mapping_source = 'GREG'
      and o.market_match_method is not null
      and o.market_match_method != 'optic_passthrough' then 2
    when o.mapping_source = 'ORIGINAL'
      or (o.mapping_source is null and not coalesce(o.is_mapping_override, false)) then 3
    when o.mapping_source = 'GREG' then 4
    else 5
  end as rank_priority,
  case coalesce(o.verify_tier, '')
    when 'optic_id_agree' then 1
    when 'optic_odd_agree' then 2
    when 'novel' then 3
    when 'semantic' then 4
    else 5
  end as verify_tier_ord,
  concat(
    coalesce(o.game_id, ''),
    '|',
    coalesce(o.market_id, ''),
    '|',
    lower(coalesce(o.sportsbook, '')),
    '|',
    coalesce(o.selection, ''),
    '|',
    coalesce(o.selection_line, ''),
    '|',
    cast(ifnull(o.points, 0) as string),
    '|',
    cast(ifnull(o.selection_points, 0) as string),
    '|',
    coalesce(o.grouping_key, '')
  ) as canonical_key_str,
  case
    when coalesce(o.is_mapping_override, false) then 'override'
    when o.mapping_source = 'GREG'
      and o.market_match_method is not null
      and o.market_match_method != 'optic_passthrough' then 'curated_greg'
    when o.mapping_source = 'ORIGINAL'
      or (o.mapping_source is null and not coalesce(o.is_mapping_override, false)) then 'original'
    when o.mapping_source = 'GREG' then 'greg_passthrough'
    else 'unknown'
  end as rank_class,
  case
    when o.mapping_source = 'ORIGINAL'
      or (o.mapping_source is null and not coalesce(o.is_mapping_override, false))
      then coalesce(fl.fixture_id, o.fixture_id)
    else o.fixture_id
  end as fixture_id_out,
  coalesce(fc.game_id is not null and fc.game_id != o.game_id, false) as is_stale_game,
  (o.mapping_source = 'GREG' and ga.game_id is null) as is_orphan_greg,
  (
    o.mapping_source = 'GREG'
    and ga.game_id is null
    and lower(o.sportsbook) = 'polymarket'
    and coalesce(o.market_match_method, 'optic_passthrough') = 'optic_passthrough'
  ) as is_withdrawn_passthrough,
  (
    bl.rfq_key is not null
    and not coalesce(o.is_mapping_override, false)
    and (
      o.mapping_source = 'ORIGINAL'
      or o.mapping_source is null
      or coalesce(o.market_match_method, 'optic_passthrough') = 'optic_passthrough'
    )
  ) as is_blocked_crosscheck
from `{project}.opticodds_us.opticodds_mapping` as o
left join `{project}.markets_us.optic_passthrough_blocklist` as bl
  on bl.rfq_key = concat(
    lower(o.sportsbook),
    '|',
    coalesce(json_value(o.source_ids, '$.market_id'), ''),
    '|',
    coalesce(json_value(o.source_ids, '$.selection_id'), '')
  )
left join greg_apply as ga
  on ga.game_id = o.game_id
  and ga.market_id = o.market_id
  and ga.sportsbook_key = lower(o.sportsbook)
  and ga.selection = o.selection
  and ga.selection_line = ifnull(o.selection_line, '')
  and ga.points = ifnull(o.points, 0)
  and ga.selection_points = ifnull(o.selection_points, 0)
  and ga.grouping_key = o.grouping_key
left join fixture_lookup as fl
  on fl.game_id = o.game_id
left join fixture_current as fc
  on fc.fixture_id = case
    when o.mapping_source = 'ORIGINAL'
      or (o.mapping_source is null and not coalesce(o.is_mapping_override, false))
      then coalesce(fl.fixture_id, o.fixture_id)
    else o.fixture_id
  end
where
  o.start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
  and o.start_date <= timestamp_add(current_timestamp(), interval 14 day)
  and (
    json_value(o.source_ids, '$.market_id') is not null
    or json_value(o.source_ids, '$.selection_id') is not null
  );

create temp table rank_stamped as
select
  rs.*,
  row_number() over (
    partition by rs.rfq_key
    order by
      rs.is_blocked_crosscheck,
      rs.is_stale_game,
      rs.is_orphan_greg,
      rs.rank_priority,
      rs.verify_tier_ord,
      rs.last_updated desc,
      rs.canonical_key_str
  ) as rn
from rank_scored as rs;

-- ---------------------------------------------------------------------------
-- 5. stamp rank columns (+ fixture_id for original rows)
-- ---------------------------------------------------------------------------
merge `{project}.opticodds_us.opticodds_mapping` as target
using rank_stamped as source
on
  target.game_id = source.game_id
  and target.market_id = source.market_id
  and lower(target.sportsbook) = source.sportsbook_key
  and target.selection = source.selection
  and ifnull(target.selection_line, '') = source.selection_line
  and ifnull(target.points, 0) = source.points
  and ifnull(target.selection_points, 0) = source.selection_points
  and target.grouping_key = source.grouping_key
when matched then
update set
  target.fixture_id = source.fixture_id_out,
  target.is_rfq_winner = (
    source.rn = 1
    and not source.is_stale_game
    and not source.is_withdrawn_passthrough
    and not source.is_blocked_crosscheck
  ),
  target.rank_class = source.rank_class,
  target.rank_run_at = current_timestamp(),
  target.rank_version = 4;

drop table greg_apply;
drop table fixture_lookup;
drop table fixture_current;
drop table rank_scored;
drop table rank_stamped;

commit;

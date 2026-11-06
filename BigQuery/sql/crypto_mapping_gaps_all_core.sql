-- Shared CTE body for the consolidated (all-league) crypto gap queries.
-- Composed with a select tail by BigQuery/crypto_gap_sql.py:
--   crypto_mapping_gaps_all_summary.sql  (rollup)
--   crypto_mapping_gaps_all.sql          (per-symbol drill-down, console)
--
-- The project id and the league dimension literal are substituted at
-- load time by BigQuery/crypto_gap_sql.py.
--
-- WHY THIS EXISTS.  The per-league templates (crypto_mapping_gaps*.sql) bake
-- league_prefix, the optic horizon and the mapped contract-type vocabulary
-- into the SQL text, so covering 27 crypto-enabled leagues meant 27 jobs,
-- each re-scanning the same four sources in full.  None of the sources
-- prunes on the per-league predicate: markets_us.market_mapping is filtered
-- only on sportsbook + a 90-day start_date window, and the crypto catalogue
-- / quote-request tables are filtered on `symbol like '<prefix>%'`, which no
-- partition or cluster key can satisfy.  Measured 2026-09-08 on
-- rs-marketmaking: 12.77 GB per league summary job, identical for all 27.
--
-- Here every per-league difference is a column on the `leagues` dimension
-- and the sources are scanned once.
--
-- SEMANTIC EQUIVALENCE.  Three places had to be generalised carefully:
--  * symbol -> league is a LIKE join, not equality, so it reproduces the
--    per-league `symbol like concat(prefix,'%')` filter exactly (including
--    the — currently impossible — case of one symbol matching two prefixes,
--    which the 27-job version would also have counted twice).
--  * the fixture-prefix regex becomes league-agnostic; `[^-]+` cannot cross
--    a '-', so it matches the same league token the literal did.
--  * every `partition by` that used to be implicitly league-scoped (because
--    the query only ever saw one league) is now explicitly partitioned by
--    league_prefix.

with leagues as (
  select * from unnest([
{leagues_struct}
  ])
),

params as (
  select
    5 as lookback_hours,
    14 as catalogue_lookback_days,
    5 as min_qr_requests
),

-- No league predicate here in the per-league form either: this scan was
-- always global and was simply repeated 27 times.
mm as (
  select
    json_value(source_ids, '$.symbol') as symbol,
    regexp_replace(json_value(source_ids, '$.symbol'), r'\.[0-9]{8}$', '') as symbol_base,
    market_type
  from `{project}.markets_us.market_mapping`
  where start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and sportsbook = 'crypto.com'
),

mm_bases as (
  select distinct symbol_base from mm
),

-- Fixtures that already have Optic-merged crypto spreads loaded.
-- Unmapped spread legs on these are crypto-only extended handicaps, not
-- mapper failures (crypto lists a wider ladder than Optic quotes).
-- fixture_prefix keys carry the league token, so one global bucket per
-- fixture is league-safe: a key from league A can never join a symbol
-- from league B.
mm_fixture_spreads as (
  select
    regexp_extract(symbol, r'(NX\.F\.OPT\.[^-]+-\d+-\d{6})') as fixture_prefix,
    count(*) as mapped_spread_symbols
  from mm
  where market_type = 'point_spread'
  group by 1
),

-- Optic fixtures in the leagues each crypto mapper actually fetches (e.g.
-- atp/atp_challenger/itf_men/itf_women/wta for NX.F.OPT.TENNIS). Crypto RFQs
-- for matches outside these leagues are not actionable alias/mapper gaps.
-- The join to `leagues` replaces the per-league `league.id in unnest([...])`
-- filter; dedupe is partitioned by league_prefix so it stays per-league.
optic_fixtures as (
  select
    l.league_prefix,
    lower(f.home_team_display) as home_cf,
    lower(f.away_team_display) as away_cf,
    f.start_date
  from `{project}.opticodds_us.opticodds_fixtures` f
  join leagues l on f.league.id in unnest(l.optic_league_ids)
  where f.start_date > timestamp_sub(current_timestamp(), interval 14 day)
    and f.start_date < timestamp_add(current_timestamp(), interval 14 day)
  qualify row_number() over (
    partition by l.league_prefix, f.game_id
    order by f.start_date desc
  ) = 1
),

-- QR volume: leg symbols from processed_upstream_us.crypto_quote_requests
-- (structured NoLegs / LegSymbol), not raw FIX regexp on fixText.
-- The group key is the symbol, which determines the league, so grouping
-- once globally gives the same per-symbol counts the 27 league-filtered
-- queries did.
qr as (
  select
    leg.symbol as sym,
    regexp_replace(leg.symbol, r'\.[0-9]{8}$', '') as symbol_base,
    count(*) as qr_requests
  from `{project}.processed_upstream_us.crypto_quote_requests`, params p,
       unnest(symbols) as s,
       unnest(s.legs) as leg
  where publish_time > timestamp_sub(current_timestamp(), interval p.lookback_hours hour)
    and leg.symbol like 'NX.F.OPT.%'
    and leg.symbol not like 'NX.F.OPT.COMBOS%'
  group by sym, symbol_base
  having count(*) >= (select min_qr_requests from params)
),

qr_league as (
  select
    l.league_prefix,
    l.optic_horizon_hours,
    l.mapped_game_lines,
    l.mapped_player_props,
    l.mapped_team_props,
    l.mapped_game_props,
    q.sym,
    q.symbol_base,
    q.qr_requests
  from qr q
  join leagues l on q.sym like concat(l.league_prefix, '%')
),

-- Catalogue: union of crypto_underlying_securities (daily SecurityList) and
-- crypto_security_def (live FIX).  The underlying table alone lags intraday
-- listings; SecurityDef carries the same meta_* fields and is fresher.
catalogue as (
  select
    symbol,
    regexp_replace(symbol, r'\.[0-9]{8}$', '') as symbol_base,
    market_group,
    contract_type,
    meta_name,
    event_date,
    publish_time
  from (
    select
      symbol,
      meta_predict_market_type as market_group,
      meta_predict_contract_type as contract_type,
      meta_name,
      safe.parse_timestamp(
        '%Y-%m-%dT%H:%M:%E*S%Ez',
        meta_event_date
      ) as event_date,
      publish_time
    from `{project}.processed_upstream_us.crypto_underlying_securities`, params p
    where publish_time > timestamp_sub(
        current_timestamp(), interval p.catalogue_lookback_days day)
      and symbol like 'NX.F.OPT.%'

    union all

    select
      symbol,
      meta_predict_market_type as market_group,
      meta_predict_contract_type as contract_type,
      meta_name,
      safe.parse_timestamp(
        '%Y-%m-%dT%H:%M:%E*S%Ez',
        meta_event_date
      ) as event_date,
      publish_time
    from `{project}.processed_upstream_us.crypto_security_def`, params p
    where publish_time > timestamp_sub(
        current_timestamp(), interval p.catalogue_lookback_days day)
      and symbol like 'NX.F.OPT.%'
  )
  qualify row_number() over (
    partition by symbol
    order by publish_time desc
  ) = 1
),

resolved_catalogue as (
  select
    q.league_prefix,
    q.sym,
    coalesce(c.symbol, c2.symbol) as catalogue_symbol,
    coalesce(c.market_group, c2.market_group) as market_group,
    coalesce(c.contract_type, c2.contract_type) as contract_type,
    coalesce(c.meta_name, c2.meta_name) as meta_name,
    -- Opponent pair for Optic fixture matching. Soccer uses
    -- "Away @ Home"; UFC uses "Home vs Away" (optionally with
    -- ": Prop" or "(Event)" suffixes).
    case
      when regexp_contains(coalesce(c.meta_name, c2.meta_name), r' @ ')
        then lower(trim(split(
          coalesce(c.meta_name, c2.meta_name), ' @ ')[safe_offset(0)]))
      when regexp_contains(coalesce(c.meta_name, c2.meta_name), r' vs ')
        then lower(trim(split(
          regexp_replace(
            coalesce(c.meta_name, c2.meta_name), r'\s*[:\(].*$', ''),
            ' vs ')[safe_offset(0)]))
      else null
    end as meta_side_a,
    case
      when regexp_contains(coalesce(c.meta_name, c2.meta_name), r' @ ')
        then lower(trim(split(
          coalesce(c.meta_name, c2.meta_name), ' @ ')[safe_offset(1)]))
      when regexp_contains(coalesce(c.meta_name, c2.meta_name), r' vs ')
        then lower(trim(split(
          regexp_replace(
            coalesce(c.meta_name, c2.meta_name), r'\s*[:\(].*$', ''),
            ' vs ')[safe_offset(1)]))
      else null
    end as meta_side_b,
    coalesce(
      c.event_date,
      c2.event_date,
      safe.parse_timestamp('%y%m%d', regexp_extract(q.sym, r'-(\d{6})-M'))
    ) as kickoff,
    c.symbol is null and c2.symbol is not null as catalogue_base_match_only
  from qr_league q
  left join catalogue c on q.sym = c.symbol
  left join catalogue c2
    on c.symbol is null
    and q.symbol_base = c2.symbol_base
  qualify row_number() over (
    partition by q.league_prefix, q.sym
    order by
      case when c.symbol is not null then 0 else 1 end,
      coalesce(c.publish_time, c2.publish_time) desc
  ) = 1
),

-- The per-league query expressed this as a correlated `exists` against
-- optic_fixtures.  Once optic_fixtures carries league_prefix the
-- correlation spans two outer tables and BigQuery refuses to de-correlate
-- it, so the same predicate is materialised as a semi-join here.  The
-- three null guards that used to sit alongside the `exists` are the where
-- clause; the join body is the `exists` body verbatim.
optic_matched as (
  select distinct rc.league_prefix, rc.sym
  from resolved_catalogue rc
  join optic_fixtures ofx
    on ofx.league_prefix = rc.league_prefix
    and abs(timestamp_diff(rc.kickoff, ofx.start_date, hour)) <= 18
    and (
      (
        rc.meta_side_a = ofx.home_cf
        and rc.meta_side_b = ofx.away_cf
      )
      or (
        rc.meta_side_a = ofx.away_cf
        and rc.meta_side_b = ofx.home_cf
      )
    )
  where rc.meta_side_a is not null
    and rc.meta_side_b is not null
    and rc.kickoff is not null
),

gaps_base as (
  select
    q.league_prefix,
    q.optic_horizon_hours,
    q.mapped_game_lines,
    q.mapped_player_props,
    q.mapped_team_props,
    q.mapped_game_props,
    q.sym as requested_symbol,
    q.qr_requests,
    coalesce(mfs.mapped_spread_symbols, 0) > 0 as fixture_has_mapped_spreads,
    om.sym is not null as fixture_has_optic,
    rc.market_group,
    rc.contract_type,
    rc.meta_name,
    rc.kickoff,
    rc.catalogue_base_match_only
  from qr_league q
  left join mm m on q.sym = m.symbol
  left join mm_bases mb on q.symbol_base = mb.symbol_base
  left join resolved_catalogue rc
    on q.league_prefix = rc.league_prefix
    and q.sym = rc.sym
  left join optic_matched om
    on q.league_prefix = om.league_prefix
    and q.sym = om.sym
  left join mm_fixture_spreads mfs
    on regexp_extract(q.sym, r'(NX\.F\.OPT\.[^-]+-\d+-\d{6})') = mfs.fixture_prefix
  where m.symbol is null
    and mb.symbol_base is null
),

-- Same classification ladder as the per-league templates, with the mapped
-- vocabulary read from the league dimension instead of a baked-in unnest
-- and the horizon read from the league row instead of `params`.
gaps as (
  select
    league_prefix,
    requested_symbol,
    qr_requests,
    market_group,
    contract_type,
    meta_name,
    kickoff,
    fixture_has_optic,
    fixture_has_mapped_spreads,
    catalogue_base_match_only,
    optic_horizon_hours,
    mapped_game_lines,
    mapped_player_props,
    mapped_team_props,
    mapped_game_props,
    case
      when market_group = 'Player Prop'
           and contract_type in unnest(mapped_player_props)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval optic_horizon_hours hour)
        then 'outside Optic horizon'
      when market_group = 'Player Prop'
           and contract_type in unnest(mapped_player_props)
           and kickoff is not null
           and kickoff < current_timestamp()
        then 'completed fixture (stale symbol): player prop'
      when market_group = 'Player Prop'
           and contract_type in unnest(mapped_player_props)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group = 'Player Prop'
           and contract_type in unnest(mapped_player_props)
        then 'actionable prop gap'
      when market_group = 'Player Prop'
        then concat('unmapped player prop: ', coalesce(contract_type, '?'))
      when market_group = 'Team Prop'
           and contract_type in unnest(mapped_team_props)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval optic_horizon_hours hour)
        then 'outside Optic horizon'
      when market_group = 'Team Prop'
           and contract_type in unnest(mapped_team_props)
           and kickoff is not null
           and kickoff < current_timestamp()
        then 'completed fixture (stale symbol): team prop'
      when market_group = 'Team Prop'
           and contract_type in unnest(mapped_team_props)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group = 'Team Prop'
           and contract_type in unnest(mapped_team_props)
        then 'actionable team-prop gap'
      when market_group = 'Team Prop'
        then concat('unmapped team prop: ', coalesce(contract_type, '?'))
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in unnest(mapped_game_props)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval optic_horizon_hours hour)
        then 'outside Optic horizon'
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in unnest(mapped_game_props)
           and kickoff is not null
           and kickoff < current_timestamp()
        then 'completed fixture (stale symbol): game prop'
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in unnest(mapped_game_props)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in unnest(mapped_game_props)
        then 'actionable game-prop gap'
      when market_group in ('Game Prop', 'Fight Prop')
        then concat('unmapped game prop: ', coalesce(contract_type, '?'))
      when market_group in ('Game Line', 'Fight Line')
           and regexp_contains(lower(coalesce(meta_name, '')), r'all stars')
        then concat('special event (no Optic fixture): ', coalesce(contract_type, '?'))
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in unnest(mapped_game_lines)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval optic_horizon_hours hour)
        then 'outside Optic horizon'
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in unnest(mapped_game_lines)
           and kickoff is not null
           and kickoff < current_timestamp()
        then concat('completed fixture (stale symbol): ', contract_type)
      when market_group in ('Game Line', 'Fight Line')
           and contract_type = 'Spread'
           and fixture_has_mapped_spreads
        then 'crypto-only spread (beyond Optic ladder)'
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in unnest(mapped_game_lines)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in unnest(mapped_game_lines)
        then concat('actionable game-line gap: ', contract_type)
      when market_group in ('Game Line', 'Fight Line')
        then concat('unmapped game line: ', coalesce(contract_type, '?'))
      when catalogue_base_match_only
        then 'in catalogue (base match only) — check maturity suffix'
      when market_group is null
        then 'not in catalogue (wait for upstream)'
      when market_group in ('Player Future', 'Tournament Prop')
        then 'tournament/future market (by design)'
      else concat(
        'unclassified catalogue: ',
        coalesce(market_group, '?'),
        ' / ',
        coalesce(contract_type, '?')
      )
    end as gap_reason
  from gaps_base
)

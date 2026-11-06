-- Summary rollup for crypto.com mapping gaps (post-pipeline alert).
-- Project placeholder {project} is substituted at runtime from GCP_PROJECT.
--
-- BigQuery console (paste-ready SQL):
--   python scripts/print_crypto_gap_sql.py --league ucl --summary
--
-- Catalogue: union of crypto_underlying_securities (daily SecurityList) and
-- crypto_security_def (live FIX).  The underlying table alone lags intraday
-- listings; SecurityDef carries the same meta_* fields and is fresher.
-- QR volume: leg symbols from processed_upstream_us.crypto_quote_requests
-- (structured NoLegs / LegSymbol), not raw FIX regexp on fixText.
--
-- Mapped contract types are substituted at runtime from league CryptoConfig.

with params as (
  select
    5 as lookback_hours,
    14 as catalogue_lookback_days,
    {optic_horizon_hours} as optic_horizon_hours,
    '{league_prefix}' as league_prefix,
    5 as min_qr_requests
),

mapped_player_props as (
  select contract_type from unnest([
    {mapped_player_props}
  ]) as contract_type
),

mapped_team_props as (
  select contract_type from unnest([
    {mapped_team_props}
  ]) as contract_type
),

mapped_game_lines as (
  select contract_type from unnest([
    {mapped_game_lines}
  ]) as contract_type
),

mapped_game_props as (
  select contract_type from unnest([{mapped_game_props}]) as contract_type
),

mm as (
  select
    json_value(source_ids, '$.symbol') as symbol,
    regexp_replace(json_value(source_ids, '$.symbol'), r'\.[0-9]{8}$', '') as symbol_base,
    market_type,
    home,
    away,
    side,
    start_date
  from `{project}.markets_us.market_mapping`, params p
  where start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and sportsbook = 'crypto.com'
),

mm_bases as (
  select distinct symbol_base from mm
),

-- Fixtures that already have Optic-merged crypto spreads loaded.
-- Unmapped spread legs on these are crypto-only extended handicaps, not
-- mapper failures (crypto lists a wider ladder than Optic quotes).
mm_fixture_spreads as (
  select
    regexp_extract(symbol, r'({fixture_prefix_re})') as fixture_prefix,
    count(*) as mapped_spread_symbols
  from mm
  where market_type = 'point_spread'
  group by 1
),

-- Optic fixtures in the leagues this mapper actually fetches (e.g.
-- atp/atp_challenger/itf_men/itf_women/wta). Crypto RFQs for matches outside these leagues
-- are not actionable alias/mapper gaps.
optic_fixtures as (
  select
    lower(home_team_display) as home_cf,
    lower(away_team_display) as away_cf,
    start_date
  from `{project}.opticodds_us.opticodds_fixtures`
  where league.id in unnest([
    {optic_league_ids}
  ])
    and start_date > timestamp_sub(current_timestamp(), interval 14 day)
    and start_date < timestamp_add(current_timestamp(), interval 14 day)
  qualify row_number() over (
    partition by game_id
    order by start_date desc
  ) = 1
),

qr as (
  select
    leg.symbol as sym,
    regexp_replace(leg.symbol, r'\.[0-9]{8}$', '') as symbol_base,
    count(*) as qr_requests
  from `{project}.processed_upstream_us.crypto_quote_requests`, params p,
       unnest(symbols) as s,
       unnest(s.legs) as leg
  where publish_time > timestamp_sub(current_timestamp(), interval p.lookback_hours hour)
    and leg.symbol like concat(p.league_prefix, '%')
    and leg.symbol not like 'NX.F.OPT.COMBOS%'
  group by sym, symbol_base
  having count(*) >= (select min_qr_requests from params)
),

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
      and symbol like concat(p.league_prefix, '%')

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
      and symbol like concat(p.league_prefix, '%')
  )
  qualify row_number() over (
    partition by symbol
    order by publish_time desc
  ) = 1
),

resolved_catalogue as (
  select
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
  from qr q
  left join catalogue c on q.sym = c.symbol
  left join catalogue c2
    on c.symbol is null
    and q.symbol_base = c2.symbol_base
  qualify row_number() over (
    partition by q.sym
    order by
      case when c.symbol is not null then 0 else 1 end,
      coalesce(c.publish_time, c2.publish_time) desc
  ) = 1
),

gaps_base as (
  select
    q.sym as requested_symbol,
    q.qr_requests,
    coalesce(mfs.mapped_spread_symbols, 0) > 0 as fixture_has_mapped_spreads,
    (
      rc.meta_side_a is not null
      and rc.meta_side_b is not null
      and rc.kickoff is not null
      and exists (
        select 1
        from optic_fixtures ofx
        where abs(timestamp_diff(rc.kickoff, ofx.start_date, hour)) <= 18
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
      )
    ) as fixture_has_optic,
    rc.market_group,
    rc.contract_type,
    rc.meta_name,
    rc.kickoff,
    rc.catalogue_base_match_only
  from qr q
  left join mm m on q.sym = m.symbol
  left join mm_bases mb on q.symbol_base = mb.symbol_base
  left join resolved_catalogue rc on q.sym = rc.sym
  left join mm_fixture_spreads mfs
    on regexp_extract(q.sym, r'({fixture_prefix_re})') = mfs.fixture_prefix
  where m.symbol is null
    and mb.symbol_base is null
),

gaps as (
  select
    requested_symbol,
    qr_requests,
    case
      when market_group = 'Player Prop'
           and contract_type in (select contract_type from mapped_player_props)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval (select optic_horizon_hours from params) hour)
        then 'outside Optic horizon'
      when market_group = 'Player Prop'
           and contract_type in (select contract_type from mapped_player_props)
           and kickoff is not null
           and kickoff < current_timestamp()
        then 'completed fixture (stale symbol): player prop'
      when market_group = 'Player Prop'
           and contract_type in (select contract_type from mapped_player_props)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group = 'Player Prop'
           and contract_type in (select contract_type from mapped_player_props)
        then 'actionable prop gap'
      when market_group = 'Player Prop'
        then concat('unmapped player prop: ', coalesce(contract_type, '?'))
      when market_group = 'Team Prop'
           and contract_type in (select contract_type from mapped_team_props)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval (select optic_horizon_hours from params) hour)
        then 'outside Optic horizon'
      when market_group = 'Team Prop'
           and contract_type in (select contract_type from mapped_team_props)
           and kickoff is not null
           and kickoff < current_timestamp()
        then 'completed fixture (stale symbol): team prop'
      when market_group = 'Team Prop'
           and contract_type in (select contract_type from mapped_team_props)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group = 'Team Prop'
           and contract_type in (select contract_type from mapped_team_props)
        then 'actionable team-prop gap'
      when market_group = 'Team Prop'
        then concat('unmapped team prop: ', coalesce(contract_type, '?'))
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in (select contract_type from mapped_game_props)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval (select optic_horizon_hours from params) hour)
        then 'outside Optic horizon'
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in (select contract_type from mapped_game_props)
           and kickoff is not null
           and kickoff < current_timestamp()
        then 'completed fixture (stale symbol): game prop'
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in (select contract_type from mapped_game_props)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group in ('Game Prop', 'Fight Prop')
           and contract_type in (select contract_type from mapped_game_props)
        then 'actionable game-prop gap'
      when market_group in ('Game Prop', 'Fight Prop')
        then concat('unmapped game prop: ', coalesce(contract_type, '?'))
      when market_group in ('Game Line', 'Fight Line')
           and regexp_contains(lower(coalesce(meta_name, '')), r'all stars')
        then concat('special event (no Optic fixture): ', coalesce(contract_type, '?'))
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in (select contract_type from mapped_game_lines)
           and kickoff > timestamp_add(
             current_timestamp(),
             interval (select optic_horizon_hours from params) hour)
        then 'outside Optic horizon'
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in (select contract_type from mapped_game_lines)
           and kickoff is not null
           and kickoff < current_timestamp()
        then concat('completed fixture (stale symbol): ', contract_type)
      when market_group in ('Game Line', 'Fight Line')
           and contract_type = 'Spread'
           and fixture_has_mapped_spreads
        then 'crypto-only spread (beyond Optic ladder)'
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in (select contract_type from mapped_game_lines)
           and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
           and not fixture_has_optic
        then concat('no Optic fixture: ', contract_type)
      when market_group in ('Game Line', 'Fight Line')
           and contract_type in (select contract_type from mapped_game_lines)
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

select
  gap_reason,
  count(*) as distinct_symbols,
  sum(qr_requests) as total_qr_requests
from gaps
group by gap_reason
order by total_qr_requests desc

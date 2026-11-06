-- Per-symbol crypto.com mapping-gap drill-down, ALL leagues in one query.
-- Console / investigation query. The mapper tick does not run it.
--
-- The shared CTE body (crypto_mapping_gaps_all_core.sql) is spliced in
-- ahead of this select at load time.
--
-- Summary rollup: crypto_mapping_gaps_all_summary.sql
-- Per-league form: crypto_mapping_gaps.sql (still used by --league)
--
-- BigQuery console (paste-ready SQL):
--   python scripts/print_crypto_gap_sql.py --all-leagues
{core}
select
  league_prefix,
  requested_symbol,
  qr_requests,
  kickoff,
  case
    when market_group is not null and contract_type is not null
      then concat(market_group, ' / ', contract_type)
    when regexp_contains(requested_symbol, r'M\.O\.1\.[123](\.[0-9]{8})?$')
      then 'Game Line / Moneyline (3-Way) (symbol guess — no catalogue)'
    when regexp_contains(requested_symbol, r'M\.O\.1\.')
      then 'unknown M.O.1.* (symbol guess — no catalogue)'
    when regexp_contains(requested_symbol, r'M\.O\.2\.')
      then 'unknown M.O.2.* (symbol guess — no catalogue)'
    else 'unknown pattern'
  end as inferred_type_label,
  gap_reason,
  case
    when catalogue_base_match_only
      then 'check maturity suffix'
    when kickoff > timestamp_add(
           current_timestamp(),
           interval optic_horizon_hours hour)
      then 'wait for horizon'
    when market_group = 'Player Prop'
         and contract_type in unnest(mapped_player_props)
         and kickoff is not null
         and kickoff < current_timestamp()
      then 'superseded symbol on completed fixture'
    when market_group = 'Player Prop'
         and contract_type in unnest(mapped_player_props)
         and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
         and not fixture_has_optic
      then 'out of scope (no Optic fixture in mapper league)'
    when market_group = 'Player Prop'
         and contract_type in unnest(mapped_player_props)
      then 'investigate mapper / load'
    when market_group = 'Team Prop'
         and contract_type in unnest(mapped_team_props)
         and kickoff is not null
         and kickoff < current_timestamp()
      then 'superseded symbol on completed fixture'
    when market_group = 'Team Prop'
         and contract_type in unnest(mapped_team_props)
         and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
         and not fixture_has_optic
      then 'out of scope (no Optic fixture in mapper league)'
    when market_group = 'Team Prop'
         and contract_type in unnest(mapped_team_props)
      then 'investigate mapper / load'
    when market_group in ('Game Line', 'Fight Line')
         and contract_type in unnest(mapped_game_lines)
         and kickoff is not null
         and kickoff < current_timestamp()
      then 'superseded symbol on completed fixture'
    when market_group in ('Game Line', 'Fight Line')
         and contract_type = 'Spread'
         and fixture_has_mapped_spreads
      then 'expected (crypto ladder wider than Optic)'
    when market_group in ('Game Line', 'Fight Line')
         and contract_type in unnest(mapped_game_lines)
         and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
         and not fixture_has_optic
      then 'out of scope (no Optic fixture in mapper league)'
    when market_group in ('Game Line', 'Fight Line')
         and contract_type in unnest(mapped_game_lines)
      then 'investigate mapper / load'
    when market_group in ('Game Prop', 'Fight Prop')
         and contract_type in unnest(mapped_game_props)
         and kickoff is not null
         and kickoff < current_timestamp()
      then 'superseded symbol on completed fixture'
    when market_group in ('Game Prop', 'Fight Prop')
         and contract_type in unnest(mapped_game_props)
         and regexp_contains(coalesce(meta_name, ''), r' @ | vs ')
         and not fixture_has_optic
      then 'out of scope (no Optic fixture in mapper league)'
    when market_group in ('Game Prop', 'Fight Prop')
         and contract_type in unnest(mapped_game_props)
      then 'investigate mapper / load'
    when market_group is null
      then 'wait for upstream catalogue'
    when market_group = 'Player Prop'
      then 'add mapper config'
    when market_group = 'Team Prop'
      then 'add mapper config'
    when market_group in ('Game Prop', 'Fight Prop')
      then 'add mapper config'
    when market_group in ('Game Line', 'Fight Line')
      then 'add mapper config'
    when market_group in ('Player Future', 'Tournament Prop')
      then 'out of scope (futures)'
    else 'investigate'
  end as action
from gaps
order by qr_requests desc, league_prefix, requested_symbol
limit 1000

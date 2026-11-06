"""BigQuery for Explore → Missing (catalogue minus market_mapping)."""

from __future__ import annotations

# Mirrors fetch/crypto_com_underlying.py catalogue window and stale kickoff gate.
_CRYPTO_MISSING_SQL = """
with cat as (
  select
    symbol,
    regexp_replace(symbol, r'\\.[0-9]{8}$', '') as symbol_base,
    regexp_extract(symbol, r'(NX\\.F\\.OPT\\.[A-Z0-9]+-\\d+-\\d{6})') as fixture_prefix,
    regexp_extract(symbol, r'NX\\.F\\.OPT\\.([A-Z0-9]+)') as crypto_prefix,
    meta_predict_market_type as market_group,
    meta_predict_contract_type as contract_type,
    meta_predict_period_type as period_type,
    meta_name,
    meta_league,
    safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', meta_event_date) as kickoff
  from `{project}.processed_upstream_us.crypto_underlying_securities`
  where publish_time > timestamp_sub(current_timestamp(), interval 21 day)
    and meta_predict_market_type in (
      'Game Line', 'Fight Line', 'Player Prop', 'Team Prop', 'Game Prop', 'Fight Prop')
    and symbol like 'NX.F.OPT.%'
    and symbol not like 'NX.F.OPT.COMBOS%'
  qualify row_number() over (partition by symbol order by publish_time desc) = 1
),
live as (
  select * from cat
  where kickoff is null
     or kickoff > timestamp_sub(current_timestamp(), interval 24 hour)
),
mapped as (
  select distinct
    json_value(source_ids, '$.symbol') as symbol,
    regexp_replace(json_value(source_ids, '$.symbol'), r'\\.[0-9]{8}$', '') as symbol_base,
    regexp_extract(
      json_value(source_ids, '$.symbol'),
      r'(NX\\.F\\.OPT\\.[A-Z0-9]+-\\d+-\\d{6})'
    ) as fixture_prefix
  from `{project}.markets_us.market_mapping`
  where start_date > timestamp_sub(current_timestamp(), interval 90 day)
    and sportsbook = 'crypto.com'
),
mapped_fixtures as (
  select distinct fixture_prefix
  from mapped
  where fixture_prefix is not null
),
missing as (
  select
    l.symbol,
    l.symbol_base,
    l.fixture_prefix,
    l.crypto_prefix,
    l.market_group,
    l.contract_type,
    l.period_type,
    l.meta_name,
    l.meta_league,
    l.kickoff,
    case
      when mf.fixture_prefix is null then 'untouched'
      else 'extra'
    end as scope
  from live l
  left join mapped m
    on m.symbol = l.symbol or m.symbol_base = l.symbol_base
  left join mapped_fixtures mf on mf.fixture_prefix = l.fixture_prefix
  where m.symbol is null
)
select * from missing
{limit_clause}
"""


def crypto_missing_sql(project: str, *, row_cap: int | None = None) -> str:
    """Return the crypto.com missing-symbol catalogue query."""
    limit_clause = f"\nlimit {int(row_cap)}" if row_cap is not None and row_cap > 0 else ""
    return _CRYPTO_MISSING_SQL.replace("{project}", project).replace("{limit_clause}", limit_clause)

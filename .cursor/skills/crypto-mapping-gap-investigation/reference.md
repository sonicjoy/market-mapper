# Crypto mapping gaps — reference

## Probe script

```bash
.venv/Scripts/python.exe .cursor/skills/crypto-mapping-gap-investigation/scripts/probe_symbol.py SYMBOL [PROJECT]
```

Runs: catalogue lookup, fixture mapping count, mapped BTTS fixtures sample, hours to kickoff, full `crypto_mapping_gaps.sql` row for symbol.

## Ad-hoc SQL snippets

### Catalogue for symbol

```sql
select symbol, meta_predict_market_type, meta_predict_contract_type,
       meta_name, meta_event_date, publish_time
from `{project}.processed_upstream_us.crypto_underlying_securities`
where symbol = @sym
   or regexp_replace(symbol, r'\.[0-9]{8}$', '') = @base
qualify row_number() over (partition by symbol order by publish_time desc) = 1
```

### Mapped rows for fixture

```sql
select json_value(source_ids, '$.symbol') as symbol, market_type, home, away, side, line
from `{project}.markets_us.market_mapping`
where start_date > timestamp_sub(current_timestamp(), interval 90 day)
  and sportsbook = 'crypto.com'
  and json_value(source_ids, '$.symbol') like @fixture_prefix || '%'
```

### Catalogue coverage by fixture

```sql
select
  regexp_extract(symbol, r'(NX\.F\.OPT\.FIFA-\d+-\d{6})') as fixture_prefix,
  count(distinct symbol) as catalogue_symbols,
  string_agg(distinct meta_predict_contract_type, ', ' order by meta_predict_contract_type) as types
from `{project}.processed_upstream_us.crypto_underlying_securities`
where symbol like 'NX.F.OPT.FIFA%'
  and publish_time > timestamp_sub(current_timestamp(), interval 14 day)
group by 1
order by 1
```

### QR volume by fixture (structured table)

```sql
select leg.symbol, count(*) as qr_requests
from `{project}.processed_upstream_us.crypto_quote_requests`,
     unnest(symbols) s, unnest(s.legs) leg
where publish_time > timestamp_sub(current_timestamp(), interval 5 hour)
  and leg.symbol like @fixture_prefix || '%'
group by 1
order by 2 desc
```

## Mapped contract types (gap SQL mirrors world_cup.py)

**Player props:** Anytime/First Goalscorer, assists, cards, shots, saves, fouls ladders.

**Game lines:** Moneyline (3-Way), Moneyline (2-Way), Total Goals, Spread, To Advance.

**Game props:** Both Teams To Score.

## Actionable rows

A `gap_reason` that contains `actionable` is a true mapper gap. Other
reasons (horizon, ladder, completed fixture, tournament) are expected.
Repairs are code changes. These queries are manual.

## Common false positives (not mapper bugs)

1. **No catalogue** — upstream SecurityList not published for fixture.
2. **Outside horizon** — crypto RFQs early; Optic/Kalshi lines not posted yet.
3. **Crypto-only spreads** — extended handicap ladder beyond Optic subset.
4. **Partial catalogue** — game lines published, prop wave still trickling.
5. **Stale completed fixtures** — QR traffic on finished games.

## Code map

| Area | Path |
|------|------|
| Crypto symbol parsing | `mappers/exchanges/crypto_com.py` |
| WC crypto vocab | `mappers/exchanges/crypto_soccer.py` (league settings still on the legacy tip) |
| Optic horizon | legacy tip `fixture_horizon_hours` (World Cup is 96h) |
| Gap detail SQL (one league) | `BigQuery/sql/crypto_mapping_gaps.sql` |
| Gap summary SQL (one league) | `BigQuery/sql/crypto_mapping_gaps_summary.sql` |
| All-league gap SQL | `BigQuery/sql/crypto_mapping_gaps_all_core.sql` + `_all_summary.sql` |
| SQL substitution | `BigQuery/crypto_gap_sql.py` |
| BQ table constants | `BigQuery/client.py` |
| Tests | `tests/BigQuery/test_crypto_gap_sql.py` |
| Crypto onboarding doc | `docs/adding-crypto.md` |

## Changelog

- **2026-07-03:** Initial gap investigations; spread reclassification (`crypto-only spread`).
- **2026-07-04:** QR source switched to `crypto_quote_requests`.
- **2026-07-06:** Game props (BTTS) added to 96h horizon gate; `FIFA-00001-260711` BTTS example.
- **2026-09-08:** Alert consolidated from 54 per-league jobs to 2 all-league
  queries and moved off the */15 mapping tick to its own 2-hourly cron.
  Cost: ~50 TiB/day -> 0.23 TiB/day. Use `--all-leagues` for the consolidated
  SQL and `--league <key>` for the unchanged single-league form.
- **2026-09-23:** Scheduled coverage alert removed. gap-propose drafts the
  repairs. The SQL remains for manual drill-down via `crypto_gap_sql.py`.

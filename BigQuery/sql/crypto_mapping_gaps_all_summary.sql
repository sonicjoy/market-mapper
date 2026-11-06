-- Summary rollup for crypto.com mapping gaps, ALL leagues in one query.
-- Manual rollup (scripts/print_crypto_gap_sql.py --all-leagues --summary).
-- The per-league form (crypto_mapping_gaps_summary.sql) is the `--league`
-- drill-down. The mapper tick does not run this query.
--
-- The shared CTE body (crypto_mapping_gaps_all_core.sql) is spliced in
-- ahead of this select at load time.
--
-- BigQuery console (paste-ready SQL):
--   python scripts/print_crypto_gap_sql.py --all-leagues --summary
--
-- Output columns match the per-league rollup plus league_prefix, so
-- GapSummaryRow is unchanged.
{core}
select
  league_prefix,
  gap_reason,
  count(*) as distinct_symbols,
  sum(qr_requests) as total_qr_requests
from gaps
group by league_prefix, gap_reason
order by league_prefix, total_qr_requests desc, gap_reason

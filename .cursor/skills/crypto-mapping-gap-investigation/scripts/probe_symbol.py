#!/usr/bin/env python3
"""Probe a single crypto.com symbol through catalogue, mapping, and gap SQL.

Usage:
    python probe_symbol.py SYMBOL [GCP_PROJECT]

Default project: marketmaking-test.  League vocabulary and fixture-prefix
regex are taken from the symbol's NX.F.OPT.<META> prefix (all crypto-enabled
leagues), not FIFA-only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from BigQuery.crypto_gap_sql import load_detail_sql
from BigQuery.crypto_gap_config import (
    all_gap_leagues,
    fixture_prefix_from_symbol,
    gap_league_for_symbol,
)

DEFAULT_PROJECT = "marketmaking-test"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1

    sym = argv[1].strip()
    project = argv[2].strip() if len(argv) > 2 else DEFAULT_PROJECT
    sym_base = re.sub(r"\.[0-9]{8}$", "", sym)

    league = gap_league_for_symbol(sym)
    if league is None:
        prefixes = ", ".join(sorted({g.league_prefix for g in all_gap_leagues()}))
        print(
            f"unknown league prefix in {sym!r} — expected one of: {prefixes}",
            file=sys.stderr,
        )
        return 1

    fixture_prefix = fixture_prefix_from_symbol(sym) or sym_base

    client = bigquery.Client(project=project)
    params = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sym", "STRING", sym),
            bigquery.ScalarQueryParameter("base", "STRING", sym_base),
        ]
    )

    print(f"=== probe {sym} @ {project} ({league.league_prefix}) ===\n")

    catalogue_sql = f"""
    select symbol, meta_predict_market_type, meta_predict_contract_type,
           meta_name, meta_event_date, publish_time
    from `{project}.processed_upstream_us.crypto_underlying_securities`
    where symbol = @sym
       or regexp_replace(symbol, r'\\.[0-9]{{8}}$', '') = @base
    order by publish_time desc
    limit 5
    """
    print("=== catalogue ===")
    rows = list(client.query(catalogue_sql, job_config=params))
    if not rows:
        print("(none)")
    for row in rows:
        print(dict(row))

    mapped_sql = f"""
    select json_value(source_ids, '$.symbol') as symbol,
           market_type, home, away, side, line, start_date
    from `{project}.markets_us.market_mapping`
    where start_date > timestamp_sub(current_timestamp(), interval 90 day)
      and sportsbook = 'crypto.com'
      and json_value(source_ids, '$.symbol') like @fixture_prefix || '%'
    limit 30
    """
    mapped_params = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "fixture_prefix", "STRING", fixture_prefix,
            ),
        ]
    )
    print("\n=== mapped (fixture) ===")
    mapped = list(client.query(mapped_sql, job_config=mapped_params))
    if not mapped:
        print("(none)")
    for row in mapped:
        print(dict(row))

    gap_sql = (
        f"select * from ({load_detail_sql(project, league)}) "
        f"where requested_symbol = @sym"
    )
    print("\n=== gap row ===")
    gap_rows = list(client.query(gap_sql, job_config=params))
    if not gap_rows:
        print("(not in gap set — below min QR threshold or already mapped)")
    for row in gap_rows:
        print(dict(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""Print ready-to-run crypto gap SQL for the BigQuery console.

The template files under BigQuery/sql/ use {placeholders}; this script
substitutes project, league prefix, mapped vocabulary, and fixture-regex
from each league CryptoConfig so you can paste the output into BigQuery
Studio (or save to a .sql file and open it there).

Usage:
    python scripts/print_crypto_gap_sql.py --all-leagues --summary
    python scripts/print_crypto_gap_sql.py --league ucl
    python scripts/print_crypto_gap_sql.py --league ucl --summary
    python scripts/print_crypto_gap_sql.py --all-leagues --out scratch/all_gaps.sql
    python scripts/print_crypto_gap_sql.py --league ucl --symbol NX.F.OPT.UCL-00001-260714-M.O.1.1.20260830
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from BigQuery.crypto_gap_sql import (
    load_all_detail_sql,
    load_all_summary_sql,
    load_detail_sql,
    load_summary_sql,
)
from BigQuery.crypto_gap_config import (
    all_gap_leagues,
    gap_league_for_cli_arg,
    gap_league_for_symbol,
)

DEFAULT_PROJECT = "marketmaking-test"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print substituted crypto gap SQL for BigQuery console",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--league",
        help="Repo league key (ucl, mlb, world_cup) or NX.F.OPT.<META> prefix",
    )
    scope.add_argument(
        "--all-leagues", action="store_true",
        help="Union gap SQL across every crypto-enabled league",
    )
    parser.add_argument(
        "--project", default=DEFAULT_PROJECT,
        help=f"GCP project id (default: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Emit summary rollup (recommended with --all-leagues)",
    )
    parser.add_argument(
        "--symbol",
        help="Wrap detail SQL filtered to one requested_symbol (single league)",
    )
    parser.add_argument(
        "--out", type=Path,
        help="Write SQL to this file instead of stdout",
    )
    return parser.parse_args(argv)


def _load_sql(project: str, league_arg: str, *, summary: bool) -> str:
    league = gap_league_for_cli_arg(league_arg)
    if league is None:
        known = ", ".join(sorted({g.league_key for g in all_gap_leagues()}))
        raise SystemExit(f"unknown league {league_arg!r} — expected one of: {known}")
    if summary:
        return load_summary_sql(project, league)
    return load_detail_sql(project, league)


def _build_sql(args: argparse.Namespace) -> tuple[str, str]:
    if args.all_leagues:
        if args.symbol:
            raise SystemExit("--symbol cannot be used with --all-leagues")
        if args.summary:
            return "all-leagues summary", load_all_summary_sql(args.project)
        return "all-leagues detail", load_all_detail_sql(args.project)

    assert args.league is not None
    sql = _load_sql(args.project, args.league, summary=args.summary)

    if args.symbol:
        if args.summary:
            raise SystemExit("--symbol requires detail SQL (omit --summary)")
        sym_league = gap_league_for_symbol(args.symbol)
        cli_league = gap_league_for_cli_arg(args.league)
        if sym_league is None:
            raise SystemExit(f"cannot infer league from symbol {args.symbol!r}")
        if cli_league is not None and sym_league.league_prefix != cli_league.league_prefix:
            raise SystemExit(
                f"--symbol league {sym_league.league_prefix!r} != "
                f"--league {cli_league.league_prefix!r}")
        escaped = args.symbol.replace("'", "\\'")
        sql = (
            f"select * from (\n{sql}\n) "
            f"where requested_symbol = '{escaped}'"
        )

    label = args.league
    kind = "summary" if args.summary else "detail"
    return f"{label} {kind}", sql


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    label, sql = _build_sql(args)
    header = f"-- crypto gap {label} @ {args.project}\n"
    out = header + sql + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

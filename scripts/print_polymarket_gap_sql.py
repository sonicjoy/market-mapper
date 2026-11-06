#!/usr/bin/env python3
"""Print ready-to-run Polymarket gap / census SQL for the BigQuery console.

Templates under BigQuery/sql/ use {project}; this script substitutes the
GCP project id so you can paste into BigQuery Studio.

Usage:
    python scripts/print_polymarket_gap_sql.py --summary
    python scripts/print_polymarket_gap_sql.py --detail
    python scripts/print_polymarket_gap_sql.py --census
    python scripts/print_polymarket_gap_sql.py --summary --project rs-marketmaking
    python scripts/print_polymarket_gap_sql.py --summary --out scratch/poly_gaps.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "BigQuery" / "sql"

DEFAULT_PROJECT = "marketmaking-test"

TEMPLATES = {
    "detail": "polymarket_mapping_gaps.sql",
    "summary": "polymarket_mapping_gaps_summary.sql",
    "census": "polymarket_prefix_optic_census.sql",
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print substituted Polymarket gap SQL for BigQuery console",
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--detail", action="store_true",
        help="Emit per-clob / per-ticker detail SQL",
    )
    which.add_argument(
        "--summary", action="store_true",
        help="Emit priority x gap_reason x prefix rollup",
    )
    which.add_argument(
        "--census", action="store_true",
        help="Emit Optic-vs-bridge prefix census",
    )
    parser.add_argument(
        "--project", default=DEFAULT_PROJECT,
        help=f"GCP project id (default: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--out", type=Path,
        help="Write SQL to this file instead of stdout",
    )
    return parser.parse_args(argv)


def _load(kind: str, project: str) -> str:
    path = SQL_DIR / TEMPLATES[kind]
    text = path.read_text(encoding="utf-8")
    return text.replace("{project}", project)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    kind = "detail" if args.detail else "summary" if args.summary else "census"
    sql = _load(kind, args.project)
    label = f"{kind} ({args.project})"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(sql, encoding="utf-8")
        print(f"wrote {label} -> {args.out}", file=sys.stderr)
    else:
        print(f"-- {label}", file=sys.stderr)
        print(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

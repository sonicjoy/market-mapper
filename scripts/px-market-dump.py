#!/usr/bin/env python3
"""Pretty-print ProphetX market records.

Usage: px-market-dump.py <sport> <date> [--list-types] [--type TYPE]

Options:
  --list-types   Show unique type values with counts, then exit.
  --type TYPE    Filter to records matching the given type
                 (e.g. moneyline, spread, total).
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Pretty-print ProphetX market records.",
    )
    parser.add_argument("sport")
    parser.add_argument("date")
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="Show unique type values with counts, then exit.",
    )
    parser.add_argument(
        "--type",
        dest="type_filter",
        help="Filter to records with this type value.",
    )
    args = parser.parse_args()

    path = Path("data") / args.sport / args.date / "prophetx_markets.jsonl"
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if args.list_types:
        counts: dict[str, int] = {}
        for rec in records:
            t = rec.get("type", "(missing)")
            counts[t] = counts.get(t, 0) + 1
        for t, cnt in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"{t}: {cnt}")
        return

    if args.type_filter:
        records = [r for r in records if r.get("type") == args.type_filter]

    for i, rec in enumerate(records):
        if i > 0:
            print()
        print(json.dumps(rec, indent=2))

    print(f"\n{len(records)} records", file=sys.stderr)


if __name__ == "__main__":
    main()

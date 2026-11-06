#!/usr/bin/env python3
"""Pretty-print a JSONL data file.

Usage: dump.py <sport> <date> <category> [<type>]

Categories:
  px-events    prophetx_events.jsonl
  px-markets   prophetx_markets.jsonl
  kalshi       kalshi_markets.jsonl
  optic        optic_fixtures_odds.jsonl

The optional <type> argument filters kalshi records by ticker type code
(e.g. SPREAD, TOTAL, PTS).  Extracted from event_ticker by stripping the
KXNBA prefix and taking everything before the dash.
"""

import json
import sys
from pathlib import Path

CATEGORIES = {
    "px-events": "prophetx_events.jsonl",
    "px-markets": "prophetx_markets.jsonl",
    "kalshi": "kalshi_markets.jsonl",
    "optic": "optic_fixtures_odds.jsonl",
}

def _kalshi_type_code(record):
    """Extract ticker type code from a Kalshi record's event_ticker.

    E.g. "KXNBASPREAD-26FEB19BKNCLE" → "SPREAD".
    Returns None if event_ticker is missing or doesn't match.
    """
    et = record.get("event_ticker", "")
    if not et.startswith("KXNBA"):
        return None
    rest = et[len("KXNBA"):]
    dash = rest.find("-")
    if dash <= 0:
        return None
    return rest[:dash]


def main():
    if not (4 <= len(sys.argv) <= 5):
        print(f"Usage: {sys.argv[0]} <sport> <date> <category> [<type>]",
              file=sys.stderr)
        sys.exit(1)

    sport, date, category = sys.argv[1], sys.argv[2], sys.argv[3]
    type_filter = sys.argv[4].upper() if len(sys.argv) == 5 else None

    if category not in CATEGORIES:
        valid = ", ".join(CATEGORIES)
        print(f"Unknown category '{category}'.  Valid: {valid}", file=sys.stderr)
        sys.exit(1)

    path = Path("data") / sport / date / CATEGORIES[category]
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    count = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if type_filter and category == "kalshi":
                code = _kalshi_type_code(record)
                if code != type_filter:
                    continue
            if count > 0:
                print()
            print(json.dumps(record, indent=2))
            count += 1

    suffix = f" (filtered by {type_filter})" if type_filter else ""
    print(f"\n{count} records{suffix}", file=sys.stderr)

if __name__ == "__main__":
    main()

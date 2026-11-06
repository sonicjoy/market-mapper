"""Fetch full raw Kalshi market data for a single ticker.

Usage (single market ticker):
    python scripts/inspect_kalshi_market.py KXNBAGAME-26MAR12CLEBOS-CLE

Usage (event ticker — fetches all markets under the event):
    python scripts/inspect_kalshi_market.py --event KXNBAGAME-26MAR12CLEBOS
"""

import json
import sys

sys.path.insert(0, ".")
from fetch.kalshi import load_credentials, kalshi_get


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--event":
        mode = "event"
        ticker = sys.argv[2]
    elif len(sys.argv) == 2:
        mode = "market"
        ticker = sys.argv[1]
    else:
        print(f"Usage: {sys.argv[0]} [--event] <ticker>", file=sys.stderr)
        sys.exit(1)

    print("Loading credentials...", file=sys.stderr)
    key_id, private_key = load_credentials()

    if mode == "event":
        print(f"Fetching event {ticker}...", file=sys.stderr)
        result = kalshi_get(
            f"/trade-api/v2/events/{ticker}",
            None, key_id, private_key,
        )
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Fetching market {ticker}...", file=sys.stderr)
        result = kalshi_get(
            f"/trade-api/v2/markets/{ticker}",
            None, key_id, private_key,
        )
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

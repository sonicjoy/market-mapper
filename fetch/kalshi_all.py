"""Fetch every Kalshi Sports market (raw) to JSONL for raw-stash.

Unlike fetch.kalshi, which fetches only the leagues the mapping
pipeline can process, this module pulls every series under
Kalshi's Sports category and writes the **full** market record
(no field-stripping) to kalshi_markets_raw.jsonl.  Intended for a
separate, less-frequent cron that loads into
raw_ingestion_us.kalshi_raw for post-hoc analysis — prices,
volumes and orderbook snapshots are preserved because they can't
be reconstructed after the fact.

Usage:
    python -m fetch.kalshi_all --out-dir data_raw/2026-04-22/12_00
"""

import argparse
import json
import os
import sys
import time

import requests

from fetch.kalshi import BASE_URL, kalshi_get, load_credentials


def fetch_sports_series() -> list[dict]:
    """Fetch all Sports-category series from the public /series endpoint.

    The category= filter is slightly loose (a handful of
    Entertainment/World records leak in); enforce client-side.
    """
    resp = requests.get(
        BASE_URL + "/trade-api/v2/series",
        params={"category": "Sports"}, timeout=30,
    )
    resp.raise_for_status()
    series = resp.json().get("series") or []
    return [s for s in series if s.get("category") == "Sports"]


def fetch_markets_raw(
    series_ticker: str, key_id, private_key, *, max_pages: int = 1000,
) -> list[dict]:
    """Paginate all open markets for a series, returning RAW records.

    Unlike fetch.kalshi.fetch_markets — which strips to structural
    fields for the mapping pipeline — this function preserves every
    field Kalshi returns so the raw-stash table can support
    downstream analysis of prices, volumes, etc.
    """
    all_markets: list[dict] = []
    cursor = ""
    for _ in range(max_pages):
        params: dict[str, str | int] = {
            "series_ticker": series_ticker,
            "status": "open",
        }
        if cursor:
            params["cursor"] = cursor
        result = kalshi_get(
            "/trade-api/v2/markets", params, key_id, private_key,
        )
        all_markets.extend(result.get("markets", []))
        cursor = result.get("cursor", "")
        if not cursor:
            break
    return all_markets


def main():
    parser = argparse.ArgumentParser(
        description="Fetch every Kalshi Sports market (raw) to JSONL.",
    )
    parser.add_argument(
        "--out-dir", required=True,
        help="Output directory for kalshi_markets_raw.jsonl",
    )
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "kalshi_markets_raw.jsonl")

    print("Loading credentials from GCP Secret Manager...", file=sys.stderr)
    key_id, private_key = load_credentials()

    t0 = time.monotonic()
    sports_series = fetch_sports_series()
    series_tickers = sorted(s["ticker"] for s in sports_series)
    print(f"Fetched {len(series_tickers)} Sports-category series",
          file=sys.stderr)

    total_markets = 0
    with open(out_path, "w") as f:
        for i, ticker in enumerate(series_tickers, 1):
            markets = fetch_markets_raw(ticker, key_id, private_key)
            for m in markets:
                f.write(json.dumps(m) + "\n")
            total_markets += len(markets)
            print(f"  [{i}/{len(series_tickers)}] {ticker}: "
                  f"{len(markets)} markets",
                  file=sys.stderr)

    elapsed = time.monotonic() - t0
    print(f"\nWrote {total_markets} markets to {out_path} "
          f"in {elapsed:.1f}s")


if __name__ == "__main__":
    main()

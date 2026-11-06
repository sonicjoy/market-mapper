"""Probe the Kalshi /series endpoint with various category params.

Unauthenticated — /series is public.  Prints counts and sample
tickers per category value, plus the unfiltered baseline.

Usage:
    python scripts/probe_kalshi_series.py
    python scripts/probe_kalshi_series.py --category Sports
"""

import argparse
import sys
from collections import Counter

import requests

BASE_URL = "https://api.elections.kalshi.com"


def fetch_series(params: dict | None) -> list[dict]:
    resp = requests.get(
        BASE_URL + "/trade-api/v2/series", params=params, timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("series") or []


def summarize(label: str, series: list[dict]) -> None:
    print(f"\n=== {label} ===")
    print(f"total: {len(series)}")
    if not series:
        return
    # Show the keys present on the first record so we learn the schema.
    print(f"keys on first record: {sorted(series[0].keys())}")
    # If there's a category-like field, count values.
    for key in ("category", "categories", "tags"):
        if key in series[0]:
            values = []
            for s in series:
                v = s.get(key)
                if isinstance(v, list):
                    values.extend(v)
                elif v is not None:
                    values.append(v)
            c = Counter(values)
            print(f"\n{key} distribution:")
            for name, n in c.most_common():
                print(f"  {n:4d}  {name}")
    # Show ticker prefix distribution (first 5-ish letters) so we
    # learn what sport prefixes exist.
    prefixes: Counter = Counter()
    for s in series:
        t = s.get("ticker", "")
        # Group by the alphabetic prefix before any digits.
        import re
        m = re.match(r"^[A-Z]+", t)
        prefixes[m.group(0) if m else t] += 1
    print(f"\nticker-prefix distribution (top 30):")
    for p, n in prefixes.most_common(30):
        print(f"  {n:4d}  {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", help="category query param to try")
    ap.add_argument(
        "--try-common", action="store_true",
        help="probe a list of plausible category values",
    )
    args = ap.parse_args()

    if args.try_common:
        # No filter baseline first.
        summarize("no filter (baseline)", fetch_series(None))
        for cat in [
            "Sports", "sports", "SPORTS",
            "Politics", "Economics", "Weather",
            "Basketball", "Baseball", "Football", "Soccer", "Tennis",
            "Hockey", "MMA", "UFC",
        ]:
            try:
                data = fetch_series({"category": cat})
                summarize(f"category={cat}", data)
            except Exception as e:
                print(f"\ncategory={cat}: ERROR {e}", file=sys.stderr)
        return

    params = {"category": args.category} if args.category else None
    label = f"category={args.category}" if args.category else "no filter"
    summarize(label, fetch_series(params))


if __name__ == "__main__":
    main()

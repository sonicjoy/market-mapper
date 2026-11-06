#!/usr/bin/env python3
"""Show fixture teams and start time in UTC, New York, and Perth.

Searches all optic_fixtures_odds.jsonl files under data/ for the given
fixture ID and prints the match info for each file where it appears.

Usage: python scripts/show_fixture.py <fixture_id>
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Fixed UTC offsets — no pytz/zoneinfo dependency.
UTC = timezone.utc
ET = timezone(timedelta(hours=-4), "ET")       # EDT (Mar–Nov)
AWST = timezone(timedelta(hours=8), "AWST")    # Perth

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FILENAME = "optic_fixtures_odds.jsonl"


def find_files(fixture_id):
    """Use grep to find JSONL files containing the fixture ID."""
    try:
        result = subprocess.run(
            ["grep", "-rl", fixture_id, str(DATA_DIR),
             "--include", FILENAME],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return []
    return sorted(result.stdout.strip().splitlines())


def print_fixture(fixture_id, path):
    """Print fixture info from a single JSONL file."""
    for line in open(path):
        g = json.loads(line)
        if g["id"] != fixture_id:
            continue

        away = g["away_team_display"]
        home = g["home_team_display"]
        dt = datetime.fromisoformat(g["start_date"].replace("Z", "+00:00"))

        print(f"  {away} @ {home}")
        print(f"    UTC:   {dt.astimezone(UTC).strftime('%a %Y-%m-%d %H:%M')}")
        print(f"    ET:    {dt.astimezone(ET).strftime('%a %Y-%m-%d %H:%M')}")
        print(f"    Perth: {dt.astimezone(AWST).strftime('%a %Y-%m-%d %H:%M')}")
        return


def main():
    parser = argparse.ArgumentParser(description="Show fixture times")
    parser.add_argument("fixture_id", help="Optic fixture ID")
    args = parser.parse_args()

    paths = find_files(args.fixture_id)
    if not paths:
        print(f"Fixture {args.fixture_id} not found in {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        # Show the path relative to the repo root.
        rel = Path(path).relative_to(DATA_DIR.parent)
        print(f"{rel}:")
        print_fixture(args.fixture_id, path)
        print()


if __name__ == "__main__":
    main()

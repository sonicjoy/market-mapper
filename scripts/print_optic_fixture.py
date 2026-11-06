#!/usr/bin/env python3
"""Print Optic fixtures as a compact schedule list.

Usage: python scripts/print_optic_fixture.py <data_dir> --league ncaab
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Print Optic fixture schedule")
    parser.add_argument("dir", type=Path, help="Data directory containing JSONL files")
    parser.add_argument("--league", required=True, help="League ID (e.g. nba, ncaab)")
    args = parser.parse_args()

    path = args.dir / "optic_fixtures_odds.jsonl"
    for line in path.open():
        g = json.loads(line)
        if g["league"]["id"] != args.league:
            continue
        away = g["away_competitors"][0]["abbreviation"]
        home = g["home_competitors"][0]["abbreviation"]
        start = g["start_date"]
        away_name = g["away_competitors"][0]["name"]
        home_name = g["home_competitors"][0]["name"]
        print(f"{start}  {away:>5} {away_name:<30} @ {home:>5} {home_name}")


if __name__ == "__main__":
    main()

"""Probe which sportsbooks cause Optic to return point_spread odds.

Fetches odds for a single fixture with different sportsbook sets and
reports which point_spread lines come back.

Usage:
    .venv/bin/python scripts/probe_spread_sbs.py --league nba 2026031788F6F987
"""

import argparse
import sys
from pathlib import Path
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetch.optic import BASE_URL, get_optic, init_headers
from mappers.run import LEAGUES

CURRENT_SBS = ["kalshi", "prophet_x", "fanatics", "draftkings", "betmgm"]

EXTRA_SBS = ["betano", "fanduel", "unibet", "hard_rock", "pinnacle"]


def fetch_spreads(headers, fixture_id, sportsbooks):
    """Fetch odds for fixture with given sportsbooks, return point_spread entries."""
    params = {"fixture_id": fixture_id}
    for sb in sportsbooks:
        params.setdefault("sportsbook", []).append(sb)
    result = get_optic(BASE_URL + "fixtures/odds", headers, params)
    assert len(result) == 1, f"Expected 1 fixture, got {len(result)}"

    spreads = []
    for odd in result[0].get("odds", []):
        market_id = odd.get("market_id", "")
        if market_id == "point_spread":
            spreads.append(odd)
    return spreads


def summarise(spreads):
    """Print a compact summary of spread lines and their source_ids."""
    if not spreads:
        print("  (no point_spread odds returned)")
        return

    for s in sorted(spreads, key=lambda x: (x.get("selection", ""), x.get("points", 0))):
        selection = s.get("selection", s.get("name", "?"))
        points = s.get("points", "?")
        source_ids = s.get("source_ids", {})
        sbs = sorted(source_ids.keys()) if source_ids else ["(none)"]
        print(f"  {selection:>25}  {points:>+6}  source_ids: {', '.join(sbs)}")

    print(f"  --- {len(spreads)} entries total ---")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fixture_id", help="Optic fixture ID")
    parser.add_argument("--league", required=True,
                        choices=sorted(LEAGUES),
                        help="League the fixture belongs to")
    args = parser.parse_args()

    headers = init_headers(args.league)

    print(f"Fixture: {args.fixture_id}\n")

    # Test 1: current sportsbooks
    print(f"=== Current SBs: {', '.join(CURRENT_SBS)} ===")
    spreads = fetch_spreads(headers, args.fixture_id, CURRENT_SBS)
    summarise(spreads)

    sleep(0.3)

    # Test 2: extra sportsbooks only
    print(f"\n=== Extra SBs: {', '.join(EXTRA_SBS)} ===")
    spreads = fetch_spreads(headers, args.fixture_id, EXTRA_SBS)
    summarise(spreads)

    sleep(0.3)

    # Test 3: all combined
    all_sbs = CURRENT_SBS + EXTRA_SBS
    print(f"\n=== All SBs ({len(all_sbs)}): {', '.join(all_sbs)} ===")
    # API limits to 5 per request, so we need two calls
    spreads_1 = fetch_spreads(headers, args.fixture_id, CURRENT_SBS)
    sleep(0.3)
    spreads_2 = fetch_spreads(headers, args.fixture_id, EXTRA_SBS)

    # Deduplicate by ID
    seen = {}
    for s in spreads_1 + spreads_2:
        sid = s.get("id", "")
        if sid not in seen:
            seen[sid] = s
        else:
            # Merge source_ids
            existing_src = seen[sid].get("source_ids", {})
            new_src = s.get("source_ids", {})
            existing_src.update(new_src)
            seen[sid]["source_ids"] = existing_src
    summarise(list(seen.values()))


if __name__ == "__main__":
    main()

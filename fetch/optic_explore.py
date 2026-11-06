"""Ad-hoc OpticOdds exploration CLI — not used by the pipeline.

Split out of fetch/optic.py so the production fetcher stays within the
500-line file gate.  These modes predate --league and take raw Optic
ids, so they are also the way to look at a league before it is wired
(fetch.optic --league is choice-restricted to wired leagues).

    python -m fetch.optic_explore --get-sports
    python -m fetch.optic_explore --fixture <FIXTURE_ID>
    python -m fetch.optic_explore --explore <OPTIC_LEAGUE_ID>
"""

import argparse
import json
import os
from time import sleep

# _init_headers is private to the sibling module by convention, not
# because it is unsafe to reuse: these modes do not know the league
# upfront, so they cannot go through init_headers(league).
from fetch.optic import (
    BASE_URL,
    _init_headers,
    get_fixture_odds,
    get_fixtures,
    get_optic,
)


def get_sports(headers):
    return get_optic(BASE_URL + "sports/active", headers)


def explore_league(headers, league, max_fixtures):
    """Dump raw odds for a few of a league's fixtures under explore/."""
    out_dir = os.path.join(os.path.dirname(__file__), "explore", league)
    os.makedirs(out_dir, exist_ok=True)

    fixtures = get_fixtures(headers, league)
    print(f"{len(fixtures)} fixtures found, fetching {max_fixtures}")

    for fixture in fixtures[:max_fixtures]:
        fixture_id = fixture["id"]
        print(f"  {fixture_id}...")
        odds_data = get_fixture_odds(headers, fixture_id)
        with open(os.path.join(out_dir, f"{fixture_id}.json"), "w") as f:
            json.dump(odds_data, f, indent=2)
        sleep(0.2)

    print(f"Wrote to {out_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description="Explore OpticOdds sports, fixtures and raw odds.",
    )
    parser.add_argument("--get-sports", action="store_true",
                        help="List active sports and exit")
    parser.add_argument(
        "--fixture", metavar="FIXTURE_ID",
        help="Fetch odds for a single fixture and print JSON to stdout",
    )
    parser.add_argument(
        "--explore", metavar="LEAGUE",
        help="Fetch a few fixtures raw and dump to explore/",
    )
    parser.add_argument(
        "--max-fixtures", type=int, default=3,
        help="Max fixtures to fetch in --explore mode (default: 3)",
    )
    args = parser.parse_args()

    headers = _init_headers("opticodds_access_key")

    if args.get_sports:
        for sport in get_sports(headers):
            print(sport["id"])
    elif args.fixture:
        print(json.dumps(get_fixture_odds(headers, args.fixture)))
    elif args.explore:
        explore_league(headers, args.explore, args.max_fixtures)
    else:
        parser.error("pass --get-sports, --fixture or --explore")


if __name__ == "__main__":
    main()

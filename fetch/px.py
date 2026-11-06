"""Fetch ProphetX events and markets for basketball leagues.

Usage:
    python scripts/fetch_px.py --league nba ncaab --out-dir data/2026-03-06/12_00

Uses requests + Bearer token auth directly (no MMProphetx dependency).
Credentials from GCP Secret Manager via gcloud CLI.
"""

import argparse
import json
import os
import subprocess
import sys
from time import sleep

import requests

from fetch.gcloud_util import gcloud_cmd
from fetch.tip import px_tournament_ids

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://cash.api.prophetx.co"
GCP_PROJECT = os.environ["GCP_PROJECT"]
MAX_TRIES = 3


def load_credentials() -> tuple[str, str]:
    """Fetch PX access key and secret key from GCP Secret Manager."""
    access_key = subprocess.check_output(
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            "--secret=prophet_x_access_key_2", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()

    secret_key = subprocess.check_output(
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            "--secret=prophet_x_secret_key_2", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()

    return access_key, secret_key


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def login(access_key: str, secret_key: str) -> str:
    """Login to PX API and return the Bearer token."""
    resp = requests.post(
        BASE_URL + "/partner/auth/login",
        json={"access_key": access_key, "secret_key": secret_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


def px_get(path: str, params: dict | None, token: str) -> dict:
    """Authenticated GET against the PX API with retries.

    PX returns 404 with a JSON body when a resource has no data (e.g.
    tournament with no active events).  Match the MMProphetx dedicated
    client behaviour: treat 404 as a valid response and return the body.
    """
    url = BASE_URL + path
    headers = {"Authorization": f"Bearer {token}"}
    backoff = 1
    for attempt in range(1, MAX_TRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code != 404:
                resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"  px_get {path} attempt {attempt} failed: {e}, retrying in {backoff}s",
                  file=sys.stderr)
            sleep(backoff)
            backoff *= 2
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    if resp.status_code != 404:
        resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


# PX API has no status or date filters; returns all events for the tournament
def fetch_events(tournament_id: int, token: str) -> list[dict]:
    """Fetch sport events for a tournament."""
    result = px_get(
        "/partner/mm/get_sport_events",
        {"tournament_id": str(tournament_id)},
        token,
    )
    # PX returns 404 without a "data" wrapper when a tournament has no
    # active events.  Match MMProphetx client: treat as empty.
    data = result.get("data", result)
    if "error" in data or "sport_events" not in data:
        print(f"  WARN: get_sport_events: {data}", file=sys.stderr)
        return []
    return data["sport_events"]


# Volatile fields stripped from each selection — prices and timestamps
# that change constantly.  Matches Nick's original market_mapping_prophetx.py.
# Includes both legacy (odds/stake) and CFTC (price/quantity) names.
VOLATILE_SELECTION_FIELDS = (
    "display_odds", "odds", "stake",
    "display_price", "price", "quantity",
    "value", "updated_at",
)

# CFTC-native markets path (v4 always returns strike/price/quantity vocabulary).
GET_MARKETS_PATH = "/partner/v4/mm/get_markets"


def _market_strike_rows(market: dict) -> list:
    """Spread/total rows under CFTC or legacy key; else the market itself."""
    return market.get("market_strikes") or market.get("market_lines") or [market]


def strip_market(market: dict) -> dict:
    """Strip volatile price fields from selections, keeping structure intact.

    Selections live either directly on the market (moneyline) or nested
    inside market_strikes / market_lines (spread/total).  Each selection
    is a list of price levels — we keep only the first (top-of-book) and
    remove volatile fields from it.
    """
    for ml in _market_strike_rows(market):
        sides = [price_levels[0] for price_levels in ml["selections"]]
        for s in sides:
            for field in VOLATILE_SELECTION_FIELDS:
                s.pop(field, None)
        ml["selections"] = sides
    return market


def fetch_markets(event_id: int, token: str) -> list[dict]:
    """Fetch and strip markets for a single event."""
    result = px_get(
        GET_MARKETS_PATH,
        {"event_id": str(event_id)},
        token,
    )
    data = result.get("data", result)
    if "error" in data or "markets" not in data:
        print(f"  WARN: get_markets for event {event_id}: {data}", file=sys.stderr)
        return []
    markets = [strip_market(m) for m in data["markets"]]
    for m in markets:
        m["sport_event_id"] = event_id
    return markets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fetch ProphetX events for basketball leagues.",
    )
    parser.add_argument(
        "--league", nargs="+",
        help="Leagues to fetch (leagues without PX coverage are skipped)",
    )
    parser.add_argument(
        "--event", type=int, metavar="EVENT_ID",
        help="Fetch markets for a single event and print JSONL to stdout",
    )
    parser.add_argument(
        "--max-items", type=int,
        help="Max events to fetch markets for (for smoke testing)",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory (written by orchestrator)",
    )
    args = parser.parse_args()

    print("Loading credentials from GCP Secret Manager...", file=sys.stderr)
    access_key, secret_key = load_credentials()

    print("Logging in to PX API...", file=sys.stderr)
    token = login(access_key, secret_key)

    if args.event:
        # Raw output — skip strip_market so price fields are visible
        result = px_get(
            GET_MARKETS_PATH,
            {"event_id": str(args.event)},
            token,
        )
        for m in result.get("data", {}).get("markets", []):
            print(json.dumps(m))
        return

    if not args.league:
        parser.error("--league is required when not using --event")

    tournament_ids = px_tournament_ids()
    all_events: list[dict] = []
    for league in args.league:
        tid = tournament_ids.get(league)
        if tid is None:
            print(f"\n{league}: no PX coverage, skipping")
            continue
        print(f"\n{league}: fetching events for tournament_id={tid}")
        events = fetch_events(tid, token)
        print(f"  {len(events)} events")
        all_events.extend(events)

    print(f"\nTotal: {len(all_events)} events")

    if args.max_items:
        all_events = all_events[:args.max_items]

    all_markets: list[dict] = []
    for i, ev in enumerate(all_events, 1):
        eid = ev["event_id"]
        print(f"  [{i}/{len(all_events)}] event {eid}")
        markets = fetch_markets(eid, token)
        all_markets.extend(markets)

    print(f"\nTotal: {len(all_markets)} markets")

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        events_path = os.path.join(args.out_dir, "prophetx_events.jsonl")
        with open(events_path, "w") as f:
            for ev in all_events:
                print(json.dumps(ev), file=f)
        print(f"Wrote {events_path}")

        markets_path = os.path.join(args.out_dir, "prophetx_markets.jsonl")
        with open(markets_path, "w") as f:
            for m in all_markets:
                print(json.dumps(m), file=f)
        print(f"Wrote {markets_path}")


if __name__ == "__main__":
    main()

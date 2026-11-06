"""Fetch Novig (NBX) events and markets for the wired leagues.

Usage:
    python -m fetch.novig --league nba wnba --out-dir data/2026-08-14/12_00
    python -m fetch.novig --all-leagues --out-dir data_raw/...   # raw stash

Writes ``novig_events.jsonl`` and ``novig_markets.jsonl``.

Auth is OAuth2 client-credentials against ``/nbx/v1/auth/emm-token``;
credentials come from GCP Secret Manager via the gcloud CLI, same as
fetch/px.py.  Tokens last 30 minutes, comfortably longer than a fetch.

Two API caps worth knowing, both discovered by probing rather than from
the docs (which disagree with the live service):

* ``/emm/events`` rejects ``limit`` > 100, so events are paged.
* ``/emm/events/getMarketsByEvents`` advertises a 100-id validator cap but
  enforces 50 in business logic, and it additionally requires a
  ``currency`` field the docs omit.  Batching at 50 turns ~300 per-event
  round trips into ~6.

``--all-leagues`` skips the wired-league filter and takes Novig's entire
book (including leagues we do not map, e.g. PGA / NCAAF).  That is the
mode the raw BigQuery stash uses -- ``infra/run_novig_raw.sh`` -- so the
raw table keeps history for leagues before we wire them.
"""

import argparse
import json
import os
import subprocess  # nosec B404 — gcloud secret read, the repo-wide pattern (fetch/runshop.py)
import sys
from datetime import UTC, datetime, timedelta
from time import sleep

import requests

from fetch.gcloud_util import gcloud_cmd
from fetch.tip import novig_league_map
from mappers.exchanges.novig import novig_league_key
from mappers.shared import FIXTURE_HORIZON_HOURS

BASE_URL = "https://api.novig.us"
GCP_PROJECT = os.environ["GCP_PROJECT"]
MAX_TRIES = 3

# Novig's own pagination cap on /emm/events (limit > 100 -> HTTP 400).
EVENTS_PAGE_SIZE = 100
# getMarketsByEvents validates <= 100 but enforces "Maximum 50 event IDs
# allowed" in business logic. Use the enforced number.
MARKETS_BATCH_SIZE = 50
# Runaway guard: the events feed is a few thousand rows, so anything past
# this is a pagination bug, not real data.
MAX_EVENT_PAGES = 200

# Only these statuses can still be traded; FINAL / CANCELED are history.
LIVE_STATUSES = frozenset({"OPEN_PREGAME", "OPEN_INGAME"})

# Volatile fields stripped from each market before it is written: the live
# order book and traded volume change every tick and would make every
# snapshot differ for no mapping benefit. Structure is kept intact.
VOLATILE_MARKET_FIELDS = ("book", "volume")
VOLATILE_OUTCOME_FIELDS = ("last",)


def load_credentials() -> tuple[str, str]:
    """Fetch the Novig client id and secret from GCP Secret Manager."""
    client_id = subprocess.check_output(  # nosec B603 — fixed argv, no shell, code-derived args
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            "--secret=novig_client_id", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()

    client_secret = subprocess.check_output(  # nosec B603 — fixed argv, no shell, code-derived args
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            "--secret=novig_client_secret", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()

    return client_id, client_secret


def login(client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a 30-minute Bearer token."""
    resp = requests.post(
        BASE_URL + "/nbx/v1/auth/emm-token",
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _request(method: str, path: str, token: str, **kwargs) -> object:
    """Authenticated request against the Novig API with retries."""
    url = BASE_URL + path
    headers = {"Authorization": f"Bearer {token}"}
    backoff = 1
    for attempt in range(1, MAX_TRIES):
        try:
            resp = requests.request(
                method, url, headers=headers, timeout=60, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"  novig {method} {path} attempt {attempt} failed: {e}, "
                  f"retrying in {backoff}s", file=sys.stderr)
            sleep(backoff)
            backoff *= 2
    resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    resp.raise_for_status()
    return resp.json()


def fetch_events(token: str) -> list[dict]:
    """Page the whole events feed."""
    events: list[dict] = []
    for page in range(MAX_EVENT_PAGES):
        offset = page * EVENTS_PAGE_SIZE
        batch = _request(
            "GET", "/nbx/v2/emm/events", token,
            params={"limit": EVENTS_PAGE_SIZE, "offset": offset},
        )
        if not isinstance(batch, list) or not batch:
            break
        events.extend(batch)
        if len(batch) < EVENTS_PAGE_SIZE:
            break
    else:
        print(f"  WARN: events paging hit the {MAX_EVENT_PAGES}-page guard",
              file=sys.stderr)
    return events


def strip_market(market: dict) -> dict:
    """Drop the live book and other volatile fields, keeping structure."""
    for field in VOLATILE_MARKET_FIELDS:
        market.pop(field, None)
    for outcome in market.get("outcomes") or []:
        for field in VOLATILE_OUTCOME_FIELDS:
            outcome.pop(field, None)
    return market


def fetch_markets(event_ids: list[str], token: str) -> list[dict]:
    """Fetch and strip markets for many events, batched."""
    markets: list[dict] = []
    for i in range(0, len(event_ids), MARKETS_BATCH_SIZE):
        batch = event_ids[i:i + MARKETS_BATCH_SIZE]
        print(f"  markets batch {i // MARKETS_BATCH_SIZE + 1} "
              f"({len(batch)} events)")
        result = _request(
            "POST", "/nbx/v2/emm/events/getMarketsByEvents", token,
            # `currency` is required but undocumented; CASH is the
            # dollar-denominated book (COIN is the play-money one).
            json={"eventIds": batch, "currency": "CASH"},
        )
        if not isinstance(result, list):
            print(f"  WARN: unexpected markets payload: {str(result)[:200]}",
                  file=sys.stderr)
            continue
        markets.extend(strip_market(m) for m in result)
    return markets


def select_events(
    events: list[dict],
    leagues: set[str] | None,
    horizon_hours: float,
) -> list[dict]:
    """Keep tradeable events for the requested leagues within the horizon.

    ``leagues`` is a set of Novig league strings, or None for every league
    (the --all-leagues raw-stash mode).  Futures and tournament-level
    events carry no Optic fixture to map against, so they are kept only in
    the all-leagues mode where the point is raw history.
    """
    now = datetime.now(UTC)
    horizon = now + timedelta(hours=horizon_hours)
    wanted = None if leagues is None else {novig_league_key(x) for x in leagues}
    kept: list[dict] = []
    for ev in events:
        if ev.get("status") not in LIVE_STATUSES:
            continue
        if wanted is not None:
            if novig_league_key(str(ev.get("league") or "")) not in wanted:
                continue
            if ev.get("type") != "Game":
                continue
            if not ev.get("opticOddsId"):
                continue
            start = ev.get("scheduledStart")
            if not start:
                continue
            when = datetime.fromisoformat(start.replace("Z", "+00:00"))
            # Live games can have started already; keep a small look-back
            # so an in-play fixture is not dropped for being in the past.
            if when > horizon or when < now - timedelta(hours=12):
                continue
        kept.append(ev)
    return kept


def _parse_args() -> argparse.Namespace:
    """CLI surface. Split out of main() to stay inside the 50-line size guard."""
    parser = argparse.ArgumentParser(
        description="Fetch Novig events and markets.",
    )
    parser.add_argument(
        "--league", nargs="+",
        help="Leagues to fetch (leagues without Novig coverage are skipped)",
    )
    parser.add_argument(
        "--all-leagues", action="store_true",
        help="Take Novig's whole book, unfiltered (raw-stash mode)",
    )
    parser.add_argument(
        "--max-items", type=int,
        help="Max events to fetch markets for (for smoke testing)",
    )
    parser.add_argument(
        "--horizon-hours", type=float, default=FIXTURE_HORIZON_HOURS,
        help="Only fetch games starting within this many hours",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory (written by orchestrator)",
    )
    args = parser.parse_args()

    if not args.league and not args.all_leagues:
        parser.error("one of --league or --all-leagues is required")

    return args


def main():
    args = _parse_args()

    leagues: set[str] | None = None
    if not args.all_leagues:
        novig_leagues = novig_league_map()
        leagues = {
            novig_leagues[key] for key in args.league if key in novig_leagues
        }
        skipped = [key for key in args.league if key not in novig_leagues]
        if skipped:
            print(f"no Novig coverage, skipping: {', '.join(sorted(skipped))}")
        if not leagues:
            print("No requested league has Novig coverage; nothing to fetch.")
            _write(args.out_dir, [], [])
            return

    print("Loading credentials from GCP Secret Manager...", file=sys.stderr)
    client_id, client_secret = load_credentials()

    print("Logging in to Novig API...", file=sys.stderr)
    token = login(client_id, client_secret)

    print("Fetching events...")
    all_events = fetch_events(token)
    print(f"  {len(all_events)} events total")

    events = select_events(all_events, leagues, args.horizon_hours)
    print(f"  {len(events)} events selected")

    if args.max_items:
        events = events[:args.max_items]

    event_ids = [ev["id"] for ev in events]
    markets = fetch_markets(event_ids, token) if event_ids else []
    print(f"\nTotal: {len(events)} events, {len(markets)} markets")

    _write(args.out_dir, events, markets)


def _write(out_dir: str | None, events: list[dict], markets: list[dict]):
    """Write the two JSONL snapshots, when an out-dir was given."""
    if not out_dir:
        return
    os.makedirs(out_dir, exist_ok=True)

    events_path = os.path.join(out_dir, "novig_events.jsonl")
    with open(events_path, "w") as f:
        for ev in events:
            print(json.dumps(ev), file=f)
    print(f"Wrote {events_path}")

    markets_path = os.path.join(out_dir, "novig_markets.jsonl")
    with open(markets_path, "w") as f:
        for m in markets:
            print(json.dumps(m), file=f)
    print(f"Wrote {markets_path}")


if __name__ == "__main__":
    main()

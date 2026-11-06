"""Explore TheSportsDB API to discover leagues, events, and field shapes.

Interactive discovery tool for finding league IDs and understanding
what data the API returns for different sports.  Not production code —
use this to figure out configs for the upcoming-events pipeline.

Usage:
    python scripts/sportsdb_explore.py sports
    python scripts/sportsdb_explore.py find-league atp
    python scripts/sportsdb_explore.py search-league "english premier"
    python scripts/sportsdb_explore.py league 4328
    python scripts/sportsdb_explore.py next 4328
    python scripts/sportsdb_explore.py prev 4328
    python scripts/sportsdb_explore.py live tennis
    python scripts/sportsdb_explore.py live-league 4328
    python scripts/sportsdb_explore.py raw schedule/next/league/4328

Requires SPORTSDB_API_KEY environment variable (or .env file in repo root).

API notes (v2, as of 2026-03)
------------------------------

Response keys mirror the first URL path segment:
    all/* → {"all": [...]},  search/* → {"search": [...]},
    lookup/* → {"lookup": [...]},  list/* → {"list": [...]},
    schedule/* → {"schedule": [...]},  livescore/* → {"livescore": [...]}

Useful league IDs:
    4387  NBA          4607  NCAA (basketball)   5272  NIT
    4424  MLB          4380  NHL                 4391  NFL
    4464  ATP          4517  WTA                 4443  UFC

schedule/next/league/{id}    — next ~10-20 events (cap varies)
schedule/previous/league/{id} — previous ~20 events
schedule/league/{id}/{season} — full season (up to 3000), filter locally

Team sports (NBA, MLB, NHL, NFL):
    - strHomeTeam / strAwayTeam populated
    - intHomeScore / intAwayScore populated after completion
    - strTimestamp has actual match times
    - Full-season schedules available early (MLB 2026: 2552 games)
    - strStatus: "NS", "FT", or live period codes (Q1, Q2, HT, etc.)

Individual sports (Tennis — ATP/WTA):
    - strHomeTeam / strAwayTeam are NULL
    - Player names embedded in strEvent: "BNP Paribas Open Sinner vs Medvedev"
    - intHomeScore / intAwayScore NULL; set scores only in strResult
      on lookup/event/{id} (requires extra API call per match)
    - strTimestamp often T00:00:00 — no actual match times in schedule
    - Events added tournament-by-tournament, often late — Miami Open
      not present as of 2026-03-24 even though matches were being played.
      Useless for "next 48h" lookahead.
    - intRound is a tournament-level identifier, not a round-of-N

Spring training detection (MLB):
    - No explicit flag; detect by venue name (Surprise Stadium,
      Camelback Ranch, Salt River Fields, CoolToday Park, etc.)

Modular upcoming-events ideas
------------------------------
- Sport config as flat dicts: league IDs, live statuses, score formatter
- Use schedule/league/{id}/{season} + local time-window filter instead
  of schedule/next (avoids the 10-event cap)
- strEvent fallback when strHomeTeam is null (tennis, UFC)
- Tennis probably needs a different data source for reliable lookahead
- ST detection for MLB via venue name set
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

API_BASE = "https://www.thesportsdb.com/api/v2/json"


# ---------------------------------------------------------------------------
# API helpers (reused from sportsdb_upcoming.py)
# ---------------------------------------------------------------------------


def _api_key():
    key = os.environ.get("SPORTSDB_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("SPORTSDB_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    print("Error: set SPORTSDB_API_KEY or add it to .env", file=sys.stderr)
    sys.exit(1)


def _get(path, api_key):
    """GET an API path, return parsed JSON or None on error."""
    url = f"{API_BASE}/{path}"
    resp = requests.get(url, headers={"X-API-KEY": api_key}, timeout=15)
    if resp.status_code != 200:
        print(f"  error: {url} → {resp.status_code}", file=sys.stderr)
        return None
    try:
        return resp.json()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _dump(data, indent=2):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=indent, ensure_ascii=False, default=str))


def _table(rows, headers):
    """Print a simple aligned table."""
    if not rows:
        print("  (no results)")
        return
    # Compute column widths from headers and data.
    widths = [len(h) for h in headers]
    str_rows = []
    for row in rows:
        sr = [str(v) for v in row]
        str_rows.append(sr)
        for i, v in enumerate(sr):
            widths[i] = max(widths[i], len(v))

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(f"  {fmt.format(*headers)}")
    print(f"  {'─' * sum(widths + [2 * (len(widths) - 1)])}")
    for sr in str_rows:
        print(f"  {fmt.format(*sr)}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_sports(api_key):
    """List all supported sports."""
    data = _get("all/sports", api_key)
    if not data:
        return
    sports = data.get("all", [])
    rows = [
        (s.get("idSport", ""), s.get("strSport", ""), s.get("strFormat", ""))
        for s in sports
    ]
    rows.sort(key=lambda r: r[1])
    _table(rows, ["ID", "Sport", "Format"])
    print(f"\n  {len(rows)} sports")


def cmd_search_league(api_key, query):
    """Search for leagues by name via the search API."""
    # API expects underscores for spaces.
    q = query.strip().replace(" ", "_")
    data = _get(f"search/league/{q}", api_key)
    if not data:
        return
    leagues = data.get("search", [])
    if not leagues:
        print(f"  No leagues found for '{query}' (try 'find-league' for broader search)")
        return
    rows = [
        (
            lg.get("idLeague", ""),
            lg.get("strLeague", ""),
            lg.get("strSport", ""),
            lg.get("strCountry", ""),
            lg.get("strCurrentSeason", ""),
        )
        for lg in leagues
    ]
    _table(rows, ["ID", "League", "Sport", "Country", "Season"])


def cmd_find_league(api_key, query):
    """Search all leagues by substring match (more thorough than search API).

    The search/league endpoint doesn't find short names like 'atp' or 'wta'.
    This fetches the full league list and filters locally.
    """
    data = _get("all/leagues", api_key)
    if not data:
        return
    all_leagues = data.get("all", [])
    q = query.lower()
    matches = []
    for lg in all_leagues:
        name = lg.get("strLeague", "")
        alt = lg.get("strLeagueAlternate", "") or ""
        sport = lg.get("strSport", "")
        haystack = f"{name} {alt} {sport}".lower()
        if q in haystack:
            matches.append((
                lg.get("idLeague", ""),
                name,
                sport,
                alt,
            ))
    if not matches:
        print(f"  No leagues matching '{query}'")
        return
    matches.sort(key=lambda r: r[1])
    _table(matches, ["ID", "League", "Sport", "Alternate names"])


def cmd_league(api_key, league_id):
    """Show league details."""
    data = _get(f"lookup/league/{league_id}", api_key)
    if not data:
        return
    leagues = data.get("lookup", [])
    if not leagues:
        print(f"  League {league_id} not found")
        return
    lg = leagues[0]
    print(f"\n  {lg.get('strLeague', '?')} ({lg.get('strSport', '?')})")
    print(f"  Country: {lg.get('strCountry', '?')}")
    print(f"  Season:  {lg.get('strCurrentSeason', '?')}")
    print(f"  Gender:  {lg.get('strGender', '?')}")
    desc = lg.get("strDescriptionEN", "") or ""
    print(f"  Format:  {desc[:120]}")
    print()

    # Also show available seasons.
    seasons_data = _get(f"list/seasons/{league_id}", api_key)
    if seasons_data:
        seasons = seasons_data.get("list", [])
        if seasons:
            labels = [s.get("strSeason", "?") for s in seasons[-5:]]
            print(f"  Recent seasons: {', '.join(labels)}")
            print(f"  ({len(seasons)} total)")
    print()


def cmd_next(api_key, league_id):
    """Show next 10 scheduled events — raw fields for inspection."""
    data = _get(f"schedule/next/league/{league_id}", api_key)
    if not data:
        return
    events = data.get("schedule", [])
    if not events:
        print(f"  No upcoming events for league {league_id}")
        return

    print(f"\n  Next {len(events)} events for league {league_id}")
    print(f"  {'─' * 60}")

    # Show all fields from first event so we know the shape.
    print(f"\n  === Field names (first event) ===")
    for k, v in events[0].items():
        vstr = str(v)
        if len(vstr) > 80:
            vstr = vstr[:77] + "..."
        print(f"    {k:30s} = {vstr}")

    # Compact summary of all events.
    print(f"\n  === All events ===")
    for e in events:
        ts = e.get("strTimestamp") or e.get("dateEvent", "")
        home = e.get("strHomeTeam")
        away = e.get("strAwayTeam")
        # Tennis and individual sports have null home/away — use strEvent.
        if home and away:
            matchup = f"{home} vs {away}"
        else:
            matchup = e.get("strEvent", "?")
        status = e.get("strStatus", "")
        rnd = e.get("intRound", "")
        eid = e.get("idEvent", "")
        hscore = e.get("intHomeScore")
        ascore = e.get("intAwayScore")
        score = f"  ({hscore}-{ascore})" if hscore is not None else ""
        print(f"    {ts}  {status:>6}  R{rnd}  {matchup}{score}  [{eid}]")
    print()


def cmd_prev(api_key, league_id):
    """Show previous 10 events — useful for seeing completed score/status."""
    data = _get(f"schedule/previous/league/{league_id}", api_key)
    if not data:
        return
    events = data.get("results", data.get("schedule", []))
    if not events:
        print(f"  No previous events for league {league_id}")
        return

    print(f"\n  Previous {len(events)} events for league {league_id}")
    print(f"  {'─' * 60}")

    # Show all fields from first event.
    print(f"\n  === Field names (first event) ===")
    for k, v in events[0].items():
        vstr = str(v)
        if len(vstr) > 80:
            vstr = vstr[:77] + "..."
        print(f"    {k:30s} = {vstr}")

    # Compact summary.
    print(f"\n  === All events ===")
    for e in events:
        ts = e.get("strTimestamp") or e.get("dateEvent", "")
        home = e.get("strHomeTeam")
        away = e.get("strAwayTeam")
        if home and away:
            matchup = f"{home} vs {away}"
        else:
            matchup = e.get("strEvent", "?")
        status = e.get("strStatus", "")
        rnd = e.get("intRound", "")
        hscore = e.get("intHomeScore")
        ascore = e.get("intAwayScore")
        score = f"  ({hscore}-{ascore})" if hscore is not None else ""
        print(f"    {ts}  {status:>6}  R{rnd}  {matchup}{score}")
    print()


def cmd_live(api_key, sport):
    """Show current livescores for a sport."""
    data = _get(f"livescore/{sport}", api_key)
    if not data:
        return
    events = data.get("livescore", [])
    if not events:
        print(f"  No live events for sport '{sport}'")
        return

    print(f"\n  {len(events)} live events for '{sport}'")
    print(f"  {'─' * 60}")

    # Show fields from first event.
    print(f"\n  === Field names (first event) ===")
    for k, v in events[0].items():
        vstr = str(v)
        if len(vstr) > 80:
            vstr = vstr[:77] + "..."
        print(f"    {k:30s} = {vstr}")

    # Compact summary.
    print(f"\n  === All events ===")
    for e in events:
        home = e.get("strHomeTeam")
        away = e.get("strAwayTeam")
        if home and away:
            matchup = f"{home} vs {away}"
        else:
            matchup = e.get("strEvent", "?")
        status = e.get("strStatus", "")
        league = e.get("strLeague", "")
        hscore = e.get("intHomeScore")
        ascore = e.get("intAwayScore")
        etime = e.get("strEventTime", "")
        score = f"  ({hscore}-{ascore})" if hscore else ""
        print(f"    {etime:>5}  {status:>6}  {league:>20}  {matchup}{score}")
    print()


def cmd_live_league(api_key, league_id):
    """Show current livescores for a specific league."""
    data = _get(f"livescore/{league_id}", api_key)
    if not data:
        return
    events = data.get("livescore", [])
    if not events:
        print(f"  No live events for league {league_id}")
        return

    print(f"\n  {len(events)} live events for league {league_id}")
    print(f"  {'─' * 60}")

    # Show fields from first event.
    print(f"\n  === Field names (first event) ===")
    for k, v in events[0].items():
        vstr = str(v)
        if len(vstr) > 80:
            vstr = vstr[:77] + "..."
        print(f"    {k:30s} = {vstr}")

    # Compact summary.
    print(f"\n  === All events ===")
    for e in events:
        home = e.get("strHomeTeam")
        away = e.get("strAwayTeam")
        if home and away:
            matchup = f"{home} vs {away}"
        else:
            matchup = e.get("strEvent", "?")
        status = e.get("strStatus", "")
        hscore = e.get("intHomeScore")
        ascore = e.get("intAwayScore")
        etime = e.get("strEventTime", "")
        score = f"  ({hscore}-{ascore})" if hscore else ""
        print(f"    {etime:>5}  {status:>6}  {matchup}{score}")
    print()


def cmd_raw(api_key, path):
    """Dump raw JSON for any API path."""
    data = _get(path, api_key)
    if data is None:
        print("  (no data)")
        return
    _dump(data)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Explore TheSportsDB API — discover leagues, events, fields"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("sports", help="List all supported sports")

    p = sub.add_parser("search-league", help="Search leagues by name (API search)")
    p.add_argument("query", help="Search string (e.g. 'english premier')")

    p = sub.add_parser("find-league", help="Find leagues by substring (searches all)")
    p.add_argument("query", help="Substring to match (e.g. 'atp', 'wta', 'ufc')")

    p = sub.add_parser("league", help="Show league details")
    p.add_argument("league_id", type=int, help="League ID")

    p = sub.add_parser("next", help="Next 10 events in a league (raw fields)")
    p.add_argument("league_id", type=int, help="League ID")

    p = sub.add_parser("prev", help="Previous 10 events in a league")
    p.add_argument("league_id", type=int, help="League ID")

    p = sub.add_parser("live", help="Livescores for a sport")
    p.add_argument("sport", help="Sport name (e.g. tennis, soccer, basketball)")

    p = sub.add_parser("live-league", help="Livescores for a specific league")
    p.add_argument("league_id", type=int, help="League ID")

    p = sub.add_parser("raw", help="Dump raw JSON for any API path")
    p.add_argument("path", help="API path (e.g. schedule/next/league/4328)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    api_key = _api_key()

    if args.command == "sports":
        cmd_sports(api_key)
    elif args.command == "search-league":
        cmd_search_league(api_key, args.query)
    elif args.command == "find-league":
        cmd_find_league(api_key, args.query)
    elif args.command == "league":
        cmd_league(api_key, args.league_id)
    elif args.command == "next":
        cmd_next(api_key, args.league_id)
    elif args.command == "prev":
        cmd_prev(api_key, args.league_id)
    elif args.command == "live":
        cmd_live(api_key, args.sport)
    elif args.command == "live-league":
        cmd_live_league(api_key, args.league_id)
    elif args.command == "raw":
        cmd_raw(api_key, args.path)


if __name__ == "__main__":
    main()

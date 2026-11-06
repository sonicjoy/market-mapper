"""Fetch NBA reference data (teams, players, schedule) and write to JSON files.

Schedule and player sources: cdn.nba.com static JSON, not the
stats.nba.com API.

We originally planned to use nba_api's ScheduleLeagueV2 endpoint, which
hits stats.nba.com. That endpoint is behind Akamai CDN and silently drops
requests — TCP connects, TLS completes, HTTP request is sent, but no
response ever comes back. This happens even with the full browser header
set that nba_api sends (Chrome UA, Sec-Ch-Ua, Sec-Fetch-Dest, etc.) and
even from a real browser. Likely IP/ISP-level blocking.

cdn.nba.com serves the same data as static JSON files with no anti-bot
filtering. Same fields, same structure, works with a bare User-Agent
header.

Player data (roster assignments, jersey numbers) changes throughout the
season as players are traded, signed, or waived. We store snapshots under
reference/nba/players/{YYYY-MM-DD}.json so matching results are
reproducible against the roster state on a given date.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import requests
from nba_api.stats.static import teams

OUTPUT_DIR = Path("reference/nba")
CDN_HEADERS = {"User-Agent": "Mozilla/5.0"}
SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
PLAYER_INDEX_URL = "https://cdn.nba.com/static/json/staticData/playerIndex.json"


def fetch_teams():
    raw = teams.get_teams()
    return [
        {
            "id": t["id"],
            "full_name": t["full_name"],
            "abbreviation": t["abbreviation"],
            "nickname": t["nickname"],
            "city": t["city"],
        }
        for t in raw
    ]


def fetch_players():
    """Fetch active player roster from cdn.nba.com playerIndex endpoint.

    Returns jersey number, team, and position alongside name fields.
    The CDN reflects current roster state (trades, signings, waivers)
    so the output is a point-in-time snapshot.
    """
    resp = requests.get(PLAYER_INDEX_URL, headers=CDN_HEADERS, timeout=30)
    resp.raise_for_status()
    # The CDN sends valid UTF-8 but declares Content-Type: text/plain
    # with no charset.  requests defaults to ISO-8859-1 per the HTTP RFC,
    # which corrupts non-ASCII names (e.g. Jokić → JokiÄ‡).  Force UTF-8.
    resp.encoding = "utf-8"
    data = resp.json()

    headers = data["resultSets"][0]["headers"]
    rows = data["resultSets"][0]["rowSet"]
    col = {name: i for i, name in enumerate(headers)}

    return [
        {
            "id": row[col["PERSON_ID"]],
            "full_name": f"{row[col['PLAYER_FIRST_NAME']]} {row[col['PLAYER_LAST_NAME']]}",
            "first_name": row[col["PLAYER_FIRST_NAME"]],
            "last_name": row[col["PLAYER_LAST_NAME"]],
            "team": row[col["TEAM_ABBREVIATION"]],
            "jersey_number": row[col["JERSEY_NUMBER"]],
            "position": row[col["POSITION"]],
        }
        for row in rows
        if row[col["ROSTER_STATUS"]] == 1.0
    ]


def fetch_schedule():
    resp = requests.get(SCHEDULE_URL, headers=CDN_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    data = resp.json()

    league = data["leagueSchedule"]
    season = league["seasonYear"]

    games = []
    for game_date in league["gameDates"]:
        for g in game_date["games"]:
            games.append({
                "game_id": g["gameId"],
                "game_datetime_utc": g["gameDateTimeUTC"],
                "game_datetime_est": g["gameDateTimeEst"],
                "home_team_id": g["homeTeam"]["teamId"],
                "home_team_abbreviation": g["homeTeam"]["teamTricode"],
                "away_team_id": g["awayTeam"]["teamId"],
                "away_team_abbreviation": g["awayTeam"]["teamTricode"],
                "season": season,
            })

    return season, games


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def verify(teams_data, players_data, schedule_data):
    ok = True

    if len(teams_data) != 30:
        print(f"WARN: expected 30 teams, got {len(teams_data)}")
        ok = False

    if not (400 <= len(players_data) <= 800):
        print(f"WARN: expected 400-800 players, got {len(players_data)}")
        ok = False

    if len(schedule_data) < 1230:
        print(f"WARN: expected 1230+ games, got {len(schedule_data)}")
        ok = False

    game_ids = [g["game_id"] for g in schedule_data]
    dupes = len(game_ids) - len(set(game_ids))
    if dupes:
        print(f"WARN: {dupes} duplicate game IDs")
        ok = False

    return ok


def main():
    parser = argparse.ArgumentParser(description="Fetch NBA reference data")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Snapshot date for player data (YYYY-MM-DD, default: today)",
    )
    args = parser.parse_args()

    print("Fetching teams...")
    teams_data = fetch_teams()
    write_json(OUTPUT_DIR / "teams.json", teams_data)
    print(f"  {len(teams_data)} teams → {OUTPUT_DIR}/teams.json")

    print("Fetching players...")
    players_data = fetch_players()
    players_path = OUTPUT_DIR / "players" / f"{args.date}.json"
    write_json(players_path, players_data)
    print(f"  {len(players_data)} active players → {players_path}")

    print("Fetching schedule...")
    try:
        season, schedule_data = fetch_schedule()
    except Exception as e:
        print(f"ERROR: schedule fetch failed: {e}", file=sys.stderr)
        sys.exit(1)
    schedule_path = OUTPUT_DIR / season / "schedule.json"
    write_json(schedule_path, schedule_data)
    print(f"  {len(schedule_data)} games → {schedule_path}")

    if not verify(teams_data, players_data, schedule_data):
        print("\nVerification warnings above — check output files.")
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()

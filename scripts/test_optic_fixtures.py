"""Fetch Optic active fixtures for NCAAB, 1 hour horizon, and print summary."""

from datetime import UTC, datetime, timedelta

from fetch.optic import BASE_URL, get_optic, init_headers

headers = init_headers("ncaab")
cutoff = datetime.now(UTC) + timedelta(hours=1)
start_date_before = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

print(f"Now:    {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
print(f"Cutoff: {start_date_before}")
print()

fixtures = get_optic(
    BASE_URL + "fixtures/active", headers,
    {"league": "ncaab", "start_date_before": start_date_before},
)

print(f"{len(fixtures)} fixtures")
for f in sorted(fixtures, key=lambda x: x["start_date"]):
    away = f.get("away_team_display", "?")
    home = f.get("home_team_display", "?")
    print(f"  {f['start_date']}  {away} at {home}")

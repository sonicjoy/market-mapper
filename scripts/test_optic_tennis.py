"""Fetch active tennis fixtures from OpticOdds and print summary.

Uses the separate tennis subscription key (opticodds_parlay_tennis_access_key).

Usage:
    python -m scripts.test_optic_tennis             # /fixtures/active (has_more pagination)
    python -m scripts.test_optic_tennis --cron-mode  # /fixtures + start_date_after (has_more)
    python -m scripts.test_optic_tennis --test-fix   # same as cron-mode but using the
                                                     # MMOpticOdds decorator from f7f1dad
    python -m scripts.test_optic_tennis --atp-only   # filter output to ATP league
"""

import argparse
import os
import subprocess
from copy import deepcopy
from datetime import datetime
from functools import wraps
from time import sleep

import requests

BASE_URL = "https://api.opticodds.com/api/v3/"
GCP_PROJECT = os.environ["GCP_PROJECT"]


# -- Our pagination (has_more) ------------------------------------------------

def get_optic(url, headers, params=None):
    params = deepcopy(params) if params else {}
    datas = []
    page = 1
    while True:
        params["page"] = str(page)
        response = requests.get(url, params, headers=headers)
        if response.status_code == 429:
            print("  Rate limited, retrying in 5s...")
            sleep(5)
            continue
        response.raise_for_status()
        data = response.json()
        datas += data["data"]
        if "has_more" in data:
            if not data["has_more"]:
                break
        elif data.get("total_pages", 1) <= page:
            break
        page += 1
    return datas


# -- MMOpticOdds decorator (exact copy from local f7f1dad) --------------------

def cron_pagination_decorator(func):
    """Exact copy of opticodds_pagination_get_decorator from the local
    MMOpticOdds repo (commit f7f1dad), with logger calls replaced by print."""
    @wraps(func)
    def wrapper(*args, from_page=1, to_page=None, **kwargs):
        response = func(*args, page=from_page, **kwargs)
        response_json = response.json()
        aggregated_data = response_json.get("data", [])

        page = response_json.get("page", from_page)
        first_page = page
        total_pages = response_json.get("total_pages", 0)

        print(f"  [decorator] total_pages={total_pages}, first page data_count={len(aggregated_data)}")

        if to_page is not None:
            to_pages = min(to_page, total_pages) if total_pages > 0 else to_page
        else:
            to_pages = total_pages

        if total_pages > 0:
            while page < to_pages:
                print(f"  [decorator] fetching page {page + 1} of {to_pages} (total_pages path)")
                response = func(*args, page=page + 1, **kwargs)
                response_json = response.json()
                page_data = response_json.get("data", [])
                aggregated_data.extend(page_data)
                page = response_json.get("page", page + 1)
                total_pages = response_json.get("total_pages", 0)
        else:
            # Fallback: paginate until empty page when API doesn't report total_pages
            while len(response_json.get("data", [])) > 0:
                print(f"  [decorator] fetching page {page + 1} (fallback path)")
                response = func(*args, page=page + 1, **kwargs)
                response_json = response.json()
                page_data = response_json.get("data", [])
                if not page_data:
                    break
                aggregated_data.extend(page_data)
                page = response_json.get("page", page + 1)

        print(f"  [decorator] done: {len(aggregated_data)} total items across {page - first_page + 1} pages")
        return aggregated_data

    return wrapper


@cron_pagination_decorator
def cron_get_request(url, headers, params, page=1):
    params = deepcopy(params)
    params["page"] = page
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response


# -- Main ---------------------------------------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--cron-mode", action="store_true",
                    help="Use /fixtures + start_date_after (has_more pagination)")
parser.add_argument("--test-fix", action="store_true",
                    help="Use /fixtures + start_date_after with the MMOpticOdds "
                         "decorator from local commit f7f1dad")
parser.add_argument("--atp-only", action="store_true",
                    help="Filter output to ATP league only")
args = parser.parse_args()

api_key = subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest",
     "--secret=opticodds_parlay_tennis_access_key",
     f"--project={GCP_PROJECT}"],
    text=True,
).strip()
headers = {"accept": "application/json", "X-Api-Key": api_key}

from_date = datetime.now().strftime("%Y-%m-%dT00:00:00Z")

if args.test_fix:
    print(f"Test-fix mode: MMOpticOdds decorator (f7f1dad)")
    print(f"  GET /fixtures  start_date_after={from_date}")
    params = {"sport": "tennis", "start_date_after": from_date}
    fixtures = cron_get_request(
        BASE_URL + "fixtures", headers=headers, params=params,
    )
elif args.cron_mode:
    print(f"Cron mode: GET /fixtures  start_date_after={from_date}")
    fixtures = get_optic(BASE_URL + "fixtures", headers,
                         {"sport": "tennis", "start_date_after": from_date})
else:
    print(f"Active mode: GET /fixtures/active")
    fixtures = get_optic(BASE_URL + "fixtures/active", headers, {"sport": "tennis"})

if args.atp_only:
    fixtures = [f for f in fixtures if f.get("league", {}).get("name") == "ATP"]

print(f"\n{len(fixtures)} fixtures\n")
for f in sorted(fixtures, key=lambda x: x["start_date"]):
    away = f.get("away_team_display", "?")
    home = f.get("home_team_display", "?")
    league = f.get("league", {}).get("name", "?")
    print(f"  {f['start_date']}  {league:30s}  {away} vs {home}")

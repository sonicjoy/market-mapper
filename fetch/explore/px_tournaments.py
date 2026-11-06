"""List PX tournaments with active events.

Usage:
    python -m fetch.explore.px_tournaments
"""

import json

import requests

from fetch.px import load_credentials, login

BASE_URL = "https://cash.api.prophetx.co"


def main():
    access_key, secret_key = load_credentials()
    token = login(access_key, secret_key)

    resp = requests.get(
        BASE_URL + "/partner/mm/get_tournaments",
        params={"has_active_events": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    for t in result.get("data", {}).get("tournaments", []):
        print(json.dumps(t))


if __name__ == "__main__":
    main()

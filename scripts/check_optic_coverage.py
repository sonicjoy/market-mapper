"""Check whether Optic returns Kalshi prices for a specific market.

Fetches the same market from both Kalshi and Optic and compares.
Kalshi: does the market have a bid/ask?
Optic:  does it return odds with Kalshi source_ids for that market?

Usage:
    python -m scripts.check_optic_coverage \
        --fixture-id 20260312D8DB0602 \
        --market point_spread \
        --kalshi-ticker KXNCAAMBSPREAD-26MAR12SCSTNORF-NORF7
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

GCP_PROJECT = os.environ["GCP_PROJECT"]

# ---- Kalshi -----------------------------------------------------------

KALSHI_BASE = "https://api.elections.kalshi.com"


def kalshi_credentials():
    key_id = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=wsd_1_kalshi_api_key", f"--project={GCP_PROJECT}"],
        text=True,
    ).strip()
    key_pem = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=wsd_1_kalshi_private_key", f"--project={GCP_PROJECT}"],
        text=True,
    ).strip()
    private_key = serialization.load_pem_private_key(
        key_pem.encode("utf-8"), password=None,
    )
    return key_id, private_key


def kalshi_auth_headers(method, path, key_id, private_key):
    ts = str(int(time.time() * 1000))
    msg = (ts + method.upper() + path.split("?")[0]).encode("utf-8")
    sig = private_key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }


def kalshi_get_market(ticker, key_id, private_key):
    path = f"/trade-api/v2/markets/{ticker}"
    url = KALSHI_BASE + path
    headers = kalshi_auth_headers("GET", path, key_id, private_key)
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["market"]


# ---- Optic ------------------------------------------------------------

OPTIC_BASE = "https://api.opticodds.com/api/v3/"


def optic_headers():
    api_key = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=opticodds_access_key", f"--project={GCP_PROJECT}"],
        text=True,
    ).strip()
    return {
        "accept": "application/json",
        "X-Api-Key": api_key,
    }


def optic_get_odds(fixture_id, market, headers):
    resp = requests.get(
        OPTIC_BASE + "fixtures/odds",
        params={
            "fixture_id": fixture_id,
            "sportsbook": "kalshi",
            "market": market,
        },
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---- Main -------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check Optic coverage for a Kalshi market.",
    )
    parser.add_argument("--fixture-id", required=True,
                        help="Optic fixture ID")
    parser.add_argument("--market", required=True,
                        help="Optic market_id (e.g. point_spread)")
    parser.add_argument("--kalshi-ticker", required=True,
                        help="Kalshi market ticker")
    args = parser.parse_args()

    print("Loading credentials...", file=sys.stderr)
    kalshi_key_id, kalshi_pk = kalshi_credentials()
    optic_hdrs = optic_headers()

    # Kalshi
    print(f"\n--- Kalshi: {args.kalshi_ticker} ---")
    km = kalshi_get_market(args.kalshi_ticker, kalshi_key_id, kalshi_pk)
    print(f"  status:    {km['status']}")
    print(f"  title:     {km['title']}")
    print(f"  yes_bid:   {km['yes_bid_dollars']}  ({km.get('yes_bid_size_fp', '?')} contracts)")
    print(f"  yes_ask:   {km['yes_ask_dollars']}  ({km.get('yes_ask_size_fp', '?')} contracts)")
    print(f"  no_bid:    {km['no_bid_dollars']}")
    print(f"  no_ask:    {km['no_ask_dollars']}")
    print(f"  volume:    {km['volume_fp']}")
    has_prices = float(km["yes_bid_dollars"]) > 0 or float(km["yes_ask_dollars"]) > 0
    print(f"  → Kalshi has prices: {has_prices}")

    # Optic
    print(f"\n--- Optic: fixture={args.fixture_id} market={args.market} sportsbook=kalshi ---")
    optic = optic_get_odds(args.fixture_id, args.market, optic_hdrs)
    data = optic.get("data", [])
    if not data:
        print("  → No fixture data returned")
    else:
        odds = data[0].get("odds", [])
        kalshi_odds = [o for o in odds if o.get("sportsbook") == "Kalshi"]
        print(f"  total odds entries: {len(odds)}")
        print(f"  kalshi odds entries: {len(kalshi_odds)}")
        for o in kalshi_odds:
            print(f"    {o['name']}  price={o['price']}  source_ids={o.get('source_ids')}")
        if not kalshi_odds:
            print("  → Optic returned NO Kalshi odds for this market")

    # Verdict
    print("\n--- Verdict ---")
    if has_prices and not (data and any(
        o.get("sportsbook") == "Kalshi"
        for d in data for o in d.get("odds", [])
    )):
        print("  MISMATCH: Kalshi has prices but Optic does not return them")
    else:
        print("  OK: consistent")


if __name__ == "__main__":
    main()

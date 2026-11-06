"""Fetch the Polymarket position↔token bridge → polymarket_markets.jsonl.

The bridge (raw_ingestion_us.polymarket_position_token_bridge) already carries,
per clob_token_id, the single market's slug/question + outcome_label. This
fetcher reads the bridge rows for fixtures still in the mapping window and
groups them by condition_id into one market-per-line for the mapper's
Polymarket matcher — mirroring fetch/crypto_com.py's flat-JSONL contract. No
live API calls (the bridge loader already did the combos-rfq/Gamma fetch).

The window is keyed on the SLUG's fixture date, NOT on last_updated. That
distinction caused a silent, months-long coverage outage, so it is load-bearing:

  * `load_polymarket_position_bridge._exclude_bridged()` deliberately SKIPS
    condition_ids that are already bridged, to spend its Gamma calls on legs
    that are still genuinely unmapped. A row's `last_updated` is therefore
    "when we FIRST discovered this token", not "when we last confirmed it".
  * This fetcher used to filter `last_updated >= now - 2 days`. Combined with
    the above, every market became invisible to the mapper 48h after it was
    first seen — even with its fixture still days away and its bridge row
    perfectly valid.
  * Nothing alerted, because leagues with fresh condition_ids every day (MLB)
    stayed healthy and masked it. Measured on 2026-08-06: Leagues Cup last
    refreshed 07-29, Conference League 08-01, MLS 08-04 — all three fetched
    ZERO markets, while the RFQ feed was failing ~346k Polymarket legs a day
    across them.

A bridge row is an immutable fact (position_id ↔ clob_token_id ↔ condition_id ↔
outcome; on-chain ids that are never reassigned), so row freshness is simply the
wrong question. What matters is whether the market's FIXTURE is still one we
map — which is exactly what the mapper itself keys on (it matches a poly slug
date to an Optic fixture date, ±1 day). Filtering on the same thing the matcher
uses makes this stage immune to the loader's refresh policy.
"""

import argparse
import json
import os
import sys

from BigQuery.polymarket_bq_util import bq_client, qualify

BRIDGE_TABLE = "raw_ingestion_us.polymarket_position_token_bridge"

# Only a lower bound is ever needed: there is no upper bound because the mapper can
# only match a poly market to an Optic fixture that exists, and league Optic horizons
# vary (optic_from_bq pulls +7d, API leagues up to horizon_hours=60d), so a far-future
# market is harmless — it simply finds no fixture.
#
# How long after its own kickoff a market stays fetchable. Matches
# load_mappings._clean_stale_started's 24h cutoff, so this never drops a market whose
# mapping row the loader would still keep — while a market from a PREVIOUS day stops
# reaching the matcher entirely.
STALE_AFTER_KICKOFF_HOURS = 24


def bridge_window_sql() -> str:
    """The WHERE predicate selecting bridge rows still worth mapping.

    Two gates, in order of authority:

    1. ``game_start_time`` (Gamma's own kickoff instant) when present: keep the row
       while the game could still be running, drop it once it is over. This is the
       real staleness test — an exact instant on both sides, no date arithmetic.
       There is no upper bound (a far-future market simply finds no fixture).
    2. Slug date, for legacy rows written before the column existed: keep only what
       cannot already have been played. A NULL instant on a PAST-dated slug is a
       settled market Gamma declines to re-enrich, which is exactly the row that
       mis-mapped, so it is dropped rather than fed to the date matcher.

    Rows with neither a parseable slug date nor an instant are KEPT (fail open):
    dropping what we cannot classify is the silent coverage loss the slug-date window
    was introduced to fix, and it matches load_polymarket_position_bridge's
    ``_is_upcoming_slug`` convention.
    """
    # legacy: ticker parse — replace with the typed venue field, do not extend
    slug_date = r"SAFE.PARSE_DATE('%Y-%m-%d', REGEXP_EXTRACT(slug, r'(\d{4}-\d{2}-\d{2})'))"
    kickoff_floor = f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(STALE_AFTER_KICKOFF_HOURS)} HOUR)"
    return (
        "CASE\n"
        "  WHEN game_start_time IS NOT NULL\n"
        f"    THEN game_start_time >= {kickoff_floor}\n"
        f"  WHEN {slug_date} IS NOT NULL\n"
        f"    THEN {slug_date} >= CURRENT_DATE()\n"
        "  ELSE TRUE\n"
        "END"
    )


def build_market_lines(rows) -> list[dict]:
    """Group bridge rows by condition_id into one market dict each.

    Outcomes are sorted by outcome_index so index-aligned consumers stay stable.
    """
    by_cid: dict[str, dict] = {}
    for r in rows:
        # Skip rows with no condition_id: str(None) -> "None" would group
        # unrelated rows into a single bogus market.
        if r.condition_id is None:
            continue
        cid = str(r.condition_id)
        m = by_cid.get(cid)
        if m is None:
            gst = getattr(r, "game_start_time", None)
            # BQ hands back a datetime; a local/offline dump may hand back a string.
            gst_iso = None if gst is None else (gst or None) if isinstance(gst, str) else gst.isoformat()
            m = {
                "condition_id": cid,
                "slug": r.slug or "",
                "question": r.question or "",
                # Polymarket's own kickoff instant; the matcher resolves the fixture
                # from it instead of the slug's venue-local date. Normalised to an ISO
                # string here because downstream consumers (PolyMarket, the pipeline's
                # _parse_instant) work on strings, and BQ hands back a datetime.
                "game_start_time": gst_iso,
                "outcomes": [],
            }
            by_cid[cid] = m
        m["outcomes"].append(
            {
                "clob_token_id": str(r.clob_token_id),
                "position_id": str(r.position_id),
                "outcome_label": r.outcome_label or "",
                "outcome_index": int(r.outcome_index) if r.outcome_index is not None else 0,
            }
        )
    for m in by_cid.values():
        m["outcomes"].sort(key=lambda o: o["outcome_index"])
    return list(by_cid.values())


def bridge_query(table: str) -> str:
    """The bridge SELECT. Split out from _fetch_rows so it is testable.

    `last_updated` still appears — but only in the QUALIFY, to pick the LATEST
    row per token when a market's text was revised. It must never come back as
    a row-recency FILTER (see the module docstring).
    """
    return f"""
      SELECT condition_id, slug, question, clob_token_id, position_id,
             outcome_label, outcome_index, game_start_time
      FROM `{table}`
      WHERE {bridge_window_sql()}
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY clob_token_id ORDER BY last_updated DESC) = 1
    """  # nosec B608 — {table} is qualify() of a module constant, no user input


def _fetch_rows(client):
    return list(client.query(bridge_query(qualify(client, BRIDGE_TABLE))).result())


def main():
    p = argparse.ArgumentParser(description="Fetch Polymarket bridge -> jsonl.")
    p.add_argument("--out-dir", help="Directory to write polymarket_markets.jsonl into.")
    p.add_argument("--out", help="Explicit output path (ad-hoc).")
    p.add_argument("--league", nargs="*", default=[], help="Ignored; bridge is league-agnostic.")
    p.add_argument("--max-items", type=int, default=None, help="Cap markets (smoke test).")
    args = p.parse_args()

    client = bq_client()
    markets = build_market_lines(_fetch_rows(client))
    if args.max_items:
        markets = markets[: args.max_items]

    out_path = None
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        out_path = os.path.join(args.out_dir, "polymarket_markets.jsonl")
    elif args.out:
        out_path = args.out

    if out_path:
        with open(out_path, "w") as f:
            for m in markets:
                print(json.dumps(m), file=f)
        print(f"Wrote {out_path} ({len(markets)} markets)", file=sys.stderr)
    else:
        for m in markets:
            print(json.dumps(m))


if __name__ == "__main__":
    main()

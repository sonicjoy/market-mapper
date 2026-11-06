"""Scan and profile a crypto.com FIX catalogue dump.

crypto.com publishes its prediction-market catalogue over FIX. Each
record describes ONE binary-option contract (a single selection) and
carries the real-world market context in a block of `eventMeta*`
fields. We dumped a stream of these to JSONL (one flat contract per
line) to work out which columns we can use for the usual market-mapping
concepts: fixture, market type, market, selection.

This is a read-only profiler. It does not touch mappers/ or any alias
files — it just streams the dump and reports structure so we can design
a crypto.com mapper.

Record shapes in the dump:
  * fix_type == "SecurityList" — a contract from a batched catalogue
                                 snapshot (the original feed)
  * fix_type == "SecurityDef"  — a contract from a per-contract
                                 definition message (all the feed has
                                 sent since 2026-06-04; field superset
                                 of the SecurityList record — see
                                 docs/adding-crypto.md "Feed change")
  * fix_type missing           — thin "combo" stubs (eventCode + symbol
                                 only); ignored here.

The same contract appears many times (repeated catalogue snapshots at
different publish_time), so we dedup by SecurityID before profiling.

Mapping cheat-sheet (see scan output for the live breakdown):
  fixture       <- eventMetaEXTERNAL_GAME_ID  (+ NAME / HOME / AWAY / EVENT_DATE)
  market type   <- eventMetaPREDICT_CONTRACT_TYPE  ("Moneyline", "Spread",
                   "Total Points", "Moneyline (3-Way)", ...)
  market group  <- eventMetaPREDICT_MARKET_TYPE    ("Game Line",
                   "Team Future", "Player Future", "")
  selection     <- eventMetaPREDICT_OUTCOME_TYPE (Home/Away/Draw/Over/Under)
                   + eventMetaPREDICT_VALUE (line/handicap) ; human label in
                   eventName / eventMetaALPHA_STRIKE
  sport/league  <- eventMetaSPORTS_GROUPING / eventMetaLEAGUE

Usage:
    python scripts/scan_crypto_com.py scratch/crypto_com_markets.jsonl
    python scripts/scan_crypto_com.py scratch/crypto_com_markets.jsonl --market-type "Spread"
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

# The catalogue record types (both flatten to the same full record).
CATALOGUE_TYPES = {"SecurityList", "SecurityDef"}

# eventMeta fields that matter for market mapping, in display order.
MAPPING_FIELDS = [
    "eventMetaSPORTS_GROUPING",
    "eventMetaLEAGUE",
    "eventMetaPREDICT_CATEGORY",
    "eventMetaPREDICT_MARKET_TYPE",
    "eventMetaPREDICT_CONTRACT_TYPE",
    "eventMetaPREDICT_EVENT_TYPE",
    "eventMetaPREDICT_PERIOD_TYPE",
    "eventMetaPREDICT_OUTCOME_TYPE",
    "eventMetaPREDICT_VALUE",
    "eventMetaEXTERNAL_GAME_ID",
    "eventMetaHOME_PARTICIPANT",
    "eventMetaAWAY_PARTICIPANT",
    "eventMetaEVENT_DATE",
]


def load_unique(path: Path):
    """Stream the dump, keep one record per SecurityID (first seen)."""
    by_id = {}
    skipped = 0
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("fix_type") not in CATALOGUE_TYPES:
                skipped += 1
                continue
            sid = rec.get("SecurityID")
            if sid and sid not in by_id:
                by_id[sid] = rec
    return list(by_id.values()), skipped


def short(v, n=40):
    s = "" if v is None else str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def print_full(recs):
    """Print every field of each record as an aligned key = value block.

    For browsing the raw catalogue — the "see all the data" view, vs the
    summary histograms above.  Keys are sorted; the provenance stamps
    (fix_type/publish_time) and null fields are omitted as noise.  The
    full on-disk record (`fetch/crypto_com.py`) carries the scalar fields
    and `attrVal*` attributes too, so they show up here automatically.
    """
    skip = {"fix_type", "publish_time"}
    for i, r in enumerate(recs, 1):
        ct = r.get("eventMetaPREDICT_CONTRACT_TYPE") or "?"
        ot = r.get("eventMetaPREDICT_OUTCOME_TYPE") or "?"
        print(f"\n  --- {i}: {ct} / {ot} ---")
        keys = sorted(k for k in r if k not in skip and r[k] is not None)
        w = max((len(k) for k in keys), default=0)
        for k in keys:
            print(f"        {k:<{w}} = {r[k]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path, help="path to crypto-com JSONL dump")
    ap.add_argument(
        "--market-type",
        help="filter to one PREDICT_CONTRACT_TYPE (e.g. 'First Field Goal Scorer')",
    )
    ap.add_argument(
        "--market-group",
        help="filter to one PREDICT_MARKET_TYPE (e.g. 'Player Prop', 'Game Line')",
    )
    ap.add_argument(
        "--full", action="store_true",
        help="print every field of each contract, not the summary",
    )
    args = ap.parse_args()

    recs, combo_stubs = load_unique(args.dump)
    print(f"Unique catalogue contracts : {len(recs)}")
    print(f"Non-catalogue lines skipped : {combo_stubs}")

    # Filters and view are orthogonal: --market-group / --market-type pick
    # WHICH contracts (they compose), --full alone picks summary vs detail.
    sel = recs
    if args.market_group:
        sel = [r for r in sel
               if r.get("eventMetaPREDICT_MARKET_TYPE") == args.market_group]
    if args.market_type:
        sel = [r for r in sel
               if r.get("eventMetaPREDICT_CONTRACT_TYPE") == args.market_type]
    if args.market_group or args.market_type:
        which = " / ".join(
            x for x in (args.market_group, args.market_type) if x)
        print(f"Filtered to [{which}]          : {len(sel)} contracts")

    # --- detail view: every field of each selected contract ----------------
    if args.full:
        print(f"\n=== {len(sel)} contracts ===")
        print_full(sel)
        return

    # --- field fill rates --------------------------------------------------
    print("\n=== mapping-field fill rate (of selected contracts) ===")
    for f in MAPPING_FIELDS:
        n = sum(1 for r in sel if r.get(f) not in (None, ""))
        print(f"  {n:4d}/{len(sel)}  {f}")

    # --- market type x market group ---------------------------------------
    print("\n=== market group (PREDICT_MARKET_TYPE) x type (CONTRACT_TYPE) ===")
    grp = defaultdict(Counter)
    for r in sel:
        g = r.get("eventMetaPREDICT_MARKET_TYPE") or "(blank)"
        grp[g][r.get("eventMetaPREDICT_CONTRACT_TYPE") or "(blank)"] += 1
    for g in sorted(grp, key=lambda k: -sum(grp[k].values())):
        print(f"\n  [{g}]  ({sum(grp[g].values())} contracts)")
        for ct, n in grp[g].most_common():
            print(f"      {n:4d}  {ct}")

    # --- selection anatomy per game-line market type ----------------------
    print("\n=== Game-Line selection anatomy (OUTCOME_TYPE x VALUE present) ===")
    gl = [r for r in sel if r.get("eventMetaPREDICT_MARKET_TYPE") == "Game Line"]
    anat = defaultdict(Counter)
    for r in gl:
        ct = r.get("eventMetaPREDICT_CONTRACT_TYPE")
        ot = r.get("eventMetaPREDICT_OUTCOME_TYPE") or "?"
        has_line = "with line" if r.get("eventMetaPREDICT_VALUE") else "no line"
        anat[ct][f"{ot} / {has_line}"] += 1
    for ct in sorted(anat):
        combos = ", ".join(f"{k}={v}" for k, v in sorted(anat[ct].items()))
        print(f"  {ct}: {combos}")

    # --- optional drill-down (sel is already filtered to this type) --------
    if args.market_type:
        print(f"\n=== selections for CONTRACT_TYPE = {args.market_type!r} "
              f"({len(sel)} contracts) ===")
        print(f"  {'OUTCOME':6} {'VALUE':>7}  {'eventName':40} {'Symbol'}")
        for r in sorted(
            sel,
            key=lambda r: (
                r.get("eventMetaEXTERNAL_GAME_ID") or "",
                r.get("eventMetaPREDICT_OUTCOME_TYPE") or "",
                float(r.get("eventMetaPREDICT_VALUE") or 0),
            ),
        ):
            print(
                f"  {short(r.get('eventMetaPREDICT_OUTCOME_TYPE'),6):6} "
                f"{short(r.get('eventMetaPREDICT_VALUE'),7):>7}  "
                f"{short(r.get('eventName'),40):40} "
                f"{r.get('Symbol')}"
            )


if __name__ == "__main__":
    main()

"""Fetch the crypto.com prediction-market catalogue from BigQuery.

The catalogue is read from processed upstream tables — no raw FIX parsing:

  Primary:       ``processed_upstream_us.crypto_underlying_securities``
  Complementary: ``processed_upstream_us.crypto_security_def``

Both are synthesized into the same flat on-disk JSONL format the mapper
already consumes (see ``fetch/crypto_com_underlying.py`` and
``fetch/crypto_com_security_def.py``).  Interpretation (game-line filter,
vocabulary translation, team resolution) happens at mapper *read* time
(``mappers/exchanges/crypto_com.py`` ``parse_selection``).

One CLI serves both cron and ad-hoc browse; they differ only in window
and destination:

  cron:         --out-dir <dir>   fixed filename; empty window → empty file, exit 0
  ad-hoc browse: --hours N --out <path>   empty window → nothing written

Usage:
    python -m fetch.crypto_com --out-dir data/2026-06-04/12_00
    python -m fetch.crypto_com --hours 48 --out scratch/crypto_com_markets.jsonl
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

from BigQuery.client import ro_client
from fetch.crypto_com_identity import build_identity_index
from fetch.crypto_com_security_def import (
    fetch_security_def_contracts,
    merge_security_def_contracts,
)
from fetch.crypto_com_underlying import (
    CATALOGUE_WINDOW_MINUTES,
    UnderlyingStats,
    build_catalogue_from_underlying,
    publish_missing_seed_alert,
)

WINDOW_MINUTES = CATALOGUE_WINDOW_MINUTES


def fetch_contracts(minutes: int) -> tuple[list[dict], int, object | None, int, UnderlyingStats, int]:
    """Build the catalogue from processed upstream tables.

    security_def is read first so its published EXTERNAL_* ids seed fixture
    identity for the underlying catalogue; remaining security_def contracts
    then supplement fixtures the underlying table lacks.

    Returns (contracts, source_row_count, newest_publish_time,
    skipped_unparseable_count, underlying_stats, security_def_added).
    """
    client = ro_client()

    sd_contracts, skipped, sd_newest, sd_rows = fetch_security_def_contracts(
        client,
        minutes,
    )
    seed_index = build_identity_index(sd_contracts)
    contracts, u_stats, underlying_rows, u_newest = build_catalogue_from_underlying(
        client,
        minutes,
        seed_identity_index=seed_index,
    )
    contracts, sd_added = merge_security_def_contracts(contracts, sd_contracts)

    newest_publish: datetime | None = u_newest if isinstance(u_newest, datetime) else None
    if isinstance(sd_newest, datetime) and (newest_publish is None or sd_newest > newest_publish):
        newest_publish = sd_newest

    source_rows = underlying_rows + sd_rows
    return contracts, source_rows, newest_publish, skipped, u_stats, sd_added


def print_breakdown(contracts: list[dict]) -> None:
    """Summarise market_group x event_type — surfaces unmapped market types."""
    by_group = Counter(
        (c.get("eventMetaPREDICT_MARKET_TYPE") or "(blank)", c.get("eventMetaPREDICT_EVENT_TYPE") or "(blank)")
        for c in contracts
    )
    has_game_id = Counter(
        (c.get("eventMetaPREDICT_MARKET_TYPE") or "(blank)") for c in contracts if c.get("eventMetaEXTERNAL_GAME_ID")
    )
    print("\n  market_group / event_type           contracts  (with game_id)", file=sys.stderr)
    for (group, etype), n in by_group.most_common():
        gid = has_game_id.get(group, 0)
        print(f"    {group:24} / {etype:14} {n:6}  ({gid} with game_id)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch the crypto.com contract catalogue from BigQuery.",
    )
    parser.add_argument("--league", nargs="+", help="(accepted, not used for filtering)")
    window = parser.add_mutually_exclusive_group()
    window.add_argument(
        "--minutes",
        type=int,
        default=None,
        help=f"Look-back window in minutes (default {WINDOW_MINUTES})",
    )
    window.add_argument(
        "--hours",
        type=int,
        default=None,
        help="Look-back window in hours (ad-hoc convenience)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help="Max contracts to write (for smoke testing)",
    )
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--out-dir", help="Output directory (cron mode; writes crypto_com_markets.jsonl)")
    out.add_argument("--out", help="Output JSONL path (ad-hoc mode; nothing written on empty window)")
    args = parser.parse_args()

    minutes = (
        args.hours * 60 if args.hours is not None else args.minutes if args.minutes is not None else WINDOW_MINUTES
    )
    print(
        f"Querying processed catalogue (underlying_securities + security_def) over the last {minutes} min...",
        file=sys.stderr,
    )
    contracts, source_rows, newest_publish, skipped, u_stats, sd_added = fetch_contracts(
        minutes,
    )

    if skipped:
        print(
            f"  WARNING: skipped {skipped} security_def rows with no parseable event metadata",
            file=sys.stderr,
        )

    total_underlying = (
        u_stats.game_lines + u_stats.player_props
        + u_stats.team_props + u_stats.game_props
    )
    if total_underlying:
        print(
            f"  {total_underlying} "
            f"contracts from underlying_securities "
            f"({u_stats.game_lines} game lines, {u_stats.player_props} player props, "
            f"{u_stats.team_props} team props, {u_stats.game_props} game props; "
            f"{u_stats.skipped_no_identity} skipped — no fixture identity, "
            f"{u_stats.skipped_duplicate} duplicate security_id)",
            file=sys.stderr,
        )

    if u_stats.skipped_no_identity:
        print(
            f"  WARNING: dropped {u_stats.skipped_no_identity} contract(s) "
            f"lacking security_def EXTERNAL_* fixture identity "
            f"({len(u_stats.no_identity_prefixes)} prefix(es)) — "
            f"missing mappings preferred over text-order home/away guesses",
            file=sys.stderr,
        )
        publish_missing_seed_alert(u_stats)
    if u_stats.skipped_unparsed_game_line:
        print(
            f"  WARNING: dropped {u_stats.skipped_unparsed_game_line} game-line "
            f"rows with a resolved fixture but an unparseable outcome/line — "
            f"likely a mapper gap (bug, unhandled contract type, or alias "
            f"drift).  See the warning log for the affected symbols.",
            file=sys.stderr,
        )
    if sd_added:
        print(
            f"  +{sd_added} contracts added/refreshed from crypto_security_def",
            file=sys.stderr,
        )

    if source_rows == 0 and not contracts:
        if args.out:
            print(
                "  WARNING: no catalogue rows in the window.  Try a wider --hours.  Nothing written.",
                file=sys.stderr,
            )
            return
        print(
            "  WARNING: no catalogue rows in the window.  Writing an empty "
            "file; crypto mappings will be absent this run.",
            file=sys.stderr,
        )
    elif contracts:
        print(
            f"  {source_rows} source rows, {len(contracts)} contracts after merge, newest {newest_publish}",
            file=sys.stderr,
        )
        print_breakdown(contracts)

    if args.max_items:
        contracts = contracts[: args.max_items]

    out_path = None
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        out_path = os.path.join(args.out_dir, "crypto_com_markets.jsonl")
    elif args.out:
        out_path = args.out

    if out_path:
        with open(out_path, "w") as f:
            for c in contracts:
                print(json.dumps(c), file=f)
        print(f"Wrote {out_path} ({len(contracts)} contracts)", file=sys.stderr)
        print(f"Browse it:  python scripts/scan_crypto_com.py {out_path}", file=sys.stderr)
    else:
        for c in contracts:
            print(json.dumps(c))


if __name__ == "__main__":
    main()

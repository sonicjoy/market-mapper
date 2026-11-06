"""Orchestrator: fetch from all exchanges and write to a timestamped directory.

Usage:
    python -m fetch --league nba ncaab --out-dir data

Runs exchange fetchers as subprocesses, passing --league and --out-dir
to each.  Creates <out-dir>/<date>/<HH_MM>/ under the given directory.
Dies if the timestamped directory already exists.

Optic runs first (required schedule index).  Remaining fetchers run in
parallel — each writes a distinct filename, so there is no shared-file
race.
"""

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from fetch.tip import huddle_requested, runshop_requested, stx_requested, underdog_requested

FETCHERS = [
    "fetch.optic",
    "fetch.kalshi",
    "fetch.px",
    "fetch.crypto_com",
    "fetch.polymarket",
    "fetch.novig",
    # DKEX: read from BigQuery; the GKE dkex-catalogue CronJob fetches it.
    "fetch.dkex_bq",
    # SX Bet: the public /markets/active book, whole (docs/adding-sxbet.md).
    "fetch.sxbet",
]

RUNSHOP_FETCHER = "fetch.runshop"
HUDDLE_FETCHER = "fetch.huddle"
UNDERDOG_FETCHER = "fetch.underdog"
STX_FETCHER = "fetch.stx"
REQUIRED = {"fetch.optic"}


def _fetcher_cmd(fetcher: str, leagues: list[str], out_dir: Path,
                 *, minimal: bool, horizon_hours: float | None) -> list[str]:
    cmd = [
        sys.executable, "-m", fetcher,
        "--league", *leagues,
        "--out-dir", str(out_dir),
    ]
    if minimal:
        cmd.extend(["--max-items", "3"])
    if horizon_hours is not None and fetcher == "fetch.optic":
        cmd.extend(["--horizon-hours", str(horizon_hours)])
    return cmd


def _run_fetcher(fetcher: str, cmd: list[str]) -> tuple[str, int]:
    print(f"Running {fetcher}")
    result = subprocess.run(cmd)
    return fetcher, result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Fetch from all exchanges for the given leagues.",
    )
    parser.add_argument(
        "--league", nargs="+", required=True,
        help="Leagues to fetch (wired League members or tip-only slugs)",
    )
    parser.add_argument(
        "--out-dir", required=True,
        help="Top-level output directory (timestamped subdir created within)",
    )
    parser.add_argument(
        "--minimal", action="store_true",
        help="Smoke-test mode: fetch only 3 items per exchange",
    )
    parser.add_argument(
        "--horizon-hours", type=float,
        help="Override the Optic fixture horizon (forwarded to "
             "fetch.optic only) — for testing leagues whose fixtures "
             "are further out",
    )
    args = parser.parse_args()

    now = datetime.now(UTC)
    out_dir = Path(args.out_dir) / now.strftime("%Y-%m-%d") / now.strftime("%H_%M")

    if out_dir.exists():
        print(f"Error: {out_dir} already exists", file=sys.stderr)
        sys.exit(1)
    out_dir.mkdir(parents=True)

    # Optic is the schedule index — without it nothing can be matched.
    # PX and Kalshi are optional: a failed exchange fetch still produces
    # useful (partial) mappings from the exchanges that succeeded.
    fetchers = list(FETCHERS)
    if runshop_requested(args.league):
        fetchers.append(RUNSHOP_FETCHER)
    if huddle_requested(args.league):
        fetchers.append(HUDDLE_FETCHER)
    # Optional like every non-Optic fetcher: a failed UDX pull leaves no
    # underdog_markets.jsonl and the map pass skips Underdog for the tick.
    if underdog_requested(args.league):
        fetchers.append(UNDERDOG_FETCHER)
    # STX (Ontario exchange): optional, and a no-op unless STX_ENV is set in .env (test only today).
    if stx_requested(args.league):
        fetchers.append(STX_FETCHER)

    optic, *optional = fetchers
    if optic != "fetch.optic":
        print(f"FATAL: expected fetch.optic first, got {optic}", file=sys.stderr)
        sys.exit(1)

    failed = []

    optic_cmd = _fetcher_cmd(
        optic, args.league, out_dir,
        minimal=args.minimal, horizon_hours=args.horizon_hours,
    )
    name, code = _run_fetcher(optic, optic_cmd)
    if code != 0:
        print(f"FAILED: {name} (exit {code})", file=sys.stderr)
        failed.append(name)
        print(f"Failures: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    if optional:
        def _submit(fetcher: str) -> tuple[str, int]:
            cmd = _fetcher_cmd(
                fetcher, args.league, out_dir,
                minimal=args.minimal, horizon_hours=args.horizon_hours,
            )
            return _run_fetcher(fetcher, cmd)

        with ThreadPoolExecutor(max_workers=len(optional)) as pool:
            futs = [pool.submit(_submit, f) for f in optional]
            for fut in as_completed(futs):
                name, code = fut.result()
                if code != 0:
                    print(f"FAILED: {name} (exit {code})", file=sys.stderr)
                    failed.append(name)

    if failed:
        print(f"Failures: {', '.join(failed)}", file=sys.stderr)
        required_failures = [f for f in failed if f in REQUIRED]
        if required_failures:
            sys.exit(1)
        print("Continuing with partial data (optic OK).")
    else:
        print("All fetchers succeeded.")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()

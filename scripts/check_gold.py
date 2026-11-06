#!/usr/bin/env python3
"""Check pipeline output against golden mapping files.

Walks data directories looking for gold/ subdirectories.  For each
golden file (e.g. gold/nba.jsonl), re-runs the pipeline for that
league and diffs the output against the saved golden mappings.

Reports PASS/FAIL per golden file and exits non-zero if any fail.

Usage:
    python scripts/check_gold.py data/
"""

import contextlib
import io
import json
import sys
from pathlib import Path

from mappers import pipeline
from mappers.run import LEAGUES


def _gold_key(row: dict) -> tuple:
    """Identity key from a golden-file row dict (the 8 key fields)."""
    return (
        row["start_date"], row["home"], row["away"],
        row["market_type"], row["entity"], row["line"],
        row["side"], row["grouping_key"],
    )


def _sort_key(key: tuple) -> tuple:
    """Sortable view of a _gold_key — None becomes '' so tuples
    that mix None and str at the same slot (e.g. grouping_key
    None vs 'marmad_round') stay comparable."""
    return tuple("" if v is None else v for v in key)


def find_gold_files(root: Path) -> list[tuple[Path, str]]:
    """Find all gold/<league>.jsonl files under root.

    Returns (data_dir, league_key) pairs, sorted by data_dir then league.
    The data_dir is the parent of the gold/ directory.
    """
    results = []
    for gold_path in sorted(root.rglob("gold/*.jsonl")):
        league_key = gold_path.stem
        if league_key not in LEAGUES:
            print(f"  skip {gold_path} (unknown league {league_key!r})",
                  file=sys.stderr)
            continue
        data_dir = gold_path.parent.parent
        results.append((data_dir, league_key))
    return results


def load_gold_file(path: Path) -> dict[tuple, dict]:
    """Load a golden JSONL file, keyed by identity tuple."""
    rows = {}
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            rows[_gold_key(row)] = row
    return rows


def run_and_diff(data_dir: Path, league_key: str) -> list[str]:
    """Run pipeline and diff against the golden file.

    Returns a list of diff lines (empty = pass).
    """
    league = LEAGUES[league_key]

    # Suppress pipeline stderr (match counts, diagnostics).
    with contextlib.redirect_stderr(io.StringIO()):
        result = pipeline.run(data_dir, league)

    # Build current gold rows keyed by identity.
    current: dict[tuple, dict] = {}
    for r in result.rows:
        row = pipeline.gold_row(r)
        current[_gold_key(row)] = row

    gold_path = data_dir / "gold" / f"{league_key}.jsonl"
    saved = load_gold_file(gold_path)

    diffs: list[str] = []

    # Removed: in saved but not in current.
    for key in sorted(saved.keys() - current.keys(), key=_sort_key):
        row = saved[key]
        diffs.append(f"  removed: {row['start_date']} {row['home']}v{row['away']} "
                     f"{row['market_type']} {row['entity'] or ''} "
                     f"{row['line'] or ''} {row['side']}")

    # Added: in current but not in saved.
    for key in sorted(current.keys() - saved.keys(), key=_sort_key):
        row = current[key]
        diffs.append(f"  added:   {row['start_date']} {row['home']}v{row['away']} "
                     f"{row['market_type']} {row['entity'] or ''} "
                     f"{row['line'] or ''} {row['side']}")

    # Changed: same key, different exchange IDs.
    for key in sorted(saved.keys() & current.keys(), key=_sort_key):
        s, c = saved[key], current[key]
        if s != c:
            changes = []
            for field in ("optic_id", "px_line_id",
                          "kalshi_ticker", "kalshi_side"):
                if s.get(field) != c.get(field):
                    changes.append(f"{field}: {s.get(field)!r} -> "
                                   f"{c.get(field)!r}")
            row = s
            diffs.append(
                f"  changed: {row['start_date']} {row['home']}v{row['away']} "
                f"{row['market_type']} {row['entity'] or ''} "
                f"{row['line'] or ''} {row['side']}  "
                f"[{', '.join(changes)}]")

    return diffs


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Check pipeline output against golden mapping files")
    parser.add_argument("dir", type=Path,
                        help="Top-level data directory to search")
    args = parser.parse_args()

    gold_files = find_gold_files(args.dir)
    if not gold_files:
        print(f"No gold/*.jsonl files found under {args.dir}",
              file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(gold_files)} golden file(s)\n")

    failures = 0
    for data_dir, league_key in gold_files:
        label = f"{data_dir} [{league_key}]"
        try:
            diffs = run_and_diff(data_dir, league_key)
        except Exception as e:
            print(f"  FAIL {label}")
            print(f"       {e}")
            failures += 1
            continue

        if diffs:
            print(f"  FAIL {label}  ({len(diffs)} diff(s))")
            for d in diffs:
                print(f"       {d}")
            failures += 1
        else:
            print(f"  ok   {label}")

    print()
    if failures:
        print(f"{failures} failure(s) out of {len(gold_files)} golden file(s)")
        sys.exit(1)
    else:
        print(f"All {len(gold_files)} golden file(s) passed")


if __name__ == "__main__":
    main()

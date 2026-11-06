#!/usr/bin/env python3
"""Run the mapping pipeline across all date/time directories.

Walks a data directory for yyyy-mm-dd/hh_mm subdirectories and runs
the pipeline on each one.  Reports pass/fail per directory and exits
non-zero if any run raised.

Usage:
    python scripts/smoke.py data/
    python scripts/smoke.py data/ --league nba
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"\d{2}_\d{2}")


def find_data_dirs(root: Path) -> list[Path]:
    """Find all root/yyyy-mm-dd/hh_mm directories, sorted."""
    dirs = []
    for date_dir in sorted(root.iterdir()):
        if not date_dir.is_dir() or not DATE_RE.fullmatch(date_dir.name):
            continue
        for time_dir in sorted(date_dir.iterdir()):
            if time_dir.is_dir() and TIME_RE.fullmatch(time_dir.name):
                dirs.append(time_dir)
    return dirs


def main():
    parser = argparse.ArgumentParser(
        description="Smoke-test the pipeline across all data snapshots")
    parser.add_argument("dir", type=Path,
                        help="Top-level data directory")
    parser.add_argument("--league", help="Pass --league to each run")
    args = parser.parse_args()

    dirs = find_data_dirs(args.dir)
    if not dirs:
        print(f"No yyyy-mm-dd/hh_mm directories found under {args.dir}",
              file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(dirs)} snapshot(s)\n")

    failures = []
    for d in dirs:
        cmd = [sys.executable, "-m", "mappers.run", str(d)]
        if args.league:
            cmd += ["--league", args.league]
        label = f"{d.parent.name}/{d.name}"
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(f"  ok   {label}")
        except subprocess.CalledProcessError as e:
            print(f"  FAIL {label}")
            if e.stderr:
                for line in e.stderr.strip().splitlines():
                    print(f"       {line}")
            failures.append(label)

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print(f"All {len(dirs)} snapshot(s) passed")


if __name__ == "__main__":
    main()

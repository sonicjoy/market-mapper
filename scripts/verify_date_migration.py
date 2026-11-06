#!/usr/bin/env python3
"""Interactive verification gate for date → start_date gold file migration.

For each data dir with gold files: backs up the old gold, regenerates,
diffs old vs new row-by-row, and asserts the ONLY changes are:
  - Old "date" and "time" fields removed
  - New "start_date" field added (UTC ISO timestamp)
  - All other fields identical
  - Row counts unchanged

Shows diff results before asking whether to keep or roll back.

Usage:
    python scripts/verify_date_migration.py
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Fields that uniquely identify a row for matching across old/new formats.
STABLE_KEY = ("home", "away", "market_type", "entity", "line", "side", "grouping_key")


def _stable_key(row: dict) -> tuple:
    """Extract a stable matching key from a gold file row."""
    return tuple(row.get(f) for f in STABLE_KEY)


def _confirm(prompt: str) -> None:
    """Wait for user confirmation, exit on decline."""
    answer = input(f"\n{prompt} [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        sys.exit(1)


def verify_gold_dir(data_dir: Path) -> tuple[list[str], bool]:
    """Back up, regenerate, and diff gold files for a data dir.

    Returns (diff_lines, all_ok).  On success the new gold files are
    on disk and the backup is at gold_backup/.  The caller decides
    whether to keep the new files (delete backup) or roll back
    (restore backup).
    """
    gold_dir = data_dir / "gold"
    backup_dir = data_dir / "gold_backup"

    # Back up
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(gold_dir, backup_dir)

    # Delete originals and regenerate
    shutil.rmtree(gold_dir)
    result = subprocess.run(
        [sys.executable, "-m", "mappers.run", str(data_dir), "--gold"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        shutil.copytree(backup_dir, gold_dir)
        shutil.rmtree(backup_dir)
        return [f"  ERROR: pipeline failed: {result.stderr[:200]}"], False

    # Diff old (backup) vs new (regenerated)
    diffs = []
    all_ok = True
    for old_file in sorted(backup_dir.glob("*.jsonl")):
        new_file = gold_dir / old_file.name
        if not new_file.exists():
            diffs.append(f"  MISSING: {old_file.name} not regenerated")
            all_ok = False
            continue

        old_rows = [json.loads(l) for l in old_file.read_text().strip().split("\n") if l.strip()]
        new_rows = [json.loads(l) for l in new_file.read_text().strip().split("\n") if l.strip()]

        if len(old_rows) != len(new_rows):
            diffs.append(f"  {old_file.name}: ROW COUNT {len(old_rows)} → {len(new_rows)}")
            all_ok = False
            continue

        # Index new rows by stable key
        new_by_key: dict[tuple, dict] = {}
        for r in new_rows:
            new_by_key[_stable_key(r)] = r

        unexpected = 0
        for old in old_rows:
            sk = _stable_key(old)
            new = new_by_key.get(sk)
            if new is None:
                unexpected += 1
                continue

            # Expected changes: date/time removed, start_date added
            old_copy = {k: v for k, v in old.items() if k not in ("date", "time")}
            new_copy = {k: v for k, v in new.items() if k != "start_date"}
            if old_copy != new_copy:
                unexpected += 1

        if unexpected:
            diffs.append(f"  {old_file.name}: {unexpected} unexpected diffs out of {len(old_rows)} rows")
            all_ok = False
        else:
            diffs.append(f"  {old_file.name}: OK ({len(old_rows)} rows, only date→start_date)")

    return diffs, all_ok


def _accept_gold(data_dir: Path) -> None:
    """Delete the backup, keeping the regenerated gold files."""
    backup_dir = data_dir / "gold_backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)


def _rollback_gold(data_dir: Path) -> None:
    """Restore the backup, discarding the regenerated gold files."""
    gold_dir = data_dir / "gold"
    backup_dir = data_dir / "gold_backup"
    if backup_dir.exists():
        if gold_dir.exists():
            shutil.rmtree(gold_dir)
        shutil.copytree(backup_dir, gold_dir)
        shutil.rmtree(backup_dir)


def main():
    print("=" * 60)
    print("Gold file migration: date → start_date")
    print("=" * 60)

    # Scan for gold dirs — only data/YYYY-MM-DD/HH_MM layout,
    # not sport-organized dirs like data/nba/2026-02-19.
    date_re = re.compile(r"\d{4}-\d{2}-\d{2}")
    unique_dirs = sorted(
        gd.parent
        for gd in Path("data").glob("*/*/gold")
        if gd.exists() and date_re.fullmatch(gd.parent.parent.name)
    )

    print(f"\nFound {len(unique_dirs)} data dirs with gold files:")
    for d in unique_dirs:
        print(f"  {d}")

    total_ok = 0
    total_error = 0
    total_skipped = 0
    for data_dir in unique_dirs:
        print(f"\n--- {data_dir} ---")

        # Skip dirs whose gold files are already migrated to start_date.
        first_line = ""
        for candidate in (data_dir / "gold").glob("*.jsonl"):
            first_line = candidate.read_text().split("\n", 1)[0].strip()
            if first_line:
                break
        if first_line:
            first_row = json.loads(first_line)
            if "start_date" in first_row and "date" not in first_row:
                print("  Already migrated — skipping")
                total_skipped += 1
                continue

        results, all_ok = verify_gold_dir(data_dir)
        for line in results:
            print(line)
            if "OK" in line:
                total_ok += 1
            elif "ERROR" in line or "UNEXPECTED" in line or "MISSING" in line:
                total_error += 1

        if all_ok:
            _confirm("Diff clean. Accept new gold files?")
            _accept_gold(data_dir)
        else:
            print("\n  *** UNEXPECTED DIFFS — rolling back ***")
            _rollback_gold(data_dir)
            _confirm("Rolled back. Continue to next directory?")

    print(f"\n{'=' * 60}")
    print(f"Final summary: {total_ok} gold files OK, {total_error} errors/unexpected, {total_skipped} skipped")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

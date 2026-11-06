#!/usr/bin/env python3
"""Export prod Missing catalogue rows to scratch/missing_catalogue_dev.jsonl for local dev.

Usage (from repo root):
  GCP_PROJECT=rs-marketmaking python scripts/export_missing_catalogue_dev.py
  # optional: --project rs-marketmaking --out scratch/missing_catalogue_dev.jsonl

Then start the console API with MAPPING_MISSING_BQ_PROJECT=local (start-console-local.ps1
does this when the file exists).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from BigQuery.client import ro_client, ro_query  # noqa: E402
from mappers.control_plane.console_missing_local import (  # noqa: E402
    missing_local_path,
    write_missing_local_jsonl,
)
from mappers.control_plane.console_missing_sql import crypto_missing_sql  # noqa: E402


def _fetch_rows(project: str) -> list[dict]:
    client = ro_client()
    sql = crypto_missing_sql(project, row_cap=None)
    return [dict(r) for r in ro_query(client, sql)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Missing catalogue to local JSONL")
    parser.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT", "rs-marketmaking"),
        help="BQ project to read (default rs-marketmaking)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default scratch/missing_catalogue_dev.jsonl)",
    )
    args = parser.parse_args()
    project = str(args.project).strip()
    if not project:
        print("project is required", file=sys.stderr)
        return 1
    os.environ.setdefault("GCP_PROJECT", project)
    print(f"Querying {project} …")
    rows = _fetch_rows(project)
    out = write_missing_local_jsonl(rows, args.out or missing_local_path())
    print(f"Wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

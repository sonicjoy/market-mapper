#!/usr/bin/env python
"""Regenerate the offline fixture from a project's activated (legacy, retiring) tip.

The whole test suite classifies against ``tests/fixtures/sot/tip.json``
rather than reaching BigQuery. Re-run this whenever the activated
rule-set changes in a way tests should see:

    GCP_PROJECT=marketmaking-test python scripts/build_sot_fixture.py

Reads the activated tip directly (``load_live_snapshot``) so it works
even though ``MAPPING_SOT_FIXTURE`` may point at the file being
rewritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mappers.seed.fixture_store import write_fixture
from mappers.seed.sot import load_live_snapshot

_DEFAULT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sot" / "tip.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT,
        help=f"fixture path to write (default: {_DEFAULT})",
    )
    args = parser.parse_args(argv)

    snap = load_live_snapshot()
    write_fixture(snap, args.out)
    print(
        f"wrote {args.out} rule_set_id={snap.rule_set_id} "
        f"leagues={len(snap.leagues)} entities={len(snap.entities)} "
        f"market_rules={len(snap.market_rules)}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

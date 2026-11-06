"""Integration test: run the NCAAB mapper against a three-game fixture.

Fixture data is trimmed from the 2026-03-07 snapshot (three games).  The
fixture's Kalshi markets predate Kalshi's typed milestone/scope fields, so
they join no fixture and contribute no rows.  Games of note:

  COLO @ ARIZ  — PX uses "COL" which is a collision entry (Colorado vs
                 Columbia).  The alias config disambiguates via event ID.
  DUKE @ UNC   — Richest player-prop coverage (10 players, 12 market
                 types).

A synthetic PX market ("Boopie Miller Total Points") was added to the
DUKE/UNC event to exercise the player alias path: PX says
"boopie_miller", the alias config maps it to "kevin_miller".

The expected output was captured from a known-good run.  If the mapper
changes behaviour, re-run and inspect the diff before updating:

    python -m mappers.run tests/mappers/fixtures/ncaab --league ncaab --json > \
        tests/mappers/fixtures/ncaab/expected_output.jsonl
"""

import difflib
import json
import os
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "2026-03-07" / "18_00"
EXPECTED = FIXTURES / "expected_output.jsonl"
_SOT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sot" / "tip.json"


def test_ncaab_mapper_output_matches_snapshot():
    """Full pipeline: parse, match, merge, serialize — compare to snapshot."""
    env = {
        **os.environ,
        "GCP_PROJECT": "marketmaking-test",
        "MAPPING_SOT_FIXTURE": str(_SOT_FIXTURE),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    result = subprocess.run(
        [sys.executable, "-m", "mappers.run", str(FIXTURES), "--league", "ncaab", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"mapper failed:\n{result.stderr}"

    actual_lines = result.stdout.strip().split("\n")
    expected_lines = EXPECTED.read_text().strip().split("\n")

    actual = [json.loads(line) for line in actual_lines]
    expected = [json.loads(line) for line in expected_lines]

    assert len(actual) == len(expected), (
        f"Row count: expected {len(expected)}, got {len(actual)}")

    for i, (act, exp) in enumerate(zip(actual, expected)):
        if act != exp:
            act_pretty = json.dumps(act, indent=2, sort_keys=True).splitlines()
            exp_pretty = json.dumps(exp, indent=2, sort_keys=True).splitlines()
            diff = difflib.unified_diff(
                exp_pretty, act_pretty,
                fromfile=f"expected row {i}",
                tofile=f"actual row {i}",
                lineterm="",
            )
            assert False, f"First diff at row {i}:\n" + "\n".join(diff)

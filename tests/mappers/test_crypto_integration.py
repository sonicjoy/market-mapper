"""Integration test: crypto.com merging onto a real NYK/SAS game.

The fixture is the upcoming 2026-06-05 New York Knicks @ San Antonio
Spurs game (Optic + ProphetX), carved from a prod snapshot and
trimmed to game-line markets.  crypto_com_markets.jsonl holds the 23
real crypto.com NBA game-line selections originally captured for the
2026-03-04 NYK/OKC game (the only real crypto.com NBA data we have),
relabeled away-team OKC->SAS and re-dated to this game so they merge.
This is the same controlled synthesis the other fixtures use (see
test_nba_integration): the crypto IDs and line values are genuine, only
the opponent label and date are restamped.

What this exercises that the unit tests can't:
  - crypto rows merging onto existing Optic/PX rows by key
    (moneyline onto both; spread/total onto Optic's line ladder),
  - identity-based side resolution end to end on real data,
  - the crypto_com serialization block.

If the mapper changes behaviour, re-run and inspect the diff before
updating:

    python -m mappers.run tests/mappers/fixtures/2026-06-04/09_44 \
        --league nba --json > \
        tests/mappers/fixtures/2026-06-04/09_44/expected_output.jsonl
"""

import difflib
import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "2026-06-04" / "09_44"
EXPECTED = FIXTURE / "expected_output.jsonl"


def _run() -> list[dict]:
    result = subprocess.run(
        [sys.executable, "-m", "mappers.run", str(FIXTURE),
         "--league", "nba", "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mapper failed:\n{result.stderr}"
    return [json.loads(line) for line in result.stdout.strip().split("\n")]


def test_output_matches_snapshot():
    """Full pipeline: parse, match, merge, serialize — compare to snapshot."""
    actual = _run()
    expected = [json.loads(line)
                for line in EXPECTED.read_text().strip().split("\n")]

    assert len(actual) == len(expected), (
        f"Row count: expected {len(expected)}, got {len(actual)}")

    for i, (act, exp) in enumerate(zip(actual, expected)):
        if act != exp:
            diff = difflib.unified_diff(
                json.dumps(exp, indent=2, sort_keys=True).splitlines(),
                json.dumps(act, indent=2, sort_keys=True).splitlines(),
                fromfile=f"expected row {i}", tofile=f"actual row {i}",
                lineterm="",
            )
            assert False, f"First diff at row {i}:\n" + "\n".join(diff)


def test_crypto_moneyline_merges_onto_all_sources():
    """Both crypto moneyline sides land on rows that already carry
    Optic and ProphetX IDs — crypto stamped alongside, not a
    separate orphan row.  (The fixture's Kalshi markets predate Kalshi's
    typed milestone/scope fields, so they no longer join a fixture.)"""
    ml = [r for r in _run()
          if r.get("crypto_com") and r["key"]["market_type"] == "moneyline"]
    assert {r["key"]["side"] for r in ml} == {"NYK", "SAS"}
    for r in ml:
        assert r["optic_odds"] is not None, r["key"]
        assert r["prophet_x"] is not None, r["key"]


def test_crypto_sides_are_identity_based():
    """Side follows the crypto selection's own named team, not the
    fixture's home/away position.  The fixture has SAS as home; a
    positional bug would tie 'Home' outcomes to SAS regardless of which
    team the selection names."""
    for r in _run():
        c = r.get("crypto_com")
        if c is None or r["key"]["market_type"] != "moneyline":
            continue
        side = r["key"]["side"]
        name = c["selection_name"]
        assert (side == "SAS") == ("Spurs" in name), (side, name)
        assert (side == "NYK") == ("Knicks" in name), (side, name)


def test_crypto_covers_all_three_game_line_types():
    """All 23 real selections map and merge across the three NBA
    crypto game-line types."""
    cr = [r for r in _run() if r.get("crypto_com")]
    assert len(cr) == 23
    assert {r["key"]["market_type"] for r in cr} == {
        "moneyline", "point_spread", "game_total"}

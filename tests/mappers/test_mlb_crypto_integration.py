"""Integration test: crypto.com merging onto an MLB game (PHI @ KAN).

Fixture carved from live crypto.com catalogue (2026-07-06 Royals vs
Phillies) with a synthetic Optic schedule row — Optic ships zero
active MLB fixtures in July 2026, so the schedule index is minimal but
valid.  All 35 real crypto game-line selections merge onto Optic keys.

Regenerate after mapper changes:

    python scripts/carve_mlb_crypto_fixture.py \\
        scratch/mlb_map_test2/2026-07-13/11_02
"""

import difflib
import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "2026-07-06" / "14_10"
EXPECTED = FIXTURE / "expected_output.jsonl"


def _run() -> list[dict]:
    result = subprocess.run(
        [sys.executable, "-m", "mappers.run", str(FIXTURE),
         "--league", "mlb", "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mapper failed:\n{result.stderr}"
    return [json.loads(line) for line in result.stdout.strip().split("\n")]


def test_output_matches_snapshot():
    actual = _run()
    expected = [json.loads(line)
                for line in EXPECTED.read_text().strip().split("\n")]
    assert len(actual) == len(expected)
    for i, (act, exp) in enumerate(zip(actual, expected)):
        if act != exp:
            diff = difflib.unified_diff(
                json.dumps(exp, indent=2, sort_keys=True).splitlines(),
                json.dumps(act, indent=2, sort_keys=True).splitlines(),
                fromfile=f"expected row {i}", tofile=f"actual row {i}",
                lineterm="",
            )
            assert False, f"First diff at row {i}:\n" + "\n".join(diff)


def test_crypto_covers_all_three_game_line_types():
    rows = _run()
    crypto = [r for r in rows if r.get("crypto_com")]
    assert len(crypto) == 35
    assert {r["key"]["market_type"] for r in crypto} == {
        "moneyline", "point_spread", "game_total",
    }


def test_crypto_moneyline_merges_onto_optic():
    """Moneyline crypto rows share Optic keys; spread/total may be crypto-only
    when the synthetic Optic ladder does not carry every line."""
    ml = [r for r in _run()
          if r.get("crypto_com") and r["key"]["market_type"] == "moneyline"]
    assert len(ml) == 2
    assert {r["key"]["side"] for r in ml} == {"KAN", "PHI"}
    for r in ml:
        assert r["optic_odds"] is not None, r["key"]


def test_crypto_sides_are_identity_based():
    for r in _run():
        c = r.get("crypto_com")
        if c is None or r["key"]["market_type"] != "moneyline":
            continue
        side = r["key"]["side"]
        name = c["selection_name"]
        assert (side == "KAN") == ("Royals" in name), (side, name)
        assert (side == "PHI") == ("Phillies" in name), (side, name)

"""Integration test: crypto.com 3-way moneyline + Anytime Goal Scorer
prop merging onto a real World Cup game (USA v Paraguay, 2026-06-12).

Small single-game fixture carved from real data (2026-06-09 fetch):
the Optic fixture trimmed to its `moneyline` market plus Haji Wright's
`player_goals` over ladder (0.5/1.5/2.5), the three Kalshi
KXWCGAME-26JUN12USAPAR markets (USA/PAR/TIE; their typed fields --
"Game" scope, soccer_team strike ids and the milestone naming Optic's
fixture and team ids -- are filled in by hand in the fetch.kalshi
shape, since the capture predates them), the three real
crypto.com FIFA `Moneyline (3-Way)` selections (Home/Away/Draw), and
the real Haji Wright `Anytime Goal Scorer` prop — all from the
2026-06-08 FIX-feed dump.  No ProphetX — the World Cup has none; no
Kalshi goalscorer — KXWCGOAL had no posted markets at fixture time.

What this exercises that the unit tests can't (and the NBA crypto
integration test doesn't, being 2-way only):
  - the THREE_WAY/Draw branch end to end, with the Draw leg merging
    onto Optic's "Draw" selection and Kalshi's `-TIE` ticker rather
    than stranding novel,
  - crypto rows merging by row_key onto Optic + Kalshi on a real WC
    fixture, neutral-site (no positional cross-wire),
  - the player-prop path: crypto's Anytime Goal Scorer "Yes" mapping
    to a player_goals over-0.5 row whose normalized entity merges onto
    the real Optic player_goals row (the name-resolution payoff —
    crypto "Haji Wright" lands on Optic's "Haji Wright"),
  - the crypto_com serialization block.

If the mapper changes behaviour, re-run and inspect the diff before
updating:

    python -m mappers.run tests/mappers/fixtures/2026-06-09/15_00 \
        --league world_cup --json > \
        tests/mappers/fixtures/2026-06-09/15_00/expected_output.jsonl
"""

import difflib
import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "2026-06-09" / "15_00"
EXPECTED = FIXTURE / "expected_output.jsonl"


def _run() -> list[dict]:
    result = subprocess.run(
        [sys.executable, "-m", "mappers.run", str(FIXTURE),
         "--league", "world_cup", "--json"],
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


def test_crypto_3way_merges_onto_optic_and_kalshi():
    """All three legs (Home/Away/Draw) land on rows that already carry
    Optic and Kalshi IDs — crypto stamped alongside, none novel.  No PX
    for the World Cup."""
    cr = [r for r in _run()
          if r.get("crypto_com") and r["key"]["market_type"] == "moneyline_3way"]
    assert len(cr) == 3
    assert {r["key"]["side"] for r in cr} == {"USA", "PAR", "_TIE"}
    for r in cr:
        assert r["optic_odds"] is not None, r["key"]
        assert r["kalshi"] is not None, r["key"]
        assert r["prophet_x"] is None, r["key"]   # WC has no ProphetX


def test_crypto_anytime_goalscorer_merges_onto_anytime_goal_scorer():
    """The Anytime Goal Scorer prop maps to an anytime_goal_scorer row
    and merges onto Optic's real 0.5 goals row by normalized entity —
    proving name-based player resolution works across the two sources.
    Kalshi carries no goalscorer market here (KXWCGOAL unposted), so the
    row has Optic + crypto only, not novel."""
    (goal,) = [r for r in _run()
               if r.get("crypto_com") and r["key"]["market_type"] == "anytime_goal_scorer"]
    assert goal["key"]["entity"] == "haji_wright"   # crypto name == Optic name, normalized
    assert goal["key"]["line"] is None              # "1+" goals is a yes/no question
    assert goal["key"]["side"] == "yes"
    assert goal["optic_odds"] is not None           # merged onto Optic
    assert goal["optic_odds"]["selection"] == "Haji Wright"
    assert goal["kalshi"] is None                   # KXWCGOAL not posted
    assert goal["crypto_com"]["selection_name"] == "Haji Wright Anytime Goal Scorer"


def test_crypto_draw_leg_merges_onto_tie():
    """The Draw leg is the reason this test exists: crypto's "Draw to
    win" resolves to TIE_SIDE and merges onto Optic's "Draw" selection
    and Kalshi's -TIE ticker, with no line."""
    (draw,) = [r for r in _run()
               if r.get("crypto_com") and r["key"]["side"] == "_TIE"]
    assert draw["key"]["line"] is None
    assert draw["crypto_com"]["selection_name"] == "Draw to win"
    assert draw["optic_odds"]["selection"] == "Draw"
    assert draw["kalshi"]["market_ticker"].endswith("-TIE")


def test_crypto_sides_are_identity_based():
    """Side follows the crypto selection's own named team, not the
    fixture's home/away position."""
    for r in _run():
        c = r.get("crypto_com")
        if c is None:
            continue
        side, name = r["key"]["side"], c["selection_name"]
        assert (side == "USA") == ("United States" in name), (side, name)
        assert (side == "PAR") == ("Paraguay" in name), (side, name)
        assert (side == "_TIE") == ("Draw" in name), (side, name)

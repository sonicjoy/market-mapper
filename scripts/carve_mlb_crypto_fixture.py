"""Carve an MLB crypto integration fixture from a fetch directory.

Builds tests/mappers/fixtures/<date>/<time>/ with real crypto.com game
lines plus a synthetic Optic schedule row so the pipeline can merge
crypto onto Optic keys.  Kalshi/PX are omitted (crypto-only rows).

Usage:
    python scripts/carve_mlb_crypto_fixture.py \\
        scratch/mlb_map_test2/2026-07-13/11_02
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

HOME = "KAN"
AWAY = "PHI"
HOME_NAME = "Kansas City Royals"
AWAY_NAME = "Philadelphia Phillies"
HOME_CRYPTO_ID = "10000005"
AWAY_CRYPTO_ID = "10000012"
GAME_DATE = "2026-07-06T18:10:00+00:00"
GAME_DATE_ET = "2026-07-06T14:10:00-04:00"


def _pick_crypto_lines(src: Path) -> list[dict]:
    rows: list[dict] = []
    for line in src.open(encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("eventMetaLEAGUE") != "MLB":
            continue
        if rec.get("eventMetaPREDICT_MARKET_TYPE") != "Game Line":
            continue
        if (
            rec.get("eventMetaHOME_PARTICIPANT") == HOME_NAME
            and rec.get("eventMetaAWAY_PARTICIPANT") == AWAY_NAME
            and rec.get("eventMetaEVENT_DATE") == GAME_DATE
        ):
            rows.append(rec)
    if not rows:
        raise SystemExit(
            f"No crypto game lines for {AWAY_NAME} @ {HOME_NAME} at {GAME_DATE}")
    return rows


def _synthetic_optic_fixture() -> dict:
    home_oid = f"mlb-home-{uuid.uuid4().hex[:8]}"
    away_oid = f"mlb-away-{uuid.uuid4().hex[:8]}"
    fixture_id = f"mlb-fix-{uuid.uuid4().hex[:12]}"
    game_id = f"mlb-game-{uuid.uuid4().hex[:8]}"
    odds = []
    for i, (market_id, team_id, side, points) in enumerate((
        ("moneyline", home_oid, HOME_NAME, None),
        ("moneyline", away_oid, AWAY_NAME, None),
        ("run_line", home_oid, HOME_NAME, 1.5),
        ("run_line", away_oid, AWAY_NAME, -1.5),
        ("total_runs", None, "over", 8.5),
        ("total_runs", None, "under", 8.5),
    )):
        odds.append({
            "id": f"odd-{i}",
            "market_id": market_id,
            "name": side,
            "selection": side,
            "normalized_selection": side,
            "selection_line": "over" if side == "over" else (
                "under" if side == "under" else None),
            "points": points,
            "team_id": team_id,
            "grouping_key": f"{market_id}:{points or 'ml'}",
        })
    return {
        "id": fixture_id,
        "game_id": game_id,
        "start_date": GAME_DATE.replace("+00:00", "Z"),
        "status": "unplayed",
        "is_live": False,
        "league": {"id": "mlb"},
        "home_competitors": [{
            "id": home_oid,
            "name": HOME_NAME,
            "abbreviation": HOME,
        }],
        "away_competitors": [{
            "id": away_oid,
            "name": AWAY_NAME,
            "abbreviation": AWAY,
        }],
        "odds": odds,
    }


def carve(src_dir: Path, dest: Path) -> None:
    crypto_src = src_dir / "crypto_com_markets.jsonl"
    if not crypto_src.exists():
        raise SystemExit(f"Missing {crypto_src}")

    crypto_lines = _pick_crypto_lines(crypto_src)
    dest.mkdir(parents=True, exist_ok=True)

    with (dest / "crypto_com_markets.jsonl").open("w", encoding="utf-8") as fh:
        for rec in crypto_lines:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")

    with (dest / "optic_fixtures_odds.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_synthetic_optic_fixture(), separators=(",", ":")) + "\n")

    for name in ("kalshi_markets.jsonl", "prophetx_events.jsonl", "prophetx_markets.jsonl"):
        (dest / name).write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "mappers.run", str(dest), "--league", "mlb", "--json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"mapper failed:\n{result.stderr}")
    (dest / "expected_output.jsonl").write_text(result.stdout, encoding="utf-8")
    crypto_rows = sum(
        1 for line in result.stdout.splitlines()
        if line.strip() and json.loads(line).get("crypto_com"))
    print(f"Wrote {dest} ({len(crypto_lines)} crypto lines, "
          f"{crypto_rows} output rows with crypto_com)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src_dir", type=Path, help="Fetch directory with crypto_com_markets.jsonl")
    parser.add_argument(
        "--dest", type=Path,
        default=Path("tests/mappers/fixtures/2026-07-06/14_10"),
    )
    args = parser.parse_args()
    carve(args.src_dir, args.dest)


if __name__ == "__main__":
    main()

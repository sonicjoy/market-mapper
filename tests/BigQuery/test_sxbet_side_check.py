"""SX Bet side check: verdicts on real SX shapes, the flip convention, batching, SQL."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from BigQuery import sxbet_side_check as sc
from BigQuery.sxbet_side_check import Row, verdict

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sxbet" / "markets_active_2026-10-13.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))


def _m(o1: str, o2: str | None = None) -> dict:
    return next(r for r in RAW if r["outcomeOneName"] == o1 and (o2 is None or r["outcomeTwoName"] == o2))


def _row(suffix: str, *, selection: str = "", selection_line: str = "", points=None, line=None,
         market_type: str = "point_spread") -> Row:
    return Row(market_hash="0xh", suffix=suffix, league="l", market_type=market_type, selection=selection,
               selection_line=selection_line, points=points, line=line, method="", fixture_id="F")


def test_the_suffix_is_the_makers_outcome() -> None:
    assert _row("two").taker_outcome == 1
    assert _row("one").taker_outcome == 2


def test_total_agrees_and_flips() -> None:
    m = _m("Over 2.5", "Under 2.5")   # Galatasaray v Barcelona
    under = {"selection_line": "under", "points": 2.5, "line": 2.5, "market_type": "game_total"}
    assert verdict(_row("one", **under), m) == "AGREE"       # |one = taker outcome two = Under
    assert verdict(_row("two", **under), m) == "FLIP"        # |two = Over, the row says under


def test_total_whose_number_matches_neither_outcome_is_a_mismatch() -> None:
    m = _m("Over 2.5", "Under 2.5")
    assert verdict(_row("one", selection_line="under", points=3.5, line=3.5, market_type="game_total"), m) == "MISMATCH"


def test_spread_agrees_and_flips_on_the_signed_points() -> None:
    m = _m("Galatasaray SK +1.5")       # outcome one GS +1.5, outcome two BAR -1.5
    gs = {"selection": "Galatasaray Spor Kulübü", "points": 1.5, "line": 1.5}
    assert verdict(_row("two", **gs), m) == "AGREE"
    assert verdict(_row("one", **gs), m) == "FLIP"          # |one prices Barcelona -1.5


def test_moneyline_draw_and_team() -> None:
    tie = _m("Tie", "Not tie")
    bar = _m("Barcelona FC", "Not Barcelona FC")
    assert verdict(_row("two", selection="Draw", market_type="moneyline_3way"), tie) == "AGREE"
    assert verdict(_row("two", selection="FC Barcelona", market_type="moneyline_3way"), bar) == "AGREE"


def test_a_row_on_the_not_x_side_is_a_finding() -> None:
    bar = _m("Barcelona FC", "Not Barcelona FC")
    assert verdict(_row("one", selection="FC Barcelona", market_type="moneyline_3way"), bar) == "NOT_SIDE"


def test_two_way_moneyline_flip_by_name() -> None:
    m = _m("Tennessee Volunteers", "Alabama Crimson Tide")
    assert verdict(_row("two", selection="Tennessee", market_type="moneyline"), m) == "AGREE"
    assert verdict(_row("one", selection="Tennessee", market_type="moneyline"), m) == "FLIP"


def test_names_that_fit_neither_side_are_noise_not_an_alert() -> None:
    m = _m("Tennessee Volunteers", "Alabama Crimson Tide")
    assert verdict(_row("two", selection="Vols", market_type="moneyline"), m) == "name_noise"


def test_an_unlisted_hash_is_unverified() -> None:
    assert verdict(_row("one", selection_line="under", points=2.5), None) == "UNVERIFIED"


def test_row_from_refuses_ids_that_are_not_hash_and_side() -> None:
    good = {"market_hash": "0xH", "selection_id": "0xh|two", "points": 1.5}
    assert sc.row_from(good) is not None and sc.row_from(good).suffix == "two"  # type: ignore[union-attr]
    assert sc.row_from({"market_hash": "0xh", "selection_id": "0xother|two"}) is None
    assert sc.row_from({"market_hash": "0xh", "selection_id": "0xh"}) is None


def test_find_markets_batches_30_and_caps_calls() -> None:
    calls: list[list[str]] = []

    def get(batch: list[str]) -> list[dict]:
        calls.append(batch)
        return [{"marketHash": h.upper()} for h in batch]

    out = sc.find_markets([f"0x{i:03d}" for i in range(95)], get, max_calls=3)
    assert [len(c) for c in calls] == [30, 30, 30]
    assert len(out) == 90 and "0x000" in out


def test_read_catalogue_keys_by_lowercase_hash(tmp_path: Path) -> None:
    (tmp_path / "sxbet_markets.jsonl").write_text(json.dumps({"marketHash": "0xAB"}) + "\nnot json\n")
    assert set(sc.read_catalogue(tmp_path)) == {"0xab"}
    assert sc.read_catalogue(None) == {}


def test_report_alerts_on_a_flip_and_lists_it() -> None:
    m = {"0xh": _m("Over 2.5", "Under 2.5")}
    rows = [_row("two", selection_line="under", points=2.5, line=2.5, market_type="game_total")]
    counts, bad = sc.judge(rows, m)
    lines = sc.report_lines(rows, counts, bad, m, expect_rows=True)
    assert lines[0].startswith("sxbet side check: 1 rows")
    assert lines[1].startswith("ALERT: SX Bet side check: 1 live mapping row(s)") and "FLIP" in lines[1]


def test_report_is_quiet_when_clean_and_alerts_when_blind() -> None:
    m = {"0xh": _m("Over 2.5", "Under 2.5")}
    rows = [_row("one", selection_line="under", points=2.5, line=2.5, market_type="game_total")]
    counts, bad = sc.judge(rows, m)
    assert len(sc.report_lines(rows, counts, bad, m, expect_rows=True)) == 1
    counts, bad = sc.judge(rows, {})
    assert "BLIND" in sc.report_lines(rows, counts, bad, {}, expect_rows=True)[-1]
    assert len(sc.report_lines(rows, counts, bad, {}, expect_rows=False)) == 1


@pytest.mark.parametrize("needle", [
    "start_date between timestamp_sub(current_timestamp(), interval 3 hour)",
    "and timestamp_add(current_timestamp(), interval 3 day)",
    "sportsbook = 'SX Bet'",
    "qualify row_number() over",
])
def test_sql_is_partition_filtered_and_newest_per_side(needle: str) -> None:
    assert needle in sc.SQL
    assert sc.MAX_BYTES_BILLED <= 2 * 1024**3

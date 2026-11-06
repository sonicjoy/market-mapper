"""DKEX NHL: the game winner (incl. OT and shootout) and the puck line from 1.5.

Catalogue rows are real staging markets in
``tests/fixtures/dkex/staging_nhl_2026-09-29.json`` (BUF Sabres @ CBJ
Blue Jackets, with each market's rules text) run through
``fetch.dkex.normalize``; the Optic side is a minimal stand-in with the
names and start Optic listed on 2026-09-29.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fetch.dkex import normalize
from mappers.exchanges.dkex import DkexConfig
from mappers.exchanges.dkex_catalogue_read import DkexTally
from mappers.exchanges.dkex_pass import run_pass
from mappers.market_types import MarketType
from mappers.profiles.registry import profile_registered
from mappers.sport import Sport
from mappers.vocab import dkex_markets as vocab

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_nhl_2026-09-29.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))
NHL = DkexConfig(
    league="NHL", market_types=vocab.HOCKEY, ignored_markets=vocab.HOCKEY_IGNORED,
    min_strikes=vocab.HOCKEY_MIN_STRIKES,
)
BUF_CBJ = SimpleNamespace(fixture=SimpleNamespace(
    start_date="2026-10-01T23:00:00Z", home="CBJ", away="BUF",
    home_name="Columbus Blue Jackets", away_name="Buffalo Sabres", odds=[],
))


def _puck_line(strike: float) -> dict:
    """BUF "wins by >= strike": the staging BUF WIN row re-typed as MOVY/FG."""
    win = next(r for r in RAW if r["ticker"] == "NHL-WIN-FG-00O3K51DQT31ALG-BUES012")
    raw = json.loads(json.dumps(win))
    raw["ticker"] = f"NHL-MOVY-FG-00O3K51DQT31ALG-BUES012-GTE-P{int(strike * 10):05d}"
    raw["parameters"].update(
        statAchievement="MOVY", timePeriod="FG", strikePrice=strike, outcomeType="GTE",
    )
    return raw


def _first_period(market: str, strike: float, *, team: bool) -> dict:
    """A 1st-period total (TGLS) or BUF team total (TMGLS) from the BUF WIN row."""
    win = next(r for r in RAW if r["ticker"] == "NHL-WIN-FG-00O3K51DQT31ALG-BUES012")
    raw = json.loads(json.dumps(win))
    raw["ticker"] = f"NHL-{market}-PR1-00O3K51DQT31ALG-GTE-P{int(strike * 10):05d}"
    raw["parameters"].update(
        statAchievement=market, timePeriod="PR1", strikePrice=strike, outcomeType="GTE",
    )
    if not team:
        del raw["parameters"]["participant"]
        raw["metadata"]["participants"] = []
    return raw


def _run(tmp_path: Path, extra: list[dict] | None = None) -> tuple[DkexTally, list]:
    (tmp_path / "dkex_markets.jsonl").write_text(
        "".join(json.dumps(normalize(r, "api")) + "\n" for r in [*RAW, *(extra or [])]),
        encoding="utf-8",
    )
    stamped: list = []

    def attach(_index, _alt, _all, dr) -> str:
        stamped.append(dr)
        return "stamped"

    tally = run_pass("nhl", NHL, [BUF_CBJ], {}, [], tmp_path, attach)
    return tally, stamped


def test_the_winner_market_includes_overtime_and_the_shootout() -> None:
    """The mapping rests on this rules text; if DKEX changes it, stop mapping."""
    rules = {r["ticker"]: r["rules"]["description"] for r in RAW}
    assert "including any overtime and shootout" in rules["NHL-WIN-FG-00O3K51DQT31ALG-BUES012"]
    assert "Overtime and the shootout are excluded" in rules["NHL-DWIN-GNO-00O3K51DQT31ALG-BUES012"]


def test_hockey_profile_registered() -> None:
    assert profile_registered("dkex_generic_v1", Sport.HOCKEY)


def test_win_fg_is_the_moneyline_and_the_regulation_three_way_is_its_own_type() -> None:
    assert vocab.HOCKEY[("WIN", "FG")] is MarketType.MONEYLINE
    assert vocab.HOCKEY[("DWIN", "GNO")] is MarketType.MONEYLINE_3WAY


def test_puck_line_from_1_5_stamps_both_sides(tmp_path: Path) -> None:
    """Yes is BUF -1.5, No is CBJ +1.5 (Optic puck_line)."""
    _, rows = _run(tmp_path, [_puck_line(1.5)])
    movy = {(r.dkex_side, r.market_type, r.side, r.line) for r in rows if "MOVY" in r.dkex_symbol}
    assert movy == {
        ("yes", "point_spread", "BUF", -1.5),
        ("no", "point_spread", "CBJ", 1.5),
    }


def test_puck_line_below_1_5_is_not_mapped(tmp_path: Path) -> None:
    """At 0.5 overtime would decide the contract, and DKEX's OT rule is unread."""
    _, rows = _run(tmp_path, [_puck_line(0.5)])
    assert not any("MOVY" in r.dkex_symbol for r in rows)


def test_each_team_leg_stamps_both_moneyline_sides(tmp_path: Path) -> None:
    tally, rows = _run(tmp_path)
    assert tally.matched_events == 1
    names = {r["ticker"]: r["metadata"]["participants"][0]["name"]
             for r in RAW if r["metadata"].get("participants")}
    got = {(names[r.dkex_symbol], r.dkex_side, r.market_type, r.side)
           for r in rows if r.market_type == "moneyline"}
    assert got == {
        ("BUF Sabres", "yes", "moneyline", "BUF"), ("BUF Sabres", "no", "moneyline", "CBJ"),
        ("CBJ Blue Jackets", "yes", "moneyline", "CBJ"), ("CBJ Blue Jackets", "no", "moneyline", "BUF"),
    }


def test_regulation_three_way_stamps_each_outcome_and_its_double_chance(tmp_path: Path) -> None:
    """Yes on a team (or the Tie) is that outcome; No is the other two together."""
    _, rows = _run(tmp_path)
    got = {(r.dkex_symbol.rsplit("-", 1)[-1], r.dkex_side, r.market_type, r.side)
           for r in rows if "DWIN" in r.dkex_symbol}
    assert got == {
        ("BUES012", "yes", "moneyline_3way", "BUF"), ("BUES012", "no", "double_chance", "CBJ/_TIE"),
        ("CBTS000", "yes", "moneyline_3way", "CBJ"), ("CBTS000", "no", "double_chance", "BUF/_TIE"),
        ("DRAW", "yes", "moneyline_3way", "_TIE"), ("DRAW", "no", "double_chance", "CBJ/BUF"),
    }


def test_first_period_total_stamps_over_and_under(tmp_path: Path) -> None:
    """Yes is over 1.5 goals in the 1st period, No is under."""
    _, rows = _run(tmp_path, [_first_period("TGLS", 1.5, team=False)])
    got = {(r.dkex_side, r.market_type, r.entity, r.side, r.line)
           for r in rows if "TGLS" in r.dkex_symbol}
    assert got == {
        ("yes", "p1_total", None, "over", 1.5),
        ("no", "p1_total", None, "under", 1.5),
    }


def test_first_period_team_total_keeps_the_team(tmp_path: Path) -> None:
    _, rows = _run(tmp_path, [_first_period("TMGLS", 0.5, team=True)])
    got = {(r.dkex_side, r.market_type, r.entity, r.side, r.line)
           for r in rows if "TMGLS" in r.dkex_symbol}
    assert got == {
        ("yes", "p1_team_total", "BUF", "over", 0.5),
        ("no", "p1_team_total", "BUF", "under", 0.5),
    }


def test_full_game_totals_ride_the_shared_total_goals_convention() -> None:
    assert vocab.HOCKEY[("TGLS", "FG")] is MarketType.GAME_TOTAL
    assert vocab.HOCKEY[("TMGLS", "FG")] is MarketType.TEAM_TOTAL


def test_every_skater_prop_token_has_a_canonical_type() -> None:
    props = {
        "PSOG": MarketType.PLAYER_SHOTS_ON_GOAL, "PSOGOU": MarketType.PLAYER_SHOTS_ON_GOAL,
        "PPTS": MarketType.PLAYER_POINTS, "PPTSOU": MarketType.PLAYER_POINTS,
        "PGLS": MarketType.PLAYER_GOALS, "SGL1": MarketType.PLAYER_GOALS,
        "PAST": MarketType.PLAYER_ASSISTS, "PPPTS": MarketType.PLAYER_POWER_PLAY_POINTS,
        "GSVS": MarketType.PLAYER_SAVES, "GSVSOU": MarketType.PLAYER_SAVES,
        "SFGL": MarketType.FIRST_GOAL_SCORER,
    }
    for token, mt in props.items():
        assert vocab.HOCKEY[(token, "FG")] is mt


def test_second_and_third_period_totals_are_mapped() -> None:
    assert vocab.HOCKEY[("TGLS", "PR2")] is MarketType.SECOND_PERIOD_TOTAL
    assert vocab.HOCKEY[("TGLS", "PR3")] is MarketType.THIRD_PERIOD_TOTAL
    assert vocab.HOCKEY[("TMGLS", "PR2")] is MarketType.SECOND_PERIOD_TEAM_TOTAL
    assert vocab.HOCKEY[("TMGLS", "PR3")] is MarketType.THIRD_PERIOD_TEAM_TOTAL

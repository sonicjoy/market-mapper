"""Underdog NBA series listed 2026-10-19: PRA, steals, blocks, double / triple double, team points.

UDXNBAOVERTIME is listed too and stays unmapped (see the last test).

Live catalogue + Optic odds for BOS @ DET (2026-10-20). Each contract is run through
``run_pass`` and stamped with the pipeline's own ``attach_underdog_row`` onto the rows
``optic.build_rows`` builds from the captured odds, so a stamp means the venue key and
the Optic key are the same.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import mappers.pipeline as pipeline
from mappers.exchanges import optic
from mappers.exchanges.underdog import UnderdogConfig, _sentence_confirms
from mappers.exchanges.underdog_pass import run_pass
from mappers.market_types import MarketType
from mappers.sport import Sport
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.underdog_markets import market_types_for_sport, player_id_markets_for_sport

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_nba_new_markets_2026-10-20.json"
_EVENT = json.loads(_FIXTURE.read_text(encoding="utf-8"))["events"][0]


def _stamp() -> tuple[dict[str, list[tuple]], dict[str, str]]:
    """{ticker: [(market_type, entity, line, side, udx_side)]}, {ticker: attach outcome}."""
    home, away = _EVENT["home_competitors"][0], _EVENT["away_competitors"][0]
    fx = optic.Fixture(
        fixture_id=_EVENT["fixture_id"], game_id="G", sportradar_id=None, start_et="2026-10-20T15:00:00",
        start_date=_EVENT["start_date"], home="DET", away="BOS", home_name=home["name"], away_name=away["name"],
        team_map={home["id"]: "DET", away["id"]: "BOS"},
        odds=[optic.Odd(**o) for o in _EVENT["odds"]], is_live=False,
    )
    cfg = optic.OpticConfig(league_id="nba", table_types=dict(BASKETBALL_OPTIC_TABLE_TYPES))
    rows, _, _ = optic.build_rows(_EVENT["start_date"], "DET", "BOS", fx, cfg, league="nba")
    row_index = {pipeline.row_key(r): r for r in rows}
    outcomes: dict[str, str] = {}

    def attach(index, alt, all_rows, item) -> str:
        outcome = pipeline.attach_underdog_row(index, alt, all_rows, item)
        outcomes.setdefault(item.underdog_ticker, outcome)
        return outcome

    ucfg = UnderdogConfig(league="NBA", market_types=market_types_for_sport(Sport.BASKETBALL),
                          player_id_markets=player_id_markets_for_sport(Sport.BASKETBALL))
    run_pass(_EVENT["rows"], ucfg, [SimpleNamespace(fixture=fx)], league="nba", attach=attach,
             row_index=row_index, all_rows=list(rows))
    stamped: dict[str, list[tuple]] = {}
    for r in rows:
        if r.underdog_ticker:
            stamped.setdefault(r.underdog_ticker, []).append(
                (r.market_type, r.entity, r.line, r.side, r.underdog_side))
    return stamped, outcomes


def test_every_contract_optic_quotes_stamps_its_optic_row() -> None:
    stamped, _ = _stamp()
    expected = {
        "UDXNBAPRA_26102015000C07D14CC5DC_14.5": ("player_pts_reb_ast", "paul_george", 14.5),
        "UDXNBAPRA_26102015000C07D14CC5DC_19.5": ("player_pts_reb_ast", "paul_george", 19.5),
        "UDXNBASTEALS_26102015000C07D14CC5DC_0.5": ("player_steals", "paul_george", 0.5),
        "UDXNBABLOCKS_261020150016C71BA69D30_0.5": ("player_blocks", "mitchell_robinson", 0.5),
    }
    for ticker, (mt, entity, line) in expected.items():
        assert (mt, entity, line, "over", "yes") in stamped[ticker], ticker
    for ticker in ("UDXNBADBLDBL_BOSDET26OCT201500AUSARTHOMPSO_0.5",
                   "UDXNBATRIPDBL_BOSDET26OCT201500AUSARTHOMPSO_0.5"):
        mt = "player_double_double" if "DBLDBL" in ticker else "player_triple_double"
        assert (mt, "ausar_thompson", None, "yes", "yes") in stamped[ticker]


def test_team_points_name_the_team_and_both_sides() -> None:
    stamped, _ = _stamp()
    for ticker, team in (("UDXNBATEAMPOINTS_BOSDET26OCT201500_DETOVER100.5", "DET"),
                         ("UDXNBATEAMPOINTS_BOSDET26OCT201500_BOSOVER100.5", "BOS")):
        assert sorted(stamped[ticker]) == [
            ("team_total", team, 100.5, "over", "yes"),
            ("team_total", team, 100.5, "under", "no"),
        ]


def test_a_line_optic_does_not_quote_stamps_nothing() -> None:
    stamped, outcomes = _stamp()
    ticker = "UDXNBAPRA_2610201500547F0B60B699_11.5"
    assert ticker not in stamped
    assert outcomes[ticker] == "dropped_no_optic"


def test_nba_overtime_jump_ball_contract_stays_unmapped() -> None:
    """NBAENTITYOUTCOME does not say how "jump balls during overtime only" settles with no overtime."""
    stamped, outcomes = _stamp()
    (row,) = [r for r in _EVENT["rows"] if r["ticker"].startswith("UDXNBAOVERTIME_")]
    assert row["ticker"] not in stamped and row["ticker"] not in outcomes
    assert "will_there_be_overtime" not in market_types_for_sport(Sport.BASKETBALL)
    assert not _sentence_confirms(MarketType.WILL_THERE_BE_OVERTIME, row["description"])

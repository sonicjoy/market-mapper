"""Underdog UDXNBATEAMTOTAL1H onto Optic's ``1st_half_team_total``.

Live catalogue + Optic odds for LAL @ LAC (2026-10-29, pre-game). Each contract is run
through ``run_pass`` and stamped with the pipeline's own ``attach_underdog_row`` onto the
rows ``optic.build_rows`` builds from the captured odds, so a stamp means the venue key and
the Optic key are the same.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import mappers.pipeline as pipeline
from mappers.exchanges import optic
from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import run_pass
from mappers.market_types import MarketType
from mappers.sport import Sport
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.underdog_markets import market_types_for_sport, player_id_markets_for_sport

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_nba_1h_team_total_2026-10-29.json"
_EVENT = json.loads(_FIXTURE.read_text(encoding="utf-8"))["events"][0]


def _stamp(odds: list[dict] | None = None) -> tuple[dict[str, list[tuple]], dict[str, str]]:
    """{ticker: [(market_type, entity, line, side, udx_side)]}, {ticker: attach outcome}."""
    home, away = _EVENT["home_competitors"][0], _EVENT["away_competitors"][0]
    fx = optic.Fixture(
        fixture_id=_EVENT["fixture_id"], game_id="G", sportradar_id=None, start_et="2026-10-28T22:30:00",
        start_date=_EVENT["start_date"], home="LAC", away="LAL", home_name=home["name"], away_name=away["name"],
        team_map={home["id"]: "LAC", away["id"]: "LAL"},
        odds=[optic.Odd(**o) for o in (_EVENT["odds"] if odds is None else odds)], is_live=False,
    )
    cfg = optic.OpticConfig(league_id="nba", table_types=dict(BASKETBALL_OPTIC_TABLE_TYPES))
    rows, _, _ = optic.build_rows(_EVENT["start_date"], "LAC", "LAL", fx, cfg, league="nba")
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


def test_vocab_maps_the_optic_id() -> None:
    assert market_types_for_sport(Sport.BASKETBALL)["1st_half_team_total"] is MarketType.FIRST_HALF_TEAM_TOTAL


def test_every_contract_stamps_the_named_teams_over_and_under() -> None:
    stamped, _ = _stamp()
    assert len(stamped) == len(_EVENT["rows"]) == 22
    for row in _EVENT["rows"]:
        team = "LAC" if "Clippers records above" in row["description"] else "LAL"
        line = float(row["strike"]["value"])
        assert sorted(stamped[row["ticker"]]) == [
            ("1h_team_total", team, line, "over", "yes"),
            ("1h_team_total", team, line, "under", "no"),
        ], row["ticker"]


def test_a_line_optic_does_not_quote_stamps_nothing() -> None:
    ticker = "UDXNBATEAMTOTAL1H_LALLAC26OCT28_LACOVER47.5"
    odds = [o for o in _EVENT["odds"] if not (o["normalized_selection"] == "los_angeles_clippers"
                                              and o["points"] == 47.5)]
    stamped, outcomes = _stamp(odds)
    assert ticker not in stamped
    assert outcomes[ticker] == "dropped_no_optic"

"""Underdog NBA race to 10/20/30 points and winning margin, listed 2026-10-23.

Live catalogue + Optic odds for ATL @ CHA (2026-10-23): BetMGM race 10/20, Superbet
race 30, Fanatics winning margin. Each contract is run through ``run_pass`` and stamped
with the pipeline's own ``attach_underdog_row`` onto the rows ``optic.build_rows``
builds from the captured odds, so a stamp means the venue key and the Optic key agree.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import mappers.pipeline as pipeline
from mappers.exchanges import optic
from mappers.exchanges.underdog import UnderdogConfig, needs_team
from mappers.exchanges.underdog_pass import run_pass
from mappers.market_types import MarketType
from mappers.sport import Sport
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.underdog_markets import market_types_for_sport, player_id_markets_for_sport

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_nba_race_margin_2026-10-23.json"
_EVENT = json.loads(_FIXTURE.read_text(encoding="utf-8"))["events"][0]


def _fixture() -> optic.Fixture:
    home, away = _EVENT["home_competitors"][0], _EVENT["away_competitors"][0]
    return optic.Fixture(
        fixture_id=_EVENT["fixture_id"], game_id="G", sportradar_id=None, start_et="2026-10-23T19:00:00",
        start_date=_EVENT["start_date"], home="CHA", away="ATL", home_name=home["name"], away_name=away["name"],
        team_map={home["id"]: "CHA", away["id"]: "ATL"},
        odds=[optic.Odd(**o) for o in _EVENT["odds"]], is_live=False,
    )


def _optic_rows() -> list:
    cfg = optic.OpticConfig(league_id="nba", table_types=dict(BASKETBALL_OPTIC_TABLE_TYPES))
    rows, _, _ = optic.build_rows(_EVENT["start_date"], "CHA", "ATL", _fixture(), cfg, league="nba")
    return rows


def _stamp(catalogue: list[dict] | None = None) -> tuple[dict[str, set[tuple]], dict[str, int]]:
    """{ticker: {(market_type, entity, line, side, grouping_key, udx_side)}}, run_pass tally."""
    rows = _optic_rows()
    all_rows = list(rows)
    row_index = {pipeline.row_key(r): r for r in rows}
    ucfg = UnderdogConfig(league="NBA", market_types=market_types_for_sport(Sport.BASKETBALL),
                          player_id_markets=player_id_markets_for_sport(Sport.BASKETBALL))
    tally = run_pass(catalogue if catalogue is not None else _EVENT["rows"], ucfg,
                     [SimpleNamespace(fixture=_fixture())], league="nba",
                     attach=pipeline.attach_underdog_row, row_index=row_index, all_rows=all_rows)
    stamped: dict[str, set[tuple]] = {}
    for r in all_rows:
        if r.underdog_ticker:
            stamped.setdefault(r.underdog_ticker, set()).add(
                (r.market_type, r.entity, r.line, r.side, r.grouping_key, r.underdog_side))
    return stamped, tally


def test_optic_winning_margin_keys_each_team_band() -> None:
    keys = {(r.entity, r.grouping_key, r.side) for r in _optic_rows() if r.market_type == "winning_margin"}
    for team in ("ATL", "CHA"):
        for band in ("1_to_5", "6_to_10", "11_to_20", "21_or_more", "11_to_15", "26_or_more"):
            assert (team, band, "yes") in keys


def test_every_race_contract_stamps_both_sides() -> None:
    stamped, tally = _stamp()
    for n in (10, 20):
        line = float(n)
        assert stamped[f"UDXNBARACE{n}_ATLCHA26OCT23_ATL"] == {
            ("race_to_points", None, line, "ATL", None, "yes"),
            ("race_to_points", None, line, "CHA", None, "no"),
        }
        assert stamped[f"UDXNBARACE{n}_ATLCHA26OCT23_CHA"] == {
            ("race_to_points", None, line, "CHA", None, "yes"),
            ("race_to_points", None, line, "ATL", None, "no"),
        }
    # Race 30 has no Optic table entry until OPTIC_NBA_RACE_TO_30 is wired: unmapped.
    assert not any(t.startswith("UDXNBARACE30") for t in stamped)
    assert tally["no_side"] == 0 and tally["dropped"] == 0


def test_every_margin_band_stamps_its_team_band_yes_only() -> None:
    stamped, _ = _stamp()
    bands = {"1TO5": "1_to_5", "6TO10": "6_to_10", "11TO20": "11_to_20", "21PLUS": "21_or_more"}
    for team in ("ATL", "CHA"):
        for suffix, band in bands.items():
            assert stamped[f"UDXNBAMOV_ATLCHA26OCT23_{team}{suffix}"] == {
                ("winning_margin", team, None, "yes", band, "yes"),
            }


def test_race_sentence_target_must_be_the_optic_ids() -> None:
    (row,) = [copy.deepcopy(r) for r in _EVENT["rows"] if r["ticker"] == "UDXNBARACE10_ATLCHA26OCT23_ATL"]
    row["external_ids"]["optic_odds"]["market_id"] = "race_to_20_points"
    stamped, tally = _stamp([row])
    assert not stamped and tally["dropped"] == 1


def test_margin_team_id_naming_the_other_side_is_rejected() -> None:
    (row,) = [copy.deepcopy(r) for r in _EVENT["rows"] if r["ticker"] == "UDXNBAMOV_ATLCHA26OCT23_ATL1TO5"]
    away = _EVENT["away_competitors"][0]["id"]
    home = _EVENT["home_competitors"][0]["id"]
    assert row["external_ids"]["optic_odds"]["team_id"] == away
    row["external_ids"]["optic_odds"]["team_id"] = home
    stamped, tally = _stamp([row])
    assert not stamped and tally["optic_team"] == 1


def test_margin_needs_a_team_and_fight_props_still_do_not() -> None:
    assert needs_team(MarketType.WINNING_MARGIN)
    assert not needs_team(MarketType.METHOD_OF_VICTORY)

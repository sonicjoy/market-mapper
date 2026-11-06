"""Underdog UDXNHLFGS onto Optic's ``first_goal_scorer``.

Live catalogue + Optic odds for TOR @ SEA (2026-10-29, pre-game). Each contract is run
through ``run_pass`` and stamped with the pipeline's own ``attach_underdog_row`` onto the
rows ``optic.build_rows`` builds from the captured odds. Optic lists one selection per
player and no NO side, so only a contract's YES stamps.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import mappers.pipeline as pipeline
from mappers.exchanges import optic
from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import run_pass
from mappers.shared import normalize_player_name
from mappers.sport import Sport
from mappers.vocab.hockey_markets import HOCKEY_OPTIC_TABLE_TYPES
from mappers.vocab.underdog_markets import market_types_for_sport, player_id_markets_for_sport

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "underdog"
_FIXTURE = _FIXTURES / "underdog_nhl_first_goalscorer_2026-10-29.json"
_EVENT = json.loads(_FIXTURE.read_text(encoding="utf-8"))["events"][0]


def _stamp(rows: list[dict] | None = None):
    """{ticker: [(market_type, entity, line, side, udx_side)]}, {(ticker, udx_side): outcome}, tally."""
    home, away = _EVENT["home_competitors"][0], _EVENT["away_competitors"][0]
    fx = optic.Fixture(
        fixture_id=_EVENT["fixture_id"], game_id="G", sportradar_id=None, start_et="2026-10-28T22:00:00",
        start_date=_EVENT["start_date"], home="SEA", away="TOR", home_name=home["name"], away_name=away["name"],
        team_map={home["id"]: "SEA", away["id"]: "TOR"},
        odds=[optic.Odd(**o) for o in _EVENT["odds"]], is_live=False,
    )
    cfg = optic.OpticConfig(league_id="nhl", table_types=dict(HOCKEY_OPTIC_TABLE_TYPES))
    optic_rows, _, _ = optic.build_rows(_EVENT["start_date"], "SEA", "TOR", fx, cfg, league="nhl")
    row_index = {pipeline.row_key(r): r for r in optic_rows}
    outcomes: dict[tuple[str, str], str] = {}

    def attach(index, alt, all_rows, item) -> str:
        outcome = pipeline.attach_underdog_row(index, alt, all_rows, item)
        outcomes.setdefault((item.underdog_ticker, item.underdog_side), outcome)
        return outcome

    ucfg = UnderdogConfig(league="NHL", market_types=market_types_for_sport(Sport.HOCKEY),
                          player_id_markets=player_id_markets_for_sport(Sport.HOCKEY))
    tally = run_pass(_EVENT["rows"] if rows is None else rows, ucfg, [SimpleNamespace(fixture=fx)], league="nhl",
                     attach=attach, row_index=row_index, all_rows=list(optic_rows))
    stamped: dict[str, list[tuple]] = {}
    for r in optic_rows:
        if r.underdog_ticker:
            stamped.setdefault(r.underdog_ticker, []).append(
                (r.market_type, r.entity, r.line, r.side, r.underdog_side))
    return stamped, outcomes, tally


def _optic_name(player_id: str) -> str:
    (name,) = {o["selection"] for o in _EVENT["odds"] if o["player_id"] == player_id}
    return name


def test_every_contract_stamps_yes_on_the_venue_player() -> None:
    stamped, outcomes, tally = _stamp()
    assert tally["unconfirmed"] == tally["optic_player"] == 0
    assert len(stamped) == len(_EVENT["rows"]) == 35
    for row in _EVENT["rows"]:
        player = normalize_player_name(_optic_name(row["external_ids"]["optic_odds"]["player_id"]))
        assert stamped[row["ticker"]] == [("first_goal_scorer", player, None, "yes", "yes")], row["ticker"]
        assert outcomes[(row["ticker"], "no")] == "dropped_no_optic"


def test_a_player_id_naming_someone_else_maps_nothing() -> None:
    row = copy.deepcopy(_EVENT["rows"][0])
    other = next(o["player_id"] for o in _EVENT["odds"]
                 if o["player_id"] != row["external_ids"]["optic_odds"]["player_id"])
    row["external_ids"]["optic_odds"]["player_id"] = other
    stamped, _, tally = _stamp([row])
    assert stamped == {}
    assert tally["optic_player"] == 1


def test_a_sentence_that_counts_the_shootout_maps_nothing() -> None:
    row = copy.deepcopy(_EVENT["rows"][0])
    row["description"] = row["description"].replace(" but excluding the shootout", " and the shootout")
    stamped, _, tally = _stamp([row])
    assert stamped == {}
    assert tally["unconfirmed"] == 1

"""Underdog NFL TD ladder, combined-yards and kicking props (live WSH @ SF, 2026-10-19): whole sentence AND the venue's
player id. Underdog confirmed passing touchdowns do not count, so quarterbacks map on the ladder like everyone else."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import is_blocked, run_pass
from mappers.exchanges.underdog_player_props import CONTRACTS
from mappers.market_types import MarketType
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.shared import CanonicalRow, normalize_player_name
from mappers.sport import Sport
from mappers.vocab.underdog_markets import (
    PLAYER_ID_MARKETS_BY_SPORT,
    market_types_for_sport,
    player_id_markets_for_sport,
)
from tests.mappers.test_tip_leagues import _row

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_nfl_props_2026-10-19.json"
_EVENT = json.loads(_FIXTURE.read_text(encoding="utf-8"))["events"][0]
_NEW = {
    "player_touchdowns": MarketType.PLAYER_TOUCHDOWNS,
    "player_passing_+_rushing_yards": MarketType.PLAYER_PASSING_RUSHING_YARDS,
    "player_rushing_+_receiving_yards": MarketType.PLAYER_RUSHING_RECEIVING_YARDS,
    "player_kicking_points": MarketType.PLAYER_KICKING_POINTS,
}


def _ids(row: dict) -> dict:
    return row["external_ids"]["optic_odds"]


def _props(rows: list[dict] | None = None) -> list[dict]:
    return [r for r in (rows or _EVENT["rows"]) if _ids(r)["market_id"] in _NEW]


def _entry(odds: list[dict] | None = None) -> SimpleNamespace:
    home, away = _EVENT["home_competitors"][0], _EVENT["away_competitors"][0]
    return SimpleNamespace(
        fixture=SimpleNamespace(
            fixture_id=_EVENT["fixture_id"],
            home="HOM",
            away="AWY",
            home_name=home["name"],
            away_name=away["name"],
            start_date=_EVENT["start_date"],
            team_map={home["id"]: "HOM", away["id"]: "AWY"},
            odds=[SimpleNamespace(**o) for o in (_EVENT["odds"] if odds is None else odds)],
        )
    )


def _run(rows: list[dict], entry: SimpleNamespace | None = None):
    stamped: list[CanonicalRow] = []
    alerts: list[str] = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(
        league="NFL",
        market_types=market_types_for_sport(Sport.FOOTBALL),
        player_id_markets=player_id_markets_for_sport(Sport.FOOTBALL),
    )
    tally = run_pass(
        rows,
        cfg,
        [entry or _entry()],
        league="nfl",
        attach=attach,
        row_index={},
        all_rows=[],
        witness_reject_alerts=alerts,
    )
    return tally, stamped, alerts


def _passer_ids() -> set[str]:
    """Players with a passing market on Optic or the venue: the quarterbacks."""
    passing = {"player_passing_touchdowns", "player_passing_yards"}
    optic = {o["player_id"] for o in _EVENT["odds"] if o["market_id"] in passing}
    return optic | {_ids(r)["player_id"] for r in _EVENT["rows"] if _ids(r)["market_id"] in passing}


def _optic_name(player_id: str, market_id: str) -> str:
    names = {o["selection"] for o in _EVENT["odds"] if o["player_id"] == player_id and o["market_id"] == market_id}
    assert len(names) == 1
    return names.pop()


def test_football_needs_the_player_id_on_the_four_new_markets() -> None:
    run = resolve_run_leagues({}, [_row("nfl", sport="football", optic="nfl")])
    cfg = run["nfl"].UNDERDOG
    assert cfg is not None
    assert cfg.player_id_markets == frozenset(_NEW)
    assert {m: cfg.market_types[m] for m in _NEW} == _NEW
    assert "player_extra_points_made" not in cfg.market_types


def test_every_strict_market_has_a_contract_sentence() -> None:
    """A market listed for the player-id rule without a sentence would map nothing, silently."""
    for markets in PLAYER_ID_MARKETS_BY_SPORT.values():
        assert markets <= set(CONTRACTS)


def test_every_live_prop_stamps_over_and_under_on_the_venue_player() -> None:
    rows = _props()
    tally, stamped, alerts = _run(rows)
    assert tally["unconfirmed"] == tally["optic_player"] == 0 and alerts == []
    by_ticker: dict[str, dict[str, CanonicalRow]] = {}
    for item in stamped:
        by_ticker.setdefault(str(item.underdog_ticker), {})[str(item.underdog_side)] = item
    assert set(by_ticker) == {r["ticker"] for r in rows}
    for row in rows:
        ids = _ids(row)
        yes, no = by_ticker[row["ticker"]]["yes"], by_ticker[row["ticker"]]["no"]
        assert (yes.side, no.side) == ("over", "under")
        assert yes.entity == no.entity == normalize_player_name(_optic_name(ids["player_id"], ids["market_id"]))
        assert yes.line == no.line == float(row["ticker"].rsplit("_", 1)[1])
        assert yes.market_type == _NEW[ids["market_id"]].value


def test_quarterbacks_map_on_the_td_ladder() -> None:
    """Underdog (2026-10-19): a quarterback's passing touchdowns do not count, so his ladder is scorer TDs."""
    qb_td = [
        r for r in _props() if _ids(r)["market_id"] == "player_touchdowns" and _ids(r)["player_id"] in _passer_ids()
    ]
    tally, stamped, _ = _run(qb_td)
    assert len(qb_td) > 0 and tally["unconfirmed"] == 0
    assert len(stamped) == 2 * len(qb_td)


def test_the_player_is_read_only_from_the_market_being_mapped() -> None:
    """Optic also labels these ids "<team> :: <player>" in team_first_touchdown_scorer: not a second name."""
    assert any(o["market_id"] == "team_first_touchdown_scorer" and "::" in o["selection"] for o in _EVENT["odds"])


def _first(market_id: str) -> dict:
    """The first live contract of ``market_id``."""
    return copy.deepcopy(next(r for r in _props() if _ids(r)["market_id"] == market_id))


def _text(market_id: str, old: str, new: str):
    def make() -> dict:
        row = _first(market_id)
        assert old in row["description"], (old, row["description"])
        row["description"] = row["description"].replace(old, new, 1)
        return row

    return make


def _swap_player() -> dict:
    row = _first("player_rushing_+_receiving_yards")
    pid = _ids(row)["player_id"]
    other = next(
        o["selection"]
        for o in _EVENT["odds"]
        if o["market_id"] == "player_rushing_+_receiving_yards" and o["player_id"] != pid
    )
    row["description"] = row["description"].replace(_optic_name(pid, "player_rushing_+_receiving_yards"), other, 1)
    return row


def _drop_player_id() -> dict:
    row = _first("player_kicking_points")
    _ids(row).pop("player_id")
    return row


_TAMPERED = {
    "TDs without overtime": (
        _text("player_touchdowns", "the full game (including overtime)", "the full duration"),
        "unconfirmed",
    ),
    "TDs as passing touchdowns": (
        _text("player_touchdowns", " touchdowns during", " passing touchdowns during"),
        "unconfirmed",
    ),
    "yards stat is not the market id's": (
        _text("player_rushing_+_receiving_yards", "rushing + receiving", "passing + rushing"),
        "unconfirmed",
    ),
    "integer line": (_text("player_kicking_points", ".5 kicking", " kicking"), "unconfirmed"),
    "another league": (
        _text("player_passing_+_rushing_yards", "National Football League", "NCAA Football"),
        "unconfirmed",
    ),
    "trailing clause": (_text("player_touchdowns", " ET on ", " ET (void if inactive) on "), "unconfirmed"),
    "no player id": (_drop_player_id, "unconfirmed"),
    "sentence names another player": (_swap_player, "optic_player"),
}


@pytest.mark.parametrize("case", sorted(_TAMPERED))
def test_a_contract_that_is_not_exactly_ours_maps_nothing(case: str) -> None:
    make, reason = _TAMPERED[case]
    tally, stamped, alerts = _run([make()])
    assert stamped == []
    assert tally[reason] == 1
    assert (len(alerts) == 1) == (reason == "optic_player")


def test_stamps_never_read_the_ticker() -> None:
    rows = _props()
    opaque = [dict(r, ticker=f"opaque-{i}") for i, r in enumerate(rows)]
    shape = lambda items: sorted((i.market_type, i.side, i.entity, i.line, i.underdog_side) for i in items)  # noqa: E731
    assert shape(_run(rows)[1]) == shape(_run(opaque)[1])


_GAME = "the Washington Commanders and the San Francisco 49ers originally scheduled for 8:15pm ET on October 19, 2026"
_LEVEL = "Resolves Yes if the National Football League game between " + _GAME + " is level at the end of the {}."


@pytest.mark.parametrize(
    "period",
    ["first quarter", "first half", "second quarter", "third quarter", "fourth quarter", "second half and overtime"],
)
def test_nfl_period_draws_map_as_the_period_draw(period: str) -> None:
    """The draw sentence reads like a game tie ("the game ... is level at the end of the third quarter"), but Underdog's
    NFLGAMEWIN filing settles every <time period> on that period's points: "only the points scored in <time period> are
    considered", and a Tie strike resolves Yes when "<time period> ends with both teams having an equal number of
    points". That is Optic's *_moneyline_3-way draw, so these map (checked 2026-10-19)."""
    assert not is_blocked({"ticker": "UDXNFLGAMEWIN3Q_WSHSF26OCT192015_DRAW", "description": _LEVEL.format(period)})

"""Underdog NHL skater props (live catalogue + Optic odds, 2026-10-15): whole sentence AND the venue's player id."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import run_pass
from mappers.market_types import MarketType
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.shared import CanonicalRow, normalize_player_name
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport, player_id_markets_for_sport
from tests.mappers.test_tip_leagues import _row

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "underdog" / "underdog_nhl_props_2026-10-15.json"
_EVENT = json.loads(_FIXTURE.read_text(encoding="utf-8"))["events"][0]
_PROPS = {"UDXNHLGOALS", "UDXNHLASSISTS", "UDXNHLPOINTS", "UDXNHLSHOTSONGOAL"}
_PROP_MARKETS = frozenset({"player_goals", "player_assists", "player_points", "player_shots_on_goal"})


def _family(row: dict) -> str:
    return row["ticker"].split("_", 1)[0]


def _ids(row: dict) -> dict:
    return row["external_ids"]["optic_odds"]


def _entry(odds: list[dict] | None = None) -> SimpleNamespace:
    """The captured Optic fixture: names, start, competitor ids, and its prop odds with Optic player ids."""
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


def _run(rows: list[dict], entry: SimpleNamespace | None = None, cfg: UnderdogConfig | None = None):
    stamped: list = []
    alerts: list[str] = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = cfg or UnderdogConfig(
        league="NHL",
        market_types=market_types_for_sport(Sport.HOCKEY),
        player_id_markets=player_id_markets_for_sport(Sport.HOCKEY),
    )
    tally = run_pass(
        rows,
        cfg,
        [entry or _entry()],
        league="nhl",
        attach=attach,
        row_index={},
        all_rows=[],
        witness_reject_alerts=alerts,
    )
    return tally, stamped, alerts


def _optic_name(player_id: str) -> str:
    names = {o["selection"] for o in _EVENT["odds"] if o["player_id"] == player_id}
    assert len(names) == 1
    return names.pop()


def _prop_rows() -> list[dict]:
    return [r for r in _EVENT["rows"] if _family(r) in _PROPS]


def _one_goals_row() -> dict:
    return copy.deepcopy(next(r for r in _EVENT["rows"] if _family(r) == "UDXNHLGOALS"))


def test_nhl_league_needs_the_player_id_on_the_skater_props_and_first_goal() -> None:
    run = resolve_run_leagues({}, [_row("nhl", sport="hockey", optic="nhl")])
    cfg = run["nhl"].UNDERDOG
    assert cfg is not None
    assert cfg.player_id_markets == _PROP_MARKETS | {"first_goal_scorer"}
    assert {m: cfg.market_types[m] for m in _PROP_MARKETS} == {
        "player_goals": MarketType.PLAYER_GOALS,
        "player_assists": MarketType.PLAYER_ASSISTS,
        "player_points": MarketType.PLAYER_POINTS,
        "player_shots_on_goal": MarketType.PLAYER_SHOTS_ON_GOAL,
    }
    assert cfg.market_types["first_goal_scorer"] is MarketType.FIRST_GOAL_SCORER
    assert "player_saves" not in cfg.market_types
    assert player_id_markets_for_sport(Sport.BASKETBALL) == frozenset()


def test_every_live_skater_prop_stamps_over_and_under_on_the_venue_player() -> None:
    rows = _prop_rows()
    tally, stamped, alerts = _run(rows)
    assert tally["unconfirmed"] == tally["optic_player"] == 0
    assert alerts == []
    by_ticker: dict[str, dict[str, CanonicalRow]] = {}
    for item in stamped:
        by_ticker.setdefault(item.underdog_ticker, {})[item.underdog_side] = item
    assert set(by_ticker) == {r["ticker"] for r in rows}
    for row in rows:
        sides = by_ticker[row["ticker"]]
        yes, no = sides["yes"], sides["no"]
        entity = normalize_player_name(_optic_name(_ids(row)["player_id"]))
        line = float(row["ticker"].rsplit("_", 1)[1])
        assert (yes.side, no.side) == ("over", "under")
        assert yes.entity == no.entity == entity
        assert yes.line == no.line == line
        assert yes.market_type == no.market_type == market_types_for_sport(Sport.HOCKEY)[_ids(row)["market_id"]].value


def test_first_goal_scorer_confirms_on_the_venue_player() -> None:
    rows = [r for r in _EVENT["rows"] if _family(r) == "UDXNHLFGS"]
    tally, stamped, alerts = _run(rows)
    assert tally["unconfirmed"] == tally["optic_player"] == 0
    assert alerts == []
    yes = {item.underdog_ticker: item for item in stamped if item.underdog_side == "yes"}
    assert set(yes) == {r["ticker"] for r in rows} and len(rows) == 8
    for row in rows:
        assert yes[row["ticker"]].entity == normalize_player_name(_optic_name(_ids(row)["player_id"]))
        assert yes[row["ticker"]].market_type == MarketType.FIRST_GOAL_SCORER.value


def test_team_goals_still_stamp_the_team_not_a_player() -> None:
    rows = [r for r in _EVENT["rows"] if _family(r) == "UDXNHLTEAMGOALS"]
    tally, stamped, _ = _run(rows)
    assert tally["stamped"] == 2 * len(rows) > 0
    assert {item.entity for item in stamped} <= {"HOM", "AWY"}


def _swap_player(row: dict) -> dict:
    """The sentence names another player on the same fixture; the venue's player id is unchanged."""
    other = next(o["selection"] for o in _EVENT["odds"] if o["player_id"] != _ids(row)["player_id"])
    row["description"] = row["description"].replace(_optic_name(_ids(row)["player_id"]), other, 1)
    return row


def _set(field: str, value):
    def edit(row: dict) -> dict:
        if value is None:
            _ids(row).pop(field)
        else:
            _ids(row)[field] = value
        return row

    return edit


def _text(old: str, new: str):
    def edit(row: dict) -> dict:
        assert old in row["description"]
        row["description"] = row["description"].replace(old, new, 1)
        return row

    return edit


_TAMPERED = {
    "no player id": (_set("player_id", None), "unconfirmed"),
    "player id not on the fixture": (_set("player_id", "000000000000"), "unconfirmed"),
    "stat is not the market id's": (_text(" goals during", " assists during"), "unconfirmed"),
    "shootout counts": (_text("but excluding the shootout", "and the shootout"), "unconfirmed"),
    "regulation only": (_text("including overtime but excluding the shootout", "during regulation"), "unconfirmed"),
    "integer line": (_text("record above 0.5 goals", "record above 1 goals"), "unconfirmed"),
    "at least, not above": (_text("record above", "record at least"), "unconfirmed"),
    "another league": (_text("Will NHL ", "Will AHL "), "unconfirmed"),
    "trailing clause": (_text(" ET?", " ET? Void if the player is scratched."), "unconfirmed"),
    "sentence names another player": (_swap_player, "optic_player"),
}


@pytest.mark.parametrize("case", sorted(_TAMPERED))
def test_a_contract_that_is_not_exactly_ours_maps_nothing(case: str) -> None:
    edit, reason = _TAMPERED[case]
    tally, stamped, alerts = _run([edit(_one_goals_row())])
    assert stamped == []
    assert tally[reason] == 1
    assert (len(alerts) == 1) == (reason == "optic_player")


def test_a_player_id_with_two_optic_names_maps_nothing() -> None:
    row = _one_goals_row()
    pid = _ids(row)["player_id"]
    odds = [
        *_EVENT["odds"],
        {
            "market_id": "player_goals",
            "selection": "Somebody Else",
            "selection_line": "over",
            "points": 0.5,
            "player_id": pid,
        },
    ]
    tally, stamped, _ = _run([row], _entry(odds))
    assert stamped == []
    assert tally["unconfirmed"] == 1


def test_without_the_player_id_rule_nhl_props_still_map_nothing() -> None:
    """A config built without ``player_id_markets`` falls back to the sentence reader, which has no NHL form."""
    cfg = UnderdogConfig(league="NHL", market_types=market_types_for_sport(Sport.HOCKEY))
    tally, stamped, _ = _run(_prop_rows(), cfg=cfg)
    assert stamped == []
    assert tally["dropped"] == len(_prop_rows())


def test_stamps_never_read_the_ticker() -> None:
    rows = _prop_rows()
    opaque = [dict(r, ticker=f"opaque-{i}") for i, r in enumerate(rows)]
    shape = lambda items: sorted(  # noqa: E731
        (i.market_type, i.side, i.entity, i.line, i.underdog_side) for i in items
    )
    assert shape(_run(rows)[1]) == shape(_run(opaque)[1])

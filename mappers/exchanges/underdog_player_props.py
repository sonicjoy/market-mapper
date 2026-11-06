"""Underdog player props that map only on the whole contract sentence and the venue's own Optic player id.

A contract whose Optic ``market_id`` is listed in ``CONTRACTS`` maps only when both witnesses agree:

* the sentence is exactly the contract we price: ``CONTRACTS[market_id]`` must match it whole, with a half-point line
  (an integer "above N" loses on exactly N, an Optic N pushes), the stat the market id names, and the settlement the
  Optic market uses. Any other wording maps nothing.
* ``external_ids.optic_odds.player_id`` names exactly one player among the matched Optic fixture's odds IN THAT
  MARKET, and that player is the sentence's player after ``normalize_player_name``. Other markets are not read: Optic
  labels the same id "Chicago Bears :: D'Andre Swift" in ``team_first_touchdown_scorer``. A missing, unknown or
  ambiguous id maps nothing; an id that names a different player is the venue disagreeing with itself and is alerted.

Underdog confirmed in writing (Jim Bumbulsky, 2026-10-19) that a quarterback's passing touchdowns do not count
toward UDXNFLTD "touchdowns": the TD ladder is Optic's scorer-touchdown ``player_touchdowns`` for every player.

Measured on the prod catalogue and Optic's odds: NHL 2026-10-15, 2,857 / 2,857 skater-prop rows fit the sentence and
every player_id named the sentence's player; NHL first goalscorer 2026-10-29 and NFL 2026-10-19, see
``docs/adding-underdog.md``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mappers.exchanges.underdog import UnderdogContract, optic_block
from mappers.shared import normalize_player_name

_TIME_ET = r"originally scheduled for \d{1,2}:\d{2}[ap]m ET on [A-Z][a-z]+ \d{1,2}, \d{4}\."

_NHL = re.compile(
    r"Will NHL (?P<player>[^()?]+?) record above (?P<line>\d+\.5) (?P<stat>goals|assists|points|shots on goal)"
    r" during the entire game including overtime but excluding the shootout"
    r" of [^()]+ \(away\) at [^()]+ \(home\),"
    r" originally scheduled for [A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2}[ap]m ET\?"
)
_NHL_FIRST_GOAL = re.compile(
    r"Will NHL (?P<player>[^()?]+?) record at least (?P<line>0\.5) (?P<stat>first goal)"
    r" during the entire game including overtime but excluding the shootout"
    r" of [^()]+ \(away\) at [^()]+ \(home\),"
    r" originally scheduled for [A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2}[ap]m ET\?"
)
_NFL_TOUCHDOWNS = re.compile(
    r"Resolves Yes if (?P<player>[^()]+?) records above (?P<line>\d+\.5) (?P<stat>touchdowns)"
    r" during the full game \(including overtime\) of the National Football League game"
    r" between the [^()]+? and the [^()]+? " + _TIME_ET
)
_NFL_FULL_DURATION = re.compile(
    r"Resolves Yes if (?P<player>[^()]+?) records above (?P<line>\d+\.5)"
    r" (?P<stat>passing \+ rushing yards|rushing \+ receiving yards|kicking points)"
    r" during the full duration of the National Football League game"
    r" between the [^()]+? and the [^()]+? " + _TIME_ET
)

#: Optic market id -> (the stat the sentence must state, the whole-sentence pattern).
CONTRACTS: dict[str, tuple[str, re.Pattern[str]]] = {
    "player_goals": ("goals", _NHL),
    "player_assists": ("assists", _NHL),
    "player_points": ("points", _NHL),
    "player_shots_on_goal": ("shots on goal", _NHL),
    "first_goal_scorer": ("first goal", _NHL_FIRST_GOAL),
    "player_touchdowns": ("touchdowns", _NFL_TOUCHDOWNS),
    "player_passing_+_rushing_yards": ("passing + rushing yards", _NFL_FULL_DURATION),
    "player_rushing_+_receiving_yards": ("rushing + receiving yards", _NFL_FULL_DURATION),
    "player_kicking_points": ("kicking points", _NFL_FULL_DURATION),
}

UNCONFIRMED = "unconfirmed"
DISAGREE = "optic_player"


@dataclass(frozen=True)
class PropCheck:
    """The prop's player entity when both witnesses agree, else why not."""

    entity: str | None
    reason: str = ""
    alert: str = ""


def sentence_player(contract: UnderdogContract) -> str | None:
    """The sentence's player when the whole sentence is the contract the market id names, else None."""
    spec = CONTRACTS.get(contract.market_id)
    match = spec[1].fullmatch(contract.description) if spec else None
    if spec is None or match is None or match["stat"] != spec[0]:
        return None
    if contract.line != float(match["line"]):
        return None
    return match["player"]


def optic_players(fx: Any, player_id: str, market_id: str) -> set[str]:
    """Normalized names Optic gives ``player_id`` in ``market_id`` on the fixture."""
    return {
        normalize_player_name(str(odd.selection))
        for odd in getattr(fx, "odds", None) or []
        if str(getattr(odd, "player_id", "") or "") == player_id
        and getattr(odd, "market_id", "") == market_id
        and getattr(odd, "selection", "")
    }


def confirm_player(contract: UnderdogContract, row: Mapping, fx: Any) -> PropCheck:
    """The entity to stamp, or the tally reason (and alert line) for withholding the contract."""
    name = sentence_player(contract)
    if name is None:
        return PropCheck(None, UNCONFIRMED)
    player_id = str(optic_block(row).get("player_id") or "").strip()
    names = optic_players(fx, player_id, contract.market_id) if player_id else set()
    if len(names) != 1:
        return PropCheck(None, UNCONFIRMED)
    entity = normalize_player_name(name)
    if names != {entity}:
        return PropCheck(
            None,
            DISAGREE,
            (
                f"{contract.ticker}: UDX player_id {player_id} is {sorted(names)[0]!r} on Optic fixture "
                f"{contract.fixture_id}, the sentence names {name!r}"
            ),
        )
    return PropCheck(entity)

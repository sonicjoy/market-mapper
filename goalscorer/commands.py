"""Channel commands: a message that is exactly one of

    international_-_friendlies                 add an Optic league (series derived)
    international_-_friendlies KXFRIENDLYGOAL  add a league with an explicit series
    202608110FBC008C / 19089-22537-2026-08     map one Optic fixture (id or game_id)
    KXEPLGAME-26AUG25ARSCHE[-ARS]              map the match any Kalshi ticker is on

Anything else is ignored, so people can still talk in the channel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_LEAGUE = re.compile(r"^[a-z0-9][a-z0-9_.'()]*_-_[a-z0-9_.'()-]+$")
_GOAL_SERIES = re.compile(r"^KX[A-Z0-9]+GOAL$")
_OPTIC_ID = re.compile(r"^[0-9A-F]{16}$")
_OPTIC_GAME_ID = re.compile(r"^\d+-\d+-\d{4}-\d{2}$")
_KALSHI = re.compile(r"^KX[A-Z0-9]+-[0-9A-Z]+(-[0-9A-Z.]+)*$")

Kind = Literal["add_league", "map_fixture", "map_ticker"]


@dataclass(frozen=True)
class Command:
    """A parsed channel command."""

    kind: Kind
    value: str
    goal_prefix: str | None = None


def _clean_token(token: str) -> str:
    """Strip Slack markup: `code`, *bold*, <url|label>; a Kalshi URL becomes its last path segment."""
    token = token.strip().strip("`*_")
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1].split("|")[0]
    if token.startswith("http"):
        token = [p for p in token.split("?")[0].split("/") if p][-1]
    return token


def parse_command(text: str) -> Command | None:
    """Classify a channel message, or None if it isn't a command."""
    tokens = [_clean_token(t) for t in (text or "").split()]
    tokens = [t for t in tokens if t]
    if len(tokens) == 2 and _LEAGUE.match(tokens[0].lower()) and _GOAL_SERIES.match(tokens[1].upper()):
        return Command("add_league", tokens[0].lower(), tokens[1].upper())
    if len(tokens) != 1:
        return None
    token = tokens[0]
    if _LEAGUE.match(token.lower()):
        return Command("add_league", token.lower())
    if _OPTIC_ID.match(token.upper()):
        return Command("map_fixture", token.upper())
    if _OPTIC_GAME_ID.match(token):
        return Command("map_fixture", token)
    if _KALSHI.match(token.upper()):
        return Command("map_ticker", token.upper())
    return None

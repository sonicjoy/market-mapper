"""Polymarket US structured market records (``polymarket_usa_markets.jsonl``).

One line per gateway market as written by ``fetch.polymarket_usa``: typed
market fields plus the event context Path 2 binds on. Parsing here reads
fields only — the instrument symbol is carried, never split.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mappers.shared import normalize_line


@dataclass(frozen=True)
class UsTeam:
    """One gateway team (event ``teams[]`` or a market side's ``team``)."""

    team_id: str
    abbreviation: str = ""
    name: str = ""
    alt_names: tuple[str, ...] = ()
    sportradar_id: str = ""


@dataclass(frozen=True)
class UsSide:
    """One venue side of a market (both sides share the market's symbol)."""

    side_id: str
    long: bool
    description: str
    team_id: str = ""


@dataclass(frozen=True)
class UsMarket:
    """One gateway market with the event fields Path 2 binds on."""

    league_id: int | None  # gateway league the fetch walked it under
    event_id: str
    event_ticker: str
    event_start: str
    sportradar_game_id: str
    teams: tuple[UsTeam, ...]
    market_id: str
    slug: str
    sports_market_type: str
    line: float | None
    player_name: str
    line_label: str
    sides: tuple[UsSide, ...]
    # Read only for the few enums with no typed outcome
    # (``polymarket_usa_titles``); never for anything else.
    title: str = ""

    def long_side(self) -> UsSide | None:
        """The side the contract pays out on."""
        return next((s for s in self.sides if s.long), None)

    def short_side(self) -> UsSide | None:
        """The complementary side."""
        return next((s for s in self.sides if not s.long), None)


def _team(raw: Mapping[str, Any]) -> UsTeam | None:
    """Gateway team dict → UsTeam; None without an id."""
    tid = str(raw.get("id") or "").strip()
    if not tid:
        return None
    alts = tuple(
        str(raw.get(k) or "").strip()
        for k in ("safe_name", "alias")
        if str(raw.get(k) or "").strip()
    )
    return UsTeam(
        team_id=tid,
        abbreviation=str(raw.get("abbreviation") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        alt_names=alts,
        sportradar_id=str(raw.get("sportradar_id") or "").strip(),
    )


def _line(raw: object) -> float | None:
    """Numeric ``line`` snapped for equality; None for absent / non-numeric."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return normalize_line(float(raw))


def parse_market(obj: Mapping[str, Any]) -> UsMarket | None:
    """``polymarket_usa_markets.jsonl`` line → UsMarket, or None if unusable."""
    slug = str(obj.get("slug") or "").strip().casefold()
    event_id = str(obj.get("event_id") or "").strip()
    if not slug or not event_id:
        return None
    teams = tuple(
        t for t in (_team(raw) for raw in obj.get("teams") or [] if isinstance(raw, dict))
        if t is not None
    )
    sides = tuple(
        UsSide(
            side_id=str(raw.get("id") or ""),
            long=raw.get("long") is True,
            description=str(raw.get("description") or "").strip(),
            team_id=str(raw.get("team_id") or "").strip(),
        )
        for raw in obj.get("sides") or []
        if isinstance(raw, dict)
    )
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    return UsMarket(
        league_id=_league_id(obj.get("league_id")),
        event_id=event_id,
        event_ticker=str(obj.get("event_ticker") or "").strip().casefold(),
        event_start=str(obj.get("event_start") or "").strip(),
        sportradar_game_id=str(obj.get("sportradar_game_id") or "").strip(),
        teams=teams,
        market_id=str(obj.get("market_id") or "").strip(),
        slug=slug,
        sports_market_type=str(obj.get("sports_market_type") or "").strip(),
        line=_line(obj.get("line")),
        player_name=str((meta or {}).get("playerName") or "").strip(),
        line_label=str((meta or {}).get("lineLabel") or "").strip(),
        sides=sides,
        title=str(obj.get("title") or "").strip(),
    )


def _league_id(raw: object) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def load_markets(lines: Iterable[str], league_ids: frozenset[int]) -> list[UsMarket]:
    """Parsed markets in these gateway leagues; bad lines skipped."""
    out: list[UsMarket] = []
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        market = parse_market(obj)
        if market is not None and market.league_id in league_ids:
            out.append(market)
    return out

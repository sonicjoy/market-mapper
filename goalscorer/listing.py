"""Listing check: move pre-game overrides onto the tickers Kalshi actually lists.

Pre-game guesses each ticker from the player's last code, but Kalshi only
creates a match's goalscorer markets ~35 minutes before kick-off, and codes
drift between games (new kit number, new club). Each run reads Kalshi's listing
for every event pre-game published to. An override whose ticker isn't listed
moves to the one free listed market for the same player: same name, or the same
code apart from the kit number. Each goal line is checked on its own: an anytime
guess only moves onto a listed 1+ market (Kalshi can list a player's 2+ / 3+
markets before his 1+ one), and a player_goals 1.5 / 2.5 guess only onto a
listed 2+ / 3+ market. First goalscorer guesses are checked against their own
event (KX…FIRSTGOAL-…), whose tickers carry no line. Moves carry LISTING_SOURCE,
so pre-game leaves them alone. Unmatched overrides stay as they are, in case
Kalshi lists the player later.

A match can be held by another selection's mapping row (Optic's own spelling of
the player), which only the mapping table shows. That read is the cost of a
run, so it happens once per run for every game, market and line with a possible
move, and stops once Kalshi closes the event.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from goalscorer import codes, kalshi
from goalscorer.config import FIRST_GOAL_MARKET_ID, LISTING_SOURCE, MARKET_ID, MULTI_GOAL_LINES, OVERRIDE_SOURCE
from goalscorer.context import Context
from goalscorer.models import GoalMapping, OverrideState
from goalscorer.overrides import override_message, player_goals_message
from goalscorer.timeutil import day_start, utcnow

logger = logging.getLogger(__name__)

# event ticker → {ticker: player name}; {} = not listed yet or closed, None = Kalshi didn't answer
Listing = Callable[[str], dict[str, str] | None]

# Pre-game publishes for today and tomorrow, so this reaches every live event.
_PUBLISHED_LOOKBACK = timedelta(days=3)
# Events dated yesterday..tomorrow are checked while open (yesterday's for games running past midnight UTC).
_EVENT_DAYS = (-1, 0, 1)


@dataclass(frozen=True)
class Move:
    """Re-point one selection's override from an unlisted ticker to a listed one.

    player_goals over `points` when points is set, else `market_id` (anytime or first goalscorer).
    """

    game_id: str
    selection: str
    old: str
    new: str
    points: float = 0.0
    market_id: str = MARKET_ID

    def message(self) -> dict:
        """The mapping_override payload re-pointing this selection."""
        if self.points:
            return player_goals_message(self.game_id, self.selection, self.new, self.points)
        return override_message(self.game_id, self.selection, self.new, market_id=self.market_id)


def event_ticker(ticker: str) -> str:
    """KXEPLGOAL-26OCT11CRYNFO from any market ticker on the event."""
    # legacy: ticker parse — replace with the typed venue field, do not extend
    return "-".join(ticker.split("-")[:2])


def event_date(ticker: str) -> date | None:
    """Date in the fixture part (26OCT11CRYNFO → 2026-10-11)."""
    try:
        return datetime.strptime(codes.fixture_part(ticker)[:7], "%y%b%d").date()
    except ValueError:
        return None


def _letters(ticker: str) -> str:
    """Player code without its kit number (…-NFOLDELAP19-1 → NFOLDELAP)."""
    # legacy: ticker parse — replace with the typed venue field, do not extend
    return codes.player_code(ticker).split("-")[0].rstrip("0123456789")


def _ours(states: Sequence[OverrideState]) -> list[OverrideState]:
    """Pre-game's own active overrides."""
    return [s for s in states if s.source == OVERRIDE_SOURCE and s.active and s.ticker]


def plan_moves(
    overrides: Sequence[OverrideState],
    listed: dict[str, str],
    existing: Sequence[GoalMapping] = (),
    *,
    line: str | None = codes.ANYTIME_LINE,
    points: float = 0.0,
    market_id: str = MARKET_ID,
) -> list[Move]:
    """Moves for one game's pre-game overrides on one goal line whose tickers Kalshi doesn't list.

    `overrides` are that line's (anytime for "1", player_goals over `points` for
    "2" / "3"; `line` None for first goalscorer, whose event lists only that
    market). `existing` can span every market: each line has its own tickers. A
    listed ticker is free unless another selection's override or mapping row holds
    it; a move needs exactly one free match, claimed by no other override.
    """
    if line is not None:
        listed = {t: name for t, name in listed.items() if t.rsplit("-", 1)[-1] == line}
    stale = sorted((o for o in _ours(overrides) if o.ticker not in listed), key=lambda o: o.selection)
    if not stale:
        return []
    moving = {o.selection for o in stale}
    taken = {o.ticker for o in overrides if o.active and o.selection not in moving}
    taken |= {m.ticker for m in existing if m.selection not in moving}
    free = {t: codes.normalise_name(name) for t, name in listed.items() if t not in taken}
    matches = {
        o.selection: [
            t
            for t, name in free.items()
            if name == codes.normalise_name(o.selection) or _letters(t) == _letters(o.ticker)
        ]
        for o in stale
    }
    claims = Counter(t for found in matches.values() for t in found)
    return [
        Move(o.game_id, o.selection, o.ticker, matches[o.selection][0], points, market_id)
        for o in stale
        if len(matches[o.selection]) == 1 and claims[matches[o.selection][0]] == 1
    ]


def _event_to_check(states: Sequence[OverrideState], today: date) -> tuple[str, date] | None:
    """(Kalshi event, its date) behind a game's pre-game overrides, if dated near today."""
    ours = _ours(states)
    day = event_date(ours[0].ticker) if ours else None
    if day is None or (day - today).days not in _EVENT_DAYS:
        return None
    return event_ticker(ours[0].ticker), day


@dataclass(frozen=True)
class _Check:
    """One game's guesses on one market or goal line, and Kalshi's listing for their event."""

    game_id: str
    states: Sequence[OverrideState]
    listed: dict[str, str]
    day: date
    line: str | None
    points: float
    market_id: str

    def moves(self, existing: Sequence[GoalMapping] = ()) -> list[Move]:
        """Planned moves, given the mapping rows that can hold a listed ticker."""
        return plan_moves(
            self.states, self.listed, existing, line=self.line, points=self.points, market_id=self.market_id
        )


# (goal line, player_goals points, market_id) checked for each kind of guess.
_Kind = tuple[str | None, float, str]
_ANYTIME: tuple[_Kind, ...] = ((codes.ANYTIME_LINE, 0.0, MARKET_ID),)
_LINES: tuple[_Kind, ...] = tuple((line, points, MARKET_ID) for line, points in MULTI_GOAL_LINES.items())
_FIRST_GOAL: tuple[_Kind, ...] = ((None, 0.0, FIRST_GOAL_MARKET_ID),)


def _checks(game_id: str, states: Sequence[OverrideState], listing: Listing, kinds: Sequence[_Kind]) -> list[_Check]:
    """One game's checks with a possible move, before any mapping rows are read."""
    target = _event_to_check(states, utcnow().date())
    listed = listing(target[0]) if target else None
    if not target or not listed:
        return []
    checks = [
        _Check(game_id, [s for s in states if s.points == points], listed, target[1], line, points, market_id)
        for line, points, market_id in kinds
    ]
    return [c for c in checks if c.moves()]


def _mapping_rows(ctx: Context, checks: Sequence[_Check]) -> dict[str, list[GoalMapping]]:
    """Mapping rows per game for every check, in one read over the games' event days ±1."""
    if not checks:
        return {}
    days = [c.day for c in checks]
    since = day_start(min(days) - timedelta(days=1))
    until = day_start(max(days) + timedelta(days=2))
    out: dict[str, list[GoalMapping]] = {}
    for row in ctx.store.held_rows(sorted({c.game_id for c in checks}), since, until):
        out.setdefault(row.game_id, []).append(row)
    return out


def _group(states: Sequence[OverrideState]) -> dict[str, list[OverrideState]]:
    """Override states by game_id."""
    by_game: dict[str, list[OverrideState]] = {}
    for state in states:
        by_game.setdefault(state.game_id, []).append(state)
    return by_game


def _cached(listing: Listing) -> Listing:
    """Ask Kalshi once per event per run (anytime and line checks share a listing)."""
    seen: dict[str, dict[str, str] | None] = {}

    def cached(event: str) -> dict[str, str] | None:
        if event not in seen:
            seen[event] = listing(event)
        return seen[event]

    return cached


def run_listing_check(ctx: Context, listing: Listing = kalshi.event_players) -> list[Move]:
    """Check every recent pre-game event against Kalshi's listing; publish the moves."""
    since = utcnow() - _PUBLISHED_LOOKBACK
    listing = _cached(listing)
    guesses = (
        (ctx.store.overrides_since(since, OVERRIDE_SOURCE), _ANYTIME),
        (ctx.store.line_overrides_since(since, OVERRIDE_SOURCE), _LINES),
        (ctx.store.overrides_since(since, OVERRIDE_SOURCE, FIRST_GOAL_MARKET_ID), _FIRST_GOAL),
    )
    checks = [
        c
        for states, kinds in guesses
        for game_id, game_states in _group(states).items()
        for c in _checks(game_id, game_states, listing, kinds)
    ]
    rows = _mapping_rows(ctx, checks)
    moves = [m for c in checks for m in c.moves(rows.get(c.game_id, []))]
    ctx.publisher.publish([m.message() for m in moves], source=LISTING_SOURCE)
    for m in moves:
        logger.info(
            "listing %s %s %s%s: %s → %s",
            m.game_id,
            m.market_id if not m.points else "player_goals",
            m.selection,
            f" o{m.points:g}" if m.points else "",
            m.old,
            m.new,
        )
    return moves

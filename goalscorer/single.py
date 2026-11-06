"""Map one match on demand — an Optic fixture id / game_id or any Kalshi ticker on it."""

from __future__ import annotations

from datetime import timedelta

from goalscorer import codes
from goalscorer.context import Context
from goalscorer.models import Fixture, Moneyline
from goalscorer.pregame import GameOutcome, map_fixtures
from goalscorer.timeutil import utcnow

# How far either side of now a posted reference is looked up.
_LOOKBACK = timedelta(days=3)
_LOOKAHEAD = timedelta(days=30)


def resolve_fixture(ctx: Context, ref: str, *, is_ticker: bool) -> tuple[Fixture | None, str | None, str]:
    """(fixture, goal-series hint from the ticker, error text when not found)."""
    now = utcnow()
    since, until = now - _LOOKBACK, now + _LOOKAHEAD
    if not is_ticker:
        fixture = ctx.store.fixture_by_ref(ref, since, until)
        return fixture, None, "" if fixture else f"No Optic fixture `{ref}` between {since:%d %b} and {until:%d %b}."
    part = codes.fixture_part(ref)
    game_ids = ctx.store.games_for_fixture_part(part, since, until)
    if not game_ids:
        return None, None, f"No Optic game has a Kalshi moneyline mapping for `{part}`."
    if len(game_ids) > 1:
        return None, None, f"`{part}` matches {len(game_ids)} Optic games ({', '.join(game_ids)}); post the fixture id."
    fixture = ctx.store.fixture_by_ref(game_ids[0], since, until)
    series = codes.series(ref)
    hint = codes.anytime_prefix(series) if series.endswith("GOAL") else None
    return fixture, hint, "" if fixture else f"Optic game `{game_ids[0]}` is outside the lookup window."


def map_single(ctx: Context, ref: str, *, is_ticker: bool) -> tuple[GameOutcome | None, str]:
    """Map one fixture even if its league isn't registered. Returns (outcome, error)."""
    fixture, hint, error = resolve_fixture(ctx, ref, is_ticker=is_ticker)
    if fixture is None:
        return None, error
    leagues = ctx.leagues.active()

    def prefix_for(fx: Fixture, ml: Moneyline) -> str | None:
        league = leagues.get(fx.league_id)
        return hint or (league.goal_prefix if league else codes.goal_prefix_for_series(ml.series))

    [outcome] = map_fixtures(ctx, [fixture], prefix_for)
    return outcome, ""

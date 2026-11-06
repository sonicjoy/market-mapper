"""Run a parsed channel command and produce the thread replies."""

from __future__ import annotations

import logging

from goalscorer.commands import Command
from goalscorer.config import League
from goalscorer.context import Context
from goalscorer.leagues import kalshi_series_exists
from goalscorer.pregame import run_pregame, summary_text
from goalscorer.single import map_single
from goalscorer.timeutil import utcnow

logger = logging.getLogger(__name__)


def add_league(ctx: Context, slug: str, goal_prefix: str | None, user: str) -> tuple[League | None, str]:
    """Validate and register a league. Returns (league if added, reply text)."""
    current = ctx.leagues.active().get(slug)
    if current and goal_prefix in (None, current.goal_prefix):
        return None, f"`{slug}` is already mapped (Kalshi series `{current.goal_prefix}`)."
    optic = ctx.leagues.optic_league(slug)
    if optic is None:
        return None, f"Optic has no fixtures for `{slug}` in the last 30 or next 60 days — check the slug."
    name, sport = optic
    prefix = goal_prefix or ctx.leagues.derived_goal_prefix(slug)
    if prefix is None:
        return None, (
            f"`{slug}` has no Kalshi moneyline mappings yet, so its goalscorer series can't be derived. "
            f"Post `{slug} KX…GOAL` to set it explicitly."
        )
    exists = kalshi_series_exists(prefix)
    if exists is False:
        return None, f"Kalshi has no series `{prefix}` — post `{slug} KX…GOAL` with the right one."
    league = League(slug, prefix, name, sport)
    ctx.leagues.add(league, added_by=user)
    caveat = "" if exists else " (Kalshi didn't answer, so the series is unconfirmed)"
    return league, f":white_check_mark: Added *{name}* (`{slug}`) with Kalshi series `{prefix}`{caveat}."


def handle_command(ctx: Context, command: Command, user: str) -> list[str]:
    """Execute one command; every returned string becomes a thread reply."""
    logger.info("command %s %s by %s", command.kind, command.value, user)
    if command.kind == "add_league":
        league, reply = add_league(ctx, command.value, command.goal_prefix, user)
        if league is None:
            return [reply]
        outcomes = run_pregame(ctx, utcnow().date(), league_ids=[league.league_id])
        if not outcomes:
            return [reply, "No fixtures in the pre-game window yet; scheduled runs will pick them up."]
        return [reply, summary_text(f"{league.display_name} — mapped now", outcomes, ctx.settings.dry_run)]
    outcome, error = map_single(ctx, command.value, is_ticker=command.kind == "map_ticker")
    if outcome is None:
        return [f":warning: {error}"]
    return [summary_text(f"Mapped on request: {outcome.fixture.label}", [outcome], ctx.settings.dry_run)]

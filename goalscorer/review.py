"""Apply a human decision on a review card."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from goalscorer.codes import is_anytime, normalise_name, player_code, to_first_goal
from goalscorer.config import FIRST_GOAL_MARKET_ID, MAPPING_SOURCE, MULTI_GOAL_LINES, REVIEW_SOURCE
from goalscorer.context import Context
from goalscorer.models import ReviewItem
from goalscorer.overrides import override_message, player_goals_message

logger = logging.getLogger(__name__)

UNKNOWN_NAME = "No book lists that name for this game. Check the spelling, or tick 'use exactly as typed'."
# start_date slack when reading the game's mapping rows.
_ROW_WINDOW = timedelta(days=1)


def resolve_typed(typed: str, candidates: Iterable[str], force: bool) -> tuple[str | None, str | None]:
    """(selection, error): snap to the book's spelling, or accept as typed when forced."""
    if not typed:
        return None, "Enter a selection name."
    by_norm = {normalise_name(c): c for c in candidates}
    hit = by_norm.get(normalise_name(typed))
    if hit:
        return hit, None
    return (typed, None) if force else (None, UNKNOWN_NAME)


def record(ctx: Context, item: ReviewItem, selection: str, user: str) -> str:
    """Record the mapping and return the note that replaces the card's buttons.

    A new selection is inserted as a knowledge row. One this job already mapped
    to another ticker (a stale guess) is re-pointed with an override, which
    prices_state_merge_us applies within 15 min. Other mappings are never replaced.
    Once the anytime line names the player, his 2+ / 3+ lines and his first
    goalscorer market are recorded the same way (``record_related``). Legacy
    cards carrying a 2+ / 3+ ticker are refused.
    """
    if not is_anytime(item.ticker):
        logger.info("review %s → %s by %s refused: not a 1+ ticker", item.ticker, selection, user)
        return f":no_entry_sign: `{item.player_code}` is a multi-goal market, not anytime — no change (<@{user}>)"
    if ctx.settings.dry_run:
        logger.info("dry-run: %s → %s by %s", item.ticker, selection, user)
        return f":test_tube: Dry run — would map to *{selection}* (<@{user}>)"
    rows = ctx.store.goal_mappings([item.game_id], item.start_date - _ROW_WINDOW, item.start_date + _ROW_WINDOW)
    holder = next((m for m in rows if m.ticker == item.ticker), None)
    current = next((m for m in rows if m.selection == selection), None)
    if holder is not None:
        if holder.selection != selection:
            return f":information_source: Mapped to *{holder.selection}* — no change (<@{user}> chose *{selection}*)"
        return f":information_source: Already mapped for this game{record_related(ctx, item, selection)} (<@{user}>)"
    if current is not None and current.mapping_source != MAPPING_SOURCE:
        source = current.mapping_source or "no source"
        return (
            f":warning: *{selection}* is already mapped to `{player_code(current.ticker)}` ({source}) — no change; "
            f"fix it in the mapping console if that's wrong (<@{user}>)"
        )
    if current is not None:
        ctx.publisher.publish([override_message(item.game_id, selection, item.ticker)], source=REVIEW_SOURCE)
        logger.info("review %s → %s by %s (replaces %s)", item.ticker, selection, user, current.ticker)
        return (
            f":white_check_mark: Mapped to *{selection}* by <@{user}>, "
            f"replacing `{player_code(current.ticker)}` (applies within 15 min){record_related(ctx, item, selection)}"
        )
    inserted = ctx.store.insert_knowledge([item.knowledge(selection)])
    logger.info("review %s → %s by %s (inserted=%d)", item.ticker, selection, user, inserted)
    if not inserted:
        return f":information_source: Already mapped for this game — no change (<@{user}> chose *{selection}*)"
    return f":white_check_mark: Mapped to *{selection}* by <@{user}>{record_related(ctx, item, selection)}"


def record_related(ctx: Context, item: ReviewItem, selection: str) -> str:
    """Map the player's 2+ / 3+ lines and first goalscorer market; returns the note suffix."""
    return record_lines(ctx, item, selection) + record_first_goal(ctx, item, selection)


def record_first_goal(ctx: Context, item: ReviewItem, selection: str) -> str:
    """Map the player's first goalscorer ticker to first_goal_scorer, by the anytime rules; returns a note suffix."""
    ticker = to_first_goal(item.ticker)
    window = (item.start_date - _ROW_WINDOW, item.start_date + _ROW_WINDOW)
    rows = ctx.store.goal_mappings([item.game_id], *window, FIRST_GOAL_MARKET_ID)
    holder = next((m for m in rows if m.ticker == ticker), None)
    current = next((m for m in rows if m.selection == selection), None)
    if holder is not None or (current is not None and current.mapping_source != MAPPING_SOURCE):
        added = False
    elif current is not None:
        message = override_message(item.game_id, selection, ticker, market_id=FIRST_GOAL_MARKET_ID)
        ctx.publisher.publish([message], source=REVIEW_SOURCE)
        added = True
    else:
        added = bool(ctx.store.insert_knowledge([item.first_goal_knowledge(selection, ticker)], FIRST_GOAL_MARKET_ID))
    logger.info("review first goal %s → %s: added=%s", ticker, selection, added)
    return " · first goal: " + ("mapped" if added else "already mapped")


def record_lines(ctx: Context, item: ReviewItem, selection: str) -> str:
    """Map the player's 2+ / 3+ tickers to player_goals over 1.5 / 2.5; returns a note suffix.

    Same rules as the anytime line: insert where nothing is mapped, re-point this
    job's own stale rows with an override, leave every other mapping alone.
    """
    rows = ctx.store.line_mappings([item.game_id], item.start_date - _ROW_WINDOW, item.start_date + _ROW_WINDOW)
    inserts, overrides, kept = [], [], 0
    for row in item.line_knowledge(selection, MULTI_GOAL_LINES):
        holder = next((m for m in rows if m.ticker == row.ticker), None)
        current = next((m for m in rows if (m.selection, m.points) == (selection, row.points)), None)
        if holder is not None or (current is not None and current.mapping_source != MAPPING_SOURCE):
            kept += 1
        elif current is not None:
            overrides.append(player_goals_message(item.game_id, selection, row.ticker, row.points))
        else:
            inserts.append(row)
    if overrides:
        ctx.publisher.publish(overrides, source=REVIEW_SOURCE)
    added = len(overrides) + ctx.store.insert_line_knowledge(inserts)
    logger.info("review lines %s → %s: added=%d kept=%d", item.base_code, selection, added, kept)
    return f" · 2+/3+ lines: {added} mapped" + (f", {kept} already mapped" if kept else "")

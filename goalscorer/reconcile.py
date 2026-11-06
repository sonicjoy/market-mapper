"""Post-game reconcile: learn player codes Kalshi listed that no mapping covered.

For each played fixture, Kalshi goal tickers (1+ / 2+ / 3+ and first
goalscorer) seen as RFQ legs whose player has no anytime mapping become review
items — one per player, not one per market. Codes already known from the
team's earlier games are recorded straight away; the rest are posted to Slack
as review cards (``goalscorer.cards``) for a human to resolve. Recording a
player writes his anytime row, his player_goals over 1.5 / 2.5 rows and his
first_goal_scorer row together. Players whose anytime row exists but whose
traded 2+ / 3+ or first goalscorer market has no row get that row recorded too.
Recorded rows are the history the next pre-game run reuses.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from goalscorer import codes
from goalscorer.cards import review_card
from goalscorer.config import FIRST_GOAL_MARKET_ID, MULTI_GOAL_LINES, League
from goalscorer.context import Context
from goalscorer.models import Fixture, GoalMapping, KnowledgeRow, LineKnowledgeRow, LineMapping, Moneyline, ReviewItem
from goalscorer.timeutil import day_window

logger = logging.getLogger(__name__)

# RFQ legs for a match mostly arrive on match day and the day before.
_LEG_LOOKBACK = timedelta(days=1)


@dataclass
class ReconcileReport:
    """Result of one reconcile run."""

    day: date
    fixtures: int = 0
    auto: list[ReviewItem] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    recorded: int = 0
    lines_recorded: int = 0
    first_goal_recorded: int = 0


def _is_goal_ticker(ticker: str) -> bool:
    """A 1+ / 2+ / 3+ or first goalscorer ticker."""
    # legacy: ticker parse — replace with the typed venue field, do not extend
    return codes.is_first_goal(ticker) or ticker.rsplit("-", 1)[-1] in {codes.ANYTIME_LINE, *MULTI_GOAL_LINES}


def find_review_items(
    fixtures: Sequence[Fixture],
    leagues: dict[str, League],
    moneylines: dict[str, Moneyline],
    tickers: Sequence[str],
    existing: Sequence[GoalMapping],
    names: dict[str, set[str]],
) -> list[ReviewItem]:
    """One item per player with a traded goal ticker (any line, or first goal) but no anytime mapping.

    The item always carries the player's 1+ ticker, whichever of his markets traded.
    """
    by_part = {moneylines[f.game_id].fixture_part: f for f in fixtures if f.game_id in moneylines}
    known: dict[str, set[str]] = {}
    for m in existing:
        if codes.is_anytime(m.ticker):
            known.setdefault(m.game_id, set()).add(codes.player_code(m.ticker))
    players = {codes.to_anytime(t) for t in tickers if _is_goal_ticker(t)}
    items: list[ReviewItem] = []
    for ticker in sorted(players):
        fixture = by_part.get(codes.fixture_part(ticker))
        code = codes.player_code(ticker)
        if fixture is None or code in known.setdefault(fixture.game_id, set()):
            continue
        parts = codes.parse_code(code, codes.code_team(code, moneylines[fixture.game_id].teams.values()))
        if parts is None:
            logger.warning("unparseable player code %s (%s)", code, ticker)
            continue
        candidates = names.get(fixture.game_id, set())
        ranked = codes.rank_candidates(parts, candidates)
        league = leagues[fixture.league_id]
        items.append(
            ReviewItem(
                game_id=fixture.game_id,
                start_date=fixture.start_date,
                sport=league.sport,
                league=league.display_name,
                game_label=fixture.label,
                player_code=code,
                ticker=ticker,
                suggested=codes.suggest(ranked),
                ranked=ranked,
                candidates=sorted(candidates),
            )
        )
        known[fixture.game_id].add(code)
    return items


def missing_lines(
    fixtures: Sequence[Fixture],
    leagues: dict[str, League],
    moneylines: dict[str, Moneyline],
    tickers: Sequence[str],
    existing: Sequence[GoalMapping],
    lines: Sequence[LineMapping],
) -> list[LineKnowledgeRow]:
    """Traded 2+ / 3+ tickers with no player_goals row, for players whose anytime row names them."""
    by_part = {moneylines[f.game_id].fixture_part: f for f in fixtures if f.game_id in moneylines}
    named = {(m.game_id, m.ticker): m.selection for m in existing if codes.is_anytime(m.ticker)}
    mapped = {(m.game_id, m.ticker) for m in lines} | {(m.game_id, m.selection, m.points) for m in lines}
    rows: list[LineKnowledgeRow] = []
    for ticker in sorted(set(tickers)):
        # legacy: ticker parse — replace with the typed venue field, do not extend
        points = MULTI_GOAL_LINES.get(ticker.rsplit("-", 1)[-1])
        fixture = by_part.get(codes.fixture_part(ticker))
        if points is None or fixture is None:
            continue
        selection = named.get((fixture.game_id, codes.to_anytime(ticker)))
        if selection is None or {(fixture.game_id, ticker), (fixture.game_id, selection, points)} & mapped:
            continue
        league = leagues[fixture.league_id]
        rows.append(
            LineKnowledgeRow(
                fixture.game_id, fixture.start_date, league.sport, league.display_name, selection, ticker, points
            )
        )
    return rows


def missing_first_goals(
    fixtures: Sequence[Fixture],
    leagues: dict[str, League],
    moneylines: dict[str, Moneyline],
    tickers: Sequence[str],
    existing: Sequence[GoalMapping],
    first_existing: Sequence[GoalMapping],
) -> list[KnowledgeRow]:
    """Traded first goalscorer tickers with no first_goal_scorer row, for players whose anytime row names them."""
    by_part = {moneylines[f.game_id].fixture_part: f for f in fixtures if f.game_id in moneylines}
    named = {(m.game_id, m.ticker): m.selection for m in existing if codes.is_anytime(m.ticker)}
    mapped = {(m.game_id, m.ticker) for m in first_existing} | {(m.game_id, m.selection) for m in first_existing}
    rows: list[KnowledgeRow] = []
    for ticker in sorted(t for t in set(tickers) if codes.is_first_goal(t)):
        fixture = by_part.get(codes.fixture_part(ticker))
        if fixture is None:
            continue
        selection = named.get((fixture.game_id, codes.to_anytime(ticker)))
        if selection is None or {(fixture.game_id, ticker), (fixture.game_id, selection)} & mapped:
            continue
        league = leagues[fixture.league_id]
        rows.append(
            KnowledgeRow(fixture.game_id, fixture.start_date, league.sport, league.display_name, selection, ticker)
        )
    return rows


def code_names(history: dict[str, list[GoalMapping]]) -> dict[str, str]:
    """Anytime player code → selection from earlier games, newest wins."""
    rows = sorted((m for ms in history.values() for m in ms), key=lambda m: m.start_date, reverse=True)
    names: dict[str, str] = {}
    for m in rows:
        names.setdefault(codes.anytime_code(codes.player_code(m.ticker)), m.selection)
    return names


def _inputs(ctx: Context, fixtures: Sequence[Fixture], leagues: dict[str, League], day: date):
    """Moneylines, RFQ goal legs, existing anytime / line / first goal rows and book names for the day's games."""
    since, until = day_window(day)
    ids = [f.game_id for f in fixtures]
    lo, hi = since - timedelta(days=1), until + timedelta(days=1)
    moneylines = ctx.store.moneylines(ids, lo, hi)
    goal_prefixes = {leagues[f.league_id].goal_prefix for f in fixtures}
    prefixes = sorted(goal_prefixes | {codes.first_goal_prefix(p) for p in goal_prefixes})
    parts = sorted({ml.fixture_part for ml in moneylines.values()})
    tickers = ctx.store.goal_leg_tickers(prefixes, parts, since - _LEG_LOOKBACK, until)
    existing = ctx.store.goal_mappings(ids, lo, hi)
    lines = ctx.store.line_mappings(ids, lo, hi)
    first = ctx.store.goal_mappings(ids, lo, hi, FIRST_GOAL_MARKET_ID)
    names = ctx.store.sportsbook_names(ids, lo, hi)
    return moneylines, tickers, existing, lines, first, names


def run_reconcile(ctx: Context, day: date, team: str | None = None) -> ReconcileReport:
    """Reconcile every registered-league fixture played on `day`."""
    report = ReconcileReport(day)
    leagues = ctx.leagues.active()
    fixtures = ctx.store.fixtures(*day_window(day), leagues.keys())
    if team:
        fixtures = [f for f in fixtures if team.lower() in f.label.lower()]
    report.fixtures = len(fixtures)
    if not fixtures:
        return report
    moneylines, tickers, existing, lines, first, names = _inputs(ctx, fixtures, leagues, day)
    items = find_review_items(fixtures, leagues, moneylines, tickers, existing, names)
    competitors = sorted({c for f in fixtures for c in (f.home_id, f.away_id)})
    since = day_window(day)[0]
    history = ctx.store.team_history(competitors, since - timedelta(days=ctx.settings.lookback_days), since)
    learned = code_names(history)
    for item in items:
        (report.auto if item.player_code in learned else report.review).append(item)
    if not ctx.settings.dry_run:
        report.recorded = ctx.store.insert_knowledge([i.knowledge(learned[i.player_code]) for i in report.auto])
        line_rows = [r for i in report.auto for r in i.line_knowledge(learned[i.player_code], MULTI_GOAL_LINES)]
        line_rows += missing_lines(fixtures, leagues, moneylines, tickers, existing, lines)
        report.lines_recorded = ctx.store.insert_line_knowledge(line_rows)
        first_rows = [
            i.first_goal_knowledge(learned[i.player_code], codes.to_first_goal(i.ticker)) for i in report.auto
        ]
        first_rows += missing_first_goals(fixtures, leagues, moneylines, tickers, existing, first)
        report.first_goal_recorded = ctx.store.insert_knowledge(first_rows, FIRST_GOAL_MARKET_ID)
    _post(ctx, report)
    return report


def _post(ctx: Context, report: ReconcileReport) -> None:
    """One review card per unresolved player (the run's counts go to the job log)."""
    for item in report.review:
        ctx.slack.post(f"Unmapped player {item.base_code} ({item.game_label})", blocks=review_card(item))

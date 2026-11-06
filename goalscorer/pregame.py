"""Pre-game mapping: reuse each team's player codes from its previous games.

For every fixture, the player codes a team carried in the last
GOALSCORER_LOOKBACK_DAYS of Kalshi goalscorer mappings are rebuilt onto
tonight's fixture part and published as overrides. Selections that are already
covered — an Optic ORIGINAL row, anyone else's override, or our identical
override — are left alone, so every run is idempotent.

The same player code also maps his 2+ / 3+ goal markets (``…-2`` / ``…-3``)
onto Optic ``player_goals`` over 1.5 / 2.5, under the same rules: a line that
already has a row from anyone else, or someone else's override, is left alone.
And his first goalscorer market (``KX…FIRSTGOAL-…-ARSBSAKA7``, the code without
its line) onto Optic ``first_goal_scorer``, under exactly the anytime rules.

These are guesses: Kalshi lists the markets only shortly before kick-off and
codes change between games, so ``goalscorer.listing`` moves any guess Kalshi
doesn't list.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from goalscorer import codes
from goalscorer.config import FIRST_GOAL_MARKET_ID, MAPPING_SOURCE, MARKET_ID, MULTI_GOAL_LINES, OVERRIDE_SOURCE, League
from goalscorer.context import Context
from goalscorer.models import Fixture, GoalMapping, LineMapping, Moneyline, OverrideState
from goalscorer.overrides import override_message, player_goals_message
from goalscorer.timeutil import day_window, utcnow

logger = logging.getLogger(__name__)

# fixture, its moneyline → Kalshi goal series to map it under (None = skip)
PrefixFor = Callable[[Fixture, Moneyline], str | None]
# (selections never to override, our own active overrides selection → ticker)
Covered = tuple[set[str], dict[str, str]]
# The same for player_goals lines, keyed by (selection, points).
LineCovered = tuple[set[tuple[str, float]], dict[tuple[str, float], str]]


@dataclass(frozen=True)
class Planned:
    """One override to publish.

    player_goals over `points` when points is set, else `market_id` (anytime or first goalscorer).
    """

    game_id: str
    selection: str
    ticker: str
    points: float = 0.0
    market_id: str = MARKET_ID

    @property
    def is_anytime(self) -> bool:
        """True for an anytime_goal_scorer override."""
        return self.points == 0.0 and self.market_id == MARKET_ID

    @property
    def is_first_goal(self) -> bool:
        """True for a first_goal_scorer override."""
        return self.points == 0.0 and self.market_id == FIRST_GOAL_MARKET_ID

    def message(self) -> dict:
        """The mapping_override payload for this override."""
        if self.points:
            return player_goals_message(self.game_id, self.selection, self.ticker, self.points)
        return override_message(self.game_id, self.selection, self.ticker, market_id=self.market_id)


@dataclass
class GameOutcome:
    """What a run did (or would do) for one fixture."""

    fixture: Fixture
    planned: list[Planned] = field(default_factory=list)
    covered: int = 0
    line_covered: int = 0
    first_goal_covered: int = 0
    skipped: str | None = None

    @property
    def anytime_planned(self) -> int:
        """New anytime overrides."""
        return sum(1 for p in self.planned if p.is_anytime)

    @property
    def lines_planned(self) -> int:
        """New player_goals (2+ / 3+) overrides."""
        return sum(1 for p in self.planned if p.points)

    @property
    def first_goal_planned(self) -> int:
        """New first goalscorer overrides."""
        return sum(1 for p in self.planned if p.is_first_goal)


def known_players(history: Sequence[GoalMapping], team_abbrev: str) -> dict[str, GoalMapping]:
    """selection → its newest row carrying this team's code (ORIGINAL wins a tie)."""
    ordered = sorted(history, key=lambda m: (m.start_date, m.mapping_source == "ORIGINAL"), reverse=True)
    players: dict[str, GoalMapping] = {}
    for mapping in ordered:
        # legacy: ticker parse — replace with the typed venue field, do not extend
        if mapping.selection not in players and codes.player_code(mapping.ticker).startswith(team_abbrev):
            players[mapping.selection] = mapping
    return players


def match_players(fixture: Fixture, moneyline: Moneyline, history: dict[str, list[GoalMapping]]) -> dict[str, str]:
    """selection → anytime player code across both teams; a player in both histories takes his newest club's code."""
    newest: dict[str, GoalMapping] = {}
    for team, competitor_id in ((fixture.home_name, fixture.home_id), (fixture.away_name, fixture.away_id)):
        for selection, row in known_players(history.get(competitor_id, []), moneyline.teams[team]).items():
            if selection not in newest or row.start_date > newest[selection].start_date:
                newest[selection] = row
    return {selection: codes.anytime_code(codes.player_code(row.ticker)) for selection, row in newest.items()}


def untouchable(existing: Sequence[GoalMapping], overrides: Sequence[OverrideState]) -> Covered:
    """(selections to never override, our own active overrides selection → ticker)."""
    fixed = {m.selection for m in existing if m.mapping_source == "ORIGINAL"}
    ours: dict[str, str] = {}
    for state in overrides:
        if state.source == OVERRIDE_SOURCE and state.active:
            ours[state.selection] = state.ticker
        else:
            fixed.add(state.selection)
    return fixed, ours


def line_untouchable(existing: Sequence[LineMapping], overrides: Sequence[OverrideState]) -> LineCovered:
    """((selection, points) never to override, our own active line overrides → ticker).

    Any row another mapper wrote (the Kalshi mapper's GREG rows, Optic's ORIGINAL) and
    any override from another source is left alone; rows we wrote are judged by our override.
    """
    fixed = {(m.selection, m.points) for m in existing if m.mapping_source != MAPPING_SOURCE}
    ours: dict[tuple[str, float], str] = {}
    for state in overrides:
        key = (state.selection, state.points)
        if state.source == OVERRIDE_SOURCE and state.active:
            ours[key] = state.ticker
        else:
            fixed.add(key)
    return fixed, ours


def plan_game(
    fixture: Fixture,
    goal_prefix: str | None,
    moneyline: Moneyline | None,
    history: dict[str, list[GoalMapping]],
    covered: Covered,
    line_covered: LineCovered | None = None,
    first_goal_covered: Covered | None = None,
) -> GameOutcome:
    """Plan the anytime, player_goals 1.5 / 2.5 and first goalscorer overrides for one fixture."""
    outcome = GameOutcome(fixture)
    if moneyline is None:
        outcome.skipped = "no Kalshi moneyline mapping"
        return outcome
    if goal_prefix is None:
        outcome.skipped = f"no goalscorer series for {moneyline.series}"
        return outcome
    missing = [t for t in (fixture.home_name, fixture.away_name) if not moneyline.teams.get(t)]
    if missing:
        outcome.skipped = f"moneyline mapping has no Kalshi abbreviation for {', '.join(missing)}"
        return outcome
    fixed, ours = covered
    line_fixed, line_ours = line_covered or (set(), {})
    first_fixed, first_ours = first_goal_covered or (set(), {})
    first_prefix = codes.first_goal_prefix(goal_prefix)
    for selection, code in match_players(fixture, moneyline, history).items():
        ticker = codes.build_ticker(goal_prefix, moneyline.fixture_part, code)
        if selection in fixed or ours.get(selection) == ticker:
            outcome.covered += 1
        else:
            outcome.planned.append(Planned(fixture.game_id, selection, ticker))
        for line, points in MULTI_GOAL_LINES.items():
            line_ticker = codes.build_ticker(goal_prefix, moneyline.fixture_part, codes.line_code(code, line))
            key = (selection, points)
            if key in line_fixed or line_ours.get(key) == line_ticker:
                outcome.line_covered += 1
            else:
                outcome.planned.append(Planned(fixture.game_id, selection, line_ticker, points))
        first_ticker = codes.build_ticker(first_prefix, moneyline.fixture_part, code.split("-")[0])
        if selection in first_fixed or first_ours.get(selection) == first_ticker:
            outcome.first_goal_covered += 1
        else:
            outcome.planned.append(Planned(fixture.game_id, selection, first_ticker, market_id=FIRST_GOAL_MARKET_ID))
    return outcome


def _by_game(rows):
    """Group rows by game_id."""
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.game_id, []).append(row)
    return grouped


def map_fixtures(ctx: Context, fixtures: Sequence[Fixture], prefix_for: PrefixFor) -> list[GameOutcome]:
    """Plan and publish overrides for these fixtures."""
    if not fixtures:
        return []
    now = utcnow()
    game_ids = [f.game_id for f in fixtures]
    lo = min(f.start_date for f in fixtures) - timedelta(days=1)
    hi = max(f.start_date for f in fixtures) + timedelta(days=1)
    moneylines = ctx.store.moneylines(game_ids, lo, hi)
    competitors = sorted({c for f in fixtures for c in (f.home_id, f.away_id)})
    history = ctx.store.team_history(competitors, now - timedelta(days=ctx.settings.lookback_days), now)
    existing = _by_game(ctx.store.goal_mappings(game_ids, lo, hi))
    overrides = _by_game(ctx.store.latest_overrides(game_ids))
    line_existing = _by_game(ctx.store.line_mappings(game_ids, lo, hi))
    line_overrides = _by_game(ctx.store.latest_line_overrides(game_ids))
    first_existing = _by_game(ctx.store.goal_mappings(game_ids, lo, hi, FIRST_GOAL_MARKET_ID))
    first_overrides = _by_game(ctx.store.latest_overrides(game_ids, FIRST_GOAL_MARKET_ID))
    outcomes = []
    for fx in fixtures:
        ml = moneylines.get(fx.game_id)
        prefix = prefix_for(fx, ml) if ml else None
        covered = untouchable(existing.get(fx.game_id, []), overrides.get(fx.game_id, []))
        line_covered = line_untouchable(line_existing.get(fx.game_id, []), line_overrides.get(fx.game_id, []))
        first_covered = untouchable(first_existing.get(fx.game_id, []), first_overrides.get(fx.game_id, []))
        outcomes.append(plan_game(fx, prefix, ml, history, covered, line_covered, first_covered))
    ctx.publisher.publish([p.message() for o in outcomes for p in o.planned])
    return outcomes


def registered_prefix(leagues: dict[str, League]) -> PrefixFor:
    """Prefix lookup for scheduled runs: the league's registered goal series."""

    def prefix_for(fixture: Fixture, _ml: Moneyline) -> str | None:
        league = leagues.get(fixture.league_id)
        return league.goal_prefix if league else None

    return prefix_for


def run_pregame(ctx: Context, day: date, league_ids: Sequence[str] | None = None) -> list[GameOutcome]:
    """Map every registered-league fixture from `day` through GOALSCORER_PREGAME_DAYS_AHEAD."""
    leagues = ctx.leagues.active()
    if league_ids is not None:
        leagues = {k: v for k, v in leagues.items() if k in league_ids}
    since, until = day_window(day, days=1 + ctx.settings.days_ahead)
    fixtures = ctx.store.fixtures(since, until, leagues.keys())
    logger.info("pregame %s: %d fixtures across %d leagues", day, len(fixtures), len(leagues))
    outcomes = map_fixtures(ctx, fixtures, registered_prefix(leagues))
    for o in outcomes:
        logger.info(
            "  %s: %d new, %d covered; 2+/3+ lines %d new, %d covered; first goal %d new, %d covered%s",
            o.fixture.label,
            o.anytime_planned,
            o.covered,
            o.lines_planned,
            o.line_covered,
            o.first_goal_planned,
            o.first_goal_covered,
            f" (skipped: {o.skipped})" if o.skipped else "",
        )
    return outcomes


def summary_text(title: str, outcomes: Sequence[GameOutcome], dry_run: bool = False) -> str:
    """Slack mrkdwn summary of a pre-game run."""
    published = sum(len(o.planned) for o in outcomes)
    verb = "would publish" if dry_run else "published"
    lines = [f":soccer: *{title}* — {verb} {published} mapping(s)"]
    for o in outcomes:
        when = o.fixture.start_date.strftime("%a %d %b %H:%M")
        if o.skipped:
            lines.append(f"• {o.fixture.label} ({when} UTC): skipped — {o.skipped}")
        else:
            lines.append(
                f"• {o.fixture.label} ({when} UTC): {o.anytime_planned} new, {o.covered} already covered"
                f" · 2+/3+ lines: {o.lines_planned} new, {o.line_covered} already covered"
                f" · first goal: {o.first_goal_planned} new, {o.first_goal_covered} already covered"
            )
    return "\n".join(lines)

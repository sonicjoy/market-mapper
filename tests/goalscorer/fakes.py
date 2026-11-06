"""In-memory stand-ins for the goalscorer store, registry, publisher and Slack."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, cast

from goalscorer.config import DEFAULT_LEAGUES, MARKET_ID, OVERRIDE_SOURCE, League, Settings
from goalscorer.context import Context
from goalscorer.models import (
    Fixture,
    GoalMapping,
    KnowledgeRow,
    LineKnowledgeRow,
    LineMapping,
    Moneyline,
    OverrideState,
)

KICKOFF = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)


def fixture(game_id: str = "g1", start: datetime = KICKOFF, league: str = "england_-_premier_league") -> Fixture:
    """Arsenal (c-ars) vs Chelsea (c-che) unless overridden."""
    return Fixture(game_id, start, league, "Arsenal", "c-ars", "Chelsea", "c-che")


def moneyline(part: str = "26SEP26ARSCHE", series: str = "KXEPLGAME") -> Moneyline:
    """Kalshi moneyline for Arsenal vs Chelsea."""
    return Moneyline(part, series, {"Arsenal": "ARS", "Chelsea": "CHE"})


def goal(
    game_id: str, selection: str, code: str, *, day: int = 1, source: str = "ORIGINAL", part: str = "26AUG01ARSMUN"
) -> GoalMapping:
    """A Kalshi goalscorer row from an earlier game."""
    start = datetime(2026, 8, day, 15, 0, tzinfo=UTC)
    return GoalMapping(game_id, start, selection, source, f"KXEPLGOAL-{part}-{code}")


@dataclass
class FakeStore:
    """GoalscorerStore over lists; records inserts."""

    fixture_rows: list[Fixture] = field(default_factory=list)
    moneyline_rows: dict[str, Moneyline] = field(default_factory=dict)
    history: dict[str, list[GoalMapping]] = field(default_factory=dict)
    mappings: list[GoalMapping] = field(default_factory=list)
    overrides: list[OverrideState] = field(default_factory=list)
    line_rows: list[LineMapping] = field(default_factory=list)
    line_overrides: list[OverrideState] = field(default_factory=list)
    first_goal_rows: list[GoalMapping] = field(default_factory=list)
    first_goal_overrides: list[OverrideState] = field(default_factory=list)
    names: dict[str, set[str]] = field(default_factory=dict)
    tickers: list[str] = field(default_factory=list)
    part_games: dict[str, list[str]] = field(default_factory=dict)
    inserted: list[KnowledgeRow] = field(default_factory=list)
    inserted_lines: list[LineKnowledgeRow] = field(default_factory=list)
    inserted_first_goal: list[KnowledgeRow] = field(default_factory=list)
    client: Any = None

    def fixtures(self, since, until, league_ids):
        ids = set(league_ids)
        return [f for f in self.fixture_rows if f.league_id in ids and since <= f.start_date < until]

    def fixture_by_ref(self, ref, since, until):
        return next((f for f in self.fixture_rows if f.game_id == ref and since <= f.start_date < until), None)

    def games_for_fixture_part(self, part, since, until):
        return self.part_games.get(part, [])

    def moneylines(self, game_ids, since, until):
        return {g: m for g, m in self.moneyline_rows.items() if g in game_ids}

    def goal_mappings(self, game_ids, since, until, market_id=MARKET_ID):
        rows = self.mappings if market_id == MARKET_ID else self.first_goal_rows
        return [m for m in rows if m.game_id in game_ids]

    def held_rows(self, game_ids, since, until):
        lines = [GoalMapping(m.game_id, KICKOFF, m.selection, m.mapping_source, m.ticker) for m in self.line_rows]
        return [m for m in (*self.mappings, *self.first_goal_rows, *lines) if m.game_id in game_ids]

    def line_mappings(self, game_ids, since, until):
        return [m for m in self.line_rows if m.game_id in game_ids]

    def latest_line_overrides(self, game_ids):
        return [o for o in self.line_overrides if o.game_id in game_ids]

    def line_overrides_since(self, since, source):
        games = {o.game_id for o in self.line_overrides if o.source == source}
        return [o for o in self.line_overrides if o.game_id in games]

    def team_history(self, competitor_ids, since, until):
        return {
            c: [m for m in rows if since <= m.start_date < until]
            for c, rows in self.history.items()
            if c in competitor_ids
        }

    def sportsbook_names(self, game_ids, since, until):
        return {g: n for g, n in self.names.items() if g in game_ids}

    def goal_leg_tickers(self, prefixes, fixtures, since, until):
        return [t for t in self.tickers if t.split("-")[0] in prefixes and t.split("-")[1] in fixtures]

    def _overrides(self, market_id):
        return self.overrides if market_id == MARKET_ID else self.first_goal_overrides

    def latest_overrides(self, game_ids, market_id=MARKET_ID):
        return [o for o in self._overrides(market_id) if o.game_id in game_ids]

    def overrides_since(self, since, source, market_id=MARKET_ID):
        states = self._overrides(market_id)
        games = {o.game_id for o in states if o.source == source}
        return [o for o in states if o.game_id in games]

    def insert_knowledge(self, rows, market_id=MARKET_ID):
        (self.inserted if market_id == MARKET_ID else self.inserted_first_goal).extend(rows)
        return len(rows)

    def insert_line_knowledge(self, rows):
        self.inserted_lines.extend(rows)
        return len(rows)


@dataclass
class FakeLeagues:
    """LeagueRegistry over a dict; records adds."""

    leagues: dict[str, League] = field(default_factory=lambda: {lg.league_id: lg for lg in DEFAULT_LEAGUES})
    optic: dict[str, tuple[str, str]] = field(default_factory=dict)
    derived: dict[str, str] = field(default_factory=dict)
    added: list[tuple[League, str]] = field(default_factory=list)

    def active(self):
        return dict(self.leagues)

    def add(self, league, added_by, *, active=True):
        self.added.append((league, added_by))
        self.leagues[league.league_id] = league

    def optic_league(self, league_id):
        return self.optic.get(league_id)

    def derived_goal_prefix(self, league_id):
        return self.derived.get(league_id)


@dataclass
class FakePublisher:
    """Collects override messages and the source attribute each was published with."""

    published: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def publish(self, messages, source=OVERRIDE_SOURCE):
        self.published.extend(messages)
        self.sources.extend(source for _ in messages)
        return len(messages)


@dataclass
class FakeSlack:
    """Collects Slack posts and uploads."""

    posts: list[tuple[str, list[dict] | None]] = field(default_factory=list)
    uploads: list[tuple[Any, str, str]] = field(default_factory=list)

    def post(self, text, blocks=None, thread_ts=None):
        self.posts.append((text, blocks))
        return f"{len(self.posts)}.0"

    def upload(self, path, title, comment):
        self.uploads.append((path, title, comment))
        return True


def make_ctx(store: FakeStore | None = None, leagues: FakeLeagues | None = None, **settings: Any) -> Context:
    """A Context wired to fakes (reach them back through ctx.store etc.)."""
    base = Settings(project="marketmaking-test", slack_channel_id="C1", approver_ids=frozenset())
    return Context(
        settings=replace(base, **settings),
        store=cast(Any, store or FakeStore()),
        leagues=cast(Any, leagues or FakeLeagues()),
        publisher=cast(Any, FakePublisher()),
        slack=cast(Any, FakeSlack()),
    )

"""Records passed between the store, the planners, and Slack."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Fixture:
    """One Optic fixture (latest published row per game_id)."""

    game_id: str
    start_date: datetime
    league_id: str
    home_name: str
    home_id: str
    away_name: str
    away_id: str

    @property
    def label(self) -> str:
        """Human-readable 'Home vs Away'."""
        return f"{self.home_name} vs {self.away_name}"


@dataclass(frozen=True)
class Moneyline:
    """Kalshi moneyline mapping for one game: fixture part + team abbreviations."""

    fixture_part: str
    series: str
    teams: dict[str, str]  # Optic selection (team name) → Kalshi abbreviation


@dataclass(frozen=True)
class GoalMapping:
    """One Kalshi anytime_goal_scorer row in opticodds_mapping."""

    game_id: str
    start_date: datetime
    selection: str
    mapping_source: str
    ticker: str


@dataclass(frozen=True)
class LineMapping:
    """One Kalshi player_goals row (over 1.5 / 2.5) in opticodds_mapping."""

    game_id: str
    selection: str
    points: float
    mapping_source: str
    ticker: str


@dataclass(frozen=True)
class OverrideState:
    """Latest mapping_override message for one (game, selection[, points]) key."""

    game_id: str
    selection: str
    ticker: str
    active: bool
    source: str
    points: float = 0.0  # player_goals line; 0 for anytime


@dataclass(frozen=True)
class KnowledgeRow:
    """A player code → selection fact, written to opticodds_mapping for a past game."""

    game_id: str
    start_date: datetime
    sport: str
    league: str
    selection: str
    ticker: str


@dataclass(frozen=True)
class LineKnowledgeRow:
    """A player's 2+ / 3+ ticker → player_goals over `points`, written for a past game."""

    game_id: str
    start_date: datetime
    sport: str
    league: str
    selection: str
    ticker: str
    points: float


@dataclass
class ReviewItem:
    """A player code from a played game that no anytime mapping covers.

    One item per player: `ticker` / `player_code` are always his 1+ (anytime) line,
    whichever of his 1+ / 2+ / 3+ / first goalscorer markets actually traded.
    """

    game_id: str
    start_date: datetime
    sport: str
    league: str
    game_label: str
    player_code: str
    ticker: str
    suggested: str | None = None
    ranked: list[tuple[str, int]] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)

    @property
    def base_code(self) -> str:
        """Player code without its goal line (MCIEHAALA9-1 → MCIEHAALA9)."""
        return self.player_code.rsplit("-", 1)[0]

    def knowledge(self, selection: str) -> KnowledgeRow:
        """The row that records this ticker as `selection`."""
        return KnowledgeRow(self.game_id, self.start_date, self.sport, self.league, selection, self.ticker)

    def first_goal_knowledge(self, selection: str, first_goal_ticker: str) -> KnowledgeRow:
        """The first_goal_scorer row recording this player's first goalscorer ticker as `selection`."""
        return KnowledgeRow(self.game_id, self.start_date, self.sport, self.league, selection, first_goal_ticker)

    def line_knowledge(self, selection: str, lines: dict[str, float]) -> list[LineKnowledgeRow]:
        """The player_goals rows recording this player's other goal lines (`lines`: line → points) as `selection`."""
        # legacy: ticker parse — replace with the typed venue field, do not extend
        base = self.ticker.rsplit("-", 1)[0]
        return [
            LineKnowledgeRow(
                self.game_id, self.start_date, self.sport, self.league, selection, f"{base}-{line}", points
            )
            for line, points in lines.items()
        ]

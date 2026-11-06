"""Map STX's catalogue onto Optic: one decision per side (YES / NO) of every STX market, mapped or with a reason.

Order per market, first refusal wins (``reason`` = ``"<code>: <detail>"``):

1. **family** (``vocab/stx_markets.rule_for``) -- unknown rules, excluded family, unknown or held competition,
   held / unreviewed family, unknown statistic. Structural, so the reason does not depend on the clock.
2. **event** -- a game event, the market ``open`` or ``suspended``, ``event_status == scheduled`` and a kickoff after
   ``as_of``. Started events with open markets exist on STX (26 on Ontario demo, 2026-10-28).
3. **fixture** (``stx_fixtures.join_event``) -- exactly one Optic fixture, same orientation.
4. **side** (``stx.yes_outcome`` / ``no_outcome``) -- NO on a 3-way leg is a double chance: not mapped.
5. **player** (``stx_players.resolve_player``) -- props only.

A mapped side carries mmmapper's canonical key (``market_type``, ``entity``, ``line``, ``side``) on the Optic fixture
plus the Optic market id and competitor / player id. ``market_mapping_row`` writes it in ``markets_us.market_mapping``
column shape with ``sportsbook = "STX"`` and ``source_ids = {market_id, selection_id: yes|no, event_id}``. The Optic
``game_id``, ``selection`` and ``grouping_key`` come from the Optic odd the row attaches to in the pipeline, so they
are None here; this module writes nothing to BigQuery.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mappers.exchanges.stx import (
    AWAY,
    HOME,
    MAPPABLE_EVENT_STATUS,
    MAPPABLE_MARKET_STATUS,
    NO,
    SPORTSBOOK,
    YES,
    StxMarket,
    StxOutcome,
    is_game_event,
    no_outcome,
    yes_outcome,
)
from mappers.exchanges.stx_fixtures import FixtureJoin, OpticFixtureRef, index_fixtures, join_market_event
from mappers.exchanges.stx_leagues import SPORT_BY_STX_SPORT, competition_for, league_label
from mappers.exchanges.stx_players import PlayerMatch, Roster, resolve_player
from mappers.market_types import Scope, Shape
from mappers.shared import TIE_SIDE, normalize_player_name, parse_iso_datetime
from mappers.vocab.stx_markets import FAMILY_BY_RULES, StxMarketRule, rule_for

FIXTURE_MATCH_METHOD = "stx_kickoff_both_teams"
MARKET_MATCH_METHOD = "stx_rules"
PLAYER_MATCH_METHOD = "stx_player_exact_name"


@dataclass(frozen=True)
class StxSideMapping:
    """One side of one STX market: mapped (``reason`` None) or the reason it is not."""

    market: StxMarket
    side: str
    reason: str | None = None
    fixture: OpticFixtureRef | None = None
    rule: StxMarketRule | None = None
    entity: str | None = None
    line: float | None = None
    selection_side: str | None = None
    selection_line: str | None = None
    optic_team_id: str | None = None
    optic_player_id: str | None = None

    @property
    def mapped(self) -> bool:
        """True when this side maps onto an Optic selection."""
        return self.reason is None

    @property
    def reason_code(self) -> str:
        """The reason's code (``no_fixture``, ``family_held``, ...); ``mapped`` when mapped."""
        return "mapped" if self.reason is None else self.reason.split(":", 1)[0]


@dataclass
class StxTally:
    """Counts for one pass: events joined, sides mapped per (competition, family), sides refused per reason code."""

    events: int = 0
    joined_events: int = 0
    mapped: Counter = field(default_factory=Counter)
    refused: Counter = field(default_factory=Counter)

    def add(self, s: StxSideMapping) -> None:
        """Count one side."""
        if s.mapped:
            self.mapped[(s.market.competition, s.rule.family if s.rule else "")] += 1
        else:
            self.refused[s.reason_code] += 1

    def lines(self) -> list[str]:
        """The stderr summary."""
        head = (
            f"  stx: {self.joined_events}/{self.events} game events joined, {sum(self.mapped.values())} sides "
            f"mapped, {sum(self.refused.values())} refused"
        )
        mapped = [f"    mapped {c} {f}: {n}" for (c, f), n in sorted(self.mapped.items())]
        refused = [f"    refused {code}: {n}" for code, n in self.refused.most_common()]
        return [head, *mapped, *refused]


@dataclass
class StxContext:
    """Everything one pass reads besides the catalogue."""

    fixtures: list[OpticFixtureRef]
    as_of: datetime
    rosters: dict[str, Roster | None] = field(default_factory=dict)
    optic_players: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    pins: dict[tuple[str, str], str] | None = None


def event_gate(m: StxMarket, as_of: datetime) -> str | None:
    """Why the market or its event cannot be mapped now, or None."""
    if not is_game_event(m):
        return f"not_a_game: {m.event_type}"
    if m.status not in MAPPABLE_MARKET_STATUS:
        return f"market_not_open: {m.status}"
    if m.event_status != MAPPABLE_EVENT_STATUS:
        return f"event_not_scheduled: {m.event_status}"
    if parse_iso_datetime(m.event_start) <= as_of:
        return f"event_started: {m.event_start}"
    return None


def _team_key(outcome: StxOutcome, fx: OpticFixtureRef, shape: Shape) -> tuple[Any, ...] | None:
    team = fx.home if outcome.role == HOME else fx.away if outcome.role == AWAY else None
    if team is None:
        return None
    if shape in (Shape.MONEYLINE, Shape.THREE_WAY) and outcome.line is None:
        return None, None, team.code, None, team.id
    if shape == Shape.SPREAD and outcome.line is not None:
        return None, outcome.line, team.code, None, team.id
    return None


def _total_key(
    outcome: StxOutcome, fx: OpticFixtureRef, rule: StxMarketRule, player: PlayerMatch | None
) -> tuple[Any, ...] | None:
    mt = rule.market_type
    if mt.shape == Shape.TOTAL and mt.scope == Scope.GAME and outcome.role is None and outcome.player is None:
        return None, outcome.line, outcome.kind, outcome.kind, None
    if mt.shape == Shape.TOTAL and mt.scope == Scope.TEAM and outcome.role in (HOME, AWAY):
        team = fx.home if outcome.role == HOME else fx.away
        return team.code, outcome.line, outcome.kind, outcome.kind, team.id
    if mt.shape == Shape.OVER_UNDER and mt.scope == Scope.PLAYER and player is not None:
        return normalize_player_name(player.optic_name), outcome.line, outcome.kind, outcome.kind, None
    return None


def canonical_key(
    outcome: StxOutcome, fx: OpticFixtureRef, rule: StxMarketRule, player: PlayerMatch | None = None
) -> tuple[Any, ...] | None:
    """``(entity, line, side, selection_line, optic_team_id)`` on mmmapper's key, or None when the shape disagrees."""
    shape = rule.market_type.shape
    if outcome.kind == "draw":
        return (None, None, TIE_SIDE, None, None) if shape == Shape.THREE_WAY else None
    if outcome.kind == "team":
        return _team_key(outcome, fx, shape)
    return _total_key(outcome, fx, rule, player)


def _side_outcome(m: StxMarket, side: str) -> StxOutcome | str:
    outcome = yes_outcome(m) if side == YES else no_outcome(m)
    if outcome is not None:
        return outcome
    if side == NO and yes_outcome(m) is not None:
        return f"no_side: NO on {m.rules} is not one Optic selection"
    return f"unreadable_market: {m.rules} {m.specifier!r}"


def _map_side(m: StxMarket, side: str, rule: StxMarketRule, fx: OpticFixtureRef, ctx: StxContext) -> StxSideMapping:
    outcome = _side_outcome(m, side)
    if isinstance(outcome, str):
        return StxSideMapping(m, side, outcome, fx, rule)
    player = None
    if outcome.player is not None:
        teams = tuple(p.name for p in m.participants if p.role in (HOME, AWAY))
        found = resolve_player(outcome.player, teams, ctx.rosters.get(m.event_id), ctx.optic_players.get(fx.fixture_id))
        if isinstance(found, str):
            return StxSideMapping(m, side, found, fx, rule)
        player = found
    key = canonical_key(outcome, fx, rule, player)
    if key is None:
        return StxSideMapping(m, side, f"shape_mismatch: {m.rules} on {rule.market_type.value}", fx, rule)
    entity, line, sel_side, sel_line, team_id = key
    return StxSideMapping(
        m,
        side,
        None,
        fx,
        rule,
        entity=entity,
        line=line,
        selection_side=sel_side,
        selection_line=sel_line,
        optic_team_id=team_id,
        optic_player_id=player.optic_player_id if player else None,
    )


def _market_sides(m: StxMarket, ctx: StxContext, index: dict, joins: dict[str, FixtureJoin]) -> list[StxSideMapping]:
    comp = competition_for(m.competition, m.sport)
    rule = rule_for(m, comp)
    refusal = rule if isinstance(rule, str) else event_gate(m, ctx.as_of)
    fx = None
    if refusal is None and comp is not None:
        join = joins.get(m.event_id)
        if join is None:
            join = joins[m.event_id] = join_market_event(m, comp, index, ctx.pins)
        refusal, fx = join.reason, join.fixture
    if isinstance(rule, str) or fx is None:
        return [StxSideMapping(m, s, refusal or "no_fixture: not joined") for s in (YES, NO)]
    return [_map_side(m, s, rule, fx, ctx) for s in (YES, NO)]


def run_pass(markets: Iterable[StxMarket], ctx: StxContext) -> tuple[list[StxSideMapping], StxTally]:
    """Both sides of every market in ``markets``, and the tally."""
    index = index_fixtures(ctx.fixtures)
    joins: dict[str, FixtureJoin] = {}
    tally = StxTally()
    out: list[StxSideMapping] = []
    for m in markets:
        for s in _market_sides(m, ctx, index, joins):
            tally.add(s)
            out.append(s)
    tally.events = len(joins)
    tally.joined_events = sum(1 for j in joins.values() if j.fixture is not None)
    return out, tally


def market_mapping_row(s: StxSideMapping) -> dict[str, Any]:
    """One ``markets_us.market_mapping``-shaped row (plus ``mapping_status`` / ``reason``) for one side."""
    m, fx, comp = s.market, s.fixture, competition_for(s.market.competition, s.market.sport)
    sport = SPORT_BY_STX_SPORT.get(m.sport)
    return {
        "sport": sport.value if sport else None,
        "league": league_label(comp, fx.league_id) if comp and fx else (comp.slug if comp else None),
        "start_date": fx.start_date if fx else None,
        "home": fx.home.code if fx else None,
        "away": fx.away.code if fx else None,
        "market_type": s.rule.market_type.value if s.mapped and s.rule else None,
        "entity": s.entity,
        "line": s.line,
        "side": s.selection_side,
        "group_key": None,
        "sportsbook": SPORTSBOOK,
        "game_id": None,
        "fixture_id": fx.fixture_id if fx and s.mapped else None,
        "market_id": s.rule.optic_market_id if s.mapped and s.rule else None,
        "selection": None,
        "selection_line": s.selection_line,
        "points": s.line,
        "grouping_key": None,
        "last_updated": None,
        "source_ids": {"market_id": m.market_id, "selection_id": s.side, "event_id": m.event_id},
        "fixture_match_method": FIXTURE_MATCH_METHOD if s.mapped else None,
        "market_match_method": (PLAYER_MATCH_METHOD if s.optic_player_id else MARKET_MATCH_METHOD)
        if s.mapped
        else None,
        "optic_team_id": s.optic_team_id,
        "optic_player_id": s.optic_player_id,
        "flags": list(s.rule.flags) if s.mapped and s.rule else [],
        "mapping_status": "mapped" if s.mapped else "unmapped",
        "reason": s.reason,
        "stx_family": FAMILY_BY_RULES.get(m.rules),
    }

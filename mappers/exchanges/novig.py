"""Novig (NBX) exchange: parse the market feed and key it to Optic.

Novig is a peer-to-peer sports exchange.  Unlike every other source we
map, its API hands us **OpticOdds ids directly**:

* ``event.opticOddsId``      == Optic ``fixture_id``   (verified 5/5 against
  ``markets_us.market_mapping`` on 2026-08-14; 100% populated across 2,292
  non-future events)
* ``competitor.opticOddsId`` == Optic team id (the ``Fixture.team_map`` key)
* ``player.opticOddsId``     == Optic ``Odd.player_id``

So fixture/team/player resolution is an **id join**, not the
``MatchKey(date, home, away)`` name matching Kalshi / PX / Polymarket rely
on.  There is no ``config/<league>/team_aliases.toml`` entry to maintain
for Novig and no name-normalization drift to chase: if the id is absent or
unknown to this run's Optic schedule, we drop the market rather than guess.

The line is an explicit numeric ``strike`` field, so there is no ticker
suffix to decode and no per-series ``line_offset`` to reverse-engineer
(the Kalshi N-0.5 headache simply does not exist here).

Two structural rules from the API that are easy to get wrong:

1. **Over/under and yes/no use ``outcome.index``, never array order.**
   ``index 0`` = Over / Yes, ``index 1`` = Under / No, and ``outcomes[]``
   is not returned in index order. A team moneyline takes its side from
   the competitor's Optic id and is dropped when either id is missing. A
   spread uses those ids when either outcome has one: index 0 must be home
   and index 1 away. Only a spread with no id on either outcome falls back
   to outcome type, and only when that type is Home then Away.

2. **Three-way soccer is not one Home/Away market.**  Each result is its
   own Yes/No market -- ``MONEYLINE_3_WAY_WIN`` (home), ``..._WIN`` (away),
   ``MONEYLINE_3_WAY_DRAW`` -- where ``No`` means "any other result
   including the draw", which has no canonical counterpart.  So a
   ``Shape.THREE_WAY`` type emits a SINGLE affirmative row keyed off the
   market's ``competitor`` (or ``_TIE`` for the draw market) and drops the
   ``No`` leg.  This mirrors Polymarket's ``THREE_WAY_FIXED`` handling.

3. **UFC victory-method markets carry the method in the TYPE.**  Novig
   ships one Yes/No market per method (``VICTORY_BY_KO_KTO_OR_DQ`` /
   ``VICTORY_BY_SUBMISSION`` / ``VICTORY_BY_DECISION``), each with
   ``market.competitor``.  That is ``METHOD_OF_VICTORY``'s shape, so the
   method is resolved from ``market.type`` and written to ``grouping_key``
   -- which is part of ``pipeline.row_key``.  Omit it and a fighter's three
   method markets share one key and merge three contracts into one row.

Rows built here are stamped onto existing Optic rows by
``pipeline.attach_novig_row`` -- a market Optic did not price is dropped
(same guard #3 discipline as Polymarket).  The source-id stamp is the
outcome id; see ``docs/adding-novig.md``.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from mappers.fight_props import is_emittable_method, novig_method_key
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import TIE_SIDE, CanonicalRow
from mappers.team_side import team_side

# Novig outcome.index is the side signal for over/under and yes/no.
HOME_OVER_YES_INDEX = 0
AWAY_UNDER_NO_INDEX = 1


# === League config ===

def novig_league_key(league: str) -> str:
    """Canonical league comparison key: Novig's casing is not ours."""
    return league.strip().casefold()


@dataclass(frozen=True)
class NovigConfig:
    """League-specific constants for Novig market classification."""

    #: Novig's own league string, e.g. "WNBA", "Champions League".  Used by
    #: fetch/novig.py to filter the events feed and by the pipeline to keep
    #: another league's markets out of this league's pass.
    league: str
    #: Novig ``market.type`` -> canonical MarketType.
    market_types: dict[str, MarketType]
    #: Novig ``market.type`` values we deliberately do NOT map (futures,
    #: awards, and anything with no clean Optic target).  Enumerating them
    #: keeps the unknown-type warning meaningful -- same discipline as
    #: every other venue's explicit ignore list.
    ignored_types: frozenset[str] = field(default_factory=frozenset)


# === Feed model ===

class NovigCompetitor(BaseModel):
    """A team on a Novig outcome or market."""

    model_config = {"extra": "allow"}

    id: str = ""
    name: str = ""
    shortName: str = ""  # noqa: N815 — Novig JSON field
    opticOddsId: str | None = None  # noqa: N815 — Novig JSON field


class NovigPlayer(BaseModel):
    """A player on a Novig player-prop market."""

    model_config = {"extra": "allow"}

    id: str = ""
    name: str = ""
    fullName: str = ""  # noqa: N815 — Novig JSON field
    opticOddsId: str | None = None  # noqa: N815 — Novig JSON field


class NovigOutcome(BaseModel):
    """One tradeable side of a Novig market."""

    model_config = {"extra": "allow"}

    id: str
    description: str = ""
    type: str = ""
    index: int
    competitor: NovigCompetitor | None = None


class NovigMarket(BaseModel):
    """One Novig market (a strike on an event) with its outcomes."""

    model_config = {"extra": "allow"}

    id: str
    type: str
    description: str = ""
    status: str = ""
    strike: float | None = None
    league: str = ""
    eventId: str  # noqa: N815 — Novig JSON field
    playerId: str | None = None  # noqa: N815 — Novig JSON field
    player: NovigPlayer | None = None
    competitor: NovigCompetitor | None = None
    outcomes: list[NovigOutcome] = []


class NovigEvent(BaseModel):
    """One Novig event; ``opticOddsId`` is the Optic fixture_id."""

    model_config = {"extra": "allow"}

    id: str
    type: str = ""
    status: str = ""
    description: str = ""
    league: str = ""
    scheduledStart: str = ""  # noqa: N815 — Novig JSON field
    opticOddsId: str | None = None  # noqa: N815 — Novig JSON field


def parse_market(line: str) -> NovigMarket | None:
    """Parse one JSON line (written by fetch/novig.py) into a NovigMarket."""
    try:
        return NovigMarket(**json.loads(line))
    except (ValueError, TypeError):
        return None


def parse_event(line: str) -> NovigEvent | None:
    """Parse one JSON line (written by fetch/novig.py) into a NovigEvent."""
    try:
        return NovigEvent(**json.loads(line))
    except (ValueError, TypeError):
        return None


# === Row building ===

def _by_index(market: NovigMarket) -> dict[int, NovigOutcome]:
    """{index: outcome}, or {} when the pair is not a clean 0/1.

    Anything other than exactly one index-0 and one index-1 outcome is
    flip-unsafe, so the caller drops the whole market rather than emit a
    side we cannot prove.
    """
    by_idx: dict[int, NovigOutcome] = {}
    for o in market.outcomes:
        if o.index in by_idx:
            return {}
        by_idx[o.index] = o
    if set(by_idx) != {HOME_OVER_YES_INDEX, AWAY_UNDER_NO_INDEX}:
        return {}
    return by_idx


def _stamp(market: NovigMarket, outcome: NovigOutcome) -> dict:
    """Shared novig_* stamp kwargs for a CanonicalRow.

    ``novig_outcome_id`` is the source-id stamp (the ``clob_token_id`` /
    ``kalshi_ticker`` analog); event and market ids are carried because
    Optic's own Novig ``source_ids`` use the same
    ``{event_id, market_id, selection_id}`` triple, so a constructed row and
    a passthrough row are indistinguishable downstream.
    """
    return {
        "novig_event_id": market.eventId,
        "novig_market_id": market.id,
        "novig_outcome_id": outcome.id,
        "novig_market_type": market.type,
        "novig_description": market.description,
    }


def _team_side(
    competitor: NovigCompetitor | None,
    team_map: dict[str, str],
) -> str | None:
    """Canonical abbrev for a Novig competitor, via its Optic team id."""
    if competitor is None or not competitor.opticOddsId:
        return None
    return team_map.get(competitor.opticOddsId)


def _entity(
    market: NovigMarket,
    scope: Scope,
    team_map: dict[str, str],
    player_names: dict[str, str],
) -> tuple[bool, str | None]:
    """``(resolved, entity)`` for a market's scope -- False drops it whole.

    A ``None`` entity is CORRECT for GAME scope, so an unresolved id cannot
    be signalled by the entity alone; hence the flag.  ``team_map`` is the
    fixture's {optic_team_id: abbrev}; ``player_names`` is
    {optic_player_id: normalized_selection} harvested from this run's Optic
    odds, so a player entity is an id lookup rather than a name
    normalization that could drift from Optic's own spelling.
    """
    if scope == Scope.TEAM:
        entity = _team_side(market.competitor, team_map)
        return entity is not None, entity  # team we cannot resolve -> drop
    if scope == Scope.PLAYER:
        if market.player is None or not market.player.opticOddsId:
            return False, None
        entity = player_names.get(market.player.opticOddsId)
        return entity is not None, entity  # player Optic didn't price -> drop
    return True, None  # GAME


def _three_way_rows(
    market: NovigMarket,
    team_map: dict[str, str],
    row: Callable[..., CanonicalRow],
) -> list[CanonicalRow]:
    """One affirmative row; the "No" leg has no canonical twin."""
    affirmative = next(
        (o for o in market.outcomes if o.index == HOME_OVER_YES_INDEX), None)
    if affirmative is None:
        return []
    # The draw market carries no competitor; a win market's competitor
    # names the side the "Yes" leg backs.
    if market.competitor is None:
        side = TIE_SIDE
    else:
        resolved = _team_side(market.competitor, team_map)
        if resolved is None:
            return []
        side = resolved
    return [row(side, entity=None, line=None, outcome=affirmative)]


def _method_of_victory_rows(
    market: NovigMarket,
    entity: str | None,
    row: Callable[..., CanonicalRow],
) -> list[CanonicalRow]:
    """One affirmative fighter/method row; the "No" leg has no Optic twin.

    Novig ships one Yes/No market PER METHOD, so the method comes from
    ``market.type`` rather than a selection label, and it must reach
    ``grouping_key`` -- it is part of ``pipeline.row_key``, and without it
    all three of a fighter's method markets collapse onto one key and merge
    three different contracts into one row.

    Optic emits only the ``yes`` side of ``method_of_victory`` (see
    ``exchanges/optic.py``), so the ``No`` leg is dropped for the same
    reason the three-way "No" is: there is nothing to stamp it onto.
    An unrecognised or non-emittable method is a drop, never a guess.
    """
    method = novig_method_key(market.type)
    if not is_emittable_method(method):
        return []
    if entity is None:      # Scope.TEAM resolved to no fighter -> drop
        return []
    affirmative = next(
        (o for o in market.outcomes if o.index == HOME_OVER_YES_INDEX), None)
    if affirmative is None:
        return []
    return [row("yes", entity=entity, line=None, outcome=affirmative,
                grouping_key=method)]


def _spread_rows(
    market: NovigMarket,
    first: NovigOutcome,
    second: NovigOutcome,
    *,
    home: str,
    away: str,
    team_map: dict[str, str],
    row: Callable[..., CanonicalRow],
) -> list[CanonicalRow]:
    """Strike is the home line. One competitor id obliges both outcomes to name their sides."""
    if market.strike is None:
        return []
    first_side = _named_side(first.competitor, team_map, home=home, away=away)
    second_side = _named_side(second.competitor, team_map, home=home, away=away)
    if first_side is None and second_side is None:
        if not _typed_home_away(first, second):
            return []
    elif (first_side, second_side) != (home, away):
        return []
    return [row(home, entity=None, line=market.strike, outcome=first),
            row(away, entity=None, line=-market.strike, outcome=second)]


def _typed_home_away(first: NovigOutcome, second: NovigOutcome) -> bool:
    """True when the outcomes themselves say index 0 is Home and 1 is Away."""
    return first.type.casefold() == "home" and second.type.casefold() == "away"


def _named_side(competitor, team_map: dict[str, str], *, home: str, away: str) -> str | None:
    """Fixture side of a competitor id, or None when the outcome does not name one."""
    return team_side(_team_side(competitor, team_map) or "", home=home, away=away)


def _team_shape_rows(
    shape: Shape,
    market: NovigMarket,
    first: NovigOutcome,
    second: NovigOutcome,
    *,
    home: str,
    away: str,
    team_map: dict[str, str],
    row: Callable[..., CanonicalRow],
) -> list[CanonicalRow]:
    """Team markets take their side from the competitor id, never from index."""
    if shape == Shape.MONEYLINE:
        first_side = _named_side(first.competitor, team_map, home=home, away=away)
        second_side = _named_side(second.competitor, team_map, home=home, away=away)
        if first_side is None or second_side is None or {first_side, second_side} != {home, away}:
            return []
        return [row(first_side, entity=None, line=None, outcome=first),
                row(second_side, entity=None, line=None, outcome=second)]

    if shape == Shape.SPREAD:
        return _spread_rows(
            market, first, second, home=home, away=away, team_map=team_map, row=row,
        )

    return []


def _label_shape_rows(
    shape: Shape,
    market: NovigMarket,
    first: NovigOutcome,
    second: NovigOutcome,
    *,
    entity: str | None,
    row: Callable[..., CanonicalRow],
) -> list[CanonicalRow]:
    """Shapes whose sides are labels (over/under, yes/no), not teams."""
    if shape in (Shape.TOTAL, Shape.OVER_UNDER):
        if market.strike is None or market.strike < 0:
            return []  # Optic over/under thresholds are always non-negative
        return [row("over", entity=entity, line=market.strike, outcome=first),
                row("under", entity=entity, line=market.strike, outcome=second)]

    if shape == Shape.YES_NO:
        return [row("yes", entity=entity, line=None, outcome=first),
                row("no", entity=entity, line=None, outcome=second)]

    if shape == Shape.YES_NO_LINE:
        if market.strike is None:
            return []
        return [row("yes", entity=entity, line=market.strike, outcome=first),
                row("no", entity=entity, line=market.strike, outcome=second)]

    # H2H / CORRECT_SCORE have no Novig equivalent in the observed feed;
    # they fall through to "unmapped" rather than being guessed at.
    return []


def _three_way_market_rows(
    market: NovigMarket,
    home: str,
    away: str,
    team_map: dict[str, str],
    row: Callable[..., CanonicalRow],
) -> list[CanonicalRow]:
    """Soccer Yes/No form, or a 2-way market (football "MONEY_1H") on Optic's 3-way key.

    The 2-way form has one outcome per team and no draw; its home/away rows are the same
    question, settling differently only when the half ties.  Outcomes naming teams are
    never the Yes/No form: unresolved teams drop, never become a tie row.
    """
    pair = _by_index(market)
    first, second = pair.get(HOME_OVER_YES_INDEX), pair.get(AWAY_UNDER_NO_INDEX)
    if first and second and (first.competitor or second.competitor):
        return _team_shape_rows(Shape.MONEYLINE, market, first, second,
                                home=home, away=away, team_map=team_map, row=row)
    return _three_way_rows(market, team_map, row)


def build_rows(
    market: NovigMarket,
    mt: MarketType,
    *,
    home: str, away: str, start_date: str, league: str,
    team_map: dict[str, str], player_names: dict[str, str],
) -> list[CanonicalRow]:
    """Emit CanonicalRows for one Novig market, or [] when unmappable.

    Flip-safety is absolute: any market whose sides, team ids, player id or
    strike cannot be resolved is dropped WHOLE rather than half-emitted.
    Rows merge onto existing Optic rows later (attach_novig_row), so a
    market Optic did not price simply disappears.  Per-shape emission lives
    in the ``_*_rows`` helpers above; the id joins live in ``_entity``.
    """
    shape = mt.shape

    def row(side: str, *, entity: str | None, line: float | None,
            outcome: NovigOutcome,
            grouping_key: str | None = None) -> CanonicalRow:
        return CanonicalRow(
            league=league, start_date=start_date, home=home, away=away,
            market_type=mt.value, entity=entity, line=line, side=side,
            grouping_key=grouping_key,
            **_stamp(market, outcome))

    resolved, entity = _entity(market, mt.scope, team_map, player_names)
    if not resolved:
        return []

    # THREE_WAY reads market.outcomes directly: its "No" leg is dropped, so
    # it never needs the index pair the other shapes require.
    if shape == Shape.THREE_WAY:
        return _three_way_market_rows(market, home, away, team_map, row)

    # METHOD_OF_VICTORY is Shape.YES_NO but emits only the affirmative leg,
    # so like THREE_WAY it must be handled before the index-pair gate.
    if mt == MarketType.METHOD_OF_VICTORY:
        return _method_of_victory_rows(market, entity, row)

    by_idx = _by_index(market)
    if not by_idx:
        return []
    first, second = by_idx[HOME_OVER_YES_INDEX], by_idx[AWAY_UNDER_NO_INDEX]

    if shape in (Shape.MONEYLINE, Shape.SPREAD):
        return _team_shape_rows(shape, market, first, second, home=home,
                                away=away, team_map=team_map, row=row)
    return _label_shape_rows(shape, market, first, second, entity=entity, row=row)

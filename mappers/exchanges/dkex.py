"""DKEX (DraftKings Exchange, ex-Railbird) typed market records and canonical keying.

DKEX is a CFTC-regulated event-contract exchange.  Every contract is a
binary yes/no market on one ticker -- the Kalshi shape, not the Novig
one -- so a single DKEX market carries BOTH canonical sides and the
``side`` (yes/no) lives outside the market, on the RFQ leg or the order.

**Identity comes from the venue's typed REST fields, never from the
ticker.**  ``POST /api/v1/markets/queries`` returns, per market:

=====================================  =====================================
typed field                            what we key on
=====================================  =====================================
``parameters.statAchievement``         market token (``MOVY``, ``TPTS``, ...)
``parameters.timePeriod``              period token (``FG``, ``H1``, ``IT5``)
``parameters.participant``             the team / player the market names
``parameters.strikePrice``             the line, as a decimal string
``parameters.outcomeType``             ``GTE`` (>=) or ``GT`` (>)
``metadata.competitionId``             the fixture handle
``metadata.participants[].role``       ``home`` / ``away`` on team markets
``subTopic``                           the league (see ``LEAGUE_TOKENS``)
=====================================  =====================================

``fetch/dkex.py`` flattens those onto the catalogue row and
:func:`market_from_row` turns a row into a :class:`DkexMarket`.  The
ticker (``BSA-MOVY-FG-02L4HV50HIO28DG-SALO008-GTE-P00035``) is carried
through as an opaque id -- it is what an RFQ leg names -- and nothing in
the mapping path reads meaning out of it.  A row without the typed
fields (the T+1 CSV report, which has only the symbol) is ``untyped``
and skipped; it is never back-filled by slicing the symbol.

The venue gives us no Optic ids, so the fixture is still a name match:
start time plus the two teams DKEX names with ``role`` home/away, run
through the shared ``team_side`` / ``names_fit`` matchers.  Teams then
resolve by participant id -> role -> fixture side, and players by
participant name against the fixture's Optic selections.

Three things that are easy to get wrong:

1. **Maturity is NOT the event start.**  The daily report's maturity is
   the event time plus exactly 30 days.  The REST row carries
   ``competitionStartTime``; the report path subtracts
   ``SETTLEMENT_LAG``.  Keying on raw maturity matches nothing.

2. **GT is not GTE.**  ``outcomeType == GT`` settles on a strict
   ``> strike``; we key it on the next half-point line so ``> 59.5``
   lands on over ``60.0``, not over ``59.5``.

3. **MOVY is the spread, expressed as a one-sided threshold.**  MOVY on
   Denver with strike 15.5 settles on "DEN wins by >= 15.5", which is
   the yes side of the -15.5 spread on Denver.  The no side is the
   opponent at +15.5.  Mapping MOVY to a total, or dropping the sign,
   silently inverts half the book.

A market with no ``parameters.participant`` is game-scoped (a game
total, both-teams-to-score, the draw leg of a 3-way, "no touchdown
scorer").  Only a game total builds from one; every team or player
market needs a resolved participant or drops whole.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from mappers.exchanges.dkex_leagues import LEAGUE_TOKENS, VENUE_TOKEN_BY_SLUG  # noqa: F401 — re-export
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import TIE_SIDE, CanonicalRow, double_chance_side

#: Maturity on every DKEX market report is the event start plus exactly
#: this much.  See gotcha 1 in the module docstring.
SETTLEMENT_LAG = timedelta(days=30)

#: ``marketProductTypeName`` of an RFQ-created combo instrument.
COMBO_PRODUCT_TYPE = "COMBO"

#: Season / tournament periods — no game-line map.
_IGNORED_PERIODS = frozenset({"FS", "RS", "TRN", "S1", "S2", "S3"})

#: Participant roles DKEX writes on team markets.
HOME = "home"
AWAY = "away"


def is_combo(raw: Mapping[str, Any]) -> bool:
    """True for an RFQ-created combo, from its typed REST fields.

    ``POST /api/v1/combos/queries`` rows carry ``marketProductTypeName ==
    "COMBO"`` and a ``legs`` list; the markets batch never returns a combo
    (it lists one under ``missingTickers``).  The ticker is not read.
    """
    return raw.get("marketProductTypeName") == COMBO_PRODUCT_TYPE or bool(raw.get("legs"))


def event_start(maturity: datetime) -> datetime:
    """Event start for a market whose report maturity is ``maturity``."""
    return maturity - SETTLEMENT_LAG


@dataclass(frozen=True)
class DkexParticipant:
    """One ``metadata.participants[]`` entry, verbatim."""

    id: str
    name: str = ""
    role: str | None = None   # "home" / "away" on team markets, None on props


@dataclass(frozen=True)
class DkexMarket:
    """One DKEX market, identified entirely by the venue's typed fields."""

    ticker: str                       # opaque venue id; never parsed
    league: str                       # venue league token (via LEAGUE_TOKENS)
    market: str                       # parameters.statAchievement
    period: str                       # parameters.timePeriod
    event_id: str                     # metadata.competitionId
    participant: DkexParticipant | None = None  # parameters.participant, resolved
    strike: float | None = None       # parameters.strikePrice
    outcome_type: str | None = None   # parameters.outcomeType: "GTE" / "GT"
    event_start: str = ""             # metadata.competitionStartTime (UTC ISO)
    participants: tuple[DkexParticipant, ...] = ()  # every metadata participant
    name: str = ""                    # the contract's own label ("No Goalscorer")


def league_token(sub_topic: str | None) -> str:
    """Venue league token for a typed ``subTopic`` ("" when absent)."""
    text = str(sub_topic or "").strip()
    if not text:
        return ""
    return LEAGUE_TOKENS.get(text, text).upper()


def participants_from_row(rec: Mapping[str, Any]) -> tuple[DkexParticipant, ...]:
    """``participants`` of a normalized catalogue row, as typed records."""
    out: list[DkexParticipant] = []
    for row in rec.get("participants") or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        role = str(row.get("role") or "").strip().casefold() or None
        out.append(DkexParticipant(
            id=pid, name=str(row.get("name") or "").strip(), role=role,
        ))
    return tuple(out)


def market_from_row(rec: Mapping[str, Any]) -> DkexMarket | None:
    """A typed market from one normalized catalogue row; None when untyped.

    Untyped means the row lacks the REST identity fields -- a CSV report
    row, or a market the venue published without parameters.  Such a row
    is counted and skipped by the caller; it is never reconstructed from
    the ticker.
    """
    market = str(rec.get("stat_achievement") or "").strip()
    period = str(rec.get("time_period") or "").strip()
    event_id = str(rec.get("competition_id") or "").strip()
    league = league_token(rec.get("sub_topic"))
    if not (market and period and event_id and league):
        return None
    participants = participants_from_row(rec)
    pid = str(rec.get("participant_id") or "").strip()
    participant: DkexParticipant | None = None
    if pid:
        participant = next((p for p in participants if p.id == pid), None)
        if participant is None:
            name = str(rec.get("participant_name") or "").strip()
            participant = DkexParticipant(id=pid, name=name)
    strike = rec.get("strike_price")
    outcome = str(rec.get("outcome_type") or "").strip().upper() or None
    return DkexMarket(
        ticker=str(rec.get("symbol") or ""),
        league=league,
        market=market,
        period=period,
        event_id=event_id,
        participant=participant,
        strike=float(strike) if isinstance(strike, int | float) and not isinstance(strike, bool) else None,
        outcome_type=outcome,
        event_start=str(rec.get("event_start") or ""),
        participants=participants,
        name=str(rec.get("name") or "").strip(),
    )


@dataclass(frozen=True)
class DkexConfig:
    """League-specific constants for DKEX market classification."""

    #: DKEX's league token, e.g. "NFL", "CFB" -- compared against
    #: ``league_token(subTopic)`` to keep another league's markets out of
    #: this league's pass.
    league: str
    #: (statAchievement, timePeriod) -> canonical MarketType.  Keyed on
    #: the pair because the period is its own field: TPTS/FG is the game
    #: total, TPTS/H1 the first-half total, TRUNS/IT5 the F5 total.
    market_types: dict[tuple[str, str], MarketType]
    #: Markets whose line is implied by the market token rather than a
    #: strikePrice: PTDS1 ("1+ touchdowns") is over 0.5, PTDS2 is over
    #: 1.5.  Without this they build as a line-less over/under and
    #: collapse onto one key.
    implied_lines: dict[str, float] = field(default_factory=dict)
    #: DKEX statAchievement tokens we deliberately do NOT map -- either
    #: no clean Optic target (PSCK sacks, LTD last touchdown) or a period
    #: Optic does not price.
    #: Enumerating them keeps the unknown-market warning meaningful --
    #: same discipline as every venue's explicit ignore list.
    ignored_markets: frozenset[str] = field(default_factory=frozenset)
    #: Fit DKEX's short club names onto Optic's official ones
    #: (``dkex_names.club_short_fits``).  On for soccer only.
    club_short_names: bool = False
    #: Competitors are people (tennis players, fighters): fixture sides
    #: resolve by person name (``dkex_names.person_side_for``), not by
    #: the team rules.
    person_names: bool = False
    #: Read every event whose markets this config maps, whatever its
    #: ``subTopic``.  For tennis, where DKEX writes the tournament
    #: ("WTA Adana 125") or just the tour, and not consistently: the
    #: fixture match (both players, one Optic fixture in this league)
    #: decides which league an event belongs to.
    any_league: bool = False
    #: (statAchievement, timePeriod) -> smallest canonical line mapped.
    #: For a contract that matches Optic only from some line up: the NHL
    #: puck line at 1.5+ settles the same with or without overtime, a
    #: 0.5 line would not.  A smaller or missing line classifies to None.
    min_strikes: dict[tuple[str, str], float] = field(default_factory=dict)

    def market_type(self, m: DkexMarket) -> MarketType | None:
        """Canonical type for a typed market, or None when unmapped."""
        if self.deliberately_unmapped(m):
            return None
        floor = self.min_strikes.get((m.market, m.period))
        if floor is not None:
            line = canonical_strike_line(m)
            if line is None or line < floor:
                return None
        return self.market_types.get((m.market, m.period))

    def deliberately_unmapped(self, m: DkexMarket) -> bool:
        """True when we intentionally do not map this (period / market token)."""
        if m.market in self.ignored_markets:
            return True
        if (m.market, m.period) in self.market_types:
            return False   # a mapped pair wins: tennis S1/S2 are sets, not seasons
        return m.period in _IGNORED_PERIODS

    def line_for(self, m: DkexMarket) -> float | None:
        """Canonical line for the Optic join (GT shifts to the next half-point)."""
        line = canonical_strike_line(m)
        if line is not None:
            return line
        return self.implied_lines.get(m.market)


def canonical_strike_line(m: DkexMarket) -> float | None:
    """Map strikePrice + outcomeType to the Optic over/under or spread line."""
    if m.strike is None:
        return None
    if m.outcome_type == "GT":
        return m.strike + 0.5
    return m.strike


# === Row construction ===

def _row_factory(
    m: DkexMarket, mt: MarketType, *,
    home: str, away: str, start_date: str, league: str,
) -> Callable[..., CanonicalRow]:
    """A CanonicalRow builder bound to one market, for the shape helpers."""
    def row(side: str, *, entity: str | None, row_line: float | None,
            dkex_side: str) -> CanonicalRow:
        return CanonicalRow(
            league=league, start_date=start_date, home=home, away=away,
            market_type=mt.value, entity=entity, line=row_line, side=side,
            dkex_symbol=m.ticker, dkex_side=dkex_side,
            dkex_event_id=m.event_id, dkex_market=m.market,
            dkex_period=m.period,
        )
    return row


def _team_pair(team: str | None, home: str, away: str) -> tuple[str, str] | None:
    """(named team, opponent) for a resolved fixture side, or None."""
    if team is None:
        return None
    if team == home:
        return team, away
    if team == away:
        return team, home
    return None


def _moneyline_rows(row, team, home, away) -> list[CanonicalRow]:
    """Yes is the named team winning; no is the opponent winning."""
    pair = _team_pair(team, home, away)
    if pair is None:
        return []
    named, opp = pair
    return [row(named, entity=None, row_line=None, dkex_side="yes"),
            row(opp, entity=None, row_line=None, dkex_side="no")]


def _spread_rows(row, team, home, away, line) -> list[CanonicalRow]:
    """"Team wins by >= L" is that team at -L; the no side is the opponent at +L.

    See gotcha 3 in the module docstring -- dropping the sign here
    silently inverts half the book.
    """
    pair = _team_pair(team, home, away)
    if pair is None or line is None:
        return []
    named, opp = pair
    return [row(named, entity=None, row_line=-line, dkex_side="yes"),
            row(opp, entity=None, row_line=line, dkex_side="no")]


def _total_rows(m, row, mt, team, home, away, line) -> list[CanonicalRow]:
    """Yes is over, no is under; team totals keep the team as entity."""
    if line is None:
        return []
    entity: str | None = None
    if mt.scope is Scope.TEAM:
        if _team_pair(team, home, away) is None:
            return []
        entity = team
    elif m.participant is not None:
        # A game total that names a participant is not the contract the
        # crosswalk describes; refuse rather than silently drop the name.
        return []
    return [row("over", entity=entity, row_line=line, dkex_side="yes"),
            row("under", entity=entity, row_line=line, dkex_side="no")]


#: The double chance each 3-way result's No side is.  Only full-game
#: 3-way is listed; a half-time 3-way would need its own entry here AND a
#: rules check that it settles on the same half-time result.
_DOUBLE_CHANCE_FOR = {
    MarketType.MONEYLINE_3WAY: MarketType.DOUBLE_CHANCE,
}


def _three_way_rows(m, row, dc_row, team, home, away) -> list[CanonicalRow]:
    """One 3-way leg: yes is its outcome, no is the double chance on the other two.

    DKEX lists the result as three binaries.  A team leg names the team in
    ``parameters.participant``; the draw leg has no participant.  The No
    side of "Home" is away-or-draw, of "Draw" is either team winning --
    exactly Optic's double chance, because both settle on the 90-minute
    result (``mappers/vocab/dkex_markets.py``).
    """
    if m.participant is None:
        if dc_row is None:
            return []
        outcome = TIE_SIDE
    else:
        pair = _team_pair(team, home, away)
        if pair is None:
            return []
        outcome = pair[0]
    if dc_row is None:
        # A period 3-way with no double-chance twin (half / quarter / F5):
        # only the team's own win has an Optic row to stamp onto.
        return [row(outcome, entity=None, row_line=None, dkex_side="yes")]
    others = {home, away, TIE_SIDE} - {outcome}
    return [row(outcome, entity=None, row_line=None, dkex_side="yes"),
            dc_row(double_chance_side(others, home, away), entity=None,
                   row_line=None, dkex_side="no")]


def _game_yes_no_rows(m, row) -> list[CanonicalRow]:
    """A game-scoped question (both teams to score): yes is yes, no is no."""
    if m.participant is not None:
        # A game question that names a participant is not the contract the
        # crosswalk describes; refuse rather than silently drop the name.
        return []
    return [row("yes", entity=None, row_line=None, dkex_side="yes"),
            row("no", entity=None, row_line=None, dkex_side="no")]


def _player_rows(row, shape, player, line) -> list[CanonicalRow]:
    """Player props: over/under when there is a line, yes/no when there is not."""
    if player is None:
        return []
    if shape is Shape.YES_NO:
        return [row("yes", entity=player, row_line=None, dkex_side="yes"),
                row("no", entity=player, row_line=None, dkex_side="no")]
    if line is None:
        return []
    return [row("over", entity=player, row_line=line, dkex_side="yes"),
            row("under", entity=player, row_line=line, dkex_side="no")]


def build_rows(
    m: DkexMarket,
    mt: MarketType,
    *,
    line: float | None,
    home: str, away: str, start_date: str, league: str,
    team: str | None = None,
    player: str | None = None,
) -> list[CanonicalRow]:
    """Emit the two canonical sides of one DKEX contract, or [].

    ``team`` is the fixture side (the ``home`` or ``away`` abbrev) the
    market's participant resolved to; ``player`` is the canonical Optic
    player name.  The caller resolves both from typed fields; this
    function only decides which canonical side the venue's yes/no is.

    A DKEX market is a single binary carrying BOTH canonical sides, so
    this always returns a pair (yes and no) or nothing.  Which canonical
    side the venue's "yes" is depends on the shape, and getting it
    backwards inverts the book, so each ``_*_rows`` helper names both
    explicitly rather than deriving one from the other.

    An unresolved entity or a missing line drops the market WHOLE --
    never half-emitted.  Rows are stamped onto Optic rows downstream
    (``attach_dkex_row``), so a contract Optic did not price simply
    disappears.
    """
    row = _row_factory(m, mt, home=home, away=away,
                       start_date=start_date, league=league)
    shape = mt.shape
    if shape is Shape.MONEYLINE:
        return _moneyline_rows(row, team, home, away)
    if shape is Shape.SPREAD:
        return _spread_rows(row, team, home, away, line)
    if shape is Shape.TOTAL:
        return _total_rows(m, row, mt, team, home, away, line)
    if shape in (Shape.OVER_UNDER, Shape.YES_NO) and mt.scope is Scope.PLAYER:
        return _player_rows(row, shape, player, line)
    if shape is Shape.THREE_WAY:
        dc_mt = _DOUBLE_CHANCE_FOR.get(mt)
        dc_row = _row_factory(m, dc_mt, home=home, away=away, start_date=start_date,
                              league=league) if dc_mt is not None else None
        return _three_way_rows(m, row, dc_row, team, home, away)
    if shape is Shape.YES_NO and mt.scope is Scope.GAME:
        return _game_yes_no_rows(m, row)
    # Every other shape (H2H, CORRECT_SCORE, YES_NO_LINE, ...) is unreached
    # today: no (market, period) in mappers/vocab/dkex_markets classifies
    # to one.  Dropping rather than guessing keeps the unmapped counter
    # honest when a new vocabulary entry lands.
    return []

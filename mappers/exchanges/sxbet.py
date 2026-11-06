"""SX Bet typed market records and canonical keying.

SX Bet (sx.bet) is a peer-to-peer exchange.  Every market is ONE binary on
one ``marketHash`` with two outcomes, and an RFQ leg names
``(marketHash, bettingOutcomeOne)`` -- so one market carries both canonical
sides, like a Kalshi or DKEX ticker.

Before this module, ``SX Bet`` rows reached ``markets_us.market_mapping``
only as an Optic passthrough (``OPTIC_MAPPED_SPORTSBOOKS``), i.e. only
where Optic itself carries SX odds.  Measured 2026-10-13 that was 5,098 of
12,272 live SX markets: Optic returns no ``sx_bet`` odds at all for, e.g.,
Leverkusen v Freiburg while SX lists the match.  This module and
``sxbet_pass`` map the rest off SX's own catalogue, the Novig/DKEX way.

**Identity comes from the venue's typed REST fields** (``GET
/markets/active``, public): ``type`` (the market AND its period, see
``mappers/vocab/sxbet_markets.py``), ``line``, ``outcomeOneName`` /
``outcomeTwoName``, ``teamOneName`` / ``teamTwoName``, ``sportXeventId``,
``leagueId`` and ``gameTime``.  Conventions, each measured on the
2026-10-13 live book (12,272 markets):

* a spread's ``line`` is outcome ONE's handicap ("Dodgers -1.5" / "Brewers
  +1.5", line -1.5): 0 exceptions in 5,079 spreads;
* a 2-way moneyline's outcome one is ``teamOneName``: 0 exceptions in 574;
* a total's outcomes are "Over N" / "Under N";
* the 1X2 (type 1) is three binaries "X" / "Not X" with "Tie" / "Not tie"
  for the draw;
* a period lives in the type id AND as a suffix on the outcome names
  ("Phoenix Suns +1.5 (1st half)", "Over 2.5 (sets)") -- stripped here.

**The source-id stamp is ``(marketHash, maker side)``, in Optic's own
shape.**  Optic's ``source_ids["SX Bet"]`` is ``{event_id, market_id:
<marketHash>, selection_id: "<marketHash>|one" | "<marketHash>|two"}``, and
the suffix is the MAKER's outcome: the ``|one`` odd is what a taker on
outcome TWO lifts.  Proof (prod, 2026-10-13): hash ``0xe995d877...`` has
SX ``outcomeOneName`` "Over 5.5" and its ``|one`` row says ``under``; 24 h
of SX RFQ legs keyed this way agreed with the maker's own mapping on 91/91
sides.  :func:`selection_id` writes exactly that shape, so a constructed
row and a passthrough one cannot be told apart downstream.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mappers.market_types import MarketType, Shape
from mappers.shared import TIE_SIDE, CanonicalRow
from mappers.vocab.sxbet_markets import THREE_WAY_TYPE

#: Display name of the book in ``market_mapping.sportsbook`` and in Optic's
#: ``source_ids`` (``OPTIC_MAPPED_SPORTSBOOKS``).
SPORTSBOOK = "SX Bet"

#: ``status`` of a tradeable market (every ``/markets/active`` row today).
OPEN_STATUS = "ACTIVE"

#: Trailing period / unit qualifier on an SX outcome name.
_SEGMENT_RE = re.compile(
    r"\s*\([^()]*\b(?:half|period|innings?|sets?|quarter)\b[^()]*\)\s*$", re.IGNORECASE)
#: "Team +1.5" / "Team -0.25" / "Team +1" / "Team 0" (a level handicap is unsigned;
#: every other line carries its sign, so "Schalke 04" alone never reads as a line).
_HANDICAP_RE = re.compile(r"^(?P<name>.*?)\s*(?P<line>[+-]\d+(?:\.\d+)?|0(?:\.0+)?)$")
#: "Over 2.5" / "Under 49.5".
_TOTAL_RE = re.compile(r"^(?P<side>over|under)\s+(?P<line>\d+(?:\.\d+)?)$", re.IGNORECASE)
#: The 1X2 complement outcome ("Not Barcelona FC", "Not tie").
_NOT_RE = re.compile(r"^not\s+\S", re.IGNORECASE)
#: The 1X2 draw outcome.
_DRAW_NAMES = frozenset({"tie", "draw"})


def selection_id(market_hash: str, outcome: int) -> str:
    """Optic's SX ``selection_id`` for the taker's ``outcome`` (1 or 2).

    The suffix is the MAKER's outcome (module docstring): a taker on
    outcome one is ``|two``, on outcome two ``|one``.
    """
    if outcome not in (1, 2):
        raise ValueError(f"SX outcome must be 1 or 2, got {outcome!r}")
    return f"{market_hash.lower()}|{'two' if outcome == 1 else 'one'}"


@dataclass(frozen=True)
class SxMarket:
    """One SX market, identified entirely by the venue's typed fields."""

    market_hash: str          # lowercase; the RFQ leg key (with the side)
    event_id: str             # sportXeventId -- the fixture handle
    league_id: int | None     # leagueId
    league_label: str         # leagueLabel (display; not unique across sports)
    sport: str                # sportLabel ("Soccer", "Football" = American)
    type: int                 # market type id (market + period)
    line: float | None        # outcome one's handicap, or the total
    outcome_one: str
    outcome_two: str
    team_one: str
    team_two: str
    start: str                # gameTime as a UTC ISO timestamp
    status: str = OPEN_STATUS


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _start_iso(game_time: Any) -> str:
    """``gameTime`` (epoch seconds) as ``YYYY-MM-DDTHH:MM:SSZ``; "" when absent."""
    seconds = _int(game_time)
    if seconds is None or seconds <= 0:
        return ""
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def market_from_row(rec: Mapping[str, Any]) -> SxMarket | None:
    """A typed market from one ``/markets/active`` row; None when it lacks a key field."""
    mh = str(rec.get("marketHash") or "").strip().lower()
    event_id = str(rec.get("sportXeventId") or "").strip()
    mtype = _int(rec.get("type"))
    o1, o2 = str(rec.get("outcomeOneName") or "").strip(), str(rec.get("outcomeTwoName") or "").strip()
    t1, t2 = str(rec.get("teamOneName") or "").strip(), str(rec.get("teamTwoName") or "").strip()
    if not (mh and event_id and mtype is not None and o1 and o2 and t1 and t2):
        return None
    return SxMarket(
        market_hash=mh, event_id=event_id, league_id=_int(rec.get("leagueId")),
        league_label=str(rec.get("leagueLabel") or "").strip(),
        sport=str(rec.get("sportLabel") or "").strip(), type=mtype,
        line=_float(rec.get("line")), outcome_one=o1, outcome_two=o2,
        team_one=t1, team_two=t2, start=_start_iso(rec.get("gameTime")),
        status=str(rec.get("status") or OPEN_STATUS).strip().upper(),
    )


@dataclass(frozen=True)
class SxConfig:
    """One tip league's SX constants (built in code: ``with_code_sxbet``)."""

    slug: str
    #: SX type id -> canonical type for this league's sport.
    market_types: Mapping[int, MarketType]
    ignored_types: frozenset[int] = frozenset()
    #: Competitors are people (tennis, MMA): sides resolve by person name.
    person_names: bool = False
    #: Fit SX's short club names onto Optic's official ones (soccer).
    club_short_names: bool = False

    def market_type(self, m: SxMarket) -> MarketType | None:
        """Canonical type of a typed market, or None when unmapped."""
        return self.market_types.get(m.type)

    def deliberately_unmapped(self, m: SxMarket) -> bool:
        """True when this type is on the ignore list and the sport does not map it."""
        return m.type not in self.market_types and m.type in self.ignored_types


def strip_segment(name: str) -> str:
    """An outcome name without its trailing period / unit qualifier."""
    return _SEGMENT_RE.sub("", name).strip()


def parse_handicap(name: str) -> tuple[str, float] | None:
    """("Phoenix Suns", 1.5) for "Phoenix Suns +1.5 (1st half)"; None when no handicap."""
    match = _HANDICAP_RE.match(strip_segment(name))
    if match is None or not match.group("name").strip():
        return None
    return match.group("name").strip(), float(match.group("line"))


def parse_total(name: str) -> tuple[str, float] | None:
    """("over", 2.5) for "Over 2.5 (sets)"; None when not a total outcome."""
    match = _TOTAL_RE.match(strip_segment(name))
    if match is None:
        return None
    return match.group("side").lower(), float(match.group("line"))


def is_not_outcome(name: str) -> bool:
    """True for the 1X2 complement outcome ("Not Barcelona FC", "Not tie")."""
    return bool(_NOT_RE.match(name.strip()))


# === Row construction ===

SideOf = Callable[[str], str | None]


def _row_factory(m: SxMarket, mt: MarketType, *, home: str, away: str,
                 start_date: str, league: str) -> Callable[..., CanonicalRow]:
    def row(side: str, *, line: float | None, outcome: int) -> CanonicalRow:
        return CanonicalRow(
            league=league, start_date=start_date, home=home, away=away,
            market_type=mt.value, entity=None, line=line, side=side,
            sx_market_hash=m.market_hash, sx_outcome=outcome,
            sx_event_id=m.event_id, sx_type=m.type,
        )
    return row


def _two_sides(m: SxMarket, side_of: SideOf, names: tuple[str, str]) -> tuple[str, str] | None:
    """The fixture sides two SX team names resolve to, or None unless both land, apart."""
    one, two = side_of(names[0]), side_of(names[1])
    if one is None or two is None or one == two:
        return None
    return one, two


def _moneyline_rows(m: SxMarket, row, side_of: SideOf) -> list[CanonicalRow]:
    sides = _two_sides(m, side_of, (strip_segment(m.outcome_one), strip_segment(m.outcome_two)))
    if sides is None:
        return []
    return [row(sides[0], line=None, outcome=1), row(sides[1], line=None, outcome=2)]


def _spread_rows(m: SxMarket, row, side_of: SideOf) -> list[CanonicalRow]:
    """Each outcome is "Team ±L"; outcome one's L is the market line and the two cancel."""
    one, two = parse_handicap(m.outcome_one), parse_handicap(m.outcome_two)
    if one is None or two is None or m.line is None:
        return []
    if abs(one[1] - m.line) > 1e-9 or abs(one[1] + two[1]) > 1e-9:
        return []
    sides = _two_sides(m, side_of, (one[0], two[0]))
    if sides is None:
        return []
    return [row(sides[0], line=one[1], outcome=1), row(sides[1], line=two[1], outcome=2)]


def _total_rows(m: SxMarket, row) -> list[CanonicalRow]:
    """"Over N" / "Under N" on the same N, one each."""
    one, two = parse_total(m.outcome_one), parse_total(m.outcome_two)
    if one is None or two is None or one[1] != two[1] or {one[0], two[0]} != {"over", "under"}:
        return []
    if m.line is not None and abs(m.line - one[1]) > 1e-9:
        return []
    return [row(one[0], line=one[1], outcome=1), row(two[0], line=two[1], outcome=2)]


def _three_way_rows(m: SxMarket, row, side_of: SideOf) -> list[CanonicalRow]:
    """1X2 binary "X" / "Not X": the affirmative outcome only (Not X is never built)."""
    if not is_not_outcome(m.outcome_two) or is_not_outcome(m.outcome_one):
        return []
    result = strip_segment(m.outcome_one)
    if result.casefold() in _DRAW_NAMES:
        return [row(TIE_SIDE, line=None, outcome=1)]
    side = side_of(result)
    if side is None:
        return []
    return [row(side, line=None, outcome=1)]


def build_rows(
    m: SxMarket, mt: MarketType, *, side_of: SideOf,
    home: str, away: str, start_date: str, league: str,
) -> list[CanonicalRow]:
    """The canonical rows one SX market stands for, each stamped with its taker outcome, or [].

    ``side_of`` resolves an SX team / player name to the fixture side
    (``home`` / ``away`` abbrev).  An outcome that does not resolve, a line
    that disagrees with the outcome names, or two outcomes on one side drop
    the market WHOLE -- never half-emitted.  Rows are stamped onto Optic rows
    downstream (``attach_sxbet_row``), so a market Optic did not price
    disappears rather than being emitted standalone.
    """
    if m.type == THREE_WAY_TYPE:
        if mt.shape is not Shape.THREE_WAY:
            return []
        row = _row_factory(m, mt, home=home, away=away, start_date=start_date, league=league)
        return _three_way_rows(m, row, side_of)
    row = _row_factory(m, mt, home=home, away=away, start_date=start_date, league=league)
    if mt.shape is Shape.MONEYLINE:
        return _moneyline_rows(m, row, side_of)
    if mt.shape is Shape.SPREAD:
        return _spread_rows(m, row, side_of)
    if mt.shape is Shape.TOTAL:
        return _total_rows(m, row)
    # No crosswalk entry classifies to another shape today; dropping keeps
    # the unbuildable counter honest when one lands.
    return []

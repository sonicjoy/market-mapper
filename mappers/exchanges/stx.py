"""STX (stxapp.ca, the Ontario exchange): the typed market record and what YES / NO pays on.

STX lists every outcome as its own binary market (docs-v1.8.0 ``concepts__market-shape.md:17-46``). A moneyline is
two markets (``home_winner`` / ``away_winner``); a total is one market per line and it is the OVER (``:279``); a
spread is one market per line, signed from the HOME side (``:280``, ``:349``). A combo leg names one market and the
outcome it needs, ``won`` (YES) or ``lost`` (NO) (``concepts__combos.md:15-26``).

Identity comes from typed fields only: ``rules``, the numeric ``specifier`` of a spread or total, ``stat_detail``
(``participant``, ``stat``, ``line``, ``player``) and the role-tagged ``participants``. ``symbol``, titles and the
question text are never read: ``symbol`` is rebuilt on a reschedule (``:193-211``) and titles are identical on both
winner markets (``:431-462``).

A NO is the same market's other outcome, never the sibling market. NO on ``home_winner`` pays when the away team wins
and half on a tie, exactly what YES on ``away_winner`` pays, so it prices as the away selection. NO on a 3-way leg is
a double chance and is not mapped here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SPORTSBOOK = "STX"
YES = "yes"
NO = "no"
HOME = "home"
AWAY = "away"

#: Market statuses that keep their mapping. A leg must be ``open`` when a request opens and again at the bind
#: (``concepts__combos.md:25``); the maker checks that per request. ``suspended`` keeps its identity, so it keeps its
#: row (816 of 6,443 markets on the 2026-10-28 capture were suspended).
MAPPABLE_MARKET_STATUS = frozenset({"open", "suspended"})
#: Events a combo leg can be priced on. Anything else (``in_progress``, ``completed``, ``cancelled``) is not mapped
#: even when its markets are still ``open``: on Ontario demo 26 started events still had open markets (2026-10-28).
MAPPABLE_EVENT_STATUS = "scheduled"

#: Winner rules -> the role whose win is YES. 2-way and 3-way are separate rules on STX.
WINNER_ROLE: dict[str, str] = {
    "home_winner": HOME,
    "away_winner": AWAY,
    "home_winner_regulation_2way": HOME,
    "away_winner_regulation_2way": AWAY,
    "home_winner_regulation": HOME,
    "away_winner_regulation": AWAY,
    "home_winner_regulation_3way": HOME,
    "away_winner_regulation_3way": AWAY,
    "home_winner_regulation_3way_r1": HOME,
    "away_winner_regulation_3way_r1": AWAY,
}
DRAW_RULES = frozenset({"draw_regulation_3way", "draw_regulation_3way_r1"})
#: Full-game 2-way winners: NO on one team is YES on the other (a tie pays half on both, ``:266-268``).
TWO_WAY_WINNER_RULES = frozenset({"home_winner", "away_winner"})


@dataclass(frozen=True)
class StxParticipant:
    """One team of an STX game: ``role`` is ``home`` / ``away`` (``team`` on futures)."""

    name: str
    role: str
    abbreviation: str = ""
    short_name: str = ""


@dataclass(frozen=True)
class StxMarket:
    """One STX market, flattened from ``GET /api/v1/markets``. The mapping key is ``event_id + rules + specifier``."""

    market_id: str
    event_id: str
    event_start: str
    event_status: str
    event_type: str
    sport: str
    competition: str
    rules: str
    specifier: str | None
    status: str
    participants: tuple[StxParticipant, ...] = ()
    stat: str | None = None
    stat_participant: str | None = None
    stat_line: float | None = None
    player: str | None = None
    prop_type: str | None = None
    grouping_id: str | None = None

    def participant(self, role: str) -> StxParticipant | None:
        """The participant carrying ``role``; None when absent or listed twice."""
        hits = [p for p in self.participants if p.role == role]
        return hits[0] if len(hits) == 1 else None


@dataclass(frozen=True)
class StxOutcome:
    """What one side of an STX market pays on, before any fixture is known.

    ``kind`` is ``team`` (``role`` wins / covers / goes over), ``draw``, ``over`` or ``under``. ``role`` names the
    team for team outcomes and team totals; ``player`` is STX's player name on a prop.
    """

    kind: str
    role: str | None = None
    line: float | None = None
    player: str | None = None


def _float(value: Any) -> float | None:
    """A typed number from the wire (``"-2.5"``, ``46.5``); None when absent or not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _participants(raw: Any) -> tuple[StxParticipant, ...]:
    out: list[StxParticipant] = []
    for p in raw or ():
        if isinstance(p, dict) and p.get("name"):
            out.append(
                StxParticipant(
                    name=str(p["name"]),
                    role=str(p.get("role") or ""),
                    abbreviation=str(p.get("abbreviation") or ""),
                    short_name=str(p.get("short_name") or ""),
                )
            )
    return tuple(out)


def market_from_row(row: dict[str, Any]) -> StxMarket | None:
    """A typed market from one catalogue row (``fetch/stx.py`` shape); None without the identity fields."""
    if not all(row.get(k) for k in ("market_id", "event_id", "rules", "event_start")):
        return None
    raw_sd = row.get("stat_detail")
    sd: dict[str, Any] = raw_sd if isinstance(raw_sd, dict) else {}
    return StxMarket(
        market_id=str(row["market_id"]),
        event_id=str(row["event_id"]),
        event_start=str(row["event_start"]),
        event_status=str(row.get("event_status") or ""),
        event_type=str(row.get("event_type") or ""),
        sport=str(row.get("sport") or ""),
        competition=str(row.get("competition") or ""),
        rules=str(row["rules"]),
        specifier=None if row.get("specifier") is None else str(row["specifier"]),
        status=str(row.get("status") or ""),
        participants=_participants(row.get("participants")),
        stat=sd.get("stat"),
        stat_participant=sd.get("participant"),
        stat_line=_float(sd.get("line")),
        player=sd.get("player"),
        prop_type=sd.get("prop_type"),
        grouping_id=None if row.get("grouping_id") is None else str(row["grouping_id"]),
    )


def is_game_event(m: StxMarket) -> bool:
    """A single game (``*_game`` / ``*_match``) with a home and an away participant; futures and ad hoc are not."""
    return m.event_type.endswith(("_game", "_match")) and bool(m.participant(HOME) and m.participant(AWAY))


def yes_outcome(m: StxMarket) -> StxOutcome | None:
    """What YES on ``m`` pays on, from typed fields alone; None for a shape this module does not read."""
    if m.rules in WINNER_ROLE:
        return StxOutcome("team", role=WINNER_ROLE[m.rules])
    if m.rules in DRAW_RULES:
        return StxOutcome("draw")
    if m.rules == "spread":
        line = _float(m.specifier)
        return None if line is None else StxOutcome("team", role=HOME, line=line)
    if m.rules == "over_under":
        line = _float(m.specifier)
        return None if line is None else StxOutcome("over", line=line)
    if m.rules == "participant_stat_line" and m.prop_type == "ou" and m.stat_participant in (HOME, AWAY):
        return None if m.stat_line is None else StxOutcome("over", role=m.stat_participant, line=m.stat_line)
    if m.rules == "player_stat_line" and m.prop_type == "ou" and m.player:
        return None if m.stat_line is None else StxOutcome("over", line=m.stat_line, player=m.player)
    return None


def no_outcome(m: StxMarket) -> StxOutcome | None:
    """What NO on ``m`` pays on: the same market's other outcome, or None when that is not one selection."""
    yes = yes_outcome(m)
    if yes is None:
        return None
    if m.rules in TWO_WAY_WINNER_RULES:
        return StxOutcome("team", role=AWAY if yes.role == HOME else HOME)
    if m.rules == "spread" and yes.line is not None:
        return StxOutcome("team", role=AWAY, line=-yes.line)
    if yes.kind == "over":
        return StxOutcome("under", role=yes.role, line=yes.line, player=yes.player)
    return None  # 3-way NO is a double chance; a regulation-only 2-way is not read here

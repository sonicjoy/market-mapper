"""Read and group DKEX catalogue rows for one league pass.

Every grouping key here is a typed venue field: markets cluster on
``metadata.competitionId`` and belong to a league by ``subTopic``.  An
event's home and away teams come from the ``role`` DKEX writes on the
``metadata.participants[]`` entry of its team markets (moneyline,
spread, team total) -- the sibling markets that share the
competitionId.  Player props list only the player, with no role, so a
props-only event (its team markets already closed or never listed) has
no home/away and cannot be matched to a fixture; it is counted under
``no_roles`` rather than guessed from the competition name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from mappers.exchanges import dkex
from mappers.exchanges.dkex import AWAY, HOME, DkexConfig, DkexMarket, DkexParticipant
from mappers.shared import parse_iso_datetime
from mappers.snapshot_index import iter_file_or_snapshot


@dataclass
class DkexTally:
    """Per-league DKEX pass counters, reported as one line at the end."""

    stamped: int = 0
    satellites: int = 0
    duplicates: int = 0
    dropped_no_optic: int = 0
    no_fixture: int = 0
    no_roles: int = 0
    unbuildable: int = 0
    combos: int = 0
    not_open: int = 0
    untyped: int = 0
    unreadable: int = 0
    other_league: int = 0
    ignored_only: int = 0
    matched_events: int = 0
    swapped_events: int = 0
    events: int = 0


@dataclass
class DkexEvent:
    """One DKEX competition: its markets, start(s), and home/away teams."""

    event_id: str
    markets: list[DkexMarket] = field(default_factory=list)
    #: UTC minute keys.  A SET: a postponed fixture keeps its
    #: competitionId and can carry markets at both start times.
    starts: set[str] = field(default_factory=set)
    #: role -> {participant id -> participant} DKEX tagged with that role.
    roles: dict[str, dict[str, DkexParticipant]] = field(default_factory=dict)

    def team(self, role: str) -> DkexParticipant | None:
        """The one participant DKEX tagged ``role``, or None if 0 or >1."""
        found = self.roles.get(role) or {}
        if len(found) != 1:
            return None
        return next(iter(found.values()))

    @property
    def home(self) -> DkexParticipant | None:
        """The participant DKEX tagged ``home``."""
        return self.team(HOME)

    @property
    def away(self) -> DkexParticipant | None:
        """The participant DKEX tagged ``away``."""
        return self.team(AWAY)

    def has_roles(self) -> bool:
        """True when exactly one distinct home and one distinct away exist."""
        home, away = self.home, self.away
        return home is not None and away is not None and home.id != away.id


def start_key(value: str) -> str:
    """UTC minute key for a start time, tolerant of Z vs +00:00."""
    try:
        return (
            parse_iso_datetime(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
        )
    except ValueError:
        return ""


def _status_open(status: str) -> bool:
    """True when the venue status means the contract is tradeable."""
    text = status.strip().casefold()
    return text in {"open", "active"}


def _ingest_record(
    rec: dict[str, Any],
    dcfg: DkexConfig,
    tally: DkexTally,
    events: dict[str, DkexEvent],
) -> None:
    """Merge one JSONL catalogue row into its competition."""
    if rec.get("is_combo") or rec.get("legs"):
        tally.combos += 1
        return
    if not _status_open(str(rec.get("status") or "")):
        tally.not_open += 1
        return
    market = dkex.market_from_row(rec)
    if market is None:
        tally.untyped += 1
        return
    if dcfg.any_league:
        if dcfg.market_type(market) is None:
            tally.other_league += 1
            return
    elif market.league != dcfg.league.strip().upper():
        tally.other_league += 1
        return
    event = events.setdefault(market.event_id, DkexEvent(market.event_id))
    event.markets.append(market)
    sk = start_key(market.event_start)
    if sk:
        event.starts.add(sk)
    for part in market.participants:
        if part.role in (HOME, AWAY):
            event.roles.setdefault(part.role, {})[part.id] = part


def read_catalogue(
    data_dir: Path,
    dcfg: DkexConfig,
    tally: DkexTally,
) -> dict[str, DkexEvent]:
    """One pass over the catalogue -> this league's events, keyed by competitionId."""
    events: dict[str, DkexEvent] = {}
    for line in iter_file_or_snapshot(
        data_dir / "dkex_markets.jsonl",
        None,
        missing_label="dkex_markets.jsonl",
    ):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            tally.unreadable += 1
            continue
        if not isinstance(rec, dict):
            tally.unreadable += 1
            continue
        _ingest_record(rec, dcfg, tally, events)
    return events

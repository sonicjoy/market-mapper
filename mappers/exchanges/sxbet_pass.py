"""Stamp SX Bet's catalogue onto Optic rows for one league.

* **league** -- ``sxbet_leagues.slug_for`` (SX ``leagueId``, tennis by label
  prefix).  A market whose league is not mapped is ``other_league``.
* **fixture** -- first Optic's own link: an Optic odd on one of this run's
  fixtures that carries ``source_ids["SX Bet"].event_id`` names the SX
  event's fixture exactly.  Otherwise the event's kickoff (exact UTC
  minute, then the UTC day) plus BOTH SX team names, each landing on a
  different side of exactly one candidate fixture (``dkex_names`` matchers:
  ``team_side_for``, club short names for soccer, ``person_side_for`` for
  tennis / MMA).  There is no one-name fallback (DKEX's "anchored" rule):
  an event whose teams do not BOTH land is left unmapped, never guessed
  (owner, 2026-10-14: mis-mapping risk to a minimum).
* **sides** -- each outcome's team name, stripped of period suffix and
  handicap, against the event's two-name map.  On an Optic-linked event the
  map is first read off Optic's own SX ids (an outcome Optic maps to a row
  names that row's side), so SX's long names ("Tulane Green Wave") need no
  name rule there; the name matcher must not disagree with it.
* **cross-check** (Novig guard #4) -- Optic's own SX ids for this run.  A
  constructed (hash, side) Optic maps to the SAME row is left to the
  passthrough; one Optic maps to a DIFFERENT row is a disagreement and is
  dropped, never stamped; one Optic does not map is stamped.

Anything that does not resolve is dropped, never guessed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mappers.exchanges import sxbet, sxbet_leagues
from mappers.exchanges.dkex_catalogue_read import start_key
from mappers.exchanges.dkex_names import person_side_for, team_side_for
from mappers.exchanges.sxbet import SPORTSBOOK, SxConfig, SxMarket
from mappers.exchanges.sxbet_names import pinned_side
from mappers.shared import CanonicalRow

CATALOGUE_FILE = "sxbet_markets.jsonl"

Attach = Callable[[CanonicalRow], str]
KeyOf = Callable[[CanonicalRow], tuple]


@dataclass
class SxTally:
    """Per-league SX pass counters, reported as one line."""

    events: int = 0
    matched_events: int = 0
    linked_events: int = 0
    stamped: int = 0
    agree: int = 0
    conflict: int = 0
    optic_other_hash: int = 0
    duplicate: int = 0
    dropped_no_optic: int = 0
    no_fixture: int = 0
    no_sides: int = 0
    unbuildable: int = 0
    ignored: int = 0
    not_open: int = 0
    unreadable: int = 0
    unknown_types: Counter = field(default_factory=Counter)
    #: A few examples per failure reason, printed with SXBET_DEBUG=1.
    samples: dict[str, list[str]] = field(default_factory=dict)

    def sample(self, reason: str, text: str, keep: int = 5) -> None:
        """Remember an example of one failure reason (first ``keep`` only)."""
        bucket = self.samples.setdefault(reason, [])
        if len(bucket) < keep:
            bucket.append(text)

    def line(self, slug: str) -> str:
        """The stderr summary."""
        unknown = ", ".join(f"{t}x{n}" for t, n in sorted(self.unknown_types.items()))
        return (
            f"  sxbet [{slug}]: {self.matched_events}/{self.events} events matched "
            f"({self.linked_events} by Optic's event link), {self.stamped} stamped, "
            f"{self.agree} agree with Optic, {self.conflict} conflict-dropped, "
            f"{self.optic_other_hash} optic has another hash, {self.duplicate} duplicate, "
            f"{self.dropped_no_optic} dropped (optic didn't price), {self.no_fixture} no fixture, "
            f"{self.no_sides} no sides, {self.unbuildable} unbuildable, {self.ignored} ignored, "
            f"{self.not_open} not open, {self.unreadable} unreadable"
            + (f"; unmapped type(s) {unknown} -- add to mappers/vocab/sxbet_markets" if unknown else "")
        )


@dataclass
class SxEvent:
    """One SX event (``sportXeventId``): its markets, kickoff(s) and two team names."""

    event_id: str
    markets: list[SxMarket] = field(default_factory=list)
    starts: set[str] = field(default_factory=set)
    teams: set[str] = field(default_factory=set)


def read_catalogue(lines: Iterable[str], slug: str, tally: SxTally) -> dict[str, SxEvent]:
    """This league's open SX markets, grouped by event."""
    events: dict[str, SxEvent] = {}
    for line in lines:
        try:
            raw = json.loads(line)
        except (TypeError, ValueError):
            tally.unreadable += 1
            continue
        m = sxbet.market_from_row(raw) if isinstance(raw, dict) else None
        if m is None:
            tally.unreadable += 1
            continue
        if sxbet_leagues.slug_for(m.league_id, m.league_label, m.sport) != slug:
            continue
        if m.status != sxbet.OPEN_STATUS:
            tally.not_open += 1
            continue
        ev = events.setdefault(m.event_id, SxEvent(m.event_id))
        ev.markets.append(m)
        if key := start_key(m.start):
            ev.starts.add(key)
        ev.teams.update({m.team_one, m.team_two})
    return events


def read_catalogue_file(data_dir: Path, slug: str, tally: SxTally) -> dict[str, SxEvent]:
    """:func:`read_catalogue` over ``<data_dir>/sxbet_markets.jsonl`` ({} when absent)."""
    path = data_dir / CATALOGUE_FILE
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return read_catalogue(fh, slug, tally)


def _sx_src(odd: Any) -> dict | None:
    src = (getattr(odd, "source_ids", None) or {}).get(SPORTSBOOK)
    return src if isinstance(src, dict) else None


def optic_event_links(entries: list) -> dict[str, Any]:
    """{SX event id -> schedule entry} from Optic's own SX ids on this run's fixtures."""
    links: dict[str, Any] = {}
    ambiguous: set[str] = set()
    for entry in entries:
        for odd in entry.fixture.odds:
            src = _sx_src(odd)
            ev = str((src or {}).get("event_id") or "").strip()
            if not ev or ev in ambiguous:
                continue
            prior = links.get(ev)
            if prior is not None and prior is not entry:
                ambiguous.add(ev)  # one SX event on two fixtures: trust neither
                links.pop(ev, None)
                continue
            links[ev] = entry
    return links


def optic_selection_index(
    rows: Iterable[CanonicalRow], odd_lookup: dict, key_of: KeyOf,
) -> tuple[dict[str, tuple], dict[str, str]]:
    """Optic's own SX ids on this run's rows.

    Returns ``({selection_id -> row key}, {selection_id -> canonical side})``
    for every row whose Optic odd carries ``source_ids["SX Bet"]``.  The
    side map is the id bridge :func:`learned_sides` reads.
    """
    idx: dict[str, tuple] = {}
    sides: dict[str, str] = {}
    for row in rows:
        odd = odd_lookup.get(row.optic_id) if row.optic_id else None
        src = _sx_src(odd)
        sel = str((src or {}).get("selection_id") or "").strip().lower()
        if sel:
            idx[sel] = key_of(row)
            sides[sel] = row.side
    return idx, sides


def _outcome_team(name: str) -> str:
    """An outcome's team / player name: period suffix and handicap stripped."""
    parsed = sxbet.parse_handicap(name)
    return parsed[0] if parsed is not None else sxbet.strip_segment(name)


def learned_sides(event: SxEvent, optic_sides: dict[str, str], fx: Any) -> dict[str, str]:
    """{SX team name -> fixture side} read off Optic's own SX ids, never off names.

    Optic maps some of the event's (hash, side) pairs to canonical rows, and
    each such row's side is a fixture side; the SX outcome it came from names
    the team.  A name Optic puts on two sides is dropped.  Only team sides
    count (not over / under / the draw).
    """
    team_sides = {str(fx.home), str(fx.away)}
    seen: dict[str, set[str]] = {}
    for m in event.markets:
        for outcome, name in ((1, m.outcome_one), (2, m.outcome_two)):
            side = optic_sides.get(sxbet.selection_id(m.market_hash, outcome))
            if side in team_sides and not sxbet.is_not_outcome(name):
                seen.setdefault(_outcome_team(name), set()).add(side)
    learned = {name: next(iter(s)) for name, s in seen.items() if len(s) == 1}
    return learned if len(set(learned.values())) <= 2 else {}


def _fixture_index(entries: list) -> tuple[dict[str, list], dict[str, list]]:
    by_start: dict[str, list] = {}
    by_day: dict[str, list] = {}
    for entry in entries:
        key = start_key(entry.fixture.start_date)
        if key:
            by_start.setdefault(key, []).append(entry)
            by_day.setdefault(key[:10], []).append(entry)
    return by_start, by_day


def side_for(name: str, fx: Any, cfg: SxConfig) -> str | None:
    """The fixture side (``fx.home`` / ``fx.away``) an SX team or player name names, or None.

    A code pin (``sxbet_names.OPTIC_IDS_BY_SX_NAME``, by Optic competitor id) is tried first; the name rules run
    either way, and a pin and the name rules must not disagree."""
    names = {"home": str(fx.home), "away": str(fx.away), "home_name": fx.home_name, "away_name": fx.away_name}
    if cfg.person_names:
        by_name = person_side_for(name, **names)
    else:
        by_name = team_side_for(name, **names, club_short=cfg.club_short_names)
    by_id = pinned_side(name, getattr(fx, "team_map", None) or {})
    if by_id is not None:
        return by_id if by_name in (None, by_id) else None
    return by_name


def event_sides(event: SxEvent, fx: Any, cfg: SxConfig) -> dict[str, str] | None:
    """{SX team name -> fixture side} when the event's two teams land on different sides."""
    if len(event.teams) != 2:
        return None
    sides = {name: side_for(name, fx, cfg) for name in event.teams}
    found = list(sides.values())
    if None in found or found[0] == found[1]:
        return None
    return sides  # type: ignore[return-value]


def _unique(event: SxEvent, candidates: list, cfg: SxConfig) -> tuple[Any, dict[str, str]] | None:
    hits = [(e, s) for e in candidates if (s := event_sides(event, e.fixture, cfg)) is not None]
    return hits[0] if len(hits) == 1 else None


def _linked_sides(event: SxEvent, fx: Any, cfg: SxConfig, optic_sides: dict[str, str]) -> dict[str, str] | None:
    """Name -> side for an Optic-linked event: Optic's id bridge, then the name matcher.

    The two must not disagree on a name; the bridge alone is enough when it
    places both of the event's teams.
    """
    learned = learned_sides(event, optic_sides, fx)
    by_name = event_sides(event, fx, cfg) or {}
    if any(by_name.get(n) not in (None, s) for n, s in learned.items()):
        return None
    merged = {**by_name, **learned}
    if {merged.get(t) for t in event.teams} == {str(fx.home), str(fx.away)}:
        return merged
    return None


def match_event(
    event: SxEvent, links: dict[str, Any], by_start: dict[str, list], by_day: dict[str, list], cfg: SxConfig,
    optic_sides: dict[str, str] | None = None,
) -> tuple[Any, dict[str, str], bool] | None:
    """(schedule entry, name -> side, linked?) for one SX event, or None."""
    linked = links.get(event.event_id)
    if linked is not None:
        sides = _linked_sides(event, linked.fixture, cfg, optic_sides or {})
        return (linked, sides, True) if sides is not None else None
    for minute in sorted(event.starts):
        if (hit := _unique(event, by_start.get(minute, []), cfg)) is not None:
            return hit[0], hit[1], False
    for day in sorted({s[:10] for s in event.starts}):
        if (hit := _unique(event, by_day.get(day, []), cfg)) is not None:
            return hit[0], hit[1], False
    return None


def _side_of(sides: dict[str, str], fx: Any, cfg: SxConfig) -> Callable[[str], str | None]:
    """An outcome's team name -> side: the event's own names first, the matcher second."""
    def resolve(name: str) -> str | None:
        if name in sides:
            return sides[name]
        return side_for(name, fx, cfg)
    return resolve


def _stamp(
    rows: list[CanonicalRow], *, optic_index: dict[str, tuple], key_of: KeyOf, attach: Attach, tally: SxTally,
) -> None:
    for row in rows:
        if row.sx_market_hash is None or row.sx_outcome is None:  # build_rows always stamps both
            tally.unbuildable += 1
            continue
        optic_key = optic_index.get(sxbet.selection_id(row.sx_market_hash, row.sx_outcome))
        if optic_key is not None:
            if optic_key == key_of(row):
                tally.agree += 1      # the passthrough emits it
            else:
                tally.conflict += 1   # Optic maps this side elsewhere: never stamp
                print(f"  sxbet CONFLICT: {row.sx_market_hash} outcome {row.sx_outcome} parsed as "
                      f"{key_of(row)} but Optic maps it to {optic_key} -- dropping", file=sys.stderr)
            continue
        outcome = attach(row)
        if outcome == "stamped":
            tally.stamped += 1
        elif outcome == "duplicate":
            tally.duplicate += 1
        elif outcome == "optic_other_hash":
            tally.optic_other_hash += 1
        else:
            tally.dropped_no_optic += 1


def _process_event(
    event: SxEvent, matched: tuple[Any, dict[str, str], bool], *, cfg: SxConfig,
    optic_index: dict[str, tuple], key_of: KeyOf, attach: Attach, tally: SxTally,
) -> None:
    entry, sides, linked = matched
    fx = entry.fixture
    tally.matched_events += 1
    tally.linked_events += int(linked)
    side_of = _side_of(sides, fx, cfg)
    for m in event.markets:
        mt = cfg.market_type(m)
        if mt is None:
            if cfg.deliberately_unmapped(m):
                tally.ignored += 1
            else:
                tally.unknown_types[m.type] += 1
            continue
        rows = sxbet.build_rows(m, mt, side_of=side_of, home=fx.home, away=fx.away,
                                start_date=fx.start_date, league=cfg.slug)
        if not rows:
            tally.unbuildable += 1
            tally.sample("unbuildable", f"type {m.type}: {m.outcome_one!r} / {m.outcome_two!r} line {m.line} "
                                        f"on {fx.home_name} v {fx.away_name}")
            continue
        _stamp(rows, optic_index=optic_index, key_of=key_of, attach=attach, tally=tally)


def debug_lines(tally: SxTally) -> list[str]:
    """The tally's failure samples, one line each (``SXBET_DEBUG=1``)."""
    return [f"    {reason}: {text}" for reason, texts in tally.samples.items() for text in texts]


def run_pass(
    cfg: SxConfig, entries: list, rows: list[CanonicalRow], odd_lookup: dict,
    events: dict[str, SxEvent], *, key_of: KeyOf, attach: Attach, tally: SxTally | None = None,
) -> SxTally:
    """Match one league's SX events onto this run's Optic fixtures and stamp the rows."""
    tally = tally or SxTally()
    tally.events = len(events)
    if not events:
        return tally
    links = optic_event_links(entries)
    optic_index, optic_sides = optic_selection_index(rows, odd_lookup, key_of)
    by_start, by_day = _fixture_index(entries)
    for event in events.values():
        matched = match_event(event, links, by_start, by_day, cfg, optic_sides)
        if matched is None:
            teams = " v ".join(sorted(event.teams))
            if len(event.teams) == 2 and event.event_id in links:
                tally.no_sides += len(event.markets)
                fx = links[event.event_id].fixture
                tally.sample("no_sides", f"{teams} on {fx.home_name} v {fx.away_name}")
            else:
                tally.no_fixture += len(event.markets)
                tally.sample("no_fixture", f"{teams} @ {sorted(event.starts)[:1]}")
            continue
        _process_event(event, matched, cfg=cfg, optic_index=optic_index,
                       key_of=key_of, attach=attach, tally=tally)
    return tally

"""Shared module: scan PX raw data for market-name prefix and
competitor abbreviation sightings.

Intentionally independent of mappers/pipeline.py and the alias TOML
files so it can serve as an independent cross-check of alias correctness.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_TEAM_PREFIX_RE = re.compile(r"^([A-Z0-9]+): ")


@dataclass(frozen=True)
class Competitor:
    abbreviation: str  # PX abbreviation e.g. "AIR"
    name: str          # "Air Force Falcons"
    id: int


@dataclass(frozen=True)
class PrefixSighting:
    prefix: str        # e.g. "AIRF"
    event_id: int
    date: str          # "2026-02-25" (from dir name)
    home: Competitor
    away: Competitor
    market_name: str   # "AIRF: Team Total Points"


def _extract_date(data_dir: Path) -> str:
    """Extract the YYYY-MM-DD date from a data directory path.

    Handles both old-format (data/ncaab/2026-02-25/) and new-format
    (data/2026-03-07/08_05/) directory layouts by walking up to find
    the component matching a date pattern.
    """
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for part in (data_dir.name, data_dir.parent.name):
        if date_re.match(part):
            return part
    raise ValueError(f"cannot extract date from path: {data_dir}")


def _parse_events(
    path: Path,
    tournament_id: int,
) -> dict[int, tuple[Competitor, Competitor]]:
    """Parse prophetx_events.jsonl → {event_id: (home, away)}.

    Only includes events whose tournament_id matches the given value.
    """
    events: dict[int, tuple[Competitor, Competitor]] = {}
    with open(path) as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("tournament_id") != tournament_id:
                continue
            comps = obj.get("competitors", [])
            if len(comps) != 2:
                continue
            by_side: dict[str, Competitor] = {}
            for c in comps:
                by_side[c["side"]] = Competitor(
                    abbreviation=c["abbreviation"],
                    name=c["name"],
                    id=c["id"],
                )
            eid = obj.get("event_id") or obj["id"]
            events[eid] = (by_side["home"], by_side["away"])
    return events


@dataclass(frozen=True)
class CompetitorSighting:
    """A competitor abbreviation observed in a PX event."""
    abbreviation: str  # PX abbreviation e.g. "AIR"
    name: str          # "Air Force Falcons"
    id: int
    date: str          # "2026-02-25" (from dir name)
    event_id: int


def scan_competitors(
    data_dirs: list[Path],
    tournament_id: int,
) -> list[CompetitorSighting]:
    """Parse date dirs, return every competitor abbreviation sighting.

    Only includes events whose tournament_id matches.
    Yields two sightings per event (home + away).
    """
    sightings: list[CompetitorSighting] = []
    for data_dir in data_dirs:
        events_file = data_dir / "prophetx_events.jsonl"
        if not events_file.exists():
            continue
        date = _extract_date(data_dir)
        events = _parse_events(events_file, tournament_id)
        for eid, (home, away) in events.items():
            for comp in (home, away):
                sightings.append(CompetitorSighting(
                    abbreviation=comp.abbreviation,
                    name=comp.name,
                    id=comp.id,
                    date=date,
                    event_id=eid,
                ))
    return sightings


def scan_prefixes(
    data_dirs: list[Path],
    tournament_id: int,
) -> list[PrefixSighting]:
    """Parse date dirs, return every (prefix, event) association.

    Only includes events whose tournament_id matches.
    Each unique (prefix, event_id, market_name) triple produces one
    sighting.  Multiple markets with the same prefix in the same event
    each appear separately so callers can see which market names use
    the prefix.
    """
    sightings: list[PrefixSighting] = []
    for data_dir in data_dirs:
        events_file = data_dir / "prophetx_events.jsonl"
        markets_file = data_dir / "prophetx_markets.jsonl"
        if not events_file.exists() or not markets_file.exists():
            continue

        date = _extract_date(data_dir)
        events = _parse_events(events_file, tournament_id)

        with open(markets_file) as f:
            for line in f:
                obj = json.loads(line)
                name = obj.get("name", "")
                match = _TEAM_PREFIX_RE.match(name)
                if not match:
                    continue
                prefix = match.group(1)
                eid = obj.get("sport_event_id")
                if eid is None:
                    continue
                competitors = events.get(eid)
                if competitors is None:
                    continue
                home, away = competitors
                sightings.append(PrefixSighting(
                    prefix=prefix,
                    event_id=eid,
                    date=date,
                    home=home,
                    away=away,
                    market_name=name,
                ))
    return sightings

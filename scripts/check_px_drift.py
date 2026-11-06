"""Detect PX abbreviation drift across dates.

Two levels of check:

  Market-name prefixes — abbreviations extracted from market titles
  (e.g. "AIRF" from "AIRF: Team Total Points").  These have no
  anchoring metadata, so a drifting prefix can cause silent
  misassignment of team-scoped markets.  This is the high-value
  check.

  Competitor abbreviations — abbreviations from the competitors
  array in PX event JSON (e.g. "AIR" for Air Force).  These are
  anchored by name and id at runtime, so drift produces unmatched
  events (loud failure) rather than silent wrong-team assignment.
  This check provides earlier diagnostic clarity — you see "AIR
  now appears with a different team name" instead of investigating
  a mysterious missing match.

Aliasing policy
---------------
Some PX market-name prefixes have no obvious derivation from the
team name (e.g. "WBD" for Milwaukee, "CAR" on a Tulsa/Tulane game).
Two policies are possible:

  1. Aggressive: alias everything, rely on this drift script to
     catch reuse of a prefix for a different team later.

  2. Conservative: only alias prefixes with a plausible derivation
     from the team name (BOSCOL = Boston College, AIRF = Air Force).
     Leave opaque prefixes unaliased — accept lost markets rather
     than risk silent misassignment.

We choose the conservative policy.  This script is a second line of
defence for the aliases we do add, not a justification for aliasing
opaque prefixes.

Interpreting drift output
-------------------------
Not all drift is a problem.  Some is expected and already handled:

  - Known collisions.  PX uses "COL" for both Colorado Buffaloes
    (id=60000250) and Columbia Lions (id=60000159).  The TOML
    handles this with dict-form collision entries that disambiguate
    by name and id:

      [COLO]
      px = [{abbr = "COL", id = 60000250, name = "Colorado Buffaloes"}]

      [COLU]
      px = [{abbr = "COL", id = 60000159, name = "Columbia Lions"}, "COLMB"]

    When you see DRIFT for an abbreviation, check the TOML for
    dict-form entries under multiple canonicals claiming that abbr.
    If they exist, the collision is already resolved at runtime.

  - PX data errors.  A prefix like "DEN" may appear on events for
    unrelated teams (Denver vs Tulane) because of a PX-side
    mistake.  These are real drift but not something we can alias
    away — they require investigation.

This script intentionally does not load the TOML (to stay
independent of the alias files it's checking), so it cannot
distinguish handled collisions from genuine problems.  That
separation is by design: it lets the script serve as an
independent cross-check.

Usage:
    python scripts/check_px_drift.py ncaab data/2026-*/*
    python scripts/check_px_drift.py --verbose nba data/2026-*/*
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections import defaultdict
from pathlib import Path

from px_scan import PrefixSighting, scan_competitors, scan_prefixes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect PX abbreviation drift across dates.")
    parser.add_argument(
        "league",
        help="League key (e.g. ncaab, nba)")
    parser.add_argument(
        "dirs", nargs="+", type=Path,
        help="Data directories (e.g. data/2026-03-07/08_05)")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show OK prefixes too")
    args = parser.parse_args()

    league_mod = importlib.import_module(f"mappers.leagues.{args.league}")
    tournament_id: int = league_mod.LEAGUE.PX.tournament_id

    sightings = scan_prefixes(args.dirs, tournament_id)

    # --- Market-name prefixes ---
    print("--- Market-name prefixes ---")

    # Group by prefix → set of (competitor_id, competitor_name) per event.
    # A prefix belongs to one team if the intersection of competitor sets
    # across all events has exactly one member.
    prefix_events: dict[str, list[PrefixSighting]] = defaultdict(list)
    for s in sightings:
        prefix_events[s.prefix].append(s)

    drift_count = 0
    for prefix in sorted(prefix_events):
        sights = prefix_events[prefix]

        # For each event, the prefix belongs to one of two teams.
        # Collect the set of competitor IDs per unique event.
        event_comp_sets: dict[int, set[int]] = {}
        event_info: dict[int, PrefixSighting] = {}
        for s in sights:
            eid = s.event_id
            event_comp_sets.setdefault(eid, {s.home.id, s.away.id})
            event_info.setdefault(eid, s)

        # The prefix's team must appear in every event.  Intersect
        # competitor ID sets across events to find it.
        common_ids: set[int] | None = None
        for ids in event_comp_sets.values():
            if common_ids is None:
                common_ids = set(ids)
            else:
                common_ids &= ids

        assert common_ids is not None
        n_events = len(event_comp_sets)

        if len(common_ids) == 0:
            # No single team appears in all events — drift.
            drift_count += 1
            print(f"DRIFT: {prefix} — {n_events} events, "
                  f"no common team across all events")
            for eid in sorted(event_info):
                s = event_info[eid]
                print(f"  {s.date} event {eid}: "
                      f"{s.away.name} @ {s.home.name}")
        elif len(common_ids) == 1:
            # Exactly one team in common — consistent.
            if args.verbose:
                # Find the common team's name.
                cid = next(iter(common_ids))
                sample = next(iter(sights))
                name = (sample.home.name if sample.home.id == cid
                        else sample.away.name)
                print(f"OK: {prefix} — {n_events} events, "
                      f"always with {name}")
        else:
            # Both teams appear in all events (same matchup repeated).
            # Can't determine which team the prefix belongs to from
            # structure alone, but no drift.
            if args.verbose:
                s = next(iter(sights))
                print(f"OK: {prefix} — {n_events} events, "
                      f"same matchup ({s.away.name} @ {s.home.name})")

    total = len(prefix_events)
    print(f"\n{total} prefixes checked, {drift_count} drift detected",
          file=sys.stderr)

    # --- Competitor abbreviations ---
    print("\n--- Competitor abbreviations ---")

    comp_sightings = scan_competitors(args.dirs, tournament_id)

    # Group by abbreviation → set of (name, id) pairs.
    # Unlike prefixes, competitor abbreviations are directly on the
    # competitor, so we check (name, id) consistency directly — no
    # set-intersection logic needed.
    abbrev_teams: dict[str, dict[tuple[str, int], list[str]]] = defaultdict(
        lambda: defaultdict(list))
    for cs in comp_sightings:
        abbrev_teams[cs.abbreviation][(cs.name, cs.id)].append(cs.date)

    comp_drift_count = 0
    for abbrev in sorted(abbrev_teams):
        teams = abbrev_teams[abbrev]
        if len(teams) == 1:
            if args.verbose:
                (name, cid), dates = next(iter(teams.items()))
                n = len(dates)
                print(f"OK: {abbrev} — {n} sightings, always {name}")
        else:
            comp_drift_count += 1
            print(f"DRIFT: {abbrev} — maps to {len(teams)} different teams")
            for (name, cid), dates in sorted(teams.items()):
                unique_dates = sorted(set(dates))
                print(f"  {name} (id={cid}): {len(dates)} sightings, "
                      f"dates {unique_dates[0]}..{unique_dates[-1]}")

    comp_total = len(abbrev_teams)
    print(f"\n{comp_total} competitor abbreviations checked, "
          f"{comp_drift_count} drift detected", file=sys.stderr)


if __name__ == "__main__":
    main()

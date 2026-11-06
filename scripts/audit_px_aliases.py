"""Audit PX market-name prefix aliases against raw data.

PX market-name prefixes are opaque strings with no anchoring metadata
— just a bare abbreviation like "AIRF: Team Total Points".  We alias
them to canonical team abbreviations in team_aliases.toml so the
pipeline can assign team-scoped markets to the right team.

The team_aliases.toml file contains two kinds of PX alias.  Competitor
aliases (like "UWM" for Milwaukee, canonical MILW) come from the
competitors array in PX event JSON and are anchored by the
competitor's name and id.  Market-name aliases (like "BOSCOL" for
Boston College, canonical BC) come from prefixes in PX market titles
and have no anchoring metadata — they are inferred from context and
added by hand based on pipeline run diagnostics.  This script verifies
the second kind by examining raw PX market data: for each market-name
alias, it finds every event where that prefix appears, checks that the
claimed canonical team is a competitor, and confirms ownership by
elimination (the other team in the event must have its own distinct
prefix).

Output categories:

  OK           — alias confirmed by elimination
  UNCONFIRMED  — alias plausible but can't determine which team owns it
  MISMATCH     — canonical is not a competitor in the observed event
  UNSEEN       — alias in TOML but never observed as a market-name
                 prefix (shown with --verbose; typically competitor-
                 level abbreviations, not market-name prefixes)
  MISSING      — prefix observed in data but no alias in TOML
  OVERRIDDEN   — prefix handled by per-event overrides in
                 px_prefix_overrides.toml (shown with --verbose)

Usage:
    python scripts/audit_px_aliases.py ncaab data/2026-*/*
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from px_scan import PrefixSighting, scan_prefixes


class AliasIndex(NamedTuple):
    """Parsed alias data from a team_aliases.toml file."""
    alias_to_canonical: dict[str, str]
    aliases_for_canonical: dict[str, set[str]]


def _print_overridden(
    prefix: str,
    sightings: list[PrefixSighting],
    px_overrides: dict[int, dict[str, str]],
    global_canonical: str | None = None,
) -> None:
    """Print one OVERRIDDEN line per event for a fully-overridden prefix."""
    seen_eids: set[int] = set()
    suffix = f" (global: {global_canonical})" if global_canonical else ""
    for s in sightings:
        if s.event_id not in seen_eids:
            seen_eids.add(s.event_id)
            target = px_overrides[s.event_id][prefix]
            print(f"OVERRIDDEN: \"{prefix}\" event {s.event_id} "
                  f"→ {target}{suffix}")


def _load_toml_aliases(path: Path) -> AliasIndex:
    """Load TOML and build an alias index.

    Returns an AliasIndex with:
    - alias_to_canonical: every unambiguous PX alias string → canonical
      section key (canonical keys also map to themselves).  Collision
      entries (dicts with abbr/id/name) are excluded because they need
      name/id to resolve.
    - aliases_for_canonical: canonical → set of all PX abbreviations
      it claims (including collision abbrs, for competitor matching)
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    alias_to_canonical: dict[str, str] = {}
    aliases_for_canonical: dict[str, set[str]] = defaultdict(set)

    for canonical, section in data.items():
        if not isinstance(section, dict):
            continue
        # The canonical itself resolves to itself.
        alias_to_canonical[canonical] = canonical
        px_list = section.get("px", [])
        for entry in px_list:
            if isinstance(entry, str):
                alias_to_canonical[entry] = canonical
                aliases_for_canonical[canonical].add(entry)
            elif isinstance(entry, dict) and "abbr" in entry:
                # Collision entries aren't tracked in alias_to_canonical
                # (they need name/id to resolve), but record the abbr
                # so the audit knows this canonical claims it.
                aliases_for_canonical[canonical].add(entry["abbr"])

    return AliasIndex(alias_to_canonical, dict(aliases_for_canonical))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit PX aliases against raw data.")
    parser.add_argument(
        "league",
        help="League key (e.g. ncaab, nba)")
    parser.add_argument(
        "dirs", nargs="+", type=Path,
        help="Data directories (e.g. data/2026-03-07/08_05)")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show UNSEEN aliases (not observed as market-name prefixes)")
    args = parser.parse_args()

    toml_path = Path(f"config/{args.league}/team_aliases.toml")
    league_mod = importlib.import_module(f"mappers.leagues.{args.league}")
    tournament_id: int = league_mod.LEAGUE.PX.tournament_id

    index = _load_toml_aliases(toml_path)
    alias_to_canonical = index.alias_to_canonical
    aliases_for_canonical = index.aliases_for_canonical

    # Load per-event prefix overrides (ephemeral, event-specific
    # aliases that take priority over global team_aliases).
    overrides_path = Path(f"config/{args.league}/px_prefix_overrides.toml")
    px_overrides: dict[int, dict[str, str]] = {}
    if overrides_path.exists():
        with open(overrides_path, "rb") as f:
            raw = tomllib.load(f)
        for eid_str, mappings in raw.items():
            px_overrides[int(eid_str)] = mappings

    sightings = scan_prefixes(args.dirs, tournament_id)

    # Group sightings by prefix and by event.
    prefix_sightings: dict[str, list[PrefixSighting]] = defaultdict(list)
    event_prefixes: dict[int, set[str]] = defaultdict(set)
    for s in sightings:
        prefix_sightings[s.prefix].append(s)
        event_prefixes[s.event_id].add(s.prefix)

    # Collect all prefixes seen in data.
    seen_prefixes = set(prefix_sightings.keys())

    # Check each alias in the TOML.
    ok_count = 0
    unconfirmed_count = 0
    mismatch_count = 0
    unseen_count = 0
    missing_count = 0
    overridden_count = 0

    # All simple (non-collision) px alias strings from the TOML.
    # Collision abbreviations are in aliases_for_canonical (for the
    # competitor-matching check) but not in alias_to_canonical, so
    # we only audit aliases that have an unambiguous canonical.
    toml_aliases: set[str] = set()
    for canonical, aliases in aliases_for_canonical.items():
        toml_aliases.update(a for a in aliases if a in alias_to_canonical)

    for alias in sorted(toml_aliases):
        canonical = alias_to_canonical[alias]

        if alias not in seen_prefixes:
            unseen_count += 1
            if args.verbose:
                print(f"UNSEEN: \"{alias}\" → {canonical} "
                      f"— not observed as market-name prefix")
            continue

        # Check: is the canonical (or any of its aliases) among the
        # competitors in the events where this prefix appears?
        # Build the set of abbreviations that resolve to this canonical.
        canonical_abbrevs = {canonical, *aliases_for_canonical.get(
            canonical, ())}

        # Filter out events handled by per-event overrides.
        active_sightings = [
            s for s in prefix_sightings[alias]
            if not (s.event_id in px_overrides
                    and alias in px_overrides[s.event_id])
        ]
        if not active_sightings:
            overridden_count += 1
            _print_overridden(alias, prefix_sightings[alias],
                              px_overrides, canonical)
            continue

        events_ok = True
        bad_events: list[PrefixSighting] = []
        seen_event_ids: set[int] = set()
        for s in active_sightings:
            if s.event_id in seen_event_ids:
                continue
            seen_event_ids.add(s.event_id)
            event_abbrevs = {s.home.abbreviation, s.away.abbreviation}
            # Does any competitor abbreviation match any alias for
            # this canonical?
            if not event_abbrevs & canonical_abbrevs:
                events_ok = False
                bad_events.append(s)

        if events_ok:
            # Elimination check: in each event, does the OTHER team
            # have at least one known prefix?  If so, this alias is
            # confirmed as belonging to the canonical team.  If not,
            # it could belong to either team — flag as UNCONFIRMED.
            confirmed = False
            for s in active_sightings:
                # Find the other team's abbreviations (everything
                # that resolves to the other canonical).
                event_comps = {s.home.abbreviation, s.away.abbreviation}
                other_comp = event_comps - canonical_abbrevs
                if not other_comp:
                    continue
                other_abbrev = next(iter(other_comp))
                other_canonical = alias_to_canonical.get(other_abbrev)
                if other_canonical is None:
                    continue
                other_abbrevs = {other_canonical,
                                 *aliases_for_canonical.get(
                                     other_canonical, ())}
                # Do any OTHER prefixes in this event belong to the
                # other team?
                sibling_prefixes = event_prefixes[s.event_id] - {alias}
                for sib in sibling_prefixes:
                    sib_canonical = alias_to_canonical.get(sib)
                    if sib_canonical == other_canonical:
                        confirmed = True
                        break
                    if sib in other_abbrevs:
                        confirmed = True
                        break
                if confirmed:
                    break

            if confirmed:
                ok_count += 1
            else:
                unconfirmed_count += 1
                sample = active_sightings[0]
                print(f"UNCONFIRMED: \"{alias}\" → {canonical} "
                      f"— can't confirm by elimination "
                      f"({sample.away.name} @ {sample.home.name})")
        else:
            mismatch_count += 1
            print(f"MISMATCH: \"{alias}\" → {canonical}")
            for s in bad_events:
                print(f"  {s.date} event {s.event_id}: "
                      f"{s.away.name} @ {s.home.name} "
                      f"(abbrevs: {s.away.abbreviation}, "
                      f"{s.home.abbreviation})")

    # Check for prefixes in data that have no alias in the TOML.
    # Exclude prefixes that ARE canonical section keys (identity
    # mappings don't need explicit aliases).
    for prefix in sorted(seen_prefixes - toml_aliases):
        if prefix in alias_to_canonical:
            # It's a canonical key or competitor alias — resolved
            # by identity or by the competitor-level alias.
            continue
        # Check if all events for this prefix are handled by overrides.
        if all(s.event_id in px_overrides and prefix in px_overrides[s.event_id]
               for s in prefix_sightings[prefix]):
            overridden_count += 1
            _print_overridden(prefix, prefix_sightings[prefix],
                              px_overrides)
            continue
        missing_count += 1
        sample = prefix_sightings[prefix][0]
        print(f"MISSING: \"{prefix}\" — no alias or override "
              f"(seen in {sample.away.name} @ {sample.home.name})")

    print(f"\n{ok_count} OK, {unconfirmed_count} unconfirmed, "
          f"{mismatch_count} mismatch, "
          f"{unseen_count} unseen, {missing_count} missing, "
          f"{overridden_count} overridden",
          file=sys.stderr)


if __name__ == "__main__":
    main()

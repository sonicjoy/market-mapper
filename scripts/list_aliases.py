"""List all team aliases with exchange team names for visual verification.

For every canonical (Optic) team, shows each PX and Kalshi alias alongside
the team name the exchange uses for that abbreviation.  This lets a human
eyeball whether "PX says CAM = Campbell Fighting Camels" and "Optic says
CAM = Campbell" really refer to the same IRL team.

PX alias tags
-------------
Competitor aliases (from the competitors array in PX event JSON) carry
a team name directly and need no tag.  Market-name prefixes (bare
abbreviations from market titles like "AIRF: Team Total Points") have
no anchoring metadata, so the script tags them by evidence strength:

  [market-name, confirmed]
      Sibling-prefix proof.  In some event with this prefix, the
      other team also has a known prefix, so this one must belong
      to the remaining team.

  [by elimination]
      The prefix appears across multiple different matchups, and
      one team is common to all of them — so it must be that team.
      Definitive, but without the double-check of a sibling prefix.

  [candidates: Team A / Team B]
      The prefix only appeared in one matchup (or repeated matchups
      of the same two teams).  Can't determine which team owns it
      from structure alone.

Kalshi aliases carry team names from GAME-type market titles
("... at ... Winner?").

Usage:
    python scripts/list_aliases.py ncaab data/2026-*/*
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from px_scan import PrefixSighting, scan_competitors, scan_prefixes

# -------------------------------------------------------------------
# TOML parsing
# -------------------------------------------------------------------

class TomlIndex(NamedTuple):
    """Parsed alias data from a team_aliases.toml file."""
    canonicals: list[str]
    # canonical → {exchange: [alias_codes]}
    canonical_aliases: dict[str, dict[str, list[str]]]
    # For elimination: simple alias → canonical (PX only, excludes collisions)
    alias_to_canonical: dict[str, str]
    # For elimination: canonical → set of all PX abbreviations it claims
    aliases_for_canonical: dict[str, set[str]]
    # (canonical, alias_code) → declared name for collision entries
    collision_names: dict[tuple[str, str], str]


def _load_toml(path: Path) -> TomlIndex:
    """Parse team_aliases.toml into a TomlIndex.

    Extracts per-exchange alias lists for every canonical, plus the
    PX-specific alias index needed for elimination logic.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    canonicals: list[str] = []
    canonical_aliases: dict[str, dict[str, list[str]]] = {}
    alias_to_canonical: dict[str, str] = {}
    aliases_for_canonical: dict[str, set[str]] = defaultdict(set)
    collision_names: dict[tuple[str, str], str] = {}

    for canonical, section in data.items():
        if not isinstance(section, dict):
            continue
        canonicals.append(canonical)
        canonical_aliases[canonical] = {}

        # The canonical itself resolves to itself (PX identity).
        alias_to_canonical[canonical] = canonical

        for exchange, alias_list in section.items():
            if not isinstance(alias_list, list):
                continue
            codes: list[str] = []
            for entry in alias_list:
                if isinstance(entry, str):
                    codes.append(entry)
                    if exchange == "px":
                        alias_to_canonical[entry] = canonical
                        aliases_for_canonical[canonical].add(entry)
                elif isinstance(entry, dict) and "abbr" in entry:
                    codes.append(entry["abbr"])
                    collision_names[(canonical, entry["abbr"])] = entry["name"]
                    if exchange == "px":
                        # Collision entries: track in aliases_for_canonical
                        # but not alias_to_canonical (need name/id to resolve).
                        aliases_for_canonical[canonical].add(entry["abbr"])
            if codes:
                canonical_aliases[canonical][exchange] = codes

    canonicals.sort()
    return TomlIndex(
        canonicals, canonical_aliases,
        alias_to_canonical, dict(aliases_for_canonical),
        collision_names)


# -------------------------------------------------------------------
# Data loading
# -------------------------------------------------------------------

def _load_optic_names(
    data_dirs: list[Path],
    optic_league_id: str,
) -> dict[str, str]:
    """Canonical abbreviation → team name from Optic fixtures.

    Only includes fixtures whose league.id matches optic_league_id.
    """
    names: dict[str, str] = {}
    for d in data_dirs:
        path = d / "optic_fixtures_odds.jsonl"
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                obj = json.loads(line)
                league = obj.get("league")
                if isinstance(league, dict) and league.get("id") != optic_league_id:
                    continue
                for side in ("home_competitors", "away_competitors"):
                    for comp in obj.get(side, []):
                        abbr = comp["abbreviation"]
                        if abbr not in names:
                            names[abbr] = comp["name"]
    return names


def _load_kalshi_names(
    data_dirs: list[Path],
    kalshi_prefix: str,
) -> dict[str, str]:
    """Kalshi team code → team name from GAME-type market titles.

    Only includes markets whose ticker starts with kalshi_prefix.

    GAME markets have tickers like:
        KXNCAAMBGAME-26MAR05SCSTNCCU-SCST
    The suffix after the last '-' is the team code, and
    yes_sub_title is the team name ("South Carolina St.").
    """
    title_re = re.compile(r"^.+ at .+ Winner\?$")
    names: dict[str, str] = {}
    for d in data_dirs:
        path = d / "kalshi_markets.jsonl"
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                obj = json.loads(line)
                ticker = obj.get("ticker", "")
                if not ticker.startswith(kalshi_prefix):
                    continue
                title = obj.get("title", "")
                if not title_re.match(title):
                    continue
                # legacy: ticker parse — replace with the typed venue field, do not extend
                parts = ticker.rsplit("-", 1)
                if len(parts) != 2:
                    continue
                code = parts[1]
                name = obj.get("yes_sub_title", "")
                if code and name and code not in names:
                    names[code] = name
    return names


def _build_px_comp_names(
    data_dirs: list[Path],
    tournament_id: int,
) -> dict[str, str]:
    """PX competitor abbreviation → team name from event JSON."""
    names: dict[str, str] = {}
    for cs in scan_competitors(data_dirs, tournament_id):
        if cs.abbreviation not in names:
            names[cs.abbreviation] = cs.name
    return names


# -------------------------------------------------------------------
# PX prefix elimination (which team owns a market-name prefix?)
# -------------------------------------------------------------------

def _build_prefix_ownership(
    data_dirs: list[Path],
    tournament_id: int,
    alias_to_canonical: dict[str, str],
    aliases_for_canonical: dict[str, set[str]],
) -> tuple[
    dict[str, str],                     # prefix → confirmed team name
    dict[str, tuple[str, str]],         # prefix → (owner_name, other_name)
    dict[str, tuple[str, str]],         # prefix → (name_a, name_b) ambiguous
    set[str],                           # all prefixes seen in data
]:
    """Run elimination logic on PX market-name prefixes.

    Returns:
      confirmed: prefix → team name (elimination succeeded)
      unconfirmed: prefix → (name_a, name_b) both candidates
      seen_prefixes: all prefixes observed in data
    """
    sightings = scan_prefixes(data_dirs, tournament_id)

    # Group sightings by prefix and by event.
    prefix_sightings: dict[str, list[PrefixSighting]] = defaultdict(list)
    event_prefixes: dict[int, set[str]] = defaultdict(set)
    for s in sightings:
        prefix_sightings[s.prefix].append(s)
        event_prefixes[s.event_id].add(s.prefix)

    seen_prefixes = set(prefix_sightings.keys())
    confirmed: dict[str, str] = {}
    # Structurally one team, but sibling-prefix proof unavailable.
    # prefix → (owner_name, other_name)
    eliminated: dict[str, tuple[str, str]] = {}
    # True ambiguity: both teams in every event.
    # prefix → (name_a, name_b)
    ambiguous: dict[str, tuple[str, str]] = {}

    for prefix in seen_prefixes:
        # For each event, intersect competitor sets to find which
        # team is common across all events with this prefix.
        events: dict[int, PrefixSighting] = {}
        for s in prefix_sightings[prefix]:
            events.setdefault(s.event_id, s)

        # Find the team(s) common to all events.
        common_ids: set[int] | None = None
        for s in events.values():
            ids = {s.home.id, s.away.id}
            common_ids = ids if common_ids is None else common_ids & ids
        assert common_ids is not None

        if len(common_ids) != 1:
            # Can't determine from structure alone (same matchup
            # repeated, or drift).  Show both teams from first event.
            sample = next(iter(events.values()))
            ambiguous[prefix] = (sample.home.name, sample.away.name)
            continue

        # One team in common — that's likely the owner, but can we
        # confirm by elimination?
        owner_id = next(iter(common_ids))
        sample = next(iter(events.values()))
        owner_name = (sample.home.name if sample.home.id == owner_id
                      else sample.away.name)

        # Check if the OTHER team in any event has a known prefix.
        elim_confirmed = False
        for s in events.values():
            other_abbr = (s.away.abbreviation if s.home.id == owner_id
                          else s.home.abbreviation)
            other_canonical = alias_to_canonical.get(other_abbr)
            if other_canonical is None:
                continue
            other_abbrevs = {other_canonical,
                             *aliases_for_canonical.get(other_canonical, ())}
            sibling_prefixes = event_prefixes[s.event_id] - {prefix}
            for sib in sibling_prefixes:
                sib_canonical = alias_to_canonical.get(sib)
                if sib_canonical == other_canonical or sib in other_abbrevs:
                    elim_confirmed = True
                    break
            if elim_confirmed:
                break

        if elim_confirmed:
            confirmed[prefix] = owner_name
        else:
            # Structurally consistent (one team common to all events)
            # but not proven by the stricter sibling-prefix check.
            # Record (owner, other) so the report can show
            # "by elimination of <other>".
            other_name = (sample.away.name if sample.home.id == owner_id
                          else sample.home.name)
            eliminated[prefix] = (owner_name, other_name)

    return confirmed, eliminated, ambiguous, seen_prefixes


# -------------------------------------------------------------------
# Report
# -------------------------------------------------------------------

def _format_line(code: str, name: str, tag: str = "") -> str:
    """Format one alias line: code padded, name, optional tag."""
    tag_str = f"  {tag}" if tag else ""
    return f"{code:<7s}{name}{tag_str}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List all team aliases with exchange team names.")
    parser.add_argument(
        "league",
        help="League key (e.g. ncaab, nba)")
    parser.add_argument(
        "dirs", nargs="+", type=Path,
        help="Data directories (e.g. data/2026-03-07/08_05)")
    args = parser.parse_args()

    toml_path = Path(f"config/{args.league}/team_aliases.toml")
    league_mod = importlib.import_module(f"mappers.leagues.{args.league}")
    league_cfg = league_mod.LEAGUE
    tournament_id: int = league_cfg.PX.tournament_id
    optic_league_id: str = league_cfg.OPTIC.league_id
    # KALSHI is Optional (e.g. MLS, the first KALSHI=None league — Task 7):
    # skip the Kalshi section entirely rather than crash, mirroring
    # probe_kalshi_catalog.py's `if cfg.KALSHI is not None` guard.
    kalshi_prefix: str | None = (
        league_cfg.KALSHI.prefix if league_cfg.KALSHI is not None else None
    )

    # --- Load data ---
    toml = _load_toml(toml_path)
    optic_names = _load_optic_names(args.dirs, optic_league_id)
    px_comp_names = _build_px_comp_names(args.dirs, tournament_id)
    kalshi_names = (
        _load_kalshi_names(args.dirs, kalshi_prefix) if kalshi_prefix is not None else {}
    )

    prefix_confirmed, prefix_eliminated, prefix_ambiguous, seen_prefixes = \
        _build_prefix_ownership(
            args.dirs, tournament_id,
            toml.alias_to_canonical, toml.aliases_for_canonical)

    # --- Print report ---
    for canonical in toml.canonicals:
        team_name = optic_names.get(canonical, "?")
        print(canonical)
        print(f"  optic:  {_format_line(canonical, team_name)}")

        aliases = toml.canonical_aliases.get(canonical, {})
        px_aliases = aliases.get("px", [])
        kalshi_aliases = aliases.get("kalshi", [])

        # PX section: show the canonical code (identity mapping)
        # plus any explicit aliases.  Skip the canonical if PX uses
        # that code for a different team (e.g. PX "CSU" → CSUB,
        # not CSU Colorado State).
        px_identity = (
            toml.alias_to_canonical.get(canonical) == canonical)
        px_codes = sorted(
            set(([canonical] if px_identity else []) + px_aliases))
        has_px = False
        for code in px_codes:
            label = "px:     " if not has_px else "        "

            # Collision entries use the declared name from the TOML
            # (the data has the same abbrev for multiple teams).
            collision_name = toml.collision_names.get(
                (canonical, code))

            if collision_name:
                print(f"  {label}{_format_line(code, collision_name, '[collision]')}")
                has_px = True
            elif code in px_comp_names:
                # Competitor-level alias — direct name.
                name = px_comp_names[code]
                print(f"  {label}{_format_line(code, name)}")
                has_px = True
            elif code in seen_prefixes:
                # Market-name prefix.
                if code in prefix_confirmed:
                    name = prefix_confirmed[code]
                    print(f"  {label}{_format_line(code, name, '[market-name, confirmed]')}")
                elif code in prefix_eliminated:
                    owner, _other = prefix_eliminated[code]
                    print(f"  {label}{_format_line(code, owner, '[by elimination]')}")
                elif code in prefix_ambiguous:
                    a, b = prefix_ambiguous[code]
                    tag = f"[candidates: {a} / {b}]"
                    print(f"  {label}{_format_line(code, '', tag)}")
                else:
                    print(f"  {label}{_format_line(code, '', '[seen, unresolved]')}")
                has_px = True
            else:
                # Not seen in data at all — only show if it's an
                # explicit alias (not the identity code).
                if code in px_aliases:
                    print(f"  {label}{_format_line(code, '', '[unseen]')}")
                    has_px = True

        if not has_px:
            print("  px:     —")

        # Kalshi section.
        kalshi_codes = sorted(set([canonical] + kalshi_aliases))
        has_kalshi = False
        for code in kalshi_codes:
            label = "kalshi: " if not has_kalshi else "        "

            if code in kalshi_names:
                name = kalshi_names[code]
                print(f"  {label}{_format_line(code, name)}")
                has_kalshi = True
            else:
                # Only show if it's an explicit alias.
                if code in kalshi_aliases:
                    print(f"  {label}{_format_line(code, '', '[unseen]')}")
                    has_kalshi = True

        if not has_kalshi:
            print("  kalshi: —")

        print()

    print(f"{len(toml.canonicals)} canonicals listed", file=sys.stderr)


if __name__ == "__main__":
    main()

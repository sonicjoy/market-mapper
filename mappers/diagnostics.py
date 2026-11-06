"""Diagnostic helpers for the merge pipeline.

Formatting functions for operator-facing warnings and error messages.
All output goes to stderr via the caller or print(..., file=sys.stderr).
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from mappers.name_match import levenshtein
from mappers.shared import CanonicalRow, MatchKey, normalize_line, time_of_day, to_date_str, to_et_str


def hours_to_game(game_start: datetime, fetch_time: datetime) -> float:
    """Hours from fetch time to estimated game start."""
    return (game_start - fetch_time).total_seconds() / 3600

if TYPE_CHECKING:
    from mappers.pipeline import ScheduleEntry


def schedule_table(
    game_date: str,
    index: dict[MatchKey, list[ScheduleEntry]],
) -> str:
    """Format an aligned fixture table for a given date, sorted by away team.

    Each line: '  HH:MM  AWAY Away Name  @ HOME Home Name'
    with fixed-width fields so the @ column aligns.
    """
    rows: list[tuple[str, str, str, str, str]] = []
    for key, entries in index.items():
        if key.game_date != game_date:
            continue
        for entry in entries:
            f = entry.fixture
            rows.append((
                time_of_day(f.start_et),
                f.away, f.away_name,
                f.home, f.home_name,
            ))
    rows.sort(key=lambda r: (r[1], r[0]))  # away abbrev, then tip-off

    if not rows:
        return f"  Schedule ({game_date}): (no fixtures)"

    # Compute column widths.
    away_w = max(len(r[1]) for r in rows)
    away_name_w = max(len(r[2]) for r in rows)
    home_w = max(len(r[3]) for r in rows)

    lines_out = [f"  Schedule ({game_date}):"]
    for time, away, away_name, home, home_name in rows:
        lines_out.append(
            f"  {time}  {away:<{away_w}} {away_name:<{away_name_w}} "
            f"@ {home:<{home_w}} {home_name}")
    return "\n".join(lines_out)


def _near_matches(
    index: dict[MatchKey, list[ScheduleEntry]],
    game_date: str,
    teams: set[str],
) -> list[tuple[MatchKey, ScheduleEntry]]:
    """Find schedule games sharing at least one team with the given pair."""
    return sorted(
        (
            (key, entry)
            for key, entries in index.items()
            for entry in entries
            if key.game_date == game_date
            and {key.home, key.away} & teams
        ),
        key=lambda pair: pair[0],
    )


def no_match_detail(
    index: dict[MatchKey, list[ScheduleEntry]],
    game_date: str,
    away: str,
    home: str,
    canonicals: set[str],
) -> tuple[str, bool]:
    """Build a diagnostic detail string for an unmatched game.

    Returns (detail_message, has_unknown_teams).  has_unknown_teams is
    True only when at least one of home/away is absent from the alias
    TOML — a near-match on the same date is diagnostic colour, not proof
    of an unknown code (wrong-claimant collisions used to be mislabeled
    actionable alias gaps because of that).
    """
    teams = {home, away}
    unknown = teams - canonicals
    nearby = _near_matches(index, game_date, teams)
    if nearby:
        canonical = sorted(teams & canonicals)
        missing = sorted(unknown)
        parts: list[str] = []
        if canonical:
            parts.append(f"Canonical: {', '.join(canonical)}")
        if missing:
            parts.append(f"Missing: {', '.join(missing)}")
        for key, entry in nearby:
            f = entry.fixture
            parts.append(
                f"Near match: {key.away}@{key.home} "
                f"({time_of_day(f.start_et)} {f.away_name} "
                f"@ {f.home_name})")
        detail = "\n  ".join(parts)
        detail += "\n\n" + schedule_table(game_date, index)
        return detail, bool(unknown)

    if not unknown:
        return (
            "Both teams are known canonicals — game likely missing "
            "from schedule source.",
            False)

    abbrs = ", ".join(sorted(unknown))
    return (
        f"No near matches — abbreviation(s) may need aliases: "
        f"{abbrs}\n\n"
        + schedule_table(game_date, index),
        True)



def _surname_key(name: str) -> tuple[str, str]:
    parts = name.rsplit("_", 1)
    return (parts[-1], parts[0]) if len(parts) > 1 else (name, "")


# Side-flip map used by row_orphan_summary to detect Optic over/under
# asymmetry.  Team-sided markets (moneyline, spread, three-way) are
# intentionally excluded: their "opposite side" lives on the other team
# under a different entity/line, so a generic flip doesn't apply.
_OPPOSITE_SIDE: dict[str, str] = {
    "over": "under",
    "under": "over",
    "yes": "no",
    "no": "yes",
}


def row_orphan_summary(all_rows: list[CanonicalRow]) -> None:
    """Classify rows that failed to match Optic and print a summary.

    Most PX-only and Kalshi-only rows reflect genuine differences in
    what each exchange chooses to publish rather than mapping bugs.
    Three benign patterns dominate and are detected here, in
    increasing order of specificity:

      - Side-asymmetric — same (entity, market_type, line) had the
        opposite side matched.  PX publishes both over and under at a
        threshold; Optic publishes only the opposite side as a
        standalone ladder line.

      - Integer push — this row's line is integer and Optic has a
        half-line neighbour for the same (entity, market_type) in
        this game.  PX publishes push-possible integer totals; Optic
        only publishes half-point lines for the same stat.

      - Ladder extension — some other line on this (game, market_type,
        entity) matched Optic.  Kalshi frequently publishes a wide
        ladder of alternate spreads/totals where Optic publishes only
        one or two; PX does the same at half-point alt lines.

    Remaining rows ("unexplained") are the ones worth investigating:
    either genuine coverage gaps we could close or real mapping bugs.

    Output is a single stderr line in the same style as the existing
    reconcile: summaries, emitted once per league.
    """
    # Index rows for two kinds of lookup:
    #   full_key: exact merge key for opposite-side lookup.
    #   game_entity: same (game, market_type, entity) for half-line
    #                neighbour lookup.
    by_full_key: dict[tuple, CanonicalRow] = {}
    by_game_entity: dict[tuple, list[CanonicalRow]] = defaultdict(list)

    for r in all_rows:
        full = (r.league, r.start_date, r.home, r.away, r.market_type,
                r.entity, normalize_line(r.line), r.grouping_key, r.side)
        by_full_key[full] = r
        ge = (r.league, r.start_date, r.home, r.away, r.market_type,
              r.entity)
        by_game_entity[ge].append(r)

    side_asymmetric = 0
    integer_push = 0
    ladder_extension = 0
    unexplained = 0

    for r in all_rows:
        # Only classify rows with an exchange match that missed Optic.
        if r.optic_id is not None:
            continue
        if r.px_line_id is None and r.kalshi_ticker is None:
            continue

        # Side asymmetry: does the opposite side on this same line
        # have an Optic match?
        opp = _OPPOSITE_SIDE.get(r.side)
        if opp is not None and r.line is not None:
            opp_key = (r.league, r.start_date, r.home, r.away,
                       r.market_type, r.entity, normalize_line(r.line),
                       r.grouping_key, opp)
            opp_row = by_full_key.get(opp_key)
            if opp_row is not None and opp_row.optic_id is not None:
                side_asymmetric += 1
                continue

        # Integer push: this row's line is an integer and Optic has
        # a half-line neighbour for the same entity in the same game.
        ge = (r.league, r.start_date, r.home, r.away,
              r.market_type, r.entity)
        if r.line is not None and float(r.line) == int(r.line):
            has_half_neighbour = any(
                n.optic_id is not None
                and n.line is not None
                and abs(n.line - r.line) == 0.5
                for n in by_game_entity.get(ge, [])
            )
            if has_half_neighbour:
                integer_push += 1
                continue

        # Ladder extension: some other line on this game+market+entity
        # did match Optic.  Covers Kalshi 1H spread/total ladders and
        # PX alternate-line offerings where Optic carries only the
        # primary line.
        if any(n.optic_id is not None for n in by_game_entity.get(ge, [])):
            ladder_extension += 1
            continue

        unexplained += 1

    total = side_asymmetric + integer_push + ladder_extension + unexplained
    if not total:
        return
    print(
        f"orphans: {total} rows without Optic match "
        f"({side_asymmetric} side-asymmetric, "
        f"{integer_push} integer-push, "
        f"{ladder_extension} ladder-extension, "
        f"{unexplained} unexplained)",
        file=sys.stderr,
    )


def player_orphan_table(
    all_rows: list[CanonicalRow],
    player_types: set[str],
    orphan_dist: int,
) -> None:
    """Print player name normalization diagnostics to stderr.

    For each game, collect per-source player name sets.  When a
    game has exchange orphans (names on PX/Kalshi but not Optic),
    print the full unified roster so a human can decide whether
    each orphan is a normalization bug (needs alias) or a genuine
    coverage gap (different real player).

    Keyed by game (not game + market_type) because PX offers many
    players Optic doesn't cover for a given type — per-type check
    is too noisy.  Per-game catches true normalization divergences.
    """
    optic_players: dict[tuple, set[str]] = defaultdict(set)
    px_players: dict[tuple, set[str]] = defaultdict(set)
    kalshi_players: dict[tuple, set[str]] = defaultdict(set)
    exchange_players: dict[tuple, set[str]] = defaultdict(set)

    for r in all_rows:
        if r.entity is None or r.market_type not in player_types:
            continue
        game = (r.start_date, r.home, r.away)
        if r.optic_id is not None:
            optic_players[game].add(r.entity)
        if r.px_line_id is not None:
            px_players[game].add(r.entity)
            exchange_players[game].add(r.entity)
        if r.kalshi_ticker is not None:
            kalshi_players[game].add(r.entity)
            exchange_players[game].add(r.entity)

    all_games = set(optic_players) | set(exchange_players)
    for game in sorted(all_games):
        optic_set = optic_players.get(game, set())
        px_set = px_players.get(game, set())
        kalshi_set = kalshi_players.get(game, set())
        ex_set = exchange_players.get(game, set())

        ex_orphans = ex_set - optic_set
        if not ex_orphans:
            continue

        all_names = sorted(optic_set | ex_set, key=_surname_key)

        # Pre-compute nearest Optic distance for each orphan.
        dist_map: dict[str, int] = {}
        if optic_set:
            for name in ex_orphans:
                dist_map[name] = min(
                    levenshtein(name, o) for o in optic_set
                )

        # Only show games where at least one orphan is close enough
        # to an Optic player to warrant investigation.
        if not any(d <= orphan_dist for d in dist_map.values()):
            continue

        start_date, home, away = game
        et_date = to_date_str(to_et_str(start_date))
        print(f"\n  {away} @ {home}  {et_date}", file=sys.stderr)
        print(
            f"  {'Player':<28} {'Optic':>5} {'PX':>7} {'Kalshi':>9}",
            file=sys.stderr,
        )
        print(
            f"  {'─' * 28} {'─' * 5} {'─' * 7} {'─' * 9}",
            file=sys.stderr,
        )
        for name in all_names:
            o = "✓" if name in optic_set else " "
            dist = dist_map.get(name)
            d_suffix = f"({dist})" if dist is not None else ""
            p = f"✓{d_suffix}" if name in px_set else " "
            k = f"✓{d_suffix}" if name in kalshi_set else " "
            print(
                f"  {name:<28} {o:>5} {p:>7} {k:>9}",
                file=sys.stderr,
            )

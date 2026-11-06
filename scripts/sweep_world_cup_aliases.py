"""Sweep World Cup fixtures: Optic abbreviations vs Kalshi codes.

For every active Optic fixture on fifa_-_world_cup, fetch Kalshi-only
odds and join each KXWCGAME moneyline row to the fixture's competitors
via source_ids — the row carries the actual Kalshi ticker, so the
Optic-abbreviation ↔ Kalshi-code pairing is ground truth (no name
heuristics, unlike the NCAAB bootstrap which had no direct join).

Also verifies the ticker's home/away ordering against the fixture's
home/away competitors, since world_cup.py will reuse the EPL game
regex and needs to know which 3-char code is which side.

Writes config/world_cup/team_aliases.toml (all canonicals as
sections, kalshi = [...] only where the code disagrees) and prints a
per-fixture report.

Usage:
    python scripts/sweep_world_cup_aliases.py [--max-fixtures N]
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from time import sleep

from fetch.optic import BASE_URL, _init_headers, get_optic

LEAGUE_ID = "fifa_-_world_cup"

# legacy: ticker parse — replace with the typed venue field, do not extend
GAME_TICKER_RE = re.compile(
    r"^KXWCGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})-([A-Z]+)$"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep WC fixtures for Kalshi/Optic code mismatches.")
    parser.add_argument(
        "--max-fixtures", type=int,
        help="Limit fixtures fetched (for smoke testing)")
    args = parser.parse_args()

    headers = _init_headers("opticodds_access_key")

    fixtures = get_optic(
        BASE_URL + "fixtures/active", headers, {"league": LEAGUE_ID})
    fixtures.sort(key=lambda fx: (fx["start_date"], fx["id"]))
    print(f"{len(fixtures)} active fixtures on {LEAGUE_ID}",
          file=sys.stderr)
    if args.max_fixtures:
        fixtures = fixtures[:args.max_fixtures]

    # kalshi_code → {optic_abbr: count}; >1 key means a conflict.
    code_to_abbr: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int))
    abbr_names: dict[str, str] = {}     # optic_abbr → country name
    # Teams where Optic ships an empty abbreviation (WC debutants,
    # probed 2026-06-07: Haiti, Curacao, New Zealand).  No canonical
    # key exists for them yet — collect name → kalshi code instead.
    empty_abbr: dict[str, str] = {}     # country name → kalshi code
    first_is_home = second_is_home = 0  # ticker code-order tallies
    no_kalshi: list[str] = []
    unmatched_selections: list[str] = []

    for i, fx in enumerate(fixtures, 1):
        fid = fx["id"]
        home = fx["home_competitors"][0]
        away = fx["away_competitors"][0]
        for c in (home, away):
            if c["abbreviation"]:
                abbr_names[c["abbreviation"]] = c["name"]

        result = get_optic(
            BASE_URL + "fixtures/odds", headers,
            {"fixture_id": fid, "sportsbook": "kalshi"})
        odds = result[0]["odds"] if result else []
        ml_rows = [o for o in odds if o.get("market_id") == "moneyline"]

        row_report: list[str] = []
        found_kalshi = False
        for row in ml_rows:
            source_ids = row.get("source_ids") or {}
            ticker = source_ids.get("market_id", "")
            m = GAME_TICKER_RE.match(ticker)
            if not m:
                continue
            found_kalshi = True
            code1, code2, sel_code = m.group(4), m.group(5), m.group(6)
            if sel_code == "TIE":
                continue

            selection = row.get("selection", "")
            if selection == home["name"]:
                competitor = home
                side = "home"
            elif selection == away["name"]:
                competitor = away
                side = "away"
            else:
                unmatched_selections.append(
                    f"{fid}: selection {selection!r} matches neither "
                    f"{home['name']!r} nor {away['name']!r} ({ticker})")
                continue

            abbr = competitor["abbreviation"]
            if not abbr:
                empty_abbr[competitor["name"]] = sel_code
                row_report.append(
                    f"    {side:4} --- ({competitor['name']}) "
                    f"= kalshi {sel_code}  <-- NO OPTIC ABBR")
                continue
            code_to_abbr[sel_code][abbr] += 1
            if side == "home":
                if sel_code == code1:
                    first_is_home += 1
                elif sel_code == code2:
                    second_is_home += 1
            marker = "" if sel_code == abbr else "  <-- DIFFERS"
            row_report.append(
                f"    {side:4} {abbr:3} ({competitor['name']}) "
                f"= kalshi {sel_code}{marker}")

        status = "" if found_kalshi else "  [no KXWCGAME odds]"
        print(f"[{i}/{len(fixtures)}] {fx['start_date']}  "
              f"{away['name']} @ {home['name']}  ({fid}){status}")
        for line in row_report:
            print(line)
        if not found_kalshi:
            no_kalshi.append(
                f"{fid} {fx['start_date']} "
                f"{away['name']} @ {home['name']}")
        sleep(0.2)

    # --- Summary ---
    conflicts: list[str] = []
    aliases: dict[str, str] = {}  # optic_abbr → kalshi code (differing only)
    identity = 0
    for code, abbrs in sorted(code_to_abbr.items()):
        if len(abbrs) > 1:
            conflicts.append(f"  {code} → {dict(abbrs)}")
            continue
        abbr = next(iter(abbrs))
        if code == abbr:
            identity += 1
        else:
            aliases[abbr] = code

    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"  teams seen: {len(abbr_names) + len(empty_abbr)} "
          f"({len(abbr_names)} with Optic abbreviations, "
          f"{len(empty_abbr)} without)", file=sys.stderr)
    print(f"  identity matches: {identity}", file=sys.stderr)
    print(f"  disagreements: {len(aliases)}", file=sys.stderr)
    for abbr, code in sorted(aliases.items()):
        print(f"    {abbr} ({abbr_names[abbr]}) ← kalshi {code}",
              file=sys.stderr)
    print(f"  ticker order: first-code-is-home {first_is_home}, "
          f"second-code-is-home {second_is_home}", file=sys.stderr)
    if empty_abbr:
        print(f"  empty Optic abbreviation ({len(empty_abbr)}):",
              file=sys.stderr)
        for name, code in sorted(empty_abbr.items()):
            print(f"    {name} ← kalshi {code}", file=sys.stderr)
    if conflicts:
        print(f"  CONFLICTS ({len(conflicts)}):", file=sys.stderr)
        for c in conflicts:
            print(c, file=sys.stderr)
    if no_kalshi:
        print(f"  fixtures with no KXWCGAME odds ({len(no_kalshi)}):",
              file=sys.stderr)
        for line in no_kalshi:
            print(f"    {line}", file=sys.stderr)
    if unmatched_selections:
        print(f"  unmatched selections ({len(unmatched_selections)}):",
              file=sys.stderr)
        for line in unmatched_selections:
            print(f"    {line}", file=sys.stderr)

    # --- Write TOML ---
    lines_out = [
        "# World Cup team aliases: canonical (Optic) → exchange variants.",
        "# Generated by scripts/sweep_world_cup_aliases.py from all",
        "# active fifa_-_world_cup fixtures vs live KXWCGAME tickers",
        "# (source_ids join, so each pairing is ground truth).",
        "",
    ]
    # Teams with an empty Optic abbreviation get their canonical
    # pinned to the Kalshi code via OpticConfig.abbr_overrides (see
    # world_cup.py), so they appear here as ordinary sections —
    # identity with Kalshi, hence no kalshi = [...] entry.
    sections = dict(abbr_names)
    for name, code in empty_abbr.items():
        sections[code] = f"{name} (canonical via OpticConfig.abbr_overrides)"

    for abbr in sorted(sections):
        lines_out.append(f"[{abbr}]  # {sections[abbr]}")
        if abbr in aliases:
            lines_out.append(f'kalshi = ["{aliases[abbr]}"]')

    toml_path = Path("config/world_cup/team_aliases.toml")
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    toml_path.write_text("\n".join(lines_out) + "\n")
    print(f"\nWrote {toml_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

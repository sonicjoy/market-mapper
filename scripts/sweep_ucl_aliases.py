"""Sweep UCL fixtures: Optic abbreviations vs Kalshi codes.

Same approach as scripts/sweep_world_cup_aliases.py — join KXUCLGAME
moneyline rows via Kalshi source_ids.

Writes config/ucl/team_aliases.toml on first run; once that file
exists it writes a .new sibling instead (the committed file carries
hand-curated entries a later sweep cannot re-derive — merge by hand,
or --force to overwrite).

Usage:
    python scripts/sweep_ucl_aliases.py [--max-fixtures N] [--force]
"""

import argparse
import io
import re
import sys
from collections import defaultdict
from pathlib import Path
from time import sleep

from fetch.optic import BASE_URL, _init_headers, get_optic

LEAGUE_ID = "uefa_-_champions_league"

# The team block is one variable-width group, not two fixed 3-letter ones:
# qualifying-round clubs carry codes of other widths (KUPS, KI, OL), and a
# fixed 3+3 pattern skipped their rows, so the sweep could never re-derive
# the very aliases those clubs need.  Ticker order is recovered below by
# asking which end of the block the selection code sits at.
# legacy: ticker parse — replace with the typed venue field, do not extend
GAME_TICKER_RE = re.compile(
    r"^KXUCLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)-([A-Z]+)$"
)


def main() -> None:
    # UCL team names carry non-Latin-1 glyphs (ş/ć/ë); a cp1252 Windows
    # console would otherwise crash the fixture report with
    # UnicodeEncodeError mid-sweep.  Force UTF-8 on the output streams.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Sweep UCL fixtures for Kalshi/Optic code mismatches.")
    parser.add_argument(
        "--max-fixtures", type=int,
        help="Limit fixtures fetched (for smoke testing)")
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="Overwrite config/ucl/team_aliases.toml even if it "
             "exists (default: write a .new sibling to merge by hand)")
    args = parser.parse_args()

    headers = _init_headers("opticodds_access_key")

    fixtures = get_optic(
        BASE_URL + "fixtures/active", headers, {"league": LEAGUE_ID})
    fixtures.sort(key=lambda fx: (fx["start_date"], fx["id"]))
    print(f"{len(fixtures)} active fixtures on {LEAGUE_ID}",
          file=sys.stderr)
    if args.max_fixtures:
        fixtures = fixtures[:args.max_fixtures]

    code_to_abbr: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int))
    abbr_names: dict[str, str] = {}
    # {section code: optic competitor id} — written as optic_id in the
    # TOML.  pipeline.run resolves competitors through these pins
    # (load_optic_abbr_overrides) before falling back to Optic's own
    # abbreviation, so every section carries one.  For teams whose
    # Optic abbreviation is empty the pin is the only resolution path:
    # without it load_fixtures raises on first sight of the team.
    optic_ids: dict[str, str] = {}
    empty_abbr: dict[str, str] = {}
    collisions: list[str] = []
    first_is_home = second_is_home = 0
    no_kalshi: list[str] = []
    unmatched_selections: list[str] = []

    for i, fx in enumerate(fixtures, 1):
        fid = fx["id"]
        home = fx["home_competitors"][0]
        away = fx["away_competitors"][0]
        for c in (home, away):
            if c["abbreviation"]:
                abbr = c["abbreviation"]
                # Optic abbreviations are not unique (2026-07-13: FLO
                # is both FC Flora Tallinn and Floriana FC).  Keep the
                # first team seen and report the clash — the operator
                # must hand-pin the loser under its Kalshi code, as
                # with empty abbreviations.
                if abbr in optic_ids and optic_ids[abbr] != c["id"]:
                    collisions.append(
                        f"{abbr}: kept {abbr_names[abbr]!r} "
                        f"(id={optic_ids[abbr]}), dropped {c['name']!r} "
                        f"(id={c['id']}) — hand-pin the dropped team "
                        f"under its Kalshi code")
                    continue
                abbr_names[abbr] = c["name"]
                optic_ids[abbr] = c["id"]

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
            team_block, sel_code = m.group(4), m.group(5)
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
                # Kalshi's code becomes the canonical for this team, so
                # the pin keys on it rather than an Optic abbreviation.
                optic_ids[sel_code] = competitor["id"]
                row_report.append(
                    f"    {side:4} --- ({competitor['name']}) "
                    f"= kalshi {sel_code}  <-- NO OPTIC ABBR")
                continue
            code_to_abbr[sel_code][abbr] += 1
            if side == "home":
                if team_block.startswith(sel_code):
                    first_is_home += 1
                elif team_block.endswith(sel_code):
                    second_is_home += 1
            marker = "" if sel_code == abbr else "  <-- DIFFERS"
            row_report.append(
                f"    {side:4} {abbr:3} ({competitor['name']}) "
                f"= kalshi {sel_code}{marker}")

        status = "" if found_kalshi else "  [no KXUCLGAME odds]"
        print(f"[{i}/{len(fixtures)}] {fx['start_date']}  "
              f"{away['name']} @ {home['name']}  ({fid}){status}")
        for line in row_report:
            print(line)
        if not found_kalshi:
            no_kalshi.append(
                f"{fid} {fx['start_date']} "
                f"{away['name']} @ {home['name']}")
        sleep(0.2)

    conflicts: list[str] = []
    aliases: dict[str, str] = {}
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

    print("\n=== Summary ===", file=sys.stderr)
    print(f"  teams seen: {len(abbr_names) + len(empty_abbr)} "
          f"({len(abbr_names)} with Optic abbreviations, "
          f"{len(empty_abbr)} without)", file=sys.stderr)
    print(f"  identity matches: {identity}", file=sys.stderr)
    print(f"  disagreements: {len(aliases)}", file=sys.stderr)
    for abbr, code in sorted(aliases.items()):
        print(f"    {abbr} ({abbr_names[abbr]}) <- kalshi {code}",
              file=sys.stderr)
    print(f"  ticker order: first-code-is-home {first_is_home}, "
          f"second-code-is-home {second_is_home}", file=sys.stderr)
    if empty_abbr:
        print(f"  empty Optic abbreviation ({len(empty_abbr)}):",
              file=sys.stderr)
        for name, code in sorted(empty_abbr.items()):
            print(f"    {name} <- kalshi {code}", file=sys.stderr)
    if conflicts:
        print(f"  CONFLICTS ({len(conflicts)}):", file=sys.stderr)
        for c in conflicts:
            print(c, file=sys.stderr)
    if collisions:
        print(f"  ABBR COLLISIONS ({len(collisions)}):", file=sys.stderr)
        for c in collisions:
            print(f"    {c}", file=sys.stderr)
    if unmatched_selections:
        print(f"  unmatched selections ({len(unmatched_selections)}):",
              file=sys.stderr)
        for line in unmatched_selections:
            print(f"    {line}", file=sys.stderr)
    if no_kalshi:
        print(f"  fixtures with no KXUCLGAME odds ({len(no_kalshi)}):",
              file=sys.stderr)
        for line in no_kalshi:
            print(f"    {line}", file=sys.stderr)

    lines_out = [
        "# UCL team aliases: canonical (Optic) -> exchange variants.",
        "# Seeded by scripts/sweep_ucl_aliases.py from active",
        "# uefa_-_champions_league fixtures vs live KXUCLGAME tickers,",
        "# then hand-curated: each sweep only sees fixtures Kalshi is",
        "# quoting that day, so entries it cannot re-derive (kalshi",
        "# aliases, collision pins) must survive regeneration.",
        "# optic_id pins competitor id -> canonical (see",
        "# load_optic_abbr_overrides); qualifying-round minnows often",
        "# ship an empty Optic abbreviation, and the pin is then the",
        "# only way load_fixtures can resolve them.",
        "",
    ]
    sections = dict(abbr_names)
    for name, code in empty_abbr.items():
        sections[code] = f"{name} (empty Optic abbr; canonical is Kalshi's code)"

    for abbr in sorted(sections):
        lines_out.append(f"[{abbr}]  # {sections[abbr]}")
        lines_out.append(f'optic_id = "{optic_ids[abbr]}"')
        if abbr in aliases:
            lines_out.append(f'kalshi = ["{aliases[abbr]}"]')

    # The committed TOML carries hand-curated entries the sweep cannot
    # re-derive (see the header lines above), so never overwrite it in
    # place: write a sibling .new file for the operator to merge by
    # hand.  Same philosophy as the gold files in mappers/run.py.
    toml_path = Path("config/ucl/team_aliases.toml")
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    if toml_path.exists() and not args.force:
        toml_path = toml_path.with_suffix(".toml.new")
        print(f"\n{toml_path.with_suffix('')} exists; writing sweep "
              f"output to {toml_path} — diff and merge by hand, or "
              f"re-run with --force to overwrite", file=sys.stderr)
    toml_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"Wrote {toml_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

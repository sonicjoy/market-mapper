"""Synthetic-fixture job orchestrator.

    GCP_PROJECT=rs-marketmaking .venv/bin/python -m synthetic.run
    GCP_PROJECT=marketmaking-test .venv/bin/python -m synthetic.run --dry-run
    ... --config path/to/series.toml     # override the series file
    ... --only KXITFDOUBLES               # restrict to one series (smoke test)

GENERAL by design: the series to run on come from `series.toml`, and the job
synthesizes a fixture + mapping ONLY for events with no coverage anywhere —
skipping anything ORIGINAL (Optic) or GREG already maps. Flow (per run): list
open Kalshi markets for each configured series → group into events → coverage gate
(skip / backfill / synth) → reconcile opticodds_fixtures + market_mapping. Safety
is real-time in the pricing layer; this job only wires up the mapping/fixture and
does status housekeeping.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime

from BigQuery.client import ro_client
from fetch.kalshi import fetch_milestones, load_credentials
from synthetic import adapters, coverage, writers
from synthetic.kalshi_series import fetch_markets


def _group_events(markets: list[dict]) -> dict[str, list[dict]]:
    """Bucket market records by their Kalshi event_ticker (one event = one match)."""
    events: dict[str, list[dict]] = defaultdict(list)
    for m in markets:
        events[m["event_ticker"]].append(m)
    return events


def run(config_path: str, only_series: str | None, dry_run: bool) -> int:
    series_list = adapters.load_series(config_path)
    if only_series:
        # --only is a SMOKE TEST ONLY, and must not write. Every reconcile step is
        # scoped by `wsdsyn-` game_id, not by series, so a single-series write run
        # is a mass teardown of the series it did NOT run:
        #   * reconcile_mappings blanket-deletes all wsdsyn- GREG rows, then
        #     inserts only this series' (for write_greg_rows=false, that is NONE)
        #   * reconcile_fixtures flips every other synthetic fixture to
        #     status='completed' via its `id NOT IN (live_ids)` housekeeping
        #   * publish_overrides set-diffs against the FULL published set, so every
        #     other series' overrides are retracted (active=false) and stop pricing
        if not dry_run:
            print(f"[synthetic] refusing to write with --only {only_series}: the "
                  f"reconcile steps are scoped by wsdsyn- game_id, not by series, "
                  f"so a single-series write run would tear down every other "
                  f"series (GREG rows deleted, fixtures completed, overrides "
                  f"retracted). Re-run with --dry-run, or drop --only.",
                  file=sys.stderr)
            return 2
        series_list = [s for s in series_list if s.series_ticker == only_series]
        if not series_list:
            print(f"[synthetic] no series {only_series!r} in {config_path}", file=sys.stderr)
            return 1
    names = [s.series_ticker for s in series_list]
    client = ro_client()
    win_start, win_end = coverage.window()
    now = writers.now_iso()

    print(f"[synthetic] project={client.project} series={names} "
          f"window={win_start}..{win_end} dry_run={dry_run}", file=sys.stderr)

    key_id, private_key = load_credentials()
    markets_by_series = {
        s.series_ticker: fetch_markets(s.series_ticker, key_id, private_key)
        for s in series_list}
    # SKIP set: anything ORIGINAL or GREG already maps (never duplicate their coverage).
    covered = coverage.load_covered_tickers(
        client, [m["ticker"] for ms in markets_by_series.values() for m in ms],
        win_start)
    # A match's day comes from its Kalshi milestone start_date. Outrights
    # take theirs from expected_expiration_time and need no milestones.
    milestones = (
        fetch_milestones(key_id, private_key)
        if any(s.market_type != "outright" for s in series_list) else {})
    # Optic fixtures only needed for the (default-off) backfill path.
    backfill_sports = {s.sport_id for s in series_list if s.allow_backfill}
    optic_fixtures = []
    for sport in sorted(backfill_sports):
        optic_fixtures += coverage.load_optic_fixtures(client, sport, win_start, win_end)
    print(f"[synthetic] {len(covered)} tickers already covered (ORIGINAL/GREG); "
          f"{len(optic_fixtures)} fixtures loaded for backfill", file=sys.stderr)

    fixture_rows: list[dict] = []
    mapping_rows: list[dict] = []
    # GREG rows are accumulated per-series, so the write_greg_rows flag never
    # has to be re-derived from a row's ticker afterwards.
    greg_rows: list[dict] = []
    n_skip = n_backfill = n_synth = n_bad = n_ttko = n_nostart = 0
    now_dt = datetime.now(UTC)

    for series in series_list:
        markets = markets_by_series[series.series_ticker]
        events = _group_events(markets)
        print(f"[synthetic] {series.series_ticker}: {len(markets)} markets, "
              f"{len(events)} events", file=sys.stderr)

        for event_ticker, ms in events.items():
            if series.market_type == "outright":
                # N-runner outright (F1/NASCAR race winner). Emulates the manual
                # F1/NASCAR process: fixture + overrides, yes side only, no GREG
                # rows (see SyntheticSeries.write_greg_rows).
                #
                # start_date comes from Kalshi's expected_expiration_time minus
                # start_bias_minutes: a race has no game milestone. The bias is ~360 min — verified against published
                # schedules for the 2026 Italian GP and four NASCAR races (see
                # series.toml). Uses the MODAL expiration across the field, not
                # ms[0]: contracts within one event occasionally disagree.
                est = adapters.estimated_start_for_event(
                    ms, series.start_bias_minutes)
                if est is None:
                    # No expected_expiration_time at all. This is the SEASON
                    # FUTURE signal (KXMOTOGP 0/22, KXINDYCARSERIES 0/25,
                    # KXNASCARTRUCKSERIES 0/35 all lack it) — reject. Note this
                    # is the opposite of the 2-way TTKO gate below, which fails
                    # OPEN when the field is missing. Counted separately from
                    # n_bad: "no start time" is what distinguishes a season
                    # future from a misconfigured series.
                    n_nostart += 1
                    continue
                if series.ttko_hours is not None:
                    if (est - now_dt).total_seconds() / 3600 > series.ttko_hours:
                        n_ttko += 1
                        continue
                # All-or-nothing by design: if ANY runner is already mapped (e.g.
                # a hand-published race_winner override still active), skip the
                # whole race rather than half-map a field of 22.
                if any(m["ticker"] in covered for m in ms):
                    n_skip += 1
                    continue
                start_iso = est.isoformat()
                game_id = fixture_id = writers.synthetic_game_id(event_ticker)
                fixture_rows.append(writers.build_outright_fixture_row(
                    game_id, series, start_iso,
                    "live" if est <= now_dt else "", now))
                new_rows = writers.build_outright_mapping_rows(
                    series, game_id, fixture_id, ms, start_iso, now)
                mapping_rows.extend(new_rows)
                if series.write_greg_rows:
                    greg_rows.extend(new_rows)
                n_synth += 1
                continue

            if len(ms) != 2:
                # Match-winner events are exactly 2 sides. Anything else
                # (futures, walkover-collapsed, mid-list) is skipped, logged.
                n_bad += 1
                continue
            ms.sort(key=lambda m: m["ticker"])
            a, b = ms
            if a["ticker"] in covered or b["ticker"] in covered:
                n_skip += 1
                continue
            if series.ttko_hours is not None:
                est = adapters.estimated_start(a, series.start_bias_minutes)
                if est is not None:
                    hours_out = (est - now_dt).total_seconds() / 3600
                    if hours_out > series.ttko_hours:
                        n_ttko += 1
                        continue
            milestone = milestones.get(event_ticker) or {}
            day_dt = adapters.match_day(milestone.get("start_date"))
            name_a = a.get("yes_sub_title") or ""
            name_b = b.get("yes_sub_title") or ""
            if day_dt is None or not name_a or not name_b:
                n_bad += 1
                continue

            existing = (
                coverage.find_existing_fixture(
                    name_a, name_b, day_dt.date(), optic_fixtures,
                    league_id=series.league_id)
                if series.allow_backfill else None
            )
            start_iso = day_dt.isoformat()
            if existing:
                game_id, fixture_id = existing          # backfill onto real fixture
                n_backfill += 1
            else:
                game_id = fixture_id = writers.synthetic_game_id(event_ticker)
                home, away = sorted([name_a, name_b])
                fixture_rows.append(writers.build_fixture_row(
                    game_id, series, home, away, start_iso, "live", now))
                n_synth += 1

            new_rows = writers.build_mapping_rows(
                series, game_id, fixture_id,
                a["ticker"], name_a, b["ticker"], name_b, start_iso, now)
            mapping_rows.extend(new_rows)
            if series.write_greg_rows:
                greg_rows.extend(new_rows)

    print(f"[synthetic] gate: {n_skip} skip (already covered), "
          f"{n_ttko} ttko (too far from kickoff), "
          f"{n_backfill} backfill (real fixture), {n_synth} synth (new fixture), "
          f"{n_bad} skipped (not a 2-side event / no milestone date / no names), "
          f"{n_nostart} skipped (outright with no expected_expiration_time — "
          f"season future)", file=sys.stderr)
    print(f"[synthetic] to write: {len(fixture_rows)} fixtures, "
          f"{len(mapping_rows)} mapping rows ({len(greg_rows)} of them GREG)",
          file=sys.stderr)

    if dry_run:
        writers.publish_overrides(client, mapping_rows, dry_run=True)
        print("[synthetic] dry-run — no writes", file=sys.stderr)
        return 0

    # Only series with write_greg_rows contribute market_mapping rows (accumulated
    # per-series above). Overrides (below) always get the FULL set — they are what
    # makes a fixture priceable. reconcile_mappings does a blanket wsdsyn- delete
    # then inserts what it is given, so flipping the flag off self-cleans on the
    # next run with no migration.
    writers.reconcile_fixtures(client, fixture_rows, win_start)
    writers.reconcile_mappings(client, greg_rows, win_start)
    # Third reconcile step: publish mapping_override messages so the Kalshi orderbook
    # price pipeline (which reads mapping_override -> prices_dedup_state, NOT GREG
    # market_mapping) actually prices these fixtures. Without this the legs map but
    # fall back to 1.0. Set-diff: only publishes changes (new enables + retractions
    # for tickers now covered by ORIGINAL/GREG).
    writers.publish_overrides(client, mapping_rows)
    print("[synthetic] done", file=sys.stderr)
    return 0


def main() -> None:
    """CLI entrypoint: parse args and run one reconcile pass."""
    p = argparse.ArgumentParser(description="Synthesize fixtures/mappings for Kalshi markets Optic has no fixture for.")
    p.add_argument("--config", default=str(adapters.DEFAULT_CONFIG),
                   help="series.toml path (default: the one shipped in synthetic/).")
    p.add_argument("--only", metavar="SERIES_TICKER", default=None,
                   help="Restrict to one series ticker. SMOKE TEST ONLY — "
                        "requires --dry-run, since the reconcile steps are scoped "
                        "by wsdsyn- game_id and would tear down every other series.")
    p.add_argument("--dry-run", action="store_true", help="Compute + report, no BQ writes.")
    args = p.parse_args()
    sys.exit(run(args.config, args.only, args.dry_run))


if __name__ == "__main__":
    main()

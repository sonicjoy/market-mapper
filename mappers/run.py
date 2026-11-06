#!/usr/bin/env python3
"""Map exchange markets onto an Optic-derived schedule.

Usage: python -m mappers.run <data_dir> [--league LEAGUE]
       [--json | --table | --eyeball [N] | --gold] [--pick HASH[,...]]

Dispatches through the activated tip. Multi-league runs fan out via
ProcessPoolExecutor (MAP_LEAGUE_WORKERS, default 4). Set to 1 for serial.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tabulate import tabulate

from mappers import eyeball, pipeline
from mappers.exchanges.optic_passthrough_crosscheck import CrosscheckLedger
from mappers.optic_crosscheck_alert import (
    enrich_ledger_blocks,
    publish_new_disagreements,
)
from mappers.pipeline import LeagueConfig, PipelineResult
from mappers.run_provenance import new_run_provenance
from mappers.seed import tip_leagues
from mappers.seed.sot import load_snapshot, reset_sot_cache
from mappers.seed.tip_leagues import load_tip_leagues
from mappers.snapshot_index import (
    SnapshotIndex,
    filter_empty_optic,
    resolve_snapshot,
    worker_init,
    worker_snapshot,
)

# Re-export: infra scripts and tests import these from mappers.run.
__all__ = ["LEAGUES", "api_fetch_league_keys"]

LEAGUES: dict[str, LeagueConfig] = load_tip_leagues()

_DEFAULT_MAP_LEAGUE_WORKERS = 4

# Active run set for this process (and ProcessPool workers via initializer).
_RUN_LEAGUES: dict[str, LeagueConfig] = dict(LEAGUES)


def map_league_workers() -> int:
    """Process-pool size for multi-league map (env MAP_LEAGUE_WORKERS)."""
    raw = os.environ.get("MAP_LEAGUE_WORKERS", str(_DEFAULT_MAP_LEAGUE_WORKERS))
    try:
        n = int(raw)
    except ValueError:
        n = _DEFAULT_MAP_LEAGUE_WORKERS
    return max(1, n)


def _emit_map_league_step(key: str, sec: int, rows: int) -> None:
    print(f"STEP name=map_league league={key} sec={sec} rows={rows}",
          file=sys.stderr)


def _run_league(
    data_dir: Path,
    key: str,
    league: LeagueConfig,
    orphan_dist: int,
    *,
    snapshot: SnapshotIndex | None = None,
) -> PipelineResult | None:
    """Map one league; None (with an alert) when its data made it raise.

    Every wired league is mapped and mappings are written only after all
    leagues finish, so an exception on one league's data used to cost
    every other league its rows for that tick — a single boxing moneyline
    odd shipped with no team_id took the whole 2026-08-06 run down.  The
    tick still exits 0 so the surviving leagues load to BigQuery;
    infra/cron_pipeline.sh greps ^ALERT: and posts the Slack warning.
    """
    try:
        snap = snapshot if snapshot is not None else worker_snapshot()
        return pipeline.run(
            data_dir, league, orphan_dist=orphan_dist, snapshot=snap,
        )
    except Exception as exc:
        # Keep the cause on the ALERT: line so cron_pipeline.sh's
        # `grep '^ALERT:'` Slack payload is self-diagnosing — the
        # traceback still lands in the log, but success-path alerts
        # used to drop it and leave only the generic league failure.
        cause = f"{type(exc).__name__}: {exc}".replace("\n", " | ")
        print(f"ALERT: {key} mapping failed and produced no rows this "
              f"tick; the other leagues continue. Cause: {cause}",
              file=sys.stderr)
        traceback.print_exc()
        return None


def api_fetch_league_keys() -> list[str]:
    """League keys for ``run_pipeline.sh`` fetch + map (legacy tip still read when SoT=bq)."""
    return tip_leagues.api_fetch_league_keys({})


def set_run_leagues(leagues: dict[str, LeagueConfig]) -> None:
    """Install the active map run set (parent + ProcessPool workers)."""
    global _RUN_LEAGUES
    _RUN_LEAGUES = leagues


def _run_league_cfg(key: str) -> LeagueConfig:
    """LeagueConfig for key from the active run set (M5 tip or LEAGUES)."""
    try:
        return _RUN_LEAGUES[key]
    except KeyError:
        return LEAGUES[key]


def _timed_run_league(
    data_dir: Path,
    key: str,
    orphan_dist: int,
    *,
    snapshot: SnapshotIndex | None = None,
) -> tuple[str, PipelineResult | None]:
    """Run one league and emit STEP map_league (serial path / tests)."""
    t0 = time.perf_counter()
    result = _run_league(
        data_dir, key, _run_league_cfg(key), orphan_dist, snapshot=snapshot,
    )
    sec = int(round(time.perf_counter() - t0))
    rows = len(result.rows) if result is not None else 0
    _emit_map_league_step(key, sec, rows)
    return key, result


def _map_league_worker(
    data_dir: str, key: str, orphan_dist: int,
) -> tuple[str, PipelineResult | None, int]:
    """Top-level worker for ProcessPoolExecutor (Windows spawn-safe).

    Returns (league_key, result_or_None, wall_sec).  STEP is printed in
    the worker so per-league timing appears as soon as that league ends.
    """
    t0 = time.perf_counter()
    result = _run_league(Path(data_dir), key, _run_league_cfg(key), orphan_dist)
    sec = int(round(time.perf_counter() - t0))
    rows = len(result.rows) if result is not None else 0
    _emit_map_league_step(key, sec, rows)
    return key, result, sec


def _worker_init_with_leagues(
    snapshot: SnapshotIndex | None,
    leagues: dict[str, LeagueConfig],
) -> None:
    """ProcessPool initializer: share SnapshotIndex + tip-resolved run set."""
    worker_init(snapshot)
    set_run_leagues(leagues)


def _collect_league_results(
    data_dir: Path,
    league_keys: list[str],
    orphan_dist: int,
    *,
    gold: bool,
    snapshot: SnapshotIndex | None = None,
) -> dict[str, PipelineResult | None]:
    """Map leagues (serial or process pool); preserve deterministic key order later."""
    # Drop gold skips before scheduling so workers never run them.
    to_run: list[str] = []
    for key in league_keys:
        if gold:
            gold_path = data_dir / "gold" / f"{key}.jsonl"
            if gold_path.exists():
                print(f"skip: {gold_path} already exists",
                      file=sys.stderr)
                continue
        to_run.append(key)
    to_run = filter_empty_optic(snapshot, to_run, _RUN_LEAGUES)
    workers = map_league_workers()
    results: dict[str, PipelineResult | None] = {}

    if workers == 1 or len(to_run) <= 1:
        for key in to_run:
            _, result = _timed_run_league(
                data_dir, key, orphan_dist, snapshot=snapshot,
            )
            results[key] = result
        return results

    with ProcessPoolExecutor(
        max_workers=min(workers, len(to_run)),
        initializer=_worker_init_with_leagues,
        initargs=(snapshot, _RUN_LEAGUES),
    ) as pool:
        futures = {
            pool.submit(
                _map_league_worker, str(data_dir), key, orphan_dist,
            ): key
            for key in to_run
        }
        for fut in as_completed(futures):
            key, result, _sec = fut.result()
            results[key] = result
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Map exchange markets onto an Optic-derived schedule")
    parser.add_argument("dir", type=Path,
                        help="Data directory containing JSONL files")
    # --league accepts tip-only slugs (M5); validate after tip resolve.
    parser.add_argument(
        "--league", nargs="+",
        help="Process only these leagues (default: tip when SoT=bq, else all)",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true",
                        help="Emit JSONL output")
    output.add_argument("--table", action="store_true",
                        help="Emit human-readable table")
    output.add_argument("--eyeball", nargs="?", const=1, type=int,
                        metavar="N",
                        help="Show N examples per market type for review")
    output.add_argument("--html", nargs="?", const=1, type=int,
                        metavar="N",
                        help="Write eyeball review as HTML")
    output.add_argument("--gold", action="store_true",
                        help="Write golden mapping files to <dir>/gold/")
    output.add_argument("--write-mappings", action="store_true",
                        help="Write JSONL mappings to <dir>/mappings.jsonl")
    parser.add_argument("--pick", type=str, metavar="HASH[,...]",
                        help="Eyeball specific bets by hash (from --table)")
    parser.add_argument("--with-orphans", action="store_true",
                        help="Include single-exchange orphans in --eyeball")
    parser.add_argument("--orphan-dist", type=int, default=5, metavar="N",
                        help="Show orphan roster when nearest Optic "
                             "distance <= N (default: 5)")
    args = parser.parse_args()

    reset_sot_cache()
    snap = load_snapshot()
    tip_rows: list = list(snap.leagues)
    market_rules: list = list(snap.market_rules)
    print(f"SOT=bq tip={snap.rule_set_id} (COW coalesced)", file=sys.stderr)

    run_leagues = tip_leagues.resolve_run_leagues(
        {},
        tip_rows,
        market_rules=market_rules or None,
        filter_keys=list(args.league) if args.league else None,
    )
    if not run_leagues:
        print("FATAL: no leagues to map (empty tip / filter)", file=sys.stderr)
        sys.exit(1)
    set_run_leagues(run_leagues)
    league_keys = list(args.league) if args.league else sorted(run_leagues)
    unknown = [k for k in league_keys if k not in run_leagues]
    if unknown:
        print(
            f"FATAL: unknown --league keys (not enabled on tip / LEAGUES): {unknown}",
            file=sys.stderr,
        )
        sys.exit(1)
    league_keys = [k for k in league_keys if k in run_leagues]

    run_provenance = new_run_provenance()
    print(
        f"mapping_run_id={run_provenance.mapping_run_id} "
        f"commit={run_provenance.mapper_git_commit or 'unknown'}",
        file=sys.stderr,
    )

    snapshot = resolve_snapshot(args.dir)

    all_rows: list = []
    all_odd_lookup: dict = {}
    all_game_ref_lookup: dict = {}
    all_output_orders: list = []
    failed: list[str] = []
    crosscheck_ledger = CrosscheckLedger()

    results = _collect_league_results(
        args.dir, league_keys, args.orphan_dist, gold=args.gold,
        snapshot=snapshot,
    )

    # Aggregate in league_keys order so mappings.jsonl stays deterministic
    # under parallel completion.
    for key in league_keys:
        if key not in results:
            continue  # gold skip
        result = results[key]
        if result is None:
            failed.append(key)
            continue
        league = _run_league_cfg(key)
        all_rows.extend(result.rows)
        all_odd_lookup.update(result.odd_lookup)
        all_game_ref_lookup.update(result.game_ref_lookup)
        all_output_orders.append(league.OUTPUT_ORDER)
        if result.crosscheck_ledger is not None:
            crosscheck_ledger.disagreements.extend(
                result.crosscheck_ledger.disagreements,
            )
            crosscheck_ledger.optic_only.extend(
                result.crosscheck_ledger.optic_only,
            )
            crosscheck_ledger.seen_disagree |= result.crosscheck_ledger.seen_disagree

        # Gold writes per-league after that league's result is in.
        # Skip when the league produced no rows for this snapshot —
        # avoids littering inactive-league gold files (e.g. mlb.jsonl
        # in NBA-only snapshots) when --league is not passed.
        if args.gold:
            if not result.rows:
                print(f"skip: no {key} rows in {args.dir}", file=sys.stderr)
                continue
            rows = sorted(result.rows, key=pipeline.gold_sort_key)
            gold_dir = args.dir / "gold"
            gold_dir.mkdir(exist_ok=True)
            gold_path = gold_dir / f"{key}.jsonl"
            with open(gold_path, "w") as f:
                for r in rows:
                    f.write(json.dumps(pipeline.gold_row(r)) + "\n")
            print(f"wrote {len(rows)} rows to {gold_path}", file=sys.stderr)

    # A single bad league is survivable; nothing left to write is not.
    # Count only leagues that were scheduled (not gold-skipped).
    scheduled = [k for k in league_keys if k in results]
    if failed and scheduled and len(failed) == len(scheduled):
        print(f"FATAL: every league failed to map: {', '.join(failed)}",
              file=sys.stderr)
        sys.exit(1)

    if args.gold:
        return

    if args.write_mappings:
        out_path = args.dir / "mappings.jsonl"
        prov_dict = run_provenance.as_dict()
        sport_by_league = {
            slug: pipeline.config_sport(cfg)
            for slug, cfg in _RUN_LEAGUES.items()
        }
        with open(out_path, "w") as f:
            for r in all_rows:
                obj = pipeline.canonical_row_to_json(
                    r, all_odd_lookup, all_game_ref_lookup,
                    run_provenance=prov_dict,
                    sport=sport_by_league.get(r.league),
                )
                f.write(json.dumps(obj) + "\n")
        meta_path = args.dir / "mapping_run.json"
        with open(meta_path, "w") as f:
            json.dump(prov_dict, f)
        blocks_path = args.dir / "optic_crosscheck_blocks.jsonl"
        blocks = enrich_ledger_blocks(crosscheck_ledger)
        if blocks:
            with open(blocks_path, "w") as bf:
                for rec in blocks:
                    bf.write(json.dumps(rec) + "\n")
            print(
                f"wrote {len(blocks)} optic cross-check block(s) to {blocks_path}",
                file=sys.stderr,
            )
        publish_new_disagreements(crosscheck_ledger, data_dir=args.dir)
        print(f"wrote {len(all_rows)} rows to {out_path}", file=sys.stderr)
        return

    # === Output ===
    if args.pick is not None:
        if args.json or args.table:
            parser.error("--pick requires --eyeball (or no output flag)")
        picks = set(args.pick.split(","))
        eyeball.print_review(
            all_rows, all_odd_lookup, all_output_orders,
            n=args.eyeball if args.eyeball is not None else 1,
            picks=picks, with_orphans=args.with_orphans)
    elif args.eyeball is not None:
        eyeball.print_review(
            all_rows, all_odd_lookup, all_output_orders, n=args.eyeball,
            with_orphans=args.with_orphans)
    elif args.html is not None:
        html = eyeball.render_html(
            all_rows, all_odd_lookup, all_output_orders, n=args.html,
            with_orphans=args.with_orphans)
        Path("eyeball.html").write_text(html)
        print("Wrote eyeball.html")
    elif args.json:
        sport_by_league = {
            slug: pipeline.config_sport(cfg)
            for slug, cfg in _RUN_LEAGUES.items()
        }
        for r in all_rows:
            print(json.dumps(pipeline.canonical_row_to_json(
                r, all_odd_lookup, all_game_ref_lookup,
                sport=sport_by_league.get(r.league),
            )))
    elif args.table:
        bets = eyeball.group_bets(all_rows)
        row_bet: dict[int, str] = {}
        for h, (_bk, bet_rows) in bets.items():
            for r in bet_rows:
                row_bet[id(r)] = h
        headers = [
            "bet", "start_date", "home", "away", "market_type",
            "entity", "line", "side", "grouping_key",
            "px_line_id", "kalshi_ticker", "kalshi_side",
            "crypto_security_id", "optic_id",
        ]
        table_data = [
            [row_bet[id(r)], r.start_date, r.home, r.away, r.market_type,
             r.entity or "", r.line if r.line is not None else "",
             r.side, r.grouping_key or "",
             r.px_line_id or "",
             r.kalshi_ticker or "", r.kalshi_side or "",
             r.crypto_security_id or "", r.optic_id or ""]
            for r in all_rows
        ]
        print(tabulate(table_data, headers=headers, tablefmt="simple"))


if __name__ == "__main__":
    # Windows spawn: guard required for ProcessPoolExecutor.
    main()

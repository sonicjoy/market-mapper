"""Kill switch: set max stake AND max risk to 0 for every selection on a fixture.

WHAT THIS IS FOR
    A synthetic fixture has gone wrong -- mis-mapped, mis-priced, attached to the
    wrong Optic match -- and you want to stop taking risk on it NOW, without
    waiting for the synthetic job's next tick, without a deploy, and without
    touching the mapping.

    Give it a fixture id; it zeroes every selection on that fixture.

    Works for ANY fixture id, not just `wsdsyn-` ones -- the override key is
    built from `optic_fixture_id`, which for a synthetic fixture IS the
    `wsdsyn-...` id (a synthetic sets id == game_id).

WHY ZERO WORKS (verified, not assumed)
    `RedisStakeTracker.check_stake_limit` (MMutils/handlers/redis_stake_tracker.py)
    resolves the per-leg override with `if leg_limit is not None:` -- so 0 is
    HONOURED, not swallowed as falsy -- then rejects when
    `current + wanted_stake > limit`. With limit 0, any positive stake is
    rejected as MARKET_STAKE_LIMIT. `max_risk_per_market` behaves the same way.
    This is the same zero-stake pattern the service's own API documents as the
    example on PUT /trading-config/overrides/ticker.

KEY FORMAT -- there is NO fixture-level key
    The override tiers are:
        selection : {optic_fixture_id}-{market}-{selection_or_line}
        line      : {selection key}-{line}
        market    : {sport}-{market}
        ticker    : rfq.metadata['market_ticker']
    There is no plain {fixture_id} tier, so "zero the fixture" means one
    override per selection. That is why this script enumerates selections
    rather than writing a single key.

    We POST to /trading-config/overrides/selections and let the SERVICE build
    the key, rather than constructing `{fixture}-{market}-{selection}` ourselves
    -- it applies its own `.replace(" ", "-")`, and player names contain spaces.
    Only --clear needs the composed key, because DELETE takes it in the path.

BOTH TENANTS BY DEFAULT
    Kalshi runs a pre-off tenant (kalshi-services/kalshi-rfq-trading-service)
    and an in-play one (inplay-parlay-services/kalshi-rfq-trading-inplay-service).
    They share rfq-config-redis, but do not rely on that: a fixture killed on one
    tenant and live on the other is the worst outcome, so we write to both and
    report per tenant. --tenant narrows it if you really want one.

USAGE
    GCP_PROJECT=rs-marketmaking python -m synthetic.zero_stake wsdsyn-KXITFMATCH-26SEP02VUJTAL
    GCP_PROJECT=rs-marketmaking python -m synthetic.zero_stake wsdsyn-... --apply
    GCP_PROJECT=rs-marketmaking python -m synthetic.zero_stake wsdsyn-... --apply --clear
    ... --tenant inplay          # one tenant only
    ... --selection "Stefan Vujic"   # one selection only, repeatable

Dry run by default: prints exactly what it would write and to where.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess  # nosec B404 - kubectl port-forward, fixed argv, no shell
import sys
import time

import requests

from BigQuery.client import ro_client

HTTP_TIMEOUT = 15
DEAD = {"max_stake_per_market": 0, "max_risk_per_market": 0}

# (label, namespace, service, service port)
TENANTS = {
    "preoff": ("preoff", "kalshi-services", "kalshi-rfq-trading-service", 80),
    "inplay": ("inplay", "inplay-parlay-services", "kalshi-rfq-trading-inplay-service", 80),
}


SYNTHETIC_PREFIX = "wsdsyn-"


def fixtures_for_leagues(client, league_ids: list[str]) -> list[str]:
    """Live `wsdsyn-` fixture ids in one or more synthetic leagues.

    This is the "halt a whole series NOW" path: you should not have to paste 40
    fixture ids to stop a league. ``league_ids`` are series.toml ``league_id``
    values, matched against the fixture's own league_id column. Scoped so it
    can only ever widen to things we minted:
      * `wsdsyn-` id, so a real Optic fixture can never be selected;
      * `status = 'live'`, so settled matches are not touched;
      * the partition filter the fixtures table requires.

    Deliberately reads `opticodds_fixtures` rather than `prices_dedup_state`: a
    fixture whose overrides were already retracted still has a fixture row, and
    zeroing its stake is harmless, whereas missing a live fixture is not.
    """
    from google.cloud import bigquery
    sql = f"""
        SELECT DISTINCT id
        FROM `{client.project}.opticodds_us.opticodds_fixtures`
        WHERE start_date BETWEEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY)
                             AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 2 DAY)
          AND status = 'live'
          AND STARTS_WITH(id, '{SYNTHETIC_PREFIX}')
          AND league_id IN UNNEST(@leagues)
        ORDER BY id
    """  # nosec B608 - project is code-derived; leagues are bound parameters
    params = [bigquery.ArrayQueryParameter("leagues", "STRING", list(league_ids))]
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    return [r["id"] for r in job.result()]


def selections_for(client, fixture_id: str) -> list[tuple[str, str]]:
    """[(market, selection)] currently live for a fixture, from prices_dedup_state.

    prices_dedup_state is the right source: it is the deduplicated CURRENT state
    the pricing path actually reads, so it lists exactly the selections that can
    be quoted. Reading our own mapping_override instead would miss anything
    already retracted, and reading Kalshi would include markets we never mapped.
    """
    sql = f"""
        SELECT DISTINCT market_id, selection
        FROM `{client.project}.opticodds_us.prices_dedup_state`
        WHERE game_id = @fixture_id
          AND selection IS NOT NULL
        ORDER BY market_id, selection
    """  # nosec B608 - project is code-derived; fixture_id is a bound parameter
    from google.cloud import bigquery
    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("fixture_id", "STRING", fixture_id)]))
    return [(r["market_id"], r["selection"]) for r in job.result()]


def _port_forward(ns: str, svc: str, svc_port: int, local_port: int):
    """kubectl port-forward to a ClusterIP/NodePort service; caller kills it."""
    kubectl = shutil.which("kubectl") or "kubectl"
    proc = subprocess.Popen(  # nosec B603 - fixed argv, no shell
        [kubectl, "port-forward", "-n", ns, f"svc/{svc}", f"{local_port}:{svc_port}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(50):
        if proc.poll() is not None:
            # `proc.stderr` is Optional to the type checker; guard it rather than
            # assuming the pipe exists.
            raw = proc.stderr.read() if proc.stderr else b""
            raise RuntimeError(
                f"kubectl port-forward exited: {(raw or b'').decode()[:400]}")
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.2):
                return proc
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError(f"port-forward to {ns}/{svc} did not become ready")


def set_zero(base_url: str, fixture_id: str, market: str, selection: str) -> tuple[bool, str]:
    """POST a selection-level override. The SERVICE composes the key."""
    r = requests.post(
        f"{base_url}/trading-config/overrides/selections",
        json={"fixture_id": fixture_id, "market": market,
              "selection": selection, "overrides": DEAD},
        timeout=HTTP_TIMEOUT)
    return r.ok, f"{r.status_code} {r.text[:120]}"


def clear(base_url: str, fixture_id: str, market: str, selection: str) -> tuple[bool, str]:
    """DELETE the override. Key must match the service's own composition rule."""
    key = f"{fixture_id}-{market}-{selection}".replace(" ", "-")
    r = requests.delete(
        f"{base_url}/trading-config/overrides/selections/{key}", timeout=HTTP_TIMEOUT)
    return r.ok, f"{r.status_code} {r.text[:120]}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("fixture_ids", nargs="*", default=[],
                   help="fixture id(s), e.g. wsdsyn-KXITFMATCH-26SEP02VUJTAL")
    p.add_argument("--league", action="append", default=[], metavar="LEAGUE_ID",
                   help="halt EVERY live synthetic fixture in a series.toml league "
                        "(repeatable), e.g. --league atp_challenger. Resolves "
                        "to wsdsyn- fixture ids with status='live'.")
    p.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    p.add_argument("--clear", action="store_true", help="REMOVE the overrides instead of setting them")
    p.add_argument("--tenant", choices=["preoff", "inplay", "both"], default="both")
    p.add_argument("--selection", action="append", default=[],
                   help="limit to this selection (repeatable); default is every selection on the fixture")
    p.add_argument("--local-port", type=int, default=18080)
    args = p.parse_args()

    if not args.fixture_ids and not args.league:
        p.error("give at least one fixture id, or --league LEAGUE_ID")

    client = ro_client()
    verb = "CLEAR" if args.clear else "ZERO"
    tenants = list(TENANTS) if args.tenant == "both" else [args.tenant]

    fixture_ids = list(args.fixture_ids)
    if args.league:
        resolved = fixtures_for_leagues(client, args.league)
        if not resolved:
            print(f"[zero_stake] --league {args.league}: no LIVE synthetic fixtures "
                  f"right now — nothing to {verb.lower()}", file=sys.stderr)
        else:
            print(f"[zero_stake] --league {args.league} resolved to "
                  f"{len(resolved)} live synthetic fixture(s)", file=sys.stderr)
        fixture_ids.extend(f for f in resolved if f not in fixture_ids)

    # --league can only ever produce wsdsyn- ids, but an explicit argument cannot be
    # trusted the same way. A typo'd real fixture id would zero stake on a REAL
    # match, so warn loudly rather than silently accepting it.
    foreign = [f for f in fixture_ids if not f.startswith(SYNTHETIC_PREFIX)]
    if foreign:
        print(f"[zero_stake] WARNING: not synthetic fixture ids: {foreign}",
              file=sys.stderr)
        print("  This tool works on any fixture by design, but these are REAL "
              "Optic fixtures. Confirm that is what you meant.", file=sys.stderr)

    targets: list[tuple[str, str, str]] = []
    for fid in fixture_ids:
        sels = selections_for(client, fid)
        if args.selection:
            want = {s.lower() for s in args.selection}
            sels = [(m, s) for m, s in sels if s.lower() in want]
        if not sels:
            print(f"[zero_stake] {fid}: NO live selections in prices_dedup_state — "
                  f"nothing to {verb.lower()}. Check the fixture id.", file=sys.stderr)
            continue
        for market, selection in sels:
            targets.append((fid, market, selection))

    if not targets:
        print("[zero_stake] nothing to do", file=sys.stderr)
        return 1

    print(f"[zero_stake] {verb} {len(targets)} selection(s) across tenants={tenants} "
          f"(project={client.project}, apply={args.apply})", file=sys.stderr)
    for fid, market, selection in targets:
        key = f"{fid}-{market}-{selection}".replace(" ", "-")
        print(f"    {key}" + ("" if args.clear else f"  -> {DEAD}"))

    if not args.apply:
        print("[zero_stake] dry run — pass --apply to write", file=sys.stderr)
        return 0

    rc = 0
    for label in tenants:
        _, ns, svc, svc_port = TENANTS[label]
        port = args.local_port + list(TENANTS).index(label)
        pf = None
        try:
            pf = _port_forward(ns, svc, svc_port, port)
            base = f"http://127.0.0.1:{port}"
            ok_n = 0
            for fid, market, selection in targets:
                fn = clear if args.clear else set_zero
                ok, detail = fn(base, fid, market, selection)
                ok_n += ok
                if not ok:
                    rc = 1
                    print(f"  [{label}] FAILED {fid}-{market}-{selection}: {detail}", file=sys.stderr)
            print(f"  [{label}] {ok_n}/{len(targets)} ok", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - report per tenant, keep going
            rc = 1
            print(f"  [{label}] ERROR: {exc}", file=sys.stderr)
        finally:
            if pf is not None:
                pf.terminate()

    if rc:
        print("[zero_stake] SOME WRITES FAILED — a fixture killed on one tenant and "
              "live on the other is the bad state. Re-run, or narrow with --tenant.",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())

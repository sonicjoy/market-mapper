"""Pause / unpause in-play betting on synthetic (`wsdsyn-`) fixtures through the console pause plane.

Publishes one fixture-scope `market_betting_pause` message per in-play tenant, in the
wire shape the console's Fixture Pause sends (mm-trading-dash
backend/app/routers/market_pause.py `_pause_message`). Every in-play maker's
MarketPauseRegistry applies it sub-second; the topic's sink is
`trading_us.market_betting_pause`.

    # dry run: print the messages, publish nothing
    GCP_PROJECT=rs-marketmaking python -m synthetic.inplay_pause --fixture wsdsyn-KXITFMATCH-26SEP02VUJTAL

    # pause on every in-play tenant
    GCP_PROJECT=rs-marketmaking python -m synthetic.inplay_pause --fixture wsdsyn-KXITFMATCH-26SEP02VUJTAL --apply

    # unpause on one tenant only
    GCP_PROJECT=rs-marketmaking python -m synthetic.inplay_pause --fixture wsdsyn-KXITFMATCH-26SEP02VUJTAL \\
        --tenant kalshi-inplay --unpause --apply

Manual CLI only, never scheduled (tests/synthetic/test_synthetic.py forbids cron).
Publishes with the caller's Application Default Credentials, which need
pubsub.publisher on the topic. Only `wsdsyn-` fixture ids are accepted, so a real
fixture cannot be paused from here; use the console for those.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
from collections.abc import Iterable, Sequence
from typing import Any

SYNTHETIC_PREFIX = "wsdsyn-"
TOPIC = "market_betting_pause"
SOURCE = "mmmapper"

# Every tenant running the in-play regime; --tenant narrows the fan-out.
INPLAY_TENANTS: tuple[str, ...] = (
    "kalshi-inplay",
    "novig-inplay",
    "polymarket-inplay",
    "polymarketus-inplay",
    "underdog-inplay",
)

# The console's fixture-id check (market_pause._FIXTURE_ID_RE).
_FIXTURE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def pause_message(
    *,
    scope: str,
    tenant: str,
    fixture_id: str | None,
    market_id: str | None,
    selection: str | None,
    paused: bool,
    ts_ms: int,
    operator: str,
) -> dict[str, Any]:
    """The wire message, semantics only: the registry canonicalizes the key.

    Field for field the console's `_pause_message`; only `source` differs.
    """
    return {
        "scope": scope,
        "tenant": tenant,
        "fixture_id": fixture_id,
        "market_id": market_id,
        "selection": selection,
        "paused": paused,
        "ts_ms": ts_ms,
        "source": SOURCE,
        "operator": operator,
    }


def build_messages(
    fixture_ids: Iterable[str], tenants: Iterable[str], *, paused: bool, operator: str, ts_ms: int,
) -> list[dict[str, Any]]:
    """One fixture-scope message per (fixture, tenant)."""
    tenants = tuple(tenants)
    return [
        pause_message(scope="fixture", tenant=tenant, fixture_id=fixture_id, market_id=None,
                      selection=None, paused=paused, ts_ms=ts_ms, operator=operator)
        for fixture_id in fixture_ids
        for tenant in tenants
    ]


def rejected_fixture_ids(fixture_ids: Iterable[str]) -> list[str]:
    """Ids this tool refuses: not `wsdsyn-`, or not shaped like a console fixture id."""
    return [f for f in fixture_ids if not (f.startswith(SYNTHETIC_PREFIX) and _FIXTURE_ID_RE.match(f))]


def publish(project: str, messages: Sequence[dict[str, Any]], timeout_s: float = 10.0) -> list[str | Exception]:
    """Publish every message with ADC credentials; per message, its id or the exception."""
    from google.cloud import pubsub_v1

    client = pubsub_v1.PublisherClient()
    topic_path = client.topic_path(project, TOPIC)
    futures = [client.publish(topic_path, json.dumps(m).encode("utf-8")) for m in messages]
    results: list[str | Exception] = []
    for future in futures:
        try:
            results.append(str(future.result(timeout=timeout_s)))
        except Exception as exc:  # noqa: BLE001 - reported per message
            results.append(exc)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fixture", action="append", required=True, metavar="FIXTURE_ID",
                   help="synthetic (wsdsyn-) fixture id, repeatable")
    p.add_argument("--tenant", action="append", metavar="TENANT",
                   help="in-play tenant to target, repeatable (default: all of "
                        + ", ".join(INPLAY_TENANTS) + ")")
    p.add_argument("--unpause", action="store_true", help="lift the pause instead of setting it")
    p.add_argument("--operator", default=None,
                   help="recorded on the message (default: the current OS user)")
    p.add_argument("--project", default=os.environ.get("GCP_PROJECT", "marketmaking-test"),
                   help="project that owns the topic (default: $GCP_PROJECT, else marketmaking-test)")
    p.add_argument("--apply", action="store_true", help="publish (default: dry run)")
    args = p.parse_args(argv)

    # Refuse out-of-scope targets before any network call.
    bad = rejected_fixture_ids(args.fixture)
    if bad:
        print(f"[inplay_pause] REFUSING: not synthetic fixture ids: {bad}\n"
              f"  This tool only ever touches `{SYNTHETIC_PREFIX}` fixtures.", file=sys.stderr)
        return 2
    tenants = tuple(args.tenant) if args.tenant else INPLAY_TENANTS
    bad_tenants = [t for t in tenants if not t.endswith("-inplay")]
    if bad_tenants:
        print(f"[inplay_pause] REFUSING: not in-play tenants: {bad_tenants}", file=sys.stderr)
        return 2

    messages = build_messages(
        args.fixture, tenants, paused=not args.unpause,
        operator=args.operator or getpass.getuser(), ts_ms=int(time.time() * 1000))
    verb = "UNPAUSE" if args.unpause else "PAUSE"
    print(f"[inplay_pause] {verb} {len(args.fixture)} fixture(s) x {len(tenants)} tenant(s) "
          f"-> {len(messages)} message(s) on projects/{args.project}/topics/{TOPIC}", file=sys.stderr)
    for m in messages:
        print(json.dumps(m))
    if not args.apply:
        print("[inplay_pause] dry run — pass --apply to publish", file=sys.stderr)
        return 0

    results = publish(args.project, messages)
    failed = [(m, r) for m, r in zip(messages, results, strict=True) if isinstance(r, Exception)]
    for m, exc in failed:
        print(f"  FAILED {m['tenant']} {m['fixture_id']}: {exc}", file=sys.stderr)
    print(f"[inplay_pause] done: {len(messages) - len(failed)} published, {len(failed)} failed",
          file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

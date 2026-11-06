#!/usr/bin/env python
"""Verify or submit Underdog gaps from fixture-matched UDX CSV rows.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/underdog_markets.py``.

Default (no ``--submit``): read-only report for test and prod tips.

    python scripts/submit_underdog_fixture_csv.py --csv ~/Downloads/udx-....csv
    python scripts/submit_underdog_fixture_csv.py --submit --env test --league nfl
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchEntryRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.underdog_fixture_classify import build_league_payloads
from mappers.control_plane.underdog_fixture_harvest import (
    build_alias_payloads,
    build_market_rule_payloads,
    harvest_for_store,
    load_fixture_csv,
)

NOTE = (
    "2026-09-24: Underdog UDX fixture CSV harvest — league enable, product_period "
    "rules, and code aliases with optic:fixture evidence."
)

_DEFAULT_CSV = Path.home() / "Downloads" / "udx-production-markets-optic-fixtures-2026-09-24.csv"


def _project(env: str) -> str:
    return "marketmaking-test" if env == "test" else "rs-marketmaking"


def _console(env: str) -> str:
    if env == "test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def _load_store(env: str) -> BigQueryStore:
    project = _project(env)
    os.environ["GCP_PROJECT"] = project
    return BigQueryStore(
        bigquery.Client(project=project),
        environment=env,
        allow_activate=False,
    )


def verify_env(
    env: str,
    csv_rows: list[Any],
    *,
    csv_path: Path,
) -> dict[str, Any]:
    store = _load_store(env)
    report = harvest_for_store(store, csv_rows, environment=env)
    summary = report.summary()
    summary["csv"] = str(csv_path)
    summary["csv_rows"] = len(csv_rows)
    return summary


def _submit_batch(
    svc: ProposalService,
    body: BatchEntryRequest,
    actor: Actor,
) -> dict[str, Any]:
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"verify blocked: {verified.get('blockers')}")
    return svc.entry_batch_submit(str(verified["preview_token"]), actor)


def submit_env(
    env: str,
    csv_rows: list[Any],
    *,
    leagues: tuple[str, ...] | None,
) -> dict[str, Any]:
    store = _load_store(env)
    report = harvest_for_store(store, csv_rows, environment=env)
    league_filter = list(leagues) if leagues else None

    league_payloads = build_league_payloads(store, report, leagues=league_filter)
    rule_payload = build_market_rule_payloads(report, leagues=league_filter)
    alias_payloads = build_alias_payloads(report, leagues=league_filter)

    if not league_payloads and not rule_payload.market_rules and not alias_payloads:
        return {
            "env": env,
            "rule_set_id": report.rule_set_id,
            "message": "no Underdog fixture gaps to propose",
            "summary": report.summary(),
        }

    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_underdog_fixture_csv", role=ActorRole.PROPOSER)
    cards: list[dict[str, Any]] = []

    if league_payloads:
        body = BatchEntryRequest(
            leagues=league_payloads,
            acknowledge_shadow=True,
            note=NOTE,
        )
        cards.append({"kind": "mapping_league", "result": _submit_batch(svc, body, actor)})

    if rule_payload.market_rules:
        body = BatchEntryRequest(
            market_rules=rule_payload.market_rules,
            acknowledge_shadow=True,
            note=NOTE,
        )
        cards.append({"kind": "market_rules", "result": _submit_batch(svc, body, actor)})

    if alias_payloads:
        body = BatchEntryRequest(
            entity_aliases=alias_payloads,
            acknowledge_shadow=True,
            note=NOTE,
        )
        cards.append({"kind": "entity_alias", "result": _submit_batch(svc, body, actor)})

    refs = [
        str(card.get("result", {}).get("ref") or card.get("result", {}).get("proposal_id") or "")
        for card in cards
    ]
    return {
        "env": env,
        "rule_set_id": report.rule_set_id,
        "leagues": list(leagues) if leagues else "all",
        "aliases": len(alias_payloads),
        "market_rule_groups": len(rule_payload.market_rules or []),
        "mapping_leagues": len(league_payloads),
        "cards": cards,
        "review_urls": [
            f"{_console(env)}/review/{ref}" for ref in refs if ref
        ],
        "summary": report.summary(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=_DEFAULT_CSV)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="both")
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        help="Limit submit to one or more tip league slugs (repeatable).",
    )
    args = parser.parse_args(argv)

    csv_rows = load_fixture_csv(args.csv)
    if not csv_rows:
        print(json.dumps({"error": f"no fixture-matched rows in {args.csv}"}, indent=2))
        return 1

    envs = ["test", "prod"] if args.env == "both" else [args.env]
    league_tuple = tuple(args.leagues) if args.leagues else None

    if not args.submit:
        out = [verify_env(e, csv_rows, csv_path=args.csv) for e in envs]
        print(json.dumps(out, indent=2, default=str))
        return 0

    results = [
        submit_env(e, csv_rows, leagues=league_tuple)
        for e in envs
    ]
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

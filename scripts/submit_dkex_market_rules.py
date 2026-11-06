#!/usr/bin/env python
"""Propose DKEX market_period rules from the Python crosswalk.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/dkex_markets.py``.

    python scripts/submit_dkex_market_rules.py
    python scripts/submit_dkex_market_rules.py --submit --env prod
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.gap_fix_dkex_leagues import ENABLED_LEAGUE_SLUGS
from mappers.control_plane.models import Actor, ActorRole, BatchEntryRequest
from mappers.control_plane.service import ProposalService
from mappers.seed.dkex_market_rules import build_dkex_game_line_payload

NOTE = "DKEX market_period pins from mappers/vocab/dkex_markets.py."


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payload = build_dkex_game_line_payload(
        store.market_rules_for(current),
        leagues=ENABLED_LEAGUE_SLUGS,
    )
    pin_count = sum(len(g.rules) for g in payload.market_rules)
    if pin_count == 0:
        return {
            "project": project,
            "skipped": "no missing DKEX market rules",
            "rule_set_id": current,
            "dkex_pins": 0,
        }
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_dkex_market_rules", role=ActorRole.PROPOSER)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(
            market_rules=list(payload.market_rules),
            acknowledge_shadow=True,
            note=NOTE,
        ),
    )
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "dkex_pins": pin_count,
        "ref": ref,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="test")
    args = parser.parse_args(argv)

    if not args.submit:
        print(json.dumps({"note": NOTE, "leagues": list(ENABLED_LEAGUE_SLUGS)}, indent=2))
        print("pass --submit --env test to propose", file=sys.stderr)
        return 0

    projects: list[str] = []
    if args.env in ("test", "both"):
        projects.append("marketmaking-test")
    if args.env in ("prod", "both"):
        projects.append("rs-marketmaking")
    results = [submit_env(project) for project in projects]
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

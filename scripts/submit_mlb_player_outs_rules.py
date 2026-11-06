#!/usr/bin/env python
"""Submit MLB player_outs market-rule pins missing from the live BQ tip.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_markets.py``.

    GCP_PROJECT=marketmaking-test python scripts/submit_mlb_player_outs_rules.py
    python scripts/submit_mlb_player_outs_rules.py --submit --env test
    python scripts/submit_mlb_player_outs_rules.py --submit --env both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchChangesPayload,
    BatchEntryRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.seed.mlb_player_outs_rules import build_mlb_player_outs_payload

NOTE = (
    "MLB player props: Optic + Kalshi pins for player_outs, player_rbis, "
    "and player_stolen_bases; crypto.com Total RBIs from optic_spine."
)


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


def _submit_payload(
    svc: ProposalService,
    payload: BatchChangesPayload,
    actor: Actor,
) -> dict[str, Any]:
    body = BatchEntryRequest(
        entity_aliases=payload.entity_aliases,
        market_rules=payload.market_rules,
        acknowledge_shadow=True,
        note=NOTE,
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"verify blocked: {verified.get('blockers')}")
    return svc.entry_batch_submit(str(verified["preview_token"]), actor)


def preview_env(env: str) -> dict[str, Any]:
    store = _load_store(env)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{env}: no current rule set")
    payload = build_mlb_player_outs_payload(store.market_rules_for(current))
    pin_count = sum(len(group.rules) for group in payload.market_rules)
    return {
        "env": env,
        "rule_set_id": current,
        "player_outs_pins": pin_count,
        "payload": payload.model_dump(),
    }


def submit_env(env: str) -> dict[str, Any]:
    store = _load_store(env)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{env}: no current rule set")
    payload = build_mlb_player_outs_payload(store.market_rules_for(current))
    pin_count = sum(len(group.rules) for group in payload.market_rules)
    if pin_count == 0:
        return {
            "env": env,
            "rule_set_id": current,
            "player_outs_pins": 0,
            "message": "tip already has all MLB player_outs pins",
        }
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(
        subject="scripts/submit_mlb_player_outs_rules",
        role=ActorRole.PROPOSER,
    )
    card = _submit_payload(svc, payload, actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "env": env,
        "rule_set_id": current,
        "player_outs_pins": pin_count,
        "ref": ref,
        "review_url": f"{_console(env)}/review/{ref}" if ref else None,
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="open a Review card")
    parser.add_argument(
        "--env",
        choices=("test", "prod", "both"),
        default="test",
        help="target environment (default: test)",
    )
    parser.add_argument("--out", help="write preview JSON")
    args = parser.parse_args(argv)

    envs = ("test", "prod") if args.env == "both" else (args.env,)
    results: list[dict[str, Any]] = []
    for env in envs:
        result = submit_env(env) if args.submit else preview_env(env)
        results.append(result)
        pin_count = result.get("player_outs_pins", 0)
        print(f"{env}: {pin_count} player_outs pins")
        if result.get("review_url"):
            print(f"  {result['review_url']}")
        if result.get("message"):
            print(f"  {result['message']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

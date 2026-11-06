#!/usr/bin/env python
"""Submit Underdog UDX market-rule pins missing from the live BQ tip.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/underdog_markets.py``.

    python scripts/submit_underdog_market_rules.py
    python scripts/submit_underdog_market_rules.py --submit --env prod
"""

from __future__ import annotations

import argparse
import json
import os
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
from mappers.control_plane.gap_fix_underdog_leagues import ENABLED_LEAGUE_SLUGS
from mappers.seed.underdog_market_rules import (
    build_underdog_game_line_payload,
    missing_market_rule_pins,
)

NOTE = (
    "Underdog UDX game-line taxonomy: product_period keys from "
    "mappers/vocab/underdog_markets.py (nfl/mlb/wnba/ncaaf)."
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
    tip_rules = store.market_rules_for(current)
    by_league = {
        league: len(missing_market_rule_pins(league, tip_rules))
        for league in ENABLED_LEAGUE_SLUGS
    }
    missing = sum(by_league.values())
    out: dict[str, Any] = {
        "env": env,
        "rule_set_id": current,
        "missing_pins": missing,
        "by_league_missing": by_league,
    }
    if missing == 0:
        out["message"] = "tip already has all Underdog game-line pins"
    return out


def submit_env(env: str) -> dict[str, Any]:
    store = _load_store(env)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{env}: no current rule set")
    payload = build_underdog_game_line_payload(store.market_rules_for(current))
    pin_count = sum(len(group.rules) for group in payload.market_rules)
    if pin_count == 0:
        return {
            "env": env,
            "rule_set_id": current,
            "underdog_pins": 0,
            "message": "tip already has all Underdog game-line pins",
        }
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_underdog_market_rules", role=ActorRole.PROPOSER)
    card = _submit_payload(svc, payload, actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "env": env,
        "rule_set_id": current,
        "underdog_pins": pin_count,
        "by_league": {g.league: len(g.rules) for g in payload.market_rules},
        "ref": ref,
        "review_url": f"{_console(env)}/review/{ref}" if ref else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="prod")
    args = parser.parse_args(argv)

    envs = ["test", "prod"] if args.env == "both" else [args.env]
    if not args.submit:
        print(json.dumps([preview_env(e) for e in envs], indent=2, default=str))
        return 0

    results = [submit_env(e) for e in envs]
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Copy Kalshi team codes onto first-class polymarket_usa entity aliases.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

League pins must already exist (see ``scripts/submit_poly_us_cards.py``). This
card writes ``mapping_entities`` only: Polymarket US market types come from
its own enum table (``mappers.vocab.poly_usa_smt``), never from Polymarket.

    GCP_PROJECT=marketmaking-test python scripts/submit_poly_us_taxonomy.py
    python scripts/submit_poly_us_taxonomy.py --submit --env test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchChangesPayload,
    BatchEntryRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.seed.poly_usa_taxonomy import build_usa_taxonomy_payload

NOTE = (
    "Poly US: copy Kalshi team codes onto polymarket_usa entity aliases."
)
_EVIDENCE = [
    "docs/polymarket-mapping-gaps.md",
    "scripts/submit_poly_us_taxonomy.py",
    "mappers/seed/poly_usa_taxonomy.py",
]


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


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


def submit_env(project: str) -> dict[str, Any]:
    from google.cloud import bigquery

    from mappers.control_plane.bq_store import BigQueryStore

    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payload = build_usa_taxonomy_payload(
        store.leagues_for(current),
        store.entities_for(current),
        store.market_rules_for(current),
    )
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_poly_us_taxonomy", role=ActorRole.PROPOSER)
    card = _submit_payload(svc, payload, actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "market_rule_leagues": len(payload.market_rules),
        "market_rule_pins": sum(len(g.rules) for g in payload.market_rules),
        "entity_alias_count": len(payload.entity_aliases),
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "evidence_refs": list(_EVIDENCE),
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="write preview JSON for the default GCP_PROJECT")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="create Review cards (propose + validate) in BigQuery",
    )
    parser.add_argument(
        "--env",
        choices=("test", "prod", "both"),
        default="both",
        help="target environment(s) for --submit (default: both)",
    )
    args = parser.parse_args(argv)

    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        results = []
        for project in projects:
            print(f"submitting {project}...", file=sys.stderr)
            results.append(submit_env(project))
        print(json.dumps(results, indent=2, default=str))
        return 0

    project = (os.environ.get("GCP_PROJECT") or "marketmaking-test").strip()
    from google.cloud import bigquery

    from mappers.control_plane.bq_store import BigQueryStore

    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError("no current rule set")
    payload = build_usa_taxonomy_payload(
        store.leagues_for(current),
        store.entities_for(current),
        store.market_rules_for(current),
    )
    preview = {
        "rule_set_id": current,
        "market_rule_leagues": len(payload.market_rules),
        "market_rule_pins": sum(len(g.rules) for g in payload.market_rules),
        "entity_alias_count": len(payload.entity_aliases),
        "payload": payload.model_dump(mode="json"),
    }
    text = json.dumps(preview, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    print(
        f"\n{preview['market_rule_pins']} US kind pins, "
        f"{preview['entity_alias_count']} US alias entities for {project}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

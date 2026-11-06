#!/usr/bin/env python
"""Propose combat match-side entity_type retag (team -> fighter) via control plane.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

    python scripts/propose_combat_entity_type_retag.py --env test
    python scripts/propose_combat_entity_type_retag.py --env test --submit
    python scripts/propose_combat_entity_type_retag.py --env test --submit --activate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.artifact_apply import dry_run_proposal
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.combat_entity_retag import COMBAT_LEAGUES, apply_combat_entity_retag
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    CombatEntityRetagPayload,
    ProposalRecord,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import new_id

NOTE = "Retag combat match-side entities from team to fighter in one activation."


def _project(env: str) -> str:
    return "marketmaking-test" if env == "test" else "rs-marketmaking"


def _console(env: str) -> str:
    if env == "test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def load_tip(env: str, *, allow_activate: bool) -> BigQueryStore:
    project = _project(env)
    os.environ["GCP_PROJECT"] = project
    return BigQueryStore(
        bigquery.Client(project=project),
        environment=env if env in {"test", "prod"} else "prod",
        allow_activate=allow_activate,
    )


def preview(store: BigQueryStore) -> dict[str, Any]:
    current = store.current_rule_set_id
    if not current:
        raise RuntimeError("no activated tip")
    parent = store.entities_for(current)
    parent_lg = store.leagues_for(current)
    child, child_lg = apply_combat_entity_retag(parent, parent_lg)
    payload = CombatEntityRetagPayload(
        leagues=sorted(COMBAT_LEAGUES),
        evidence_refs=[NOTE],
    )
    proposal = ProposalRecord(
        proposal_id="preview",
        request_id="preview",
        status="proposed",
        expected_rule_set_id=current,
        artifact_type="combat_entity_retag",
        summary="Combat entity_type retag preview",
        evidence_refs=[NOTE],
        work_item_id=None,
        payload=payload,
        proposer_subject="preview",
    )
    dry = dry_run_proposal(store, current, proposal)
    team_left = sum(
        1
        for ent in child
        if ent.league in COMBAT_LEAGUES and ent.entity_type == "team" and not ent.tombstone
    )
    return {
        "tip": current,
        "dry_run": dry,
        "combat_team_rows_after": team_left,
        "entity_count_before": len(parent),
        "entity_count_after": len(child),
    }


def submit_env(env: str, *, activate: bool, summary: str) -> dict[str, Any]:
    store = load_tip(env, allow_activate=activate)
    current = store.current_rule_set_id
    if not current:
        raise RuntimeError(f"no activated tip in {env}")
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/propose_combat_entity_type_retag", role=ActorRole.ADMIN)
    payload = CombatEntityRetagPayload(
        leagues=sorted(COMBAT_LEAGUES),
        evidence_refs=[NOTE],
    )
    req = ProposeRequest(
        request_id=new_id("req"),
        expected_rule_set_id=current,
        artifact_type="combat_entity_retag",
        summary=summary,
        evidence_refs=[NOTE],
        payload=payload,
    )
    prop = svc.propose(req, actor)
    validated = svc.validate(prop.proposal_id, actor)
    status = validated.status
    activated = None
    if activate:
        approved = svc.approve(prop.proposal_id, actor)
        status = approved.status
        activated = approved.activated_rule_set_id
    return {
        "env": env,
        "ref": prop.proposal_id,
        "status": status,
        "activated_rule_set_id": activated,
        "review_url": f"{_console(env)}/review/{prop.proposal_id}",
        "dry_run": validated.dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--i-mean-it", action="store_true")
    args = parser.parse_args(argv)
    if args.activate and not args.submit:
        parser.error("--activate requires --submit")
    if args.env == "prod" and args.activate and not args.i_mean_it:
        parser.error("prod --activate requires --i-mean-it")
    store = load_tip(args.env, allow_activate=args.activate)
    result: dict[str, Any] = {"env": args.env, "preview": preview(store)}
    if args.submit:
        result["submit"] = submit_env(
            args.env,
            activate=args.activate,
            summary="Retag UFC/boxing match-side entities team -> fighter",
        )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

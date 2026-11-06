#!/usr/bin/env python
"""Propose alias removals via the control plane (AliasPin.remove=True).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

    python scripts/propose_alias_removals.py --env test
    python scripts/propose_alias_removals.py --env test --submit
    python scripts/propose_alias_removals.py --env test --submit --activate
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
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import new_id

NOTE = "Remove stray alias pins from the activated tip."


def _project(env: str) -> str:
    return "marketmaking-test" if env == "test" else "rs-marketmaking"


def _console(env: str) -> str:
    if env == "test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def load_tip(env: str, *, allow_activate: bool) -> BigQueryStore:
    """BigQueryStore bound to test or prod."""
    project = _project(env)
    os.environ["GCP_PROJECT"] = project
    return BigQueryStore(
        bigquery.Client(project=project),
        environment=env if env in {"test", "prod"} else "prod",
        allow_activate=allow_activate,
    )


def removal_payload(
    *,
    league: str,
    canonical_key: str,
    canonical_name: str,
    entity_type: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    evidence_refs: list[str] | None = None,
) -> EntityAliasPayload:
    """One entity_alias row that drops a live alias triple."""
    return EntityAliasPayload(
        league=league,
        canonical_key=canonical_key,
        canonical_name=canonical_name,
        entity_type=entity_type,  # type: ignore[arg-type]
        aliases=[
            AliasPin(
                sportsbook=sportsbook,
                alias_kind=alias_kind,
                alias_value=alias_value,
                remove=True,
            )
        ],
        evidence_refs=list(evidence_refs or [NOTE]),
    )


def submit_env(
    env: str,
    payloads: list[EntityAliasPayload],
    *,
    activate: bool,
    summary: str,
) -> dict[str, Any]:
    """Propose + validate; optionally approve (activates when allow_activate)."""
    store = load_tip(env, allow_activate=activate)
    current = store.current_rule_set_id
    if not current:
        raise RuntimeError(f"no activated tip in {env}")
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/propose_alias_removals", role=ActorRole.ADMIN)
    payload = BatchChangesPayload(entity_aliases=payloads)
    req = ProposeRequest(
        request_id=new_id("req"),
        expected_rule_set_id=current,
        artifact_type="batch_changes",
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
    ref = prop.proposal_id
    return {
        "env": env,
        "ref": ref,
        "status": status,
        "activated_rule_set_id": activated,
        "review_url": f"{_console(env)}/review/{ref}",
        "alias_count": sum(len(p.aliases) for p in payloads),
        "entity_count": len(payloads),
    }


def trevor_sva_removals() -> list[EntityAliasPayload]:
    """Stray SVA pins on Trevor Svajda (Zachary owns kalshi SVA on ATP main)."""
    note = "note:SVA belongs to Zachary Svajda (SVA); remove duplicate from Trevor Svajda."
    return [
        removal_payload(
            league="atp",
            canonical_key="SVA2",
            canonical_name="Trevor Svajda",
            entity_type="team",
            sportsbook="kalshi",
            alias_kind="code",
            alias_value="SVA",
            evidence_refs=[note],
        ),
        removal_payload(
            league="atp_challenger",
            canonical_key="TSR2",
            canonical_name="Trevor Svajda",
            entity_type="team",
            sportsbook="kalshi",
            alias_kind="code",
            alias_value="SVA",
            evidence_refs=[note],
        ),
        removal_payload(
            league="atp_challenger",
            canonical_key="TSR2",
            canonical_name="Trevor Svajda",
            entity_type="team",
            sportsbook="polymarket_usa",
            alias_kind="code",
            alias_value="SVA",
            evidence_refs=[note],
        ),
    ]


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
    payloads = trevor_sva_removals()
    result: dict[str, Any] = {
        "env": args.env,
        "removals": [
            {
                "league": p.league,
                "canonical_key": p.canonical_key,
                "alias": f"{p.aliases[0].sportsbook} {p.aliases[0].alias_value}",
            }
            for p in payloads
        ],
    }
    if args.submit:
        result["submit"] = submit_env(
            args.env,
            payloads,
            activate=args.activate,
            summary=f"Remove {len(payloads)} stray Trevor Svajda SVA alias pins",
        )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Inventory and strip Polymarket handicap name crumbs from the tip.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

    python scripts/strip_handicap_name_crumbs.py
    python scripts/strip_handicap_name_crumbs.py --env test --submit --activate
    python scripts/strip_handicap_name_crumbs.py --env prod --submit --activate --i-mean-it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Literal

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
from mappers.control_plane.rows import EntityRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import new_id
from mappers.handicap_name_crumb import is_selection_alias

NOTE = (
    "Deactivate Polymarket name overlays that are handicap/spread crumbs "
    "(Name (±1.5)), not teams or players."
)
EntityType = Literal["team", "player", "fighter"]


def _project(env: str) -> str:
    return "marketmaking-test" if env == "test" else "rs-marketmaking"


def _console(env: str) -> str:
    if env == "test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def _entity_type(raw: str) -> EntityType:
    if raw == "player":
        return "player"
    if raw == "fighter":
        return "fighter"
    return "team"


def crumb_pins(ent: EntityRow) -> list[AliasPin]:
    """Polymarket name overlays that look like handicap lines."""
    out: list[AliasPin] = []
    for alias in ent.aliases:
        if str(alias.get("sportsbook") or "").lower() != "polymarket":
            continue
        if str(alias.get("alias_kind") or "") != "name":
            continue
        if alias.get("enabled") is False:
            continue
        value = str(alias.get("alias_value") or "")
        if not is_selection_alias(value):
            continue
        out.append(
            AliasPin(
                sportsbook="polymarket",
                alias_kind="name",
                alias_value=value,
                remove=True,
            )
        )
    return out


def payloads_for(entities: list[EntityRow]) -> list[EntityAliasPayload]:
    """One remove payload per entity that still has a crumb."""
    out: list[EntityAliasPayload] = []
    for ent in entities:
        pins = crumb_pins(ent)
        if not pins:
            continue
        out.append(
            EntityAliasPayload(
                league=ent.league,
                canonical_key=ent.canonical_key,
                entity_type=_entity_type(ent.entity_type),
                canonical_name=ent.canonical_name,
                aliases=pins,
                evidence_refs=[NOTE],
            )
        )
    return out


def inventory_rows(payloads: list[EntityAliasPayload]) -> list[dict[str, Any]]:
    """Flatten remove pins for a dry-run print."""
    rows: list[dict[str, Any]] = []
    for ea in payloads:
        for pin in ea.aliases:
            rows.append(
                {
                    "league": ea.league,
                    "canonical_key": ea.canonical_key,
                    "canonical_name": ea.canonical_name,
                    "alias_value": pin.alias_value,
                }
            )
    return rows


def load_tip(env: str, *, allow_activate: bool) -> Any:
    """BigQueryStore bound to test or prod."""
    project = _project(env)
    os.environ["GCP_PROJECT"] = project
    return BigQueryStore(
        bigquery.Client(project=project),
        environment=env if env in {"test", "prod"} else "prod",
        allow_activate=allow_activate,
    )


def submit_env(
    env: str,
    payloads: list[EntityAliasPayload],
    *,
    activate: bool,
) -> dict[str, Any]:
    """Propose + validate; optionally approve (activates when allow_activate)."""
    store = load_tip(env, allow_activate=activate)
    current = store.current_rule_set_id
    if not current:
        raise RuntimeError(f"no activated tip in {env}")
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/strip_handicap_name_crumbs", role=ActorRole.ADMIN)
    payload = BatchChangesPayload(entity_aliases=payloads)
    req = ProposeRequest(
        request_id=new_id("req"),
        expected_rule_set_id=current,
        artifact_type="batch_changes",
        summary=f"Strip {len(payloads)} Polymarket handicap name crumbs",
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


def run_env(env: str, *, submit: bool, activate: bool) -> dict[str, Any]:
    """Inventory one environment; optionally write a control-plane proposal."""
    store = load_tip(env, allow_activate=False)
    current = store.current_rule_set_id
    if not current:
        raise RuntimeError(f"no activated tip in {env}")
    payloads = payloads_for(store.entities_for(current))
    result: dict[str, Any] = {
        "env": env,
        "rule_set_id": current,
        "crumbs": inventory_rows(payloads),
        "entity_count": len(payloads),
        "alias_count": sum(len(p.aliases) for p in payloads),
    }
    if submit and payloads:
        result["submit"] = submit_env(env, payloads, activate=activate)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("test", "prod", "both"), default="both")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--i-mean-it", action="store_true")
    args = parser.parse_args(argv)
    if args.activate and not args.submit:
        parser.error("--activate requires --submit")
    if args.env == "prod" and args.activate and not args.i_mean_it:
        parser.error("prod --activate requires --i-mean-it")
    targets = ["test", "prod"] if args.env == "both" else [args.env]
    out = [run_env(env, submit=args.submit, activate=args.activate) for env in targets]
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

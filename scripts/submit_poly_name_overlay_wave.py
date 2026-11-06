#!/usr/bin/env python
"""Harvest unique official Polymarket name overlays and submit a Review card.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

Path 2 already on: live matcher misses when question names do not contain
Optic display names. Drafts ``(polymarket, name)`` only when both sides
uniquely bind by significant last-token. Does not Approve.

    python scripts/submit_poly_name_overlay_wave.py
    python scripts/submit_poly_name_overlay_wave.py --submit --env test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.gap_fix_poly import harvest_poly_side, load_poly_side_inputs
from mappers.control_plane.gap_fix_poly_bq import fetch_poly_official_events
from mappers.control_plane.models import Actor, ActorRole, BatchEntryRequest
from mappers.control_plane.pin_flow import alias_from_pin as _alias_from_pin
from mappers.control_plane.service import ProposalService

NOTE = (
    "2026-08-29 official Path 2 name overlay: unique last-token binds for "
    "live matcher-miss question names (uru1/lal/ere/fl1/cfb). Pin "
    "polymarket/name onto existing Optic entities; do not invent keys."
)

PREFIXES = ("uru1", "lal", "ere", "fl1", "cfb")


def _official_events() -> list[dict[str, Any]]:
    """Official-bridge RFQ gaps for the name-overlay prefixes."""
    return fetch_poly_official_events(list(PREFIXES))


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def harvest_env(project: str) -> dict[str, Any]:
    """Draft unique name-overlay pins against this project's tip + RFQ."""
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    us_events, official, optic_rows = load_poly_side_inputs(
        list(PREFIXES),
        list,
        _official_events,
        None,
    )
    pins, skipped = harvest_poly_side(
        store, list(PREFIXES), us_events, optic_rows, official_events=official,
    )
    names = [p for p in pins if p.get("kind") == "entity_alias"]
    leagues = [p for p in pins if p.get("kind") == "mapping_league"]
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": store.current_rule_set_id,
        "name_pins": names,
        "league_pins": leagues,
        "skipped": skipped,
        "store": store,
    }


def submit_env(project: str) -> dict[str, Any]:
    harvested = harvest_env(project)
    names = list(harvested["name_pins"])
    if not names:
        return {
            "project": project,
            "environment": harvested["environment"],
            "rule_set_id": harvested["rule_set_id"],
            "alias_count": 0,
            "ref": None,
            "review_url": None,
            "skipped": harvested["skipped"],
        }
    store = harvested["store"]
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_poly_name_overlay_wave", role=ActorRole.PROPOSER)
    refs: list[str] = []
    for pin in names:
        refs.extend(str(r) for r in (pin.get("evidence_refs") or []) if r)
    body = BatchEntryRequest(
        entity_aliases=[_alias_from_pin(pin) for pin in names],
        acknowledge_shadow=True,
        note=NOTE + " " + " ".join(dict.fromkeys(refs)),
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": harvested["environment"],
        "rule_set_id": harvested["rule_set_id"],
        "alias_count": len(names),
        "keys": [str(p.get("canonical_key") or "") for p in names],
        "leagues": sorted({str(p.get("league") or "") for p in names}),
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "card": card,
    }


def _dump_pins(harvested: dict[str, Any]) -> dict[str, Any]:
    names = harvested["name_pins"]
    return {
        "project": harvested["project"],
        "environment": harvested["environment"],
        "rule_set_id": harvested["rule_set_id"],
        "alias_count": len(names),
        "pins": [
            {
                "league": p.get("league"),
                "canonical_key": p.get("canonical_key"),
                "canonical_name": p.get("canonical_name"),
                "alias": (p.get("aliases") or [{}])[0].get("alias_value"),
                "evidence_refs": p.get("evidence_refs"),
            }
            for p in names
        ],
        "league_pin_count": len(harvested["league_pins"]),
        "skipped": harvested["skipped"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--env",
        choices=("test", "prod", "both"),
        default="test",
        help="target environment(s) (default: test)",
    )
    args = parser.parse_args(argv)
    projects: list[str] = []
    if args.env in ("test", "both"):
        projects.append("marketmaking-test")
    if args.env in ("prod", "both"):
        projects.append("rs-marketmaking")
    if args.submit:
        results = [submit_env(project) for project in projects]
        print(json.dumps(results, indent=2, default=str))
        return 0
    dumped = [_dump_pins(harvest_env(project)) for project in projects]
    print(json.dumps(dumped, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

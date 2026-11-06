#!/usr/bin/env python
"""Clear wrong Polymarket US inners (propose + validate; human Approve).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

Turns off polymarket_usa on leagues that do not own that inner:
norway_3_division (setkameua). ATP Challenger sharing inner `atp` is
intentional — see SHARED_US_INNERS.

    python scripts/submit_clear_wrong_usa_inners.py --submit --env both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.gap_fix_poly_leagues import disable_us_pin
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchEntryRequest,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow
from mappers.seed.poly_usa_exchange import us_league_code

NOTE = (
    "2026-08-31: clear wrong polymarket_usa inners. setkameua is SETKA "
    "(no Optic book), not Norway 3rd."
)
CLEAR_LEAGUES = ("norway_3_division",)


def _payloads(rows: list[LeagueRow]) -> list[MappingLeaguePayload]:
    by_slug = {str(row.league): row for row in rows if not row.tombstone}
    out: list[MappingLeaguePayload] = []
    for slug in CLEAR_LEAGUES:
        row = by_slug.get(slug)
        if row is None or not us_league_code(row):
            continue
        out.append(MappingLeaguePayload.model_validate(disable_us_pin(row)))
    return out


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    leagues = _payloads(store.leagues_for(current))
    if not leagues:
        return {"project": project, "skipped": "already clear", "rule_set_id": current}
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_clear_wrong_usa_inners", role=ActorRole.PROPOSER)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(leagues=leagues, acknowledge_shadow=True, note=NOTE),
    )
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    host = (
        "https://mapping.mm-test.whiteswandata.com"
        if environment == "test"
        else "https://mapping.mm.whiteswandata.com"
    )
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "leagues": [lg.league for lg in leagues],
        "ref": ref,
        "review_url": f"{host}/review/{ref}" if ref else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="both")
    args = parser.parse_args(argv)
    if not args.submit:
        print("pass --submit --env both", file=sys.stderr)
        return 2
    projects: list[str] = []
    if args.env in ("test", "both"):
        projects.append("marketmaking-test")
    if args.env in ("prod", "both"):
        projects.append("rs-marketmaking")
    results = [submit_env(project) for project in projects]
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

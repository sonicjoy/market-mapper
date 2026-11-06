#!/usr/bin/env python
"""Enable Huddle on NFL (propose + validate; human Approve).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

    python scripts/submit_enable_nfl_huddle.py --submit --env test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.gap_fix_huddle_leagues import (
    enable_huddle_pin,
    huddle_competition_id,
)
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchEntryRequest,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow
from mappers.vocab.football_huddle import NFL_COMPETITION_ID

NOTE = (
    "2026-09-21: enable Huddle on nfl with competition_id "
    f"{NFL_COMPETITION_ID} (huddle_nfl_v1, merge-only onto Optic)."
)
LEAGUE = "nfl"


def _payload(rows: list[LeagueRow]) -> MappingLeaguePayload | None:
    by_slug = {str(row.league): row for row in rows if not row.tombstone}
    row = by_slug.get(LEAGUE)
    if row is None:
        return None
    if huddle_competition_id(row) == NFL_COMPETITION_ID:
        return None
    pin = MappingLeaguePayload.model_validate(enable_huddle_pin(row))
    pin.notes = NOTE
    pin.evidence_refs = list(dict.fromkeys([*pin.evidence_refs, f"gap:huddle:nfl:{NFL_COMPETITION_ID}"]))
    return pin


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    league = _payload(store.leagues_for(current))
    if league is None:
        return {"project": project, "skipped": "already enabled", "rule_set_id": current}
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_enable_nfl_huddle", role=ActorRole.PROPOSER)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(leagues=[league], acknowledge_shadow=True, note=NOTE),
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
        "league": league.league,
        "ref": ref,
        "review_url": f"{host}/review/{ref}" if ref else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="test")
    args = parser.parse_args(argv)
    if not args.submit:
        print("pass --submit --env test", file=sys.stderr)
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

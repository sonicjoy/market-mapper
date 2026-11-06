#!/usr/bin/env python
"""Enable Underdog UDX on nfl, mlb, wnba, and ncaaf (propose; human Approve).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/underdog_markets.py``.

    python scripts/submit_enable_underdog_leagues.py
    python scripts/submit_enable_underdog_leagues.py --submit --env test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.gap_fix_underdog_leagues import (
    ENABLED_LEAGUE_SLUGS,
    enable_underdog_pin,
    underdog_venue_token,
    venue_token_for_slug,
)
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchEntryRequest,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow

NOTE = (
    "2026-09-24: enable Underdog UDX on game-line leagues "
    "(underdog_generic_v1, venue league NFL/MLB/WNBA/NCAAMFB)."
)


def _payloads(rows: list[LeagueRow]) -> list[MappingLeaguePayload]:
    by_slug = {str(row.league): row for row in rows if not row.tombstone}
    out: list[MappingLeaguePayload] = []
    for slug in ENABLED_LEAGUE_SLUGS:
        row = by_slug.get(slug)
        if row is None:
            continue
        want = venue_token_for_slug(slug, str(row.optic_league_id))
        if not want:
            continue
        have = underdog_venue_token(row)
        if have == want:
            continue
        pin = MappingLeaguePayload.model_validate(enable_underdog_pin(row, want))
        pin.notes = NOTE
        pin.evidence_refs = list(dict.fromkeys([*pin.evidence_refs, f"gap:underdog:{slug}:{want}"]))
        out.append(pin)
    return out


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


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
        return {
            "project": project,
            "skipped": "all target leagues already have Underdog pins",
            "rule_set_id": current,
        }
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_enable_underdog_leagues", role=ActorRole.PROPOSER)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(leagues=leagues, acknowledge_shadow=True, note=NOTE),
    )
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "leagues": [row.league for row in leagues],
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
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
    raise SystemExit(main())

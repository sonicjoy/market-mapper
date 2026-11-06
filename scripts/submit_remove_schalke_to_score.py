#!/usr/bin/env python
"""Remove leftover Polymarket ``to score first`` name on Schalke.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

Harvest already skips selection aliases. This pin is a leftover on S04.

    python scripts/submit_remove_schalke_to_score.py
    python scripts/submit_remove_schalke_to_score.py --submit --env both
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
    BatchEntryRequest,
    EntityAliasPayload,
)
from mappers.control_plane.pin_flow import draft_and_verify_remove
from mappers.control_plane.service import ProposalService

NOTE = (
    "2026-09-04: drop polymarket name 'FC Schalke 04 to score first' on S04. "
    "Selection aliases are not team names (same gate as Cart / harvest)."
)
LEAGUE = "germany_bundesliga"
KEY = "S04"
NAME = "FC Schalke 04"
ALIAS = "FC Schalke 04 to score first"
_EVIDENCE = [
    "poly:name:S04:FC Schalke 04 to score first",
    "reason:selection_alias",
    "note:do not pin to-score market labels as team names",
]


def removal() -> EntityAliasPayload:
    """One delete pin for the leftover Schalke selection alias."""
    return EntityAliasPayload(
        league=LEAGUE,
        canonical_key=KEY,
        entity_type="team",
        canonical_name=NAME,
        aliases=[
            AliasPin(
                sportsbook="polymarket",
                alias_kind="name",
                alias_value=ALIAS,
                remove=True,
            )
        ],
        evidence_refs=_EVIDENCE,
    )


def _pin() -> dict[str, Any]:
    row = removal()
    return row.model_dump(mode="json")


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    staged = draft_and_verify_remove(store, _pin())
    if not staged.get("ok"):
        return {
            "project": project,
            "ok": False,
            "error": staged.get("error") or staged.get("blockers"),
        }
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_remove_schalke_to_score", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        entity_aliases=[removal()],
        acknowledge_shadow=True,
        note=NOTE,
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "ok": True,
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="both")
    args = parser.parse_args(argv)
    if not args.submit:
        print(json.dumps(removal().model_dump(mode="json"), indent=2))
        return 0
    projects: list[str] = []
    if args.env in ("test", "both"):
        projects.append("marketmaking-test")
    if args.env in ("prod", "both"):
        projects.append("rs-marketmaking")
    print(json.dumps([submit_env(p) for p in projects], indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

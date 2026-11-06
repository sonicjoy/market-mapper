#!/usr/bin/env python
"""Pin official Polymarket question names onto Bundesliga RBL / BMG.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

Path 2 is already on for ``bun``. Live matcher containment cannot join
``RB Leipzig`` / ``Borussia Mönchengladbach`` to Optic
``RasenBallsport Leipzig`` / ``Borussia VfL Mönchengladbach``. Overlay
reads ``(polymarket, name)`` aliases.

    python scripts/submit_bun_poly_name_aliases.py
    python scripts/submit_bun_poly_name_aliases.py --submit --env test
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
    BatchEntryRequest,
    EntityAliasPayload,
)
from mappers.control_plane.service import ProposalService

NOTE = (
    "2026-08-29 bun: pin polymarket question names for Leipzig / Gladbach "
    "so official Path 2 can stamp O/U and spreads on bun-lei-moe-2026-08-29."
)

LEAGUE = "germany_bundesliga"
_SLUG = "bun-lei-moe-2026-08-29-total-2pt5"
_FX = "2026082905E0734E"
_QUESTION = "RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5"

# key, optic display name, poly question name, optic competitor id
_TEAMS: tuple[tuple[str, str, str, str], ...] = (
    ("RBL", "RasenBallsport Leipzig", "RB Leipzig", "23643B23434A"),
    (
        "BMG",
        "Borussia VfL Mönchengladbach",
        "Borussia Mönchengladbach",
        "153911A72568",
    ),
)


def _poly_name(value: str) -> AliasPin:
    return AliasPin(sportsbook="polymarket", alias_kind="name", alias_value=value)


def _evidence() -> list[str]:
    refs = [
        f"gap:{_SLUG}",
        f"poly:question:{_QUESTION}",
        f"optic:fixture:{_FX}:RasenBallsport Leipzig vs Borussia VfL Mönchengladbach",
    ]
    for key, optic_name, poly_name, oid in _TEAMS:
        refs.append(f"optic:competitor:{oid}:{optic_name}")
        refs.append(f"poly:name:{key}:{poly_name}")
    return refs


def build_payload() -> BatchChangesPayload:
    aliases = [
        EntityAliasPayload(
            league=LEAGUE,
            canonical_key=key,
            entity_type="team",
            canonical_name=optic_name,
            aliases=[_poly_name(poly_name)],
        )
        for key, optic_name, poly_name, _oid in _TEAMS
    ]
    return BatchChangesPayload(entity_aliases=aliases)


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
    payload = build_payload()
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_bun_poly_name_aliases", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        entity_aliases=payload.entity_aliases,
        acknowledge_shadow=True,
        note=NOTE + " " + " ".join(_evidence()),
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "alias_count": len(payload.entity_aliases),
        "keys": [row.canonical_key for row in payload.entity_aliases],
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "evidence_refs": _evidence(),
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--env",
        choices=("test", "prod", "both"),
        default="test",
        help="target environment(s) for --submit (default: test)",
    )
    args = parser.parse_args(argv)
    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        results = [submit_env(project) for project in projects]
        print(json.dumps(results, indent=2, default=str))
        return 0
    payload = build_payload()
    print(json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True))
    print(f"\n{len(payload.entity_aliases)} entity pin(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

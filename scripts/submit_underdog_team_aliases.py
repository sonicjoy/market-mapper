#!/usr/bin/env python
"""Pin Underdog UDX team codes onto existing tip entities (merge-only).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

Sources: Appendix B (MLB/NFL/WNBA) in ``docs/adding-underdog.md`` and NCAAF
``UDXNCAAMFBGAMEWIN`` rows in the golden catalogue.

    python scripts/submit_underdog_team_aliases.py
    python scripts/submit_underdog_team_aliases.py --league nfl --submit --env test
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
from mappers.control_plane.service import ProposalService
from mappers.control_plane.underdog_team_catalog import (
    entity_has_underdog_code,
    resolve_team_entity,
    team_catalog,
)

NOTE = (
    "2026-09-24: pin Underdog UDX team codes (alias_kind=code) for game-line "
    "leagues; codes from docs/adding-underdog.md Appendix B + golden NCAAF GAMEWIN."
)

_DEFAULT_LEAGUES = ("nfl", "mlb", "wnba", "ncaaf")


def _underdog_pin(code: str) -> AliasPin:
    return AliasPin(sportsbook="underdog", alias_kind="code", alias_value=code)


def build_aliases(
    store: BigQueryStore,
    rule_set_id: str,
    leagues: tuple[str, ...],
) -> tuple[list[EntityAliasPayload], list[dict[str, str]]]:
    catalog = team_catalog()
    entities = store.entities_for(rule_set_id)
    by_league = {
        slug: [e for e in entities if str(e.league) == slug]
        for slug in leagues
    }
    payloads: list[EntityAliasPayload] = []
    skipped: list[dict[str, str]] = []
    for slug in leagues:
        codes = catalog.get(slug) or {}
        for code, venue_name in sorted(codes.items()):
            entity = resolve_team_entity(by_league.get(slug, []), code, venue_name)
            if entity is None:
                skipped.append({"league": slug, "code": code, "reason": "no entity match"})
                continue
            if entity_has_underdog_code(entity, code):
                skipped.append({"league": slug, "code": code, "reason": "already pinned"})
                continue
            payloads.append(
                EntityAliasPayload(
                    league=slug,
                    canonical_key=str(entity.canonical_key),
                    entity_type="team",
                    canonical_name=entity.canonical_name,
                    aliases=[_underdog_pin(code)],
                    evidence_refs=[
                        f"gap:underdog:{slug}:{code}",
                        "docs/adding-underdog.md",
                    ],
                ),
            )
    return payloads, skipped


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def submit_env(
    project: str,
    leagues: tuple[str, ...],
) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    aliases, skipped = build_aliases(store, current, leagues)
    if not aliases:
        return {
            "project": project,
            "skipped": "no new Underdog team aliases to propose",
            "unresolved": skipped[:20],
            "rule_set_id": current,
        }
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_underdog_team_aliases", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        entity_aliases=aliases,
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
        "environment": environment,
        "rule_set_id": current,
        "alias_count": len(aliases),
        "skipped_count": len(skipped),
        "leagues": list(leagues),
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "unresolved_sample": skipped[:12],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--league",
        action="append",
        choices=_DEFAULT_LEAGUES,
        help="limit to one or more leagues (default: all four)",
    )
    parser.add_argument("--env", choices=("test", "prod", "both"), default="test")
    args = parser.parse_args(argv)
    leagues = tuple(args.league) if args.league else _DEFAULT_LEAGUES

    if not args.submit:
        catalog = team_catalog()
        counts = {slug: len(catalog.get(slug) or {}) for slug in leagues}
        print(json.dumps({"leagues": leagues, "code_counts": counts}, indent=2))
        print("pass --submit to verify against BQ tip and propose", file=sys.stderr)
        return 0

    projects: list[str] = []
    if args.env in ("test", "both"):
        projects.append("marketmaking-test")
    if args.env in ("prod", "both"):
        projects.append("rs-marketmaking")
    results = [submit_env(project, leagues) for project in projects]
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

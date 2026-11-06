#!/usr/bin/env python
"""Add ``davis_cup`` to the ATP tip ``extra_optic_league_ids`` (propose + validate).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

Crypto.com Davis Cup singles use ``meta_league=ATP`` and ``NX.F.OPT.TENNIS`` symbols
while Optic fixtures live under league ``davis_cup``. Player aliases stay on the
``atp`` tip; the mapper must fetch Davis Cup fixtures via ``extra_optic_league_ids``.

    python scripts/submit_atp_davis_cup_extra.py --submit --env both
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
    BatchEntryRequest,
    ExchangePin,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow
from mappers.seed.league_meta import merge_league_meta_into_exchanges

LEAGUE = "atp"
EXTRA = "davis_cup"
NOTE = (
    "2026-09-19: crypto.com Davis Cup singles catalogue as ATP but Optic league "
    "davis_cup — fetch fixtures via extra_optic_league_ids while aliases stay on atp."
)
_EVIDENCE = [
    "gap:crypto:TENNIS:ATP:davis_cup",
    "optic:league:davis_cup",
    "crypto:meta_league:ATP",
    "scripts/submit_atp_davis_cup_extra.py",
]


def _settings(row: LeagueRow) -> dict[str, Any]:
    return dict(getattr(row, "settings", None) or {})


def _payload(row: LeagueRow) -> MappingLeaguePayload | None:
    extra = [str(x).strip() for x in (row.extra_optic_league_ids or []) if str(x).strip()]
    if EXTRA in extra:
        return None
    extra = [*extra, EXTRA]
    settings = _settings(row)
    entity_type = str(settings.get("entity_type") or "player")
    alias_enforcement = str(settings.get("alias_enforcement") or "raise")
    pins = [
        ExchangePin(
            sportsbook=str(ex.get("sportsbook") or ""),
            enabled=bool(ex.get("enabled", True)),
            parser_profile=str(ex.get("parser_profile") or ""),
            source_league_id=ex.get("source_league_id"),
            settings=dict(ex.get("settings") or {}),
        )
        for ex in (row.exchanges or [])
    ]
    exchange_dicts = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in pins],
        settings,
    )
    pins = [
        ExchangePin(
            sportsbook=str(ex["sportsbook"]),
            enabled=bool(ex.get("enabled", True)),
            parser_profile=str(ex.get("parser_profile") or ""),
            source_league_id=ex.get("source_league_id"),
            settings=dict(ex.get("settings") or {}),
        )
        for ex in exchange_dicts
    ]
    return MappingLeaguePayload(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=str(row.optic_league_id),
        extra_optic_league_ids=extra,
        fixture_source=str(row.fixture_source),
        fixture_horizon_hours=float(row.fixture_horizon_hours),
        enabled=bool(row.enabled),
        output_order=list(row.output_order),
        entity_type=entity_type,  # type: ignore[arg-type]
        alias_enforcement=alias_enforcement,  # type: ignore[arg-type]
        runshop_enabled=bool(settings.get("runshop_enabled")),
        exchanges=pins,
        notes=NOTE,
        evidence_refs=list(_EVIDENCE),
    )


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    by_slug = {str(row.league): row for row in store.leagues_for(current) if not row.tombstone}
    row = by_slug.get(LEAGUE)
    if row is None:
        raise RuntimeError(f"{project}: missing {LEAGUE} league row")
    league = _payload(row)
    if league is None:
        return {"project": project, "skipped": "already has davis_cup extra", "rule_set_id": current}
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_atp_davis_cup_extra", role=ActorRole.PROPOSER)
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
        "extra_optic_league_ids": league.extra_optic_league_ids,
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

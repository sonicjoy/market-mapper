#!/usr/bin/env python
"""Rewrite Polymarket US inner codes that do not match live tickers.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

Path 2 only stamps ``ut.inner == pin``. These pins still carry the
official-slug guess; live polymarketus uses a different inner, so classify
stays silent while Optic passthrough maps the same fixtures.

    GCP_PROJECT=marketmaking-test python scripts/submit_poly_us_inner_code_pins.py
    python scripts/submit_poly_us_inner_code_pins.py --submit --env test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchChangesPayload,
    BatchEntryRequest,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK, find_exchange
from scripts.submit_poly_us_cards import _league_payload, _settings

# One-shot Review-card targets (not live SoT). Tip already has the pin;
# these are the live inners confirmed vs Optic 2026-08-28/29.
PIN_FIXES: dict[str, str] = {
    "korea_k1": "kl1",
    "spain_la_liga_2": "lal2",
    "norway_eliteserien": "els",
    "peru_primera_division": "pl1",
    "cricket_test": "testcr",
    "sweden_allsvenskan": "alsv",
    "chile_primera_division": "pdc",
    "bulgaria_parva_liga": "pvl",
    "colombia_primera_a": "lco",
}

NOTE = (
    "2026-08-29 Poly US: set polymarket_usa source_league_id to the live "
    "inner ticker code (kl1 / lal2 / els / pl1 / testcr / alsv / pdc / "
    "pvl / lco) so Path 2 can stamp."
)
_EVIDENCE = [
    "gap:usa-inner:korea_k1:kl1:atc-kl1-bch-any-2026-08-29",
    "optic:fixture:korea_-_k1_league:Bucheon FC 1995 vs FC Anyang",
    "gap:usa-inner:spain_la_liga_2:lal2:atc-lal2-cdt-spo-2026-08-28",
    "optic:fixture:spain_-_la_liga_2:CD Tenerife vs Real Sporting de Gijon",
    "gap:usa-inner:spain_la_liga_2:lal2:atc-lal2-leg-eld-2026-08-29",
    "optic:fixture:spain_-_la_liga_2:CD Leganes vs CD Eldense",
    "gap:usa-inner:norway_eliteserien:els:atc-els-vif-mol-2026-08-29",
    "optic:fixture:norway_-_eliteserien:Valerenga IF vs Molde FK",
    "gap:usa-inner:norway_eliteserien:els:atc-els-bog-rbk-2026-08-30",
    "optic:fixture:norway_-_eliteserien:FK Bodo / Glimt vs Rosenborg BK",
    "gap:usa-inner:peru_primera_division:pl1:atc-pl1-cou-caj-2026-08-28",
    "optic:fixture:peru_-_primera_division:Comerciantes Unidos vs FC Cajamarca",
    "gap:usa-inner:cricket_test:testcr:aec-testcr-eng-pak-2026-08-27",
    "optic:fixture:international_-_test_matches:England vs Pakistan",
    "gap:usa-inner:sweden_allsvenskan:alsv:atc-alsv-elf-deg-2026-08-29",
    "optic:fixture:sweden_-_allsvenskan:IF Elfsborg vs Degerfors IF",
    "gap:usa-inner:chile_primera_division:pdc:atc-pdc-cbs-pal-2026-08-28",
    "optic:fixture:chile_-_primera_division:Cobresal vs Palestino",
    "gap:usa-inner:chile_primera_division:pdc:atc-pdc-col-aud-2026-08-30",
    "optic:fixture:chile_-_primera_division:Colo Colo vs Audax Italiano",
    "gap:usa-inner:bulgaria_parva_liga:pvl:atc-pvl-fcc-lok-2026-08-28",
    "optic:fixture:bulgaria_-_parva_liga:FK CSKA 1948 Sofia vs Lokomotiv Plovdiv",
    "gap:usa-inner:colombia_primera_a:lco:atc-lco-jag-ame-2026-08-29",
    "optic:fixture:colombia_-_primera_a:Jaguares de Cordoba vs America de Cali",
    "docs/polymarket-mapping-gaps.md",
]


def _current_us_code(row: LeagueRow) -> str:
    usa = find_exchange(list(row.exchanges or []), POLY_USA_BOOK)
    if usa is None:
        return ""
    source = str(usa.get("source_league_id") or "").strip()
    slug = str(_settings(usa).get("slug_prefix") or "").strip()
    return source or slug


def _needs_fix(row: LeagueRow) -> str | None:
    target = PIN_FIXES.get(str(row.league))
    if not target:
        return None
    if _current_us_code(row) == target:
        return None
    return target


def build_payload(rows: list[LeagueRow]) -> BatchChangesPayload:
    leagues: list[MappingLeaguePayload] = []
    for row in sorted(rows, key=lambda item: item.league):
        target = _needs_fix(row)
        if target is None:
            continue
        payload = _league_payload(row, us_code=target)
        payload.notes = NOTE
        payload.evidence_refs = list(_EVIDENCE)
        leagues.append(payload)
    if not leagues:
        raise RuntimeError("no inner-code pin updates needed")
    return BatchChangesPayload(leagues=leagues)


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def submit_env(project: str) -> dict[str, Any]:
    from google.cloud import bigquery

    from mappers.control_plane.bq_store import BigQueryStore

    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payload = build_payload(store.leagues_for(current))
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_poly_us_inner_code_pins", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        leagues=payload.leagues,
        acknowledge_shadow=True,
        note=NOTE,
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(
            f"{project}: verify blocked: {verified.get('blockers')}",
        )
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "league_count": len(payload.leagues),
        "leagues": [lg.league for lg in payload.leagues],
        "codes": {lg.league: PIN_FIXES[lg.league] for lg in payload.leagues},
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
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
        results = []
        for project in projects:
            print(f"submitting {project}...", file=sys.stderr)
            results.append(submit_env(project))
        print(json.dumps(results, indent=2, default=str))
        return 0

    project = (os.environ.get("GCP_PROJECT") or "marketmaking-test").strip()
    from google.cloud import bigquery

    from mappers.control_plane.bq_store import BigQueryStore

    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError("no current rule set")
    payload = build_payload(store.leagues_for(current))
    print(json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True))
    print(f"\n{len(payload.leagues)} league update(s) for {project}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Migrate Polymarket US to a first-class ``polymarket_usa`` exchange pin.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

Drops the legacy ``settings.us_slug_prefix`` from the ``polymarket`` pin and
adds a ``polymarket_usa`` pin to every league with an enabled ``polymarket``
exchange. The inner US league code lives in ``source_league_id`` like every
other book (bootstrap ``US_CODE_OVERRIDES`` only when the league has no US pin yet).

    # Preview JSON only
    GCP_PROJECT=marketmaking-test python scripts/submit_poly_us_cards.py

    # Create Review cards on test + prod (propose + validate; human Approve)
    python scripts/submit_poly_us_cards.py --submit --env both
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
    ExchangePin,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow
from mappers.seed.league_meta import merge_league_meta_into_exchanges
from mappers.seed.poly_usa_exchange import (
    POLY_BOOK,
    POLY_USA_BOOK,
    US_CODE_OVERRIDES,
    default_us_code,
    find_exchange,
)
from mappers.seed.profiles import DEFAULT_PROFILES

NOTE = (
    "2026-08-27 Poly US: promote Polymarket US to its own polymarket_usa "
    "exchange pin (inner league code in source_league_id)."
)
_EVIDENCE = [
    "docs/polymarket-mapping-gaps.md",
    "scripts/submit_poly_us_cards.py",
    "mappers/seed/poly_usa_exchange.py",
    "mappers/profiles/registry.py poly_usa_generic_v1",
]


def _row_settings(row: LeagueRow) -> dict[str, Any]:
    return dict(getattr(row, "settings", None) or {})


def _settings(ex: dict[str, Any] | None) -> dict[str, Any]:
    return dict((ex or {}).get("settings") or {})


def _target_us_code(row: LeagueRow, poly_ex: dict[str, Any] | None) -> str:
    usa_ex = find_exchange(list(row.exchanges or []), POLY_USA_BOOK)
    if usa_ex is not None:
        current = str(usa_ex.get("source_league_id") or "").strip()
        if current:
            return current
    legacy = str(_settings(poly_ex).get("us_slug_prefix") or "").strip()
    if legacy:
        return legacy
    return default_us_code(row, poly_ex)


def _exchange_pins(row: LeagueRow, *, us_code: str) -> list[ExchangePin]:
    pins: list[ExchangePin] = []
    usa_seen = False
    for ex in row.exchanges or []:
        book = str(ex.get("sportsbook") or "")
        settings = dict(ex.get("settings") or {})
        source_league_id = ex.get("source_league_id")
        if book == POLY_BOOK:
            settings.pop("us_slug_prefix", None)
        elif book == POLY_USA_BOOK:
            usa_seen = True
            settings.pop("us_slug_prefix", None)
            source_league_id = us_code
            settings["slug_prefix"] = us_code
        pins.append(
            ExchangePin(
                sportsbook=book,
                enabled=bool(ex.get("enabled", True)),
                parser_profile=str(ex.get("parser_profile") or ""),
                source_league_id=source_league_id,
                settings=settings,
            ),
        )
    if not usa_seen:
        pins.append(
            ExchangePin(
                sportsbook=POLY_USA_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[POLY_USA_BOOK],
                source_league_id=us_code,
                settings={"slug_prefix": us_code},
            ),
        )
    return pins


def _league_payload(row: LeagueRow, *, us_code: str) -> MappingLeaguePayload:
    settings = _row_settings(row)
    entity_type = settings.get("entity_type", "team")
    alias_enforcement = settings.get("alias_enforcement", "raise")
    if entity_type not in ("team", "player", "fighter"):
        entity_type = "team"
    if alias_enforcement not in ("raise", "warn"):
        alias_enforcement = "raise"
    pins = _exchange_pins(row, us_code=us_code)
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
        extra_optic_league_ids=list(row.extra_optic_league_ids),
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


def _already_migrated(row: LeagueRow, us_code: str) -> bool:
    usa = find_exchange(list(row.exchanges or []), POLY_USA_BOOK)
    poly = find_exchange(list(row.exchanges or []), POLY_BOOK)
    if usa is None:
        return False
    if str(usa.get("source_league_id") or "").strip() != us_code:
        return False
    return "us_slug_prefix" not in _settings(poly)


def _needs_update(row: LeagueRow) -> tuple[bool, str]:
    poly = find_exchange(list(row.exchanges or []), POLY_BOOK)
    poly_live = poly is not None and poly.get("enabled", True)
    # Polymarket US now stands alone, so a league with a known US code gets a
    # pin even where the official book has none (ncaaf trades only as cfb).
    if not poly_live and str(row.league) not in US_CODE_OVERRIDES:
        return False, ""
    us_code = _target_us_code(row, poly)
    if not us_code or _already_migrated(row, us_code):
        return False, ""
    return True, us_code


def build_payload(
    rows: list[LeagueRow], only: frozenset[str] | None = None,
) -> BatchChangesPayload:
    leagues: list[MappingLeaguePayload] = []
    for row in sorted(rows, key=lambda item: item.league):
        if only and str(row.league) not in only:
            continue
        needs, us_code = _needs_update(row)
        if not needs:
            continue
        leagues.append(_league_payload(row, us_code=us_code))
    if not leagues:
        raise RuntimeError(
            "no league updates needed — tip already has polymarket_usa pins",
        )
    return BatchChangesPayload(leagues=leagues)


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def submit_env(project: str, only: frozenset[str] | None = None) -> dict[str, Any]:
    from google.cloud import bigquery

    from mappers.control_plane.bq_store import BigQueryStore

    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payload = build_payload(store.leagues_for(current), only)
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_poly_us_cards", role=ActorRole.PROPOSER)
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
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        help="write preview JSON for the default GCP_PROJECT",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="create Review cards (propose + validate) in BigQuery",
    )
    parser.add_argument(
        "--env",
        choices=("test", "prod", "both"),
        default="both",
        help="target environment(s) for --submit (default: both)",
    )
    parser.add_argument(
        "--league",
        nargs="+",
        help="only these tip league slugs (default: every league needing a pin)",
    )
    args = parser.parse_args(argv)
    only = frozenset(args.league) if args.league else None

    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        results = []
        for project in projects:
            print(f"submitting {project}...", file=sys.stderr)
            results.append(submit_env(project, only))
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
    payload = build_payload(store.leagues_for(current), only)
    text = json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    print(f"\n{len(payload.leagues)} league update(s) for {project}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

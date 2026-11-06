#!/usr/bin/env python
"""Pin official Polymarket Path 2 slug prefixes for live RFQ gaps.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

Enables ``sportsbook=polymarket`` ``settings.slug_prefix`` on tip leagues that
already have Optic (and often Polymarket US), and onboards soccer leagues that
are still Path 2 off despite live Optic fixtures.

    python scripts/submit_poly_path2_gap_wave.py
    python scripts/submit_poly_path2_gap_wave.py --submit --env both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.chat_profiles import all_platform_exchanges
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
from mappers.seed.poly_usa_exchange import POLY_BOOK
from mappers.seed.profiles import DEFAULT_PROFILES

NOTE = (
    "2026-08-29 official Path 2: RFQ MAPPING_FAILED prefixes with Optic "
    "fixtures present (ja2/cfb/rus/chi2/sui/…). Pin slug_prefix; do not "
    "invent Kalshi/PX/crypto ids."
)

# Existing tip leagues: copy every exchange, set/add official polymarket prefix.
ENABLE_OFFICIAL: dict[str, str] = {
    "ncaaf": "cfb",
    "russia_premier_league": "rus",
    "switzerland_super_league": "sui",
    "czech_first_league": "cze1",
    "caribbean_premier_league": "criccpl",
}

# slug, sport, optic_league_id, slug_prefix, clone_market_rules_from
NEW_LEAGUES: tuple[tuple[str, str, str, str, str], ...] = (
    ("japan_j2_league", "soccer", "japan_-_j2_league", "ja2", "colombia_primera_a"),
    ("china_league_one", "soccer", "china_-_league_one", "chi2", "colombia_primera_a"),
    ("chile_primera_b", "soccer", "chile_-_primera_b", "chl2", "colombia_primera_a"),
    ("brazil_serie_c", "soccer", "brazil_-_serie_c", "bra3", "colombia_primera_a"),
    ("croatia_1_hnl", "soccer", "croatia_-_1_hnl", "hr1", "colombia_primera_a"),
    ("serbia_super_liga", "soccer", "serbia_-_super_liga", "srb", "colombia_primera_a"),
    ("uae_pro_league", "soccer", "uae_-_pro_league", "uae1", "colombia_primera_a"),
    ("slovakia_superliga", "soccer", "slovakia_-_superliga", "svk1", "colombia_primera_a"),
    ("azerbaijan_premier_league", "soccer", "azerbaijan_-_premier_league", "aze1", "colombia_primera_a"),
    ("colombia_primera_b", "soccer", "colombia_-_primera_b", "col2", "colombia_primera_a"),
    ("slovenia_prvaliga", "soccer", "slovenia_-_prvaliga", "slo", "colombia_primera_a"),
    ("venezuela_primera", "soccer", "venezuela_-_primera_division", "ven1", "colombia_primera_a"),
    ("lithuania_a_lyga", "soccer", "lithuania_-_a_lyga", "ltu1", "colombia_primera_a"),
    ("faroe_premier_league", "soccer", "faroe_islands_-_premier_league", "fro1", "colombia_primera_a"),
    ("belgium_challenger_pro_league", "soccer", "belgium_-_challenger_pro_league", "bel2", "colombia_primera_a"),
)

_ENTITY = frozenset({"team", "player", "fighter"})
_ENFORCE = frozenset({"raise", "warn"})


def poly_settings(optic_id: str, prefix: str) -> dict[str, Any]:
    """Official Path 2 settings blob (slug_prefix is the join key)."""
    return {
        "slug_prefix": prefix,
        "optic_league_id": optic_id,
        "question_style": "mlb_suffix",
    }


def official_prefix(exchanges: list[dict[str, Any]]) -> str:
    """Current official Polymarket slug_prefix, or empty."""
    for ex in exchanges:
        if str(ex.get("sportsbook") or "") != POLY_BOOK:
            continue
        if ex.get("enabled") is False:
            continue
        settings = ex.get("settings") or {}
        if not isinstance(settings, dict):
            continue
        pfx = str(settings.get("slug_prefix") or "").strip()
        if pfx:
            return pfx
    return ""


def _pin_from_dict(ex: dict[str, Any]) -> ExchangePin:
    return ExchangePin(
        sportsbook=str(ex.get("sportsbook") or ""),
        enabled=bool(ex.get("enabled", True)),
        parser_profile=str(ex.get("parser_profile") or ""),
        source_league_id=ex.get("source_league_id"),
        settings=dict(ex.get("settings") or {}),
    )


def _with_official_poly(row: LeagueRow, prefix: str) -> list[ExchangePin]:
    """Copy tip exchanges; set or add the official Polymarket slug_prefix."""
    optic = str(row.optic_league_id)
    pins: list[ExchangePin] = []
    seen = False
    for ex in row.exchanges or []:
        book = str(ex.get("sportsbook") or "")
        settings = dict(ex.get("settings") or {})
        source = ex.get("source_league_id")
        if book == POLY_BOOK:
            seen = True
            settings.update(poly_settings(optic, prefix))
            source = source or optic
            ex = {**ex, "enabled": True}
        pins.append(_pin_from_dict({**ex, "source_league_id": source, "settings": settings}))
    if not seen:
        pins.append(
            ExchangePin(
                sportsbook=POLY_BOOK,
                enabled=True,
                parser_profile=DEFAULT_PROFILES[POLY_BOOK],
                source_league_id=optic,
                settings=poly_settings(optic, prefix),
            ),
        )
    return pins


def _row_payload(row: LeagueRow, prefix: str) -> MappingLeaguePayload:
    settings = dict(getattr(row, "settings", None) or {})
    entity = settings.get("entity_type", "team")
    enforce = settings.get("alias_enforcement", "raise")
    pins = _with_official_poly(row, prefix)
    merged = merge_league_meta_into_exchanges(
        [pin.model_dump(mode="json") for pin in pins],
        settings,
    )
    return MappingLeaguePayload(
        league=str(row.league),
        sport=str(row.sport),
        optic_league_id=str(row.optic_league_id),
        extra_optic_league_ids=list(row.extra_optic_league_ids),
        fixture_source=str(row.fixture_source) or "api",
        fixture_horizon_hours=float(row.fixture_horizon_hours or 96.0),
        enabled=bool(row.enabled),
        output_order=list(row.output_order),
        entity_type=entity if entity in _ENTITY else "team",  # type: ignore[arg-type]
        alias_enforcement=enforce if enforce in _ENFORCE else "raise",  # type: ignore[arg-type]
        runshop_enabled=bool(settings.get("runshop_enabled")),
        exchanges=[_pin_from_dict(ex) for ex in merged],
        notes=NOTE,
        evidence_refs=[
            f"gap:poly-prefix:{prefix}",
            f"optic:league:{row.optic_league_id}",
            "docs/polymarket-mapping-gaps.md",
        ],
    )


def _new_league_payload(item: tuple[str, str, str, str, str]) -> MappingLeaguePayload:
    slug, sport, optic, prefix, clone = item
    raw = all_platform_exchanges(
        optic_league_id=optic,
        evidence_books=["optic", POLY_BOOK],
    )
    pins: list[ExchangePin] = []
    for ex in raw:
        book = str(ex["sportsbook"])
        source = ex.get("source_league_id")
        settings = dict(ex.get("settings") or {})
        if book == POLY_BOOK:
            source = optic
            settings.update(poly_settings(optic, prefix))
        pins.append(
            ExchangePin(
                sportsbook=book,
                enabled=bool(ex.get("enabled")),
                parser_profile=str(ex.get("parser_profile") or ""),
                source_league_id=source,
                settings=settings,
            ),
        )
    return MappingLeaguePayload(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        exchanges=pins,
        clone_market_rules_from=clone,
        notes=NOTE,
        evidence_refs=[
            f"gap:poly-prefix:{prefix}",
            f"optic:league:{optic}",
            "docs/polymarket-mapping-gaps.md",
        ],
    )


def build_leagues(rows: list[LeagueRow]) -> list[MappingLeaguePayload]:
    """ENABLE existing rows that lack the prefix; onboard missing NEW_LEAGUES."""
    by_slug = {r.league: r for r in rows if not r.tombstone}
    leagues: list[MappingLeaguePayload] = []
    for slug, prefix in sorted(ENABLE_OFFICIAL.items()):
        row = by_slug.get(slug)
        if row is None:
            continue
        if official_prefix(list(row.exchanges or [])) == prefix:
            continue
        payload = _row_payload(row, prefix)
        payload.notes = NOTE
        leagues.append(payload)
    for item in NEW_LEAGUES:
        slug, _sport, _optic, prefix, _clone = item
        if slug in by_slug:
            row = by_slug[slug]
            if official_prefix(list(row.exchanges or [])) == prefix:
                continue
            leagues.append(_row_payload(row, prefix))
            continue
        leagues.append(_new_league_payload(item))
    return leagues


def build_payload(rows: list[LeagueRow]) -> BatchChangesPayload:
    return BatchChangesPayload(leagues=build_leagues(rows))


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    tip = store.current_rule_set_id
    if tip is None:
        raise RuntimeError(f"{project}: no tip")
    payload = build_payload(store.leagues_for(tip))
    if not payload.leagues:
        return {"project": project, "rule_set_id": tip, "league_count": 0, "ref": None}
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_poly_path2_gap_wave", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        leagues=payload.leagues,
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
        "rule_set_id": tip,
        "league_count": len(payload.leagues),
        "leagues": [lg.league for lg in payload.leagues],
        "prefixes": {
            lg.league: official_prefix([e.model_dump(mode="json") for e in lg.exchanges])
            for lg in payload.leagues
        },
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="both")
    args = parser.parse_args(argv)
    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        out = [submit_env(project) for project in projects]
        print(json.dumps(out, indent=2, default=str))
        return 0
    os.environ.setdefault("GCP_PROJECT", "rs-marketmaking")
    project = os.environ["GCP_PROJECT"]
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    tip = store.current_rule_set_id
    if not tip:
        raise RuntimeError(f"{project}: no tip")
    payload = build_payload(store.leagues_for(tip))
    summary = {
        "tip": store.current_rule_set_id,
        "leagues": [
            {
                "league": lg.league,
                "optic": lg.optic_league_id,
                "new": lg.clone_market_rules_from is not None,
                "prefix": official_prefix(
                    [e.model_dump(mode="json") for e in lg.exchanges],
                ),
            }
            for lg in payload.leagues
        ],
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

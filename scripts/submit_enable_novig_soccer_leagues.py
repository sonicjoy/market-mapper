#!/usr/bin/env python
"""Enable Novig on UEFA Nations League.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

Novig lists the league as "UEFA Nations League" (6,670 markets in the raw
feed over 24h), but the tip row carries no Novig exchange, so every Novig
leg in it died as MAPPING_FAILED -- the most popular unmapped Novig combo
(Montenegro @ Latvia BTTS No + Armenia @ Cyprus BTTS Yes) was this league.
Novig has no CONCACAF Nations League, so that row is left alone.

The Novig entry mirrors MLS: novig_generic_v1 with just the league string,
no market rules (the soccer profile supplies the crosswalk). An env missing
the league, or some of its prod market rules, gets those too, so test
rehearses the same end state.

Prod only proposes; a human approves the Review card. Test can go all
the way to activation with --activate-test.

    python scripts/submit_enable_novig_soccer_leagues.py
    python scripts/submit_enable_novig_soccer_leagues.py --submit --env test --activate-test
    python scripts/submit_enable_novig_soccer_leagues.py --submit --env prod
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
    MarketRulePin,
)
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService

PROD, TEST = "rs-marketmaking", "marketmaking-test"
NOVIG = "novig"
NOVIG_PROFILE = "novig_generic_v1"

# Novig's own league string per tip league (the feed's `league` field).
NOVIG_LEAGUE_BY_LEAGUE: dict[str, str] = {
    "uefa_nations_league": "UEFA Nations League",
}

NOTE = (
    "2026-10-02: enable Novig on UEFA Nations League; Novig lists it as "
    "'UEFA Nations League' and the tip row had no Novig exchange."
)
ACTOR = "scripts/submit_enable_novig_soccer_leagues"


def novig_settings(novig_league: str) -> dict[str, Any]:
    return {"league": novig_league}


def _novig_live(row: LeagueRow, novig_league: str) -> bool:
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") == NOVIG:
            settings = ex.get("settings") or {}
            return bool(ex.get("enabled", True)) and settings.get("league") == novig_league
    return False


def exchanges_with_novig(row: LeagueRow, novig_league: str) -> list[ExchangePin]:
    """The row's exchanges unchanged, with Novig added or switched on."""
    novig = ExchangePin(
        sportsbook=NOVIG,
        enabled=True,
        parser_profile=NOVIG_PROFILE,
        source_league_id=novig_league,
        settings=novig_settings(novig_league),
    )
    out: list[ExchangePin] = []
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") == NOVIG:
            continue
        out.append(ExchangePin(
            sportsbook=str(ex.get("sportsbook") or ""),
            enabled=bool(ex.get("enabled", True)),
            parser_profile=str(ex.get("parser_profile") or ""),
            source_league_id=ex.get("source_league_id"),
            settings=dict(ex.get("settings") or {}),
        ))
    return [*out, novig]


def _rule_key(rule: MarketRuleRow) -> tuple[str, str, str]:
    return (str(rule.sportsbook), str(rule.source_key_type), str(rule.source_key))


def missing_rules(
    league: str,
    prod_rules: list[MarketRuleRow],
    env_rules: list[MarketRuleRow],
) -> list[MarketRulePin]:
    """Prod market rules for this league that the env tip lacks."""
    have = {_rule_key(r) for r in env_rules if r.league == league and not r.tombstone}
    return [
        MarketRulePin(
            sportsbook=r.sportsbook,
            rule_kind=r.rule_kind,
            source_key_type=r.source_key_type,
            source_key=r.source_key,
            action=r.action,
            canonical_market_type=r.canonical_market_type,
            league=league,
            priority=r.priority,
            enabled=r.enabled,
            confidence=r.confidence,
            match_operator=r.match_operator,
            notes=r.notes,
        )
        for r in prod_rules
        if r.league == league and not r.tombstone and _rule_key(r) not in have
    ]


def build_payloads(
    prod_leagues: list[LeagueRow],
    prod_rules: list[MarketRuleRow],
    env_leagues: list[LeagueRow],
    env_rules: list[MarketRuleRow],
) -> list[MappingLeaguePayload]:
    """One league payload per target that is not already live in the env."""
    prod_by = {r.league: r for r in prod_leagues if not r.tombstone}
    env_by = {r.league: r for r in env_leagues if not r.tombstone}
    out: list[MappingLeaguePayload] = []
    for league, novig_league in NOVIG_LEAGUE_BY_LEAGUE.items():
        prod_row = prod_by.get(league)
        if prod_row is None:
            raise RuntimeError(f"{league}: not on the prod tip")
        row = env_by.get(league, prod_row)
        rules = missing_rules(league, prod_rules, env_rules)
        if league in env_by and _novig_live(row, novig_league) and not rules:
            continue
        settings = row.settings or {}
        out.append(MappingLeaguePayload(
            league=league,
            sport=row.sport,
            optic_league_id=row.optic_league_id,
            extra_optic_league_ids=list(row.extra_optic_league_ids),
            fixture_source=row.fixture_source or "api",
            fixture_horizon_hours=row.fixture_horizon_hours,
            enabled=row.enabled,
            output_order=list(row.output_order),
            entity_type=settings.get("entity_type", "team"),
            alias_enforcement=settings.get("alias_enforcement", "raise"),
            runshop_enabled=bool(settings.get("runshop_enabled")),
            exchanges=exchanges_with_novig(row, novig_league),
            market_rules=rules,
            notes=NOTE,
            evidence_refs=[
                f"novig:league:{novig_league}",
                f"optic:league:{row.optic_league_id}",
            ],
        ))
    return out


def _store(project: str, *, allow_activate: bool = False) -> BigQueryStore:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == TEST else "prod"
    return BigQueryStore(
        bigquery.Client(project=project),
        environment=environment,
        allow_activate=allow_activate,
    )


def _review_url(project: str, ref: str) -> str:
    host = "mapping.mm-test" if project == TEST else "mapping.mm"
    return f"https://{host}.whiteswandata.com/review/{ref}"


def submit_env(project: str, *, activate: bool) -> dict[str, Any]:
    if activate and project != TEST:
        raise RuntimeError("--activate-test only applies to test")
    prod = _store(PROD)
    prod_leagues = prod.leagues_for(prod.current_rule_set_id or "")
    prod_rules = prod.market_rules_for(prod.current_rule_set_id or "")
    store = prod if project == PROD else _store(TEST, allow_activate=activate)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    leagues = build_payloads(
        prod_leagues, prod_rules,
        store.leagues_for(current), store.market_rules_for(current),
    )
    if not leagues:
        return {"project": project, "skipped": "Novig already live", "rule_set_id": current}

    svc = ProposalService(store, require_maker_checker=False)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(leagues=leagues, acknowledge_shadow=True, note=NOTE),
    )
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(
        str(verified["preview_token"]), Actor(subject=ACTOR, role=ActorRole.PROPOSER))
    ref = str(card.get("ref") or "")
    result: dict[str, Any] = {
        "project": project,
        "rule_set_id": current,
        "leagues": {lg.league: len(lg.market_rules) for lg in leagues},
        "warnings": verified.get("warnings"),
        "ref": ref,
        "review_url": _review_url(project, ref),
    }
    if activate:
        approved = svc.approve_review(ref, Actor(subject=ACTOR, role=ActorRole.APPROVER))
        after = _store(TEST)
        result["status"] = approved.get("status")
        result["activated_rule_set_id"] = after.current_rule_set_id
        result["novig_live"] = sorted(
            r.league for r in after.leagues_for(after.current_rule_set_id or "")
            if r.league in NOVIG_LEAGUE_BY_LEAGUE and _novig_live(r, NOVIG_LEAGUE_BY_LEAGUE[r.league])
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument(
        "--activate-test", action="store_true",
        help="test only: approve and activate the card as well",
    )
    args = parser.parse_args(argv)
    project = TEST if args.env == "test" else PROD

    if not args.submit:
        prod = _store(PROD)
        env = prod if project == PROD else _store(TEST)
        plan = build_payloads(
            prod.leagues_for(prod.current_rule_set_id or ""),
            prod.market_rules_for(prod.current_rule_set_id or ""),
            env.leagues_for(env.current_rule_set_id or ""),
            env.market_rules_for(env.current_rule_set_id or ""),
        )
        print(json.dumps([p.model_dump(mode="json") for p in plan], indent=2))
        print(f"{len(plan)} league change(s) for {args.env}; pass --submit to propose",
              file=sys.stderr)
        return 0

    print(json.dumps(submit_env(project, activate=args.activate_test), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

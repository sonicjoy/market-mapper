#!/usr/bin/env python
"""Enable ProphetX on International Friendlies (national teams).

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/exchanges/*_leagues.py``.

PX lists the league as tournament 54 "International Friendlies" (Argentina
v Benin, event 90123170, 2026-10-06), but the tip row carries no PX
exchange, so its spread / goalscorer legs could not be quoted.

Two stages, because the goalscorer rules need code that ships separately:

  1. (default) the PX exchange pin plus EPL's three game-line rules
     (Moneyline (2 Way) / Spread (Regular Time) / Total Goals (Regular Time)).
     Safe on any deployed mapper.
  2. --goalscorer adds the "<Player> To Score A Goal" / "To Score N+ Goals"
     suffix rules -> player_goals.  ONLY after the PLAYER_GOALS_YN mapper
     change is deployed: older code raises on a sup_moneyline player_goals
     market and aborts the league run.

Prod only proposes; a human approves the Review card. Test can go all
the way to activation with --activate-test.

    python scripts/submit_enable_px_intl_friendlies.py
    python scripts/submit_enable_px_intl_friendlies.py --submit --env test --activate-test
    python scripts/submit_enable_px_intl_friendlies.py --submit --env prod
    python scripts/submit_enable_px_intl_friendlies.py --goalscorer --submit --env prod
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
PX = "px"
PX_PROFILE = "px_generic_v1"
LEAGUE = "international_friendlies"
TOURNAMENT_ID = 54
TEMPLATE_LEAGUE = "epl"  # PX game-line rules are copied from here

# (suffix, canonical type).  PX capitalisation varies by market ("A Goal"
# today; NFL ships "a Touchdown"), and suffix matching is exact.
GOALSCORER_SUFFIXES: list[tuple[str, str]] = [
    (" To Score A Goal", "player_goals"),
    (" To Score a Goal", "player_goals"),
    (" To Score 2+ Goals", "player_goals"),
    (" To Score 3+ Goals", "player_goals"),
]

NOTE = (
    "2026-10-06: enable ProphetX (tournament 54) on International Friendlies "
    "for Argentina v Benin spread + Messi goalscorer legs."
)
ACTOR = "scripts/submit_enable_px_intl_friendlies"


def _px_settings_live(row: LeagueRow) -> bool:
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") == PX:
            settings = ex.get("settings") or {}
            return bool(ex.get("enabled", True)) and settings.get("tournament_id") == TOURNAMENT_ID
    return False


def exchanges_with_px(row: LeagueRow) -> list[ExchangePin]:
    """The row's exchanges unchanged, with PX added or switched on."""
    pin = ExchangePin(
        sportsbook=PX,
        enabled=True,
        parser_profile=PX_PROFILE,
        source_league_id=None,
        settings={"tournament_id": TOURNAMENT_ID},
    )
    out: list[ExchangePin] = []
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") == PX:
            continue
        out.append(ExchangePin(
            sportsbook=str(ex.get("sportsbook") or ""),
            enabled=bool(ex.get("enabled", True)),
            parser_profile=str(ex.get("parser_profile") or ""),
            source_league_id=ex.get("source_league_id"),
            settings=dict(ex.get("settings") or {}),
        ))
    return [*out, pin]


def _rule_key(sportsbook: str, key_type: str, key: str) -> tuple[str, str, str]:
    return (sportsbook, key_type, key)


def wanted_rules(prod_rules: list[MarketRuleRow], *, goalscorer: bool) -> list[MarketRulePin]:
    """EPL's PX game-line rules re-pinned to LEAGUE, plus goalscorer suffixes."""
    template = [
        r for r in prod_rules
        if r.league == TEMPLATE_LEAGUE and r.sportsbook == PX and not r.tombstone
        and r.action == "map"
    ]
    if len(template) < 3:
        raise RuntimeError(f"{TEMPLATE_LEAGUE}: expected 3 PX map rules, got {len(template)}")
    out = [
        MarketRulePin(
            sportsbook=r.sportsbook,
            rule_kind=r.rule_kind,
            source_key_type=r.source_key_type,
            source_key=r.source_key,
            action=r.action,
            canonical_market_type=r.canonical_market_type,
            league=LEAGUE,
            priority=r.priority,
            enabled=r.enabled,
            confidence=r.confidence,
            match_operator=r.match_operator,
            notes=NOTE,
        )
        for r in template
    ]
    if goalscorer:
        base = template[0]
        out += [
            MarketRulePin(
                sportsbook=PX,
                rule_kind=base.rule_kind,
                source_key_type=base.source_key_type,
                source_key=suffix,
                action="map",
                canonical_market_type=canonical,
                league=LEAGUE,
                priority=base.priority,
                enabled=True,
                confidence=base.confidence,
                match_operator="suffix",
                notes=NOTE,
            )
            for suffix, canonical in GOALSCORER_SUFFIXES
        ]
    return out


def build_payload(
    prod_leagues: list[LeagueRow],
    prod_rules: list[MarketRuleRow],
    env_leagues: list[LeagueRow],
    env_rules: list[MarketRuleRow],
    *,
    goalscorer: bool,
) -> MappingLeaguePayload | None:
    """The league payload, or None when the env already has all of it."""
    env_by = {r.league: r for r in env_leagues if not r.tombstone}
    prod_by = {r.league: r for r in prod_leagues if not r.tombstone}
    row = env_by.get(LEAGUE) or prod_by.get(LEAGUE)
    if row is None:
        raise RuntimeError(f"{LEAGUE}: not on the tip")
    have = {
        _rule_key(r.sportsbook, r.source_key_type, r.source_key)
        for r in env_rules if r.league == LEAGUE and not r.tombstone
    }
    rules = [
        r for r in wanted_rules(prod_rules, goalscorer=goalscorer)
        if _rule_key(r.sportsbook, r.source_key_type, r.source_key) not in have
    ]
    if LEAGUE in env_by and _px_settings_live(row) and not rules:
        return None
    settings = row.settings or {}
    return MappingLeaguePayload(
        league=LEAGUE,
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
        exchanges=exchanges_with_px(row),
        market_rules=rules,
        notes=NOTE,
        evidence_refs=[
            f"px:tournament:{TOURNAMENT_ID}",
            "px:event:90123170",
            f"optic:league:{row.optic_league_id}",
        ],
    )


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


def _plan(project: str, *, goalscorer: bool, allow_activate: bool = False):
    prod = _store(PROD)
    prod_leagues = prod.leagues_for(prod.current_rule_set_id or "")
    prod_rules = prod.market_rules_for(prod.current_rule_set_id or "")
    store = prod if project == PROD else _store(TEST, allow_activate=allow_activate)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payload = build_payload(
        prod_leagues, prod_rules,
        store.leagues_for(current), store.market_rules_for(current),
        goalscorer=goalscorer,
    )
    return store, current, payload


def submit_env(project: str, *, activate: bool, goalscorer: bool) -> dict[str, Any]:
    if activate and project != TEST:
        raise RuntimeError("--activate-test only applies to test")
    store, current, payload = _plan(project, goalscorer=goalscorer, allow_activate=activate)
    if payload is None:
        return {"project": project, "skipped": "PX already live", "rule_set_id": current}

    svc = ProposalService(store, require_maker_checker=False)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(leagues=[payload], acknowledge_shadow=True, note=NOTE),
    )
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(
        str(verified["preview_token"]), Actor(subject=ACTOR, role=ActorRole.PROPOSER))
    ref = str(card.get("ref") or "")
    result: dict[str, Any] = {
        "project": project,
        "rule_set_id": current,
        "market_rules": len(payload.market_rules),
        "warnings": verified.get("warnings"),
        "ref": ref,
        "review_url": _review_url(project, ref),
    }
    if activate:
        approved = svc.approve_review(ref, Actor(subject=ACTOR, role=ActorRole.APPROVER))
        after = _store(TEST)
        result["status"] = approved.get("status")
        result["activated_rule_set_id"] = after.current_rule_set_id
        result["px_live"] = any(
            r.league == LEAGUE and _px_settings_live(r)
            for r in after.leagues_for(after.current_rule_set_id or "")
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod"), default="test")
    parser.add_argument("--goalscorer", action="store_true",
                        help="also pin the To Score suffix rules (needs PLAYER_GOALS_YN deployed)")
    parser.add_argument(
        "--activate-test", action="store_true",
        help="test only: approve and activate the card as well",
    )
    args = parser.parse_args(argv)
    project = TEST if args.env == "test" else PROD

    if not args.submit:
        _, _, payload = _plan(project, goalscorer=args.goalscorer)
        print(json.dumps(payload.model_dump(mode="json") if payload else None, indent=2))
        print(f"{'1' if payload else '0'} league change for {args.env}; pass --submit to propose",
              file=sys.stderr)
        return 0

    print(json.dumps(
        submit_env(project, activate=args.activate_test, goalscorer=args.goalscorer),
        indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

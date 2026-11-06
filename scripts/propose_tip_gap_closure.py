#!/usr/bin/env python
"""Emit and optionally submit a control-plane batch that closes Phase 7b tip gaps.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in
``mappers/profiles/`` / ``mappers/vocab/``.

``tests/mappers/test_profile_equivalence.py`` measures where a tip-only
build still diverges from the Python registry. This script turns that
divergence into a ``batch_changes`` proposal for the normal
propose → validate → approve → activate flow.

    # Review only
    GCP_PROJECT=marketmaking-test python scripts/propose_tip_gap_closure.py \
        --out tip_gap_closure.json

    # Propose, validate, approve, and activate on test
    GCP_PROJECT=marketmaking-test python scripts/propose_tip_gap_closure.py \
        --submit --i-mean-it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import fields, is_dataclass
from typing import Any

from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.exchanges.crypto_soccer import TO_ADVANCE_PERIOD
from mappers.seed.league_meta import merge_league_meta_into_exchanges
from mappers.seed.sot import load_snapshot
from mappers.seed.tip_leagues import resolve_run_leagues

_BOOKS = ("PX", "CRYPTO", "POLYMARKET", "OPTIC", "NOVIG", "RUNSHOP")

_RELOCATED = {
    ("POLYMARKET", "team_name_aliases"),
}

_WORLD_CUP_CRYPTO_PATCH = {
    "extra_contract_types": {
        "To Lift The Cup": "to_advance",
        "To Win Bronze": "to_advance",
    },
    "contract_period_types": {
        "To Lift The Cup": TO_ADVANCE_PERIOD,
        "To Win Bronze": TO_ADVANCE_PERIOD,
    },
}
def _config_diff(left: Any, right: Any, book: str) -> list[str]:
    """Field names where two exchange configs disagree."""
    if left == right:
        return []
    if left is None or right is None or not is_dataclass(left):
        return ["<whole config>"]
    return [
        f.name
        for f in fields(left)
        if getattr(left, f.name) != getattr(right, f.name)
        and (book, f.name) not in _RELOCATED
    ]


def _row_settings(row: Any) -> dict[str, Any]:
    return dict(getattr(row, "settings", None) or {})


def _exchange_pins(
    row: Any,
    *,
    crypto_patch: dict[str, Any],
    novig_settings: dict[str, Any] | None = None,
    crypto_settings: dict[str, Any] | None = None,
) -> list[ExchangePin]:
    """Copy the tip row's exchanges, merging crypto settings patches."""
    pins: list[ExchangePin] = []
    for ex in getattr(row, "exchanges", None) or []:
        book = str(ex.get("sportsbook") or "")
        settings = dict(ex.get("settings") or {})
        if book == "crypto.com" and crypto_patch:
            settings.update(crypto_patch)
        pins.append(
            ExchangePin(
                sportsbook=book,
                enabled=bool(ex.get("enabled", True)),
                parser_profile=str(ex.get("parser_profile") or ""),
                source_league_id=ex.get("source_league_id"),
                settings=settings,
            ),
        )
    if novig_settings and not any(pin.sportsbook == "novig" for pin in pins):
        pins.append(
            ExchangePin(
                sportsbook="novig",
                enabled=True,
                parser_profile="novig_generic_v1",
                source_league_id=str(novig_settings.get("league") or ""),
                settings=novig_settings,
            ),
        )
    if crypto_settings and not any(pin.sportsbook == "crypto.com" for pin in pins):
        pins.append(
            ExchangePin(
                sportsbook="crypto.com",
                enabled=True,
                parser_profile="crypto_generic_v1",
                source_league_id=str(crypto_settings.get("league") or ""),
                settings=crypto_settings,
            ),
        )
    return pins


def _novig_pin_settings(left_cfg: Any) -> dict[str, Any]:
    """Map a Python NovigConfig onto tip exchange settings."""
    novig = getattr(left_cfg, "NOVIG", None)
    if novig is None:
        return {}
    league = str(getattr(novig, "league", "") or "").strip()
    return {"league": league} if league else {}


def _crypto_pin_settings(left_cfg: Any) -> dict[str, Any]:
    """Map a Python CryptoConfig onto tip exchange settings."""
    crypto = getattr(left_cfg, "CRYPTO", None)
    if crypto is None:
        return {}
    settings: dict[str, Any] = {
        "league": str(crypto.league),
        "sport_grouping": str(crypto.sport_grouping),
        "period_type": str(crypto.period_type),
    }
    if crypto.game_prop_period_type:
        settings["game_prop_period_type"] = str(crypto.game_prop_period_type)
    settings["game_prop_accept_round_periods"] = bool(
        getattr(crypto, "game_prop_accept_round_periods", False),
    )
    return settings


def _entity_alias_payloads() -> list[EntityAliasPayload]:
    """PX EPL pins that still diverge from the Python alias archive."""
    return [
        EntityAliasPayload(
            league="epl",
            canonical_key="MUF9",
            entity_type="team",
            aliases=[
                AliasPin(sportsbook="px", alias_kind="code", alias_value="MNU"),
            ],
            reassign=True,
        ),
        EntityAliasPayload(
            league="epl",
            canonical_key="SAU3",
            entity_type="team",
            aliases=[
                AliasPin(sportsbook="px", alias_kind="code", alias_value="SUN"),
            ],
        ),
    ]


def _runshop_pin_settings(left_cfg: Any) -> dict[str, Any]:
    """Map a Python RunshopConfig onto tip exchange settings."""
    rs = getattr(left_cfg, "RUNSHOP", None)
    if rs is None:
        return {}
    settings: dict[str, Any] = {"enabled": True}
    if rs.markets_path:
        settings["markets_path"] = str(rs.markets_path)
    if rs.crosswalk_path:
        settings["crosswalk_path"] = str(rs.crosswalk_path)
    return settings


def _ensure_runshop_exchange(
    pins: list[ExchangePin],
    *,
    settings: dict[str, Any],
) -> list[ExchangePin]:
    """Add a runshop exchange row when the Python module carries RUNSHOP."""
    if any(pin.sportsbook == "runshop" for pin in pins):
        return pins
    return [
        *pins,
        ExchangePin(
            sportsbook="runshop",
            enabled=True,
            parser_profile="runshop_generic_v1",
            settings=settings,
        ),
    ]


def _league_payload(
    row: Any,
    *,
    crypto_patch: dict[str, Any],
    runshop_enabled: bool | None,
    runshop_settings: dict[str, Any],
    league_settings_patch: dict[str, Any],
    novig_settings: dict[str, Any] | None = None,
    crypto_settings: dict[str, Any] | None = None,
) -> MappingLeaguePayload:
    """Build a mapping_league update from an existing tip row."""
    settings = _row_settings(row)
    if runshop_enabled is not None:
        settings["runshop_enabled"] = runshop_enabled
    settings.update(league_settings_patch)
    entity_type = settings.get("entity_type", "team")
    alias_enforcement = settings.get("alias_enforcement", "raise")
    if entity_type not in ("team", "player", "fighter"):
        entity_type = "team"
    if alias_enforcement not in ("raise", "warn"):
        alias_enforcement = "raise"
    pins = _exchange_pins(
        row,
        crypto_patch=crypto_patch,
        novig_settings=novig_settings or None,
        crypto_settings=crypto_settings or None,
    )
    if runshop_enabled:
        pins = _ensure_runshop_exchange(pins, settings=runshop_settings)
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
        notes="phase-7b tip gap closure",
    )


def build_proposal() -> BatchChangesPayload:
    """Return a ``batch_changes`` payload that closes measured tip gaps."""
    snap = load_snapshot()
    rows = list(snap.leagues)
    rules = list(snap.market_rules)
    python_leagues: dict[str, Any] = {}
    overlaid = resolve_run_leagues(python_leagues, rows, market_rules=rules)
    tip_only = resolve_run_leagues({}, rows, market_rules=rules)
    by_slug = {str(row.league): row for row in rows}

    league_payloads: list[MappingLeaguePayload] = []
    rule_groups: list[MappingMarketRulesPayload] = []

    for slug in sorted(python_leagues):
        left, right = overlaid.get(slug), tip_only.get(slug)
        row = by_slug.get(slug)
        if left is None or right is None or row is None:
            continue
        crypto_patch: dict[str, Any] = {}
        novig_settings: dict[str, Any] = {}
        crypto_settings: dict[str, Any] = {}
        runshop_needed = False
        runshop_settings: dict[str, Any] = {}
        pins: list[MarketRulePin] = []
        for book in _BOOKS:
            changed = _config_diff(
                getattr(left, book, None), getattr(right, book, None), book,
            )
            if book == "CRYPTO" and changed:
                if slug == "world_cup" and "contract_period_types" in changed:
                    crypto_patch.update(_WORLD_CUP_CRYPTO_PATCH)
                if "<whole config>" in changed:
                    crypto_settings = _crypto_pin_settings(left)
            if book == "NOVIG" and changed:
                novig_settings = _novig_pin_settings(left)
            if book == "RUNSHOP" and changed:
                runshop_needed = getattr(left, "RUNSHOP", None) is not None
                if runshop_needed:
                    runshop_settings = _runshop_pin_settings(left)

        if not (
            crypto_patch
            or novig_settings
            or crypto_settings
            or runshop_needed
            or pins
        ):
            continue
        league_payloads.append(
            _league_payload(
                row,
                crypto_patch=crypto_patch,
                runshop_enabled=runshop_needed,
                runshop_settings=runshop_settings,
                league_settings_patch={},
                novig_settings=novig_settings,
                crypto_settings=crypto_settings,
            ),
        )
        if pins:
            rule_groups.append(
                MappingMarketRulesPayload(league=slug, rules=pins),
            )

    return BatchChangesPayload(
        entity_aliases=_entity_alias_payloads(),
        leagues=league_payloads,
        market_rules=rule_groups,
    )


def _submit(payload: BatchChangesPayload) -> str:
    """Propose, validate, approve, and activate on the current GCP project."""
    from BigQuery.client import ro_client
    from mappers.control_plane.bq_store import BigQueryStore

    project = (os.environ.get("GCP_PROJECT") or "").strip()
    if not project:
        raise RuntimeError("GCP_PROJECT is required for --submit")
    environment = "test" if project == "marketmaking-test" else "prod"
    store = BigQueryStore(
        ro_client(),
        environment=environment,
        allow_activate=environment == "test",
    )
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError("no activated rule set in BigQuery")
    svc = ProposalService(store, require_maker_checker=False)
    proposer = Actor(subject="scripts/propose_tip_gap_closure", role=ActorRole.PROPOSER)
    approver = Actor(subject="control-plane-service", role=ActorRole.SERVICE)
    req = ProposeRequest(
        request_id=f"tip-gap-closure-{uuid.uuid4()}",
        expected_rule_set_id=current,
        artifact_type="batch_changes",
        summary=(
            f"Phase 7b tip gap closure: {len(payload.leagues)} leagues, "
            f"{sum(len(g.rules) for g in payload.market_rules)} market rules"
        ),
        evidence_refs=["scripts/propose_tip_gap_closure.py"],
        payload=payload,
    )
    prop = svc.propose(req, proposer)
    svc.validate(prop.proposal_id, proposer)
    out = svc.approve(prop.proposal_id, approver)
    activated = out.activated_rule_set_id or prop.candidate_rule_set_id
    if activated is None:
        raise RuntimeError("approve did not yield a candidate rule set")
    return activated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="write the artifact JSON here")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="propose, validate, approve, and activate on test BigQuery",
    )
    parser.add_argument(
        "--i-mean-it",
        action="store_true",
        help="required with --submit",
    )
    args = parser.parse_args(argv)

    payload = build_proposal()
    text = json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    print(
        f"\nleague patches : {len(payload.leagues)}"
        f"\nrule groups    : {len(payload.market_rules)}",
        file=sys.stderr,
    )
    if args.submit:
        if not args.i_mean_it:
            print("refusing --submit without --i-mean-it", file=sys.stderr)
            return 2
        activated = _submit(payload)
        print(f"activated rule_set_id={activated}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

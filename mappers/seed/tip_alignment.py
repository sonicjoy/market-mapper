"""Tip alignment: latest seed rule set vs the activated (served) tip.

Declarative dual-read compares Python ``LEAGUES`` to the *served* tip.
A leftover unactivated seed (CLI load, or a proposal that has not been
approved) would otherwise be invisible. This module emits
``tip_alignment_ok`` / ``tip_alignment_stale`` so that gap is visible.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from BigQuery.mapping_rule_rows import (
    AUDIT_EVENTS_TABLE,
    LEAGUES_TABLE,
    RULE_SETS_TABLE,
)
from mappers.seed.audit import git_commit_short

ACTIVATION_EVENT_TYPES = ("rule_set_activated", "rule_set_rolled_back")
MAX_MISSING_LEAGUES = 100

LeagueLayer = Sequence[tuple[str, bool]]


def activated_rule_set_id(
    client: bigquery.Client, *, environment: str,
) -> str | None:
    """Rule set the console serves, or None when never activated."""
    sql = f"""
    select rule_set_id from `{AUDIT_EVENTS_TABLE}`
    where environment = @environment
      and event_type in ('rule_set_activated', 'rule_set_rolled_back')
    order by occurred_at desc, event_id desc limit 1
    """  # nosec B608 — table name is a module constant
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("environment", "STRING", environment),
        ]
    )
    rows = list(client.query(sql, job_config=config).result())
    if not rows or not rows[0].rule_set_id:
        return None
    return str(rows[0].rule_set_id)


def rule_set_parents(
    client: bigquery.Client, *, environment: str,
) -> dict[str, str | None]:
    """rule_set_id -> parent_rule_set_id for one environment."""
    sql = f"""
    select rule_set_id, parent_rule_set_id from `{RULE_SETS_TABLE}`
    where environment = @environment
    """  # nosec B608
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("environment", "STRING", environment),
        ]
    )
    return {
        str(row.rule_set_id): (
            str(row.parent_rule_set_id) if row.parent_rule_set_id else None
        )
        for row in client.query(sql, job_config=config).result()
    }


def lineage_ids(
    parents: Mapping[str, str | None], rule_set_id: str,
) -> list[str]:
    """Tip -> root rule_set_id chain (COW layers, nearest first)."""
    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = rule_set_id
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = parents.get(cur)
    return chain


def coalesce_league_keys(layers: Sequence[LeagueLayer]) -> set[str]:
    """Enabled league keys from tip->root (league, tombstone) layers."""
    resolved: dict[str, bool] = {}
    for layer in layers:
        for league, tombstone in layer:
            resolved.setdefault(league, tombstone)
    return {league for league, tombstone in resolved.items() if not tombstone}


def league_keys_for(
    client: bigquery.Client,
    rule_set_id: str,
    *,
    parents: Mapping[str, str | None],
) -> set[str]:
    """Coalesced league keys for one rule set (walks its COW lineage)."""
    chain = lineage_ids(parents, rule_set_id)
    sql = f"""
    select rule_set_id, league, ifnull(tombstone, false) as tombstone
    from `{LEAGUES_TABLE}`
    where rule_set_id in unnest(@ids)
    """  # nosec B608
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", chain)]
    )
    by_layer: dict[str, list[tuple[str, bool]]] = {}
    for row in client.query(sql, job_config=config).result():
        key = str(row.rule_set_id)
        by_layer.setdefault(key, []).append(
            (str(row.league), bool(row.tombstone))
        )
    return coalesce_league_keys([by_layer.get(rid, []) for rid in chain])


def _alignment_payload(
    *,
    seed_rule_set_id: str,
    activated: str | None,
    served_rule_set_id: str,
    seed_leagues: set[str],
    served_leagues: set[str],
    missing: list[str],
    project: str,
) -> dict[str, Any]:
    """Payload describing seed vs served tip (mismatch_count = missing)."""
    return {
        "latest_seed_rule_set_id": seed_rule_set_id,
        "activated_rule_set_id": activated,
        "served_rule_set_id": served_rule_set_id,
        "seed_league_count": len(seed_leagues),
        "served_league_count": len(served_leagues),
        "missing_leagues": missing[:MAX_MISSING_LEAGUES],
        "missing_league_count": len(missing),
        "mismatch_count": len(missing),
        "mapper_git_commit": git_commit_short(),
        "project": project,
    }


def tip_alignment_event(
    *,
    seed_rule_set_id: str,
    activated: str | None,
    seed_leagues: set[str],
    served_leagues: set[str],
    mapping_run_id: str,
    project: str,
    environment: str,
) -> dict[str, Any]:
    """Audit row for served-tip alignment (OK heartbeat or stale)."""
    served_rule_set_id = activated or seed_rule_set_id
    missing = sorted(seed_leagues - served_leagues)
    aligned = served_rule_set_id == seed_rule_set_id and not missing
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "request_id": mapping_run_id,
        "event_type": "tip_alignment_ok" if aligned else "tip_alignment_stale",
        "occurred_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "rule_set_id": served_rule_set_id,
        "previous_rule_set_id": None,
        "expected_rule_set_id": seed_rule_set_id,
        "proposal_id": None,
        "mapping_run_id": mapping_run_id,
        "mapping_key_hash": None,
        "league": None,
        "sportsbook": None,
        "artifact_type": "rule_set",
        "artifact_id": served_rule_set_id,
        "actor_subject": None,
        "actor_role": "service",
        "status": "shadow",
        "reason_code": (
            "activated_tip_aligned" if aligned else "activated_tip_behind_seed"
        ),
        "payload": _alignment_payload(
            seed_rule_set_id=seed_rule_set_id,
            activated=activated,
            served_rule_set_id=served_rule_set_id,
            seed_leagues=seed_leagues,
            served_leagues=served_leagues,
            missing=missing,
            project=project,
        ),
    }


def check_tip_alignment(
    client: bigquery.Client,
    *,
    seed_rule_set_id: str,
    mapping_run_id: str,
    project: str,
    environment: str,
    served_rule_set_id: str | None = None,
) -> dict[str, Any]:
    """Resolve served vs seed tip and build the audit row."""
    activated = served_rule_set_id or activated_rule_set_id(
        client, environment=environment,
    )
    parents = rule_set_parents(client, environment=environment)
    seed_leagues = league_keys_for(client, seed_rule_set_id, parents=parents)
    served = activated or seed_rule_set_id
    served_leagues = (
        seed_leagues
        if served == seed_rule_set_id
        else league_keys_for(client, served, parents=parents)
    )
    return tip_alignment_event(
        seed_rule_set_id=seed_rule_set_id,
        activated=activated,
        seed_leagues=seed_leagues,
        served_leagues=served_leagues,
        mapping_run_id=mapping_run_id,
        project=project,
        environment=environment,
    )

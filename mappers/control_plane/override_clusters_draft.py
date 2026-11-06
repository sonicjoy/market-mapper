"""Draft + stage rule proposals for override clusters through the existing kernel.

Market rules go through ``draft_and_verify_market_rules`` with the cluster's Optic
market as the only live id, so the bind still has to survive the spine / unique
name gates, the overlay simulation and the dry-run: the overrides are evidence,
not a bypass. Aliases resolve the Optic selection to exactly one tip entity with
``names_fit`` (the same test harvest uses for an existing code owner), then pass
``verify_pins`` and the alias dry-run. Staging uses ``propose_gap_pins`` - verify
and submit to Proposed, never approve.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from mappers.canonical_codes import names_fit
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.dry_run import resolve_alias, thin_dry_run
from mappers.control_plane.entity_types import match_entity_type_for_league
from mappers.control_plane.gap_fix import propose_gap_pins
from mappers.control_plane.league_cfg_memo import league_cfg_memo
from mappers.control_plane.override_clusters import (
    DEFAULT_MIN_GAMES,
    SAMPLE_KEYS,
    OverrideCluster,
    cluster_overrides,
)
from mappers.control_plane.pin_flow import alias_from_pin, verify_pins
from mappers.control_plane.pin_flow_markets import MarketRuleObservation, draft_and_verify_market_rules
from mappers.control_plane.pipeline_gap_merge import OPEN_REVIEW_STATUSES
from mappers.control_plane.store import EntityRow

# ``note:`` keeps the marker on alias rows (Proposed drops non-source refs there).
EVIDENCE_PREFIX = "note:override_cluster:"
_CLUSTER_REF = re.compile(r"override_cluster:((?:market_rule|alias):[0-9a-f]{12})")
MAX_DRAFTED = 60
_PEOPLE = frozenset({"player", "fighter"})

RowsFn = Callable[[], list[dict[str, Any]]]


def _evidence(cluster: OverrideCluster) -> list[str]:
    """Cluster marker first (Proposed filters on it), then sample override keys."""
    samples = [f"{cluster.sportsbook}:override:{key.split('|', 1)[-1]}" for key in cluster.keys[:SAMPLE_KEYS]]
    return [f"{EVIDENCE_PREFIX}{cluster.cluster_id}", *samples]


def _verdict(status: str, detail: str = "", pins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"status": status, "detail": detail, "pins": pins or []}


def draft_market_rule(store: Any, cluster: OverrideCluster) -> dict[str, Any]:
    """Kernel draft for a market-shape cluster."""
    obs: MarketRuleObservation = {
        "league": cluster.league,
        "sportsbook": cluster.sportsbook,
        "source_key": cluster.source_key,
        "source_key_type": cluster.source_key_type,
        "demand": len(cluster.keys),
        "evidence_refs": _evidence(cluster),
        "live_optic_market_ids": {cluster.optic_market_id},
    }
    pins, skipped = draft_and_verify_market_rules(store, [obs])
    if pins:
        return _verdict("draftable", pins=pins)
    first = skipped[0] if skipped else {}
    return _verdict(str(first.get("reason") or "not_drafted"), str(first.get("detail") or ""))


def _league_entities(store: Any, league: str) -> list[EntityRow]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return []
    return [e for e in store.entities_for(rid) if not getattr(e, "tombstone", False)]


def _alias_target(
    entities: list[EntityRow], cluster: OverrideCluster, player: bool
) -> tuple[EntityRow | None, dict[str, Any] | None]:
    """The one tip entity the Optic selection names, or a verdict explaining why not."""
    fits = [
        e
        for e in entities
        if e.league == cluster.league
        and names_fit(e.canonical_name or e.canonical_key, cluster.selection, player=player)
    ]
    if not fits:
        return None, _verdict("no_tip_entity", f"no {cluster.league} entity fits {cluster.selection!r}")
    if len(fits) > 1:
        return None, _verdict("ambiguous_entity", ",".join(sorted(e.canonical_key for e in fits))[:200])
    return fits[0], None


def draft_alias(store: Any, cluster: OverrideCluster) -> dict[str, Any]:
    """Code alias onto the single tip entity the overrides keep pointing at."""
    entities = _league_entities(store, cluster.league)
    entity_type = match_entity_type_for_league(store, cluster.league)
    target, why = _alias_target(entities, cluster, entity_type in _PEOPLE)
    if target is None:
        return why or _verdict("no_tip_entity")
    owners = resolve_alias(
        entities, league=cluster.league, sportsbook=cluster.sportsbook, alias_kind="code", alias_value=cluster.code
    )
    if target.canonical_key in owners:
        return _verdict("already_live", target.canonical_key)
    if owners:
        return _verdict("code_owned_by_other", ",".join(owners))
    alias = {"sportsbook": cluster.sportsbook, "alias_kind": "code", "alias_value": cluster.code}
    pin = alias_payload(
        cluster.league,
        target.canonical_key,
        target.canonical_name or target.canonical_key,
        target.entity_type or entity_type,
        [alias],
        _evidence(cluster),
    )
    kept, blockers = verify_pins(store, [pin], probe=None)
    dry = thin_dry_run(entities, alias_from_pin(pin))
    blockers = blockers + [str(b) for b in (dry.get("blockers") or [])]
    if blockers or not kept:
        return _verdict("verify_blocked", "; ".join(blockers)[:200] or "no actionable pin")
    return _verdict("draftable", target.canonical_key, kept)


def draft_cluster(store: Any, cluster: OverrideCluster) -> dict[str, Any]:
    """Kernel verdict for one cluster (market rule or alias)."""
    if cluster.kind == "market_rule":
        return draft_market_rule(store, cluster)
    return draft_alias(store, cluster)


def _open_cluster_ids(service: Any) -> set[str]:
    """Cluster ids already carried by an open Proposed card."""
    out: set[str] = set()
    lister = getattr(service, "list_proposals", None)
    if lister is None:
        return out
    for proposal in lister():
        if proposal.status not in OPEN_REVIEW_STATUSES:
            continue
        blob = json.dumps(proposal.payload.model_dump(mode="json")) + json.dumps(proposal.evidence_refs)
        out.update(_CLUSTER_REF.findall(blob))
    return out


def list_override_patterns(
    service: Any,
    rows_fn: RowsFn,
    *,
    min_games: int = DEFAULT_MIN_GAMES,
    include_inactive: bool = False,
    kind: str | None = None,
) -> dict[str, Any]:
    """Clusters with a kernel verdict each (top ``MAX_DRAFTED``), plus unparsed counts."""
    store = getattr(service, "store", None)
    try:
        rows = rows_fn()
    except Exception as exc:  # noqa: BLE001 - surfaced on the page, not a 500
        return {"clusters": [], "unparsed": {}, "error": str(exc)}
    grouped = cluster_overrides(rows, store, min_games=min_games, include_inactive=include_inactive)
    clusters = [c for c in grouped["clusters"] if not kind or c.kind == kind]
    open_ids = _open_cluster_ids(service)
    out: list[dict[str, Any]] = []
    with league_cfg_memo():
        for index, cluster in enumerate(clusters):
            view = cluster.as_dict()
            verdict = draft_cluster(store, cluster) if index < MAX_DRAFTED else _verdict("not_evaluated")
            view["draft"] = {"status": verdict["status"], "detail": verdict["detail"]}
            view["proposed"] = cluster.cluster_id in open_ids
            out.append(view)
    return {"clusters": out, "unparsed": grouped["unparsed"], "error": None}


def stage_override_pattern(
    service: Any,
    actor: Any,
    cluster_id: str,
    rows_fn: RowsFn,
    *,
    acknowledge_shadow: bool = False,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Draft one cluster's rule and submit it to Proposed (human Approve only).

    ``acknowledge_shadow`` is the operator's Editor-style acknowledgement that the
    proposal writes the rules snapshot; without it submit returns the ack blocker.
    """
    store = getattr(service, "store", None)
    grouped = cluster_overrides(rows_fn(), store, min_games=1, include_inactive=include_inactive)
    cluster = next((c for c in grouped["clusters"] if c.cluster_id == cluster_id), None)
    if cluster is None:
        return {"ok": False, "error": f"unknown cluster {cluster_id}"}
    if cluster_id in _open_cluster_ids(service):
        return {"ok": False, "error": "already on Proposed", "cluster": cluster.as_dict()}
    with league_cfg_memo():
        verdict = draft_cluster(store, cluster)
    if verdict["status"] != "draftable":
        return {"ok": False, "error": verdict["status"], "detail": verdict["detail"], "cluster": cluster.as_dict()}
    note = f"Override pattern {cluster_id}: {len(cluster.keys)} overrides across {len(cluster.games)} fixtures"
    result = propose_gap_pins(service, actor, verdict["pins"], acknowledge_shadow=acknowledge_shadow, note=note)
    return {**result, "cluster": cluster.as_dict()}

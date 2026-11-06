"""Proposed mappings rail: unique rows + next fixtures per league."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.console_mapping_fixtures import (
    attach_next_fixtures,
    fixture_rows_from_optic,
    rail_fixtures_for_rows,
)
from mappers.control_plane.console_mapping_rows import mapping_rows_from_proposal, payload_as_batch
from mappers.control_plane.console_rfq_demand import (
    attach_rfq_demand,
    collect_gap_keys,
    fixture_ids_from,
    name_tokens_from,
    safe_rfq_demand,
)
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.control_plane.models import ProposalRecord
from mappers.control_plane.rows import MarketRuleRow

_OPEN = frozenset({"proposed", "validated"})


def _tip_league_map(store: Any) -> dict[str, Any]:
    rid = store.current_rule_set_id
    if not rid:
        return {}
    return {row.league: row for row in store.leagues_for(rid)}


def tip_market_rules(store: Any) -> list[MarketRuleRow]:
    """Activated-tip market_rules, or empty when the store has no tip."""
    rid = store.current_rule_set_id
    if not rid or not hasattr(store, "market_rules_for"):
        return []
    return list(store.market_rules_for(rid))


def _new_leagues(store: Any, payload: object) -> set[str]:
    batch = payload_as_batch(payload)
    if batch is None:
        return set()
    tip = {row.league for row in _tip_league_map(store).values()}
    return {lg.league for lg in batch.leagues if lg.league not in tip}


def _fixtures_for_leagues(
    store: Any,
    leagues: set[str],
    *,
    fetch_fn: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    tip = _tip_league_map(store)
    out: dict[str, list[dict[str, Any]]] = {}
    for slug in leagues:
        row = tip.get(slug)
        if row is None:
            out[slug] = []
            continue
        oid = str(getattr(row, "optic_league_id", "") or "").strip()
        if not oid:
            out[slug] = []
            continue
        horizon = optic_horizon_hours(row)
        raw = cached_optic_fixtures(oid, horizon_hours=horizon, fetch_fn=fetch_fn)
        out[slug] = fixture_rows_from_optic(raw)
    return out


def _collect_proposal_rows(
    proposals: list[ProposalRecord],
    store: Any,
    *,
    groups_by_id: dict[str, dict[str, Any] | None],
    tip: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    all_leagues: set[str] = set()
    tip_rules = tip_market_rules(store)
    for proposal in proposals:
        proposal_rows = mapping_rows_from_proposal(
            proposal,
            groups=groups_by_id.get(proposal.proposal_id),
            tip_leagues=tip,
            new_leagues=_new_leagues(store, proposal.payload),
            tip_market_rules=tip_rules,
        )
        for row in proposal_rows:
            row["proposal_ref"] = proposal.proposal_id
            rows.append(row)
            all_leagues.add(str(row.get("league") or ""))
    return rows, all_leagues


def _league_blocks(
    all_leagues: set[str],
    rows: list[dict[str, Any]],
    tip: dict[str, Any],
    fixtures_by_league: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for slug in sorted(all_leagues):
        if not slug:
            continue
        tip_row = tip.get(slug)
        league_rows = [r for r in rows if r.get("league") == slug]
        blocks.append(
            {
                "league": slug,
                "league_label": league_label(slug),
                "sport": str(getattr(tip_row, "sport", None) or league_rows[0].get("sport") or ""),
                "is_new": any(r.get("league_is_new") for r in league_rows),
                "fixtures": rail_fixtures_for_rows(
                    league_rows, fixtures_by_league.get(slug) or [],
                ),
                "rows": league_rows,
            }
        )
    return blocks


def proposed_leagues_view(
    store: Any,
    proposals: list[ProposalRecord],
    *,
    groups_by_id: dict[str, dict[str, Any] | None],
    fetch_fn: Any | None = None,
    demand_fn: Any | None = None,
) -> dict[str, Any]:
    """Build league-grouped proposed rows for the console rail."""
    tip = _tip_league_map(store)
    rows, all_leagues = _collect_proposal_rows(
        proposals, store, groups_by_id=groups_by_id, tip=tip,
    )
    fixtures_by_league = _fixtures_for_leagues(store, all_leagues, fetch_fn=fetch_fn)
    attach_next_fixtures(rows, fixtures_by_league)
    _stamp_rfq_demand(rows, fixtures_by_league, demand_fn)
    return {
        "count": len(rows),
        "leagues": _league_blocks(all_leagues, rows, tip, fixtures_by_league),
        "rows": rows,
    }


def _stamp_rfq_demand(
    rows: list[dict[str, Any]],
    fixtures_by_league: dict[str, list[dict[str, Any]]],
    demand_fn: Any | None,
) -> None:
    """Join live RFQ volume onto Proposed rows and rail fixtures."""
    fetch_demand = demand_fn or safe_rfq_demand
    attach_rfq_demand(
        rows,
        fixtures_by_league,
        fetch_demand(
            collect_gap_keys(rows),
            fixture_ids_from(fixtures_by_league),
            name_tokens_from(fixtures_by_league),
        ),
    )


def proposed_for_ref(
    store: Any,
    proposal: ProposalRecord,
    *,
    groups: dict[str, Any] | None,
    fetch_fn: Any | None = None,
    demand_fn: Any | None = None,
) -> dict[str, Any]:
    """Single-proposal slice for /review/:ref detail."""
    if proposal.status not in _OPEN:
        return {"count": 0, "leagues": [], "rows": []}
    view = proposed_leagues_view(
        store,
        [proposal],
        groups_by_id={proposal.proposal_id: groups},
        fetch_fn=fetch_fn,
        demand_fn=demand_fn,
    )
    view["proposal_ref"] = proposal.proposal_id
    return view

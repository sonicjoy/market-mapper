"""opticodds_mapping catalog lookup for the mapping console (Release 068 G5)."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from BigQuery.oom_winner_query import build_rfq_key_lookup_sql, rfq_key_lookup_job_config
from mappers.control_plane.console_sportsbook import sportsbook_lower


def _project() -> str:
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def _row_to_dict(row: Any) -> dict[str, Any]:
    payload = dict(row.items())
    source_ids = payload.get("source_ids")
    if source_ids is not None and not isinstance(source_ids, str):
        payload["source_ids"] = json.loads(json.dumps(source_ids, default=str))
    for key in ("start_date", "rank_run_at", "last_updated"):
        value = payload.get(key)
        if value is not None and hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


def _winner_from_candidates(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match live winner SQL: stamped row, or sole candidate with null is_rfq_winner."""
    in_window = [row for row in rows if row.get("in_rank_window") is True]
    for row in in_window:
        if row.get("is_rfq_winner") is True:
            return row
    if len(rows) == 1 and rows[0].get("is_rfq_winner") is None:
        return rows[0]
    if len(in_window) == 1 and in_window[0].get("is_rfq_winner") is None:
        return in_window[0]
    for row in rows:
        if row.get("is_rfq_winner") is True:
            return row
    return None


def _winner_in_rank_window(
    rows: list[dict[str, Any]],
    winner: dict[str, Any] | None,
) -> bool | None:
    if not rows:
        return None
    if winner is not None:
        flag = winner.get("in_rank_window")
        return flag is True
    return any(row.get("in_rank_window") is True for row in rows)


def _norm_source_id(value: str | None) -> str:
    return (value or "").casefold()


def _matching_candidates(
    candidates: list[dict[str, Any]],
    expected_source_market_id: str,
    expected_source_selection_id: str,
) -> list[dict[str, Any]]:
    expected_market = _norm_source_id(expected_source_market_id)
    expected_selection = _norm_source_id(expected_source_selection_id)
    return [
        row
        for row in candidates
        if _norm_source_id(row.get("src_market_id")) == expected_market
        and _norm_source_id(row.get("src_selection_id")) == expected_selection
    ]


def _materialisation_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold+rank only stamps rows explicitly inside the live rank window."""
    return [row for row in candidates if row.get("in_rank_window") is True]


_OUTSIDE_RANK_WINDOW = (
    "fixture outside live rank window (4h .. 14d); fold+rank will not restamp"
)

_LOOKUP_RECENCY_DAYS = 60
_LOOKUP_STALE_FALLBACK_DAYS = 365


def _resolved_source_ids(
    rows: list[dict[str, Any]],
    winner: dict[str, Any] | None,
    market_id: str,
    selection_id: str,
) -> tuple[str, str]:
    source = winner or (rows[0] if len(rows) == 1 else None)
    if source is None:
        return market_id, selection_id
    resolved_market = str(source.get("src_market_id") or market_id)
    resolved_selection = str(source.get("src_selection_id") or selection_id)
    return resolved_market, resolved_selection


def _lookup_note(
    *,
    rows: list[dict[str, Any]],
    winner: dict[str, Any] | None,
    in_rank_window: bool | None,
) -> str:
    if not rows:
        return "no opticodds_mapping row for this RFQ key yet"
    if in_rank_window is not True:
        if winner:
            return (
                "mapping row start_date is outside the live rank window (4h .. 14d); "
                "fold+rank will not restamp on this row; active publish still requires "
                "game_id in opticodds_fixtures within the rank window"
            )
        return (
            "candidates outside the live rank window (4h .. 14d); "
            "no stamped RFQ winner in window"
        )
    if winner and winner.get("is_rfq_winner") is True:
        rank_class = winner.get("rank_class") or "unknown"
        return f"stamped RFQ winner ({rank_class}) in live rank window"
    if len(rows) > 1:
        return f"{len(rows)} candidates in live rank window; no stamped RFQ winner yet"
    return "found mapping row in live rank window (not yet stamped as RFQ winner)"


def preflight_fixture_materialisation(
    client: bigquery.Client,
    project: str,
    game_id: str,
) -> str | None:
    """R13 preflight: fold+rank / lookup only see fixtures in the 4h .. 14d window."""
    gid = game_id.strip()
    if not gid:
        return "game_id is required for an active override"
    sql = f"""
        select start_date
        from `{project}.opticodds_us.opticodds_fixtures`
        where game_id = @game_id
          and start_date >= timestamp_sub(current_timestamp(), interval 4 hour)
          and start_date <= timestamp_add(current_timestamp(), interval 14 day)
        limit 1
    """  # nosec B608 — project from env
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("game_id", "STRING", gid)]
    )
    rows = list(ro_query(client, sql, job_config=job_config))
    if not rows:
        return (
            "no fixture in opticodds_fixtures for game_id in rank window "
            "(4h .. 14d); override will not materialise"
        )
    return None


def assess_materialisation(
    *,
    candidates: list[dict[str, Any]],
    expected_source_market_id: str,
    expected_source_selection_id: str,
    active: bool,
) -> str | None:
    """Return not-materialised reason after merge+rank, or None when satisfied."""
    all_matches = _matching_candidates(
        candidates,
        expected_source_market_id,
        expected_source_selection_id,
    )
    windowed = _materialisation_candidates(candidates)
    matches = _matching_candidates(
        windowed,
        expected_source_market_id,
        expected_source_selection_id,
    )
    winner = next((row for row in windowed if row.get("is_rfq_winner") is True), None)
    winner_match = (
        winner
        if winner
        and _norm_source_id(winner.get("src_market_id"))
        == _norm_source_id(expected_source_market_id)
        and _norm_source_id(winner.get("src_selection_id"))
        == _norm_source_id(expected_source_selection_id)
        else None
    )
    if active:
        if winner_match and winner_match.get("rank_class") == "override":
            return None
        if not matches:
            if all_matches:
                return f"override accepted but {_OUTSIDE_RANK_WINDOW}"
            return "no opticodds_mapping row for this RFQ key yet"
        return "override accepted; override winner not stamped yet"
    if not all_matches:
        return "no opticodds_mapping row for this RFQ key yet"
    if not matches:
        return f"deactivate accepted but {_OUTSIDE_RANK_WINDOW}"
    if winner_match and winner_match.get("rank_class") == "override":
        return "deactivate accepted; override still winning"
    return None


def _query_lookup_rows(
    client: bigquery.Client,
    *,
    project: str,
    sb_lower: str,
    market_id: str,
    selection_id: str,
    min_last_updated_days: int | None,
) -> list[dict[str, Any]]:
    sql = build_rfq_key_lookup_sql(project, min_last_updated_days=min_last_updated_days)
    job_config = rfq_key_lookup_job_config(
        sportsbook_lower=sb_lower,
        src_market_id=market_id,
        src_selection_id=selection_id,
    )
    return [_row_to_dict(row) for row in ro_query(client, sql, job_config=job_config)]


def _lookup_rows_with_recency_fallback(
    client: bigquery.Client,
    *,
    project: str,
    sb_lower: str,
    market_id: str,
    selection_id: str,
) -> list[dict[str, Any]]:
    rows = _query_lookup_rows(
        client,
        project=project,
        sb_lower=sb_lower,
        market_id=market_id,
        selection_id=selection_id,
        min_last_updated_days=_LOOKUP_RECENCY_DAYS,
    )
    if rows:
        return rows
    return _query_lookup_rows(
        client,
        project=project,
        sb_lower=sb_lower,
        market_id=market_id,
        selection_id=selection_id,
        min_last_updated_days=_LOOKUP_STALE_FALLBACK_DAYS,
    )


def lookup_rfq_key(
    client: bigquery.Client,
    *,
    sportsbook: str,
    source_market_id: str,
    source_selection_id: str,
    project: str | None = None,
) -> dict[str, Any]:
    """Return winner + all oom candidates for one RFQ key."""
    proj = project or _project()
    sb_lower = sportsbook_lower(sportsbook)
    market_id = (source_market_id or "").strip()
    selection_id = (source_selection_id or "").strip()
    rows = _lookup_rows_with_recency_fallback(
        client,
        project=proj,
        sb_lower=sb_lower,
        market_id=market_id,
        selection_id=selection_id,
    )
    winner = _winner_from_candidates(rows)
    in_rank_window = _winner_in_rank_window(rows, winner)
    lookup_note = _lookup_note(rows=rows, winner=winner, in_rank_window=in_rank_window)
    resolved_market_id, resolved_selection_id = _resolved_source_ids(
        rows,
        winner,
        market_id,
        selection_id,
    )
    return {
        "sportsbook": sb_lower,
        "source_market_id": market_id,
        "source_selection_id": selection_id,
        "resolved_source_market_id": resolved_market_id,
        "resolved_source_selection_id": resolved_selection_id,
        "rfq_key": f"{sb_lower}|{resolved_market_id}|{resolved_selection_id}",
        "winner": winner,
        "candidates": rows,
        "candidate_count": len(rows),
        "in_rank_window": in_rank_window,
        "lookup_note": lookup_note,
    }

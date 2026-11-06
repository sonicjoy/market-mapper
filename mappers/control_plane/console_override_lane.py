"""Console side of the override lane (``BigQuery/override_lane.py``).

crypto.com and Polymarket (USA) read ``markets_us.market_mapping``, not
``opticodds_mapping``. With ``MAPPING_OVERRIDE_LANE`` on, a console override for
them is keyed the way their consumer looks rows up, looked up and confirmed in
``market_mapping``, and lands at the next mapping pipeline run. With the flag
OFF nothing here changes the existing Catalog behaviour.

Venue keys:
  * crypto.com: ``source_ids = {"symbol": "<NX.F.OPT... FIX symbol>"}``;
  * Polymarket (USA): ``source_ids = {"market_id": "<instrument symbol>",
    "selection_id": "yes" | "no"}`` — ``yes`` = this Optic selection is the
    instrument's LONG side, ``no`` = its complement. Publish both sides of a
    two-way market: the lane replaces every mapper row of the symbol.
"""

from __future__ import annotations

import json
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from BigQuery.override_lane import CRYPTO, lane_sportsbooks
from mappers.control_plane.console_sportsbook import canonical_sportsbook

LANE_LATENCY_NOTE = (
    "Lands in markets_us.market_mapping at the next mapping pipeline run "
    "(cron every 15 min, plus the run itself); crypto.com then picks it up on its "
    "next 10-min mapping reload. Look it up again after that to confirm."
)
_CRYPTO_PREFIX = "NX.F.OPT."
_USA_SIDES = frozenset({"yes", "no"})

_LOOKUP_SQL = """
    select game_id, fixture_id, market_id, selection, selection_line, points, grouping_key,
           sport, league, start_date, side, market_match_method, mapping_audit_event_id,
           to_json_string(source_ids) as source_ids
    from `{project}.markets_us.market_mapping`
    where start_date >= timestamp_sub(current_timestamp(), interval 20 day)
      and sportsbook = @sportsbook
      and json_value(source_ids, '$.{field}') = @venue_key
    order by start_date desc, last_updated desc
    limit 20
"""


def lane_venue(sportsbook: str) -> bool:
    """True when the lane is on and ``sportsbook`` is one of its venues."""
    try:
        book = canonical_sportsbook(sportsbook)
    except ValueError:
        return False
    return book in lane_sportsbooks()


def lane_source_ids(sportsbook: str, source_market_id: str, source_selection_id: str) -> dict[str, str]:
    """Venue-shaped ``source_ids`` for a lane override; ValueError on a malformed key."""
    book = canonical_sportsbook(sportsbook)
    key = source_market_id.strip()
    if book == CRYPTO:
        if not key.startswith(_CRYPTO_PREFIX):
            raise ValueError(f"crypto.com override needs the FIX symbol ({_CRYPTO_PREFIX}...), got {key!r}")
        return {"symbol": key}
    side = source_selection_id.strip().lower()
    if not key or side not in _USA_SIDES:
        raise ValueError("Polymarket (USA) override needs the instrument symbol and selection id 'yes' or 'no'")
    return {"market_id": key, "selection_id": side}


def reshape_message(
    message: dict[str, Any], sportsbook: str, source_market_id: str, source_selection_id: str
) -> dict[str, Any]:
    """Swap the ticker-shaped ``source_ids`` for the lane venue's key (no-op off-lane)."""
    if not lane_venue(sportsbook):
        return message
    shaped = lane_source_ids(sportsbook, source_market_id, source_selection_id)
    return {**message, "source_ids": json.dumps(shaped)}


def _winner(rows: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
    """Current row the venue serves: the only row, or (Poly USA) the one for the side."""
    if len(rows) == 1:
        return rows[0]
    for row in rows:
        src = json.loads(row.get("source_ids") or "{}")
        if side and str(src.get("selection_id") or "").lower() == side:
            return row
    return None


def lookup_lane_key(
    client: bigquery.Client,
    *,
    sportsbook: str,
    source_market_id: str,
    source_selection_id: str,
    project: str,
) -> dict[str, Any]:
    """``lookup_rfq_key``-shaped answer read from ``market_mapping`` for a lane venue."""
    book = canonical_sportsbook(sportsbook)
    key, side = source_market_id.strip(), source_selection_id.strip().lower()
    field = "symbol" if book == CRYPTO else "market_id"
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sportsbook", "STRING", book),
            bigquery.ScalarQueryParameter("venue_key", "STRING", key),
        ]
    )
    sql = _LOOKUP_SQL.format(project=project, field=field)  # nosec B608 — project from env, field fixed
    rows = [_plain(dict(row.items())) for row in ro_query(client, sql, job_config=config)]
    note = f"{len(rows)} market_mapping row(s) for this key. " if rows else "no market_mapping row for this key yet. "
    return {
        "sportsbook": book.lower(),
        "source_market_id": key,
        "source_selection_id": side,
        "resolved_source_market_id": key,
        "resolved_source_selection_id": side,
        "rfq_key": f"{book.lower()}|{key}|{side}",
        "winner": _winner(rows, side),
        "candidates": rows,
        "candidate_count": len(rows),
        "in_rank_window": True if rows else None,
        "lookup_note": note + LANE_LATENCY_NOTE,
        "table": "markets_us.market_mapping",
    }


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe row (timestamps as ISO); flags whether the served row is an override."""
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
    out["is_mapping_override"] = out.get("market_match_method") == "override"
    return out


def lane_job_outcome(active: bool) -> tuple[str, str]:
    """(status, message) for a lane job once the sink holds the message."""
    verb = "publish" if active else "deactivate"
    return "accepted_not_materialised", f"override {verb} accepted for the market_mapping lane. {LANE_LATENCY_NOTE}"

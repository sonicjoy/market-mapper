"""BigQuery fetch for RFQ gap inventory (kept out of gap_inventory for size guard)."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.gap_inventory import (
    CLOSE_MAX_DAYS,
    INVENTORY_PAGE,
    RfqGapItem,
    _inventory_meta,
    rank_rfq_gaps,
)
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL


def _terminal_exclude(
    store: Any,
    proj: str,
    tip: str | None,
    exclude: set[tuple[str, str]],
    terminal_query_fn: Any | None,
    fail_closed: bool,
) -> set[tuple[str, str]]:
    from mappers.control_plane.gap_ledger import (
        GapLedgerQueryError,
        gap_ledger_enabled,
        load_terminal_keys,
    )

    if exclude or not tip or not gap_ledger_enabled():
        return exclude
    try:
        return load_terminal_keys(
            tip,
            project=proj,
            query_fn=terminal_query_fn,
            fail_closed=fail_closed,
        )
    except GapLedgerQueryError:
        raise


def _run_inventory_sql(sql: str, proj: str, query_fn: Any | None) -> list[Any]:
    if query_fn is not None:
        return list(query_fn(sql))
    return list(ro_query(bigquery.Client(project=proj), sql))


def fetch_rfq_inventory_bq(
    store: Any,
    *,
    project: str | None = None,
    limit: int = INVENTORY_PAGE,
    query_fn: Any | None = None,
    exclude_keys: set[tuple[str, str]] | None = None,
    terminal_query_fn: Any | None = None,
    fail_closed_ledger: bool = False,
) -> list[RfqGapItem]:
    """Top RFQ true gaps: close (high demand first), then demanding, then rest."""
    from mappers.control_plane.gap_ledger import gap_ledger_enabled, ledger_inventory_sql_suffix

    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    tip = getattr(store, "current_rule_set_id", None)
    use_ledger = bool(tip and gap_ledger_enabled())
    exclude = set(exclude_keys or ())
    if not use_ledger:
        exclude = _terminal_exclude(
            store,
            proj,
            str(tip) if tip else None,
            exclude,
            terminal_query_fn,
            fail_closed_ledger,
        )
    ledger_cte, ledger_pred = ledger_inventory_sql_suffix(project=proj, enabled=use_ledger)
    page = max(limit, INVENTORY_PAGE)
    sql = RFQ_INVENTORY_SQL.format(
        project=proj,
        limit=page,
        close_days=CLOSE_MAX_DAYS,
        ledger_cte=ledger_cte,
        ledger_exclude_predicate=ledger_pred,
    )
    raw = _run_inventory_sql(sql, proj, query_fn)
    rows = [
        (
            str(getattr(r, "book", "") or ""),
            str(getattr(r, "key", "") or ""),
            int(getattr(r, "demand", 0) or 0),
            _inventory_meta(r),
        )
        for r in raw
        if (str(getattr(r, "book", "") or ""), str(getattr(r, "key", "") or "")) not in exclude
    ]
    return rank_rfq_gaps(rows, limit=page)

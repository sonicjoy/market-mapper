"""Per-tick gap harvest outcomes (optional BQ ``mapping_gap_ledger``)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from BigQuery.alerts import bool_env
from BigQuery.client import is_missing_bq_table
from mappers.control_plane.gap_fix_walk import WALK_WITHOUT_OUTCOME, pin_harvest_pairs
from mappers.control_plane.gap_inventory import RfqGapItem

logger = logging.getLogger(__name__)

LEDGER_TABLE = "markets_us.mapping_gap_ledger"
LEAGUE_REOPEN_OUTCOME = "league_reopen"
# Kickoff beyond the Optic horizon: excluded for HORIZON_WAIT_HOURS, then re-inventoried.
HORIZON_OUTCOME = "horizon_wait"
HORIZON_WAIT_HOURS = 24
_HORIZON_REASONS = frozenset({"outside_horizon", "horizon_wait"})
_REOPEN_BOOK = "_reopen"
_REOPEN_KEY = "_reopen"


class GapLedgerQueryError(RuntimeError):
    """Ledger terminal-key read failed (fail-closed callers must not assume idle)."""


@dataclass(frozen=True)
class GapOutcome:
    book: str
    key: str
    demand: int
    outcome: str
    reason: str = ""
    league_token: str = ""


def gap_ledger_enabled() -> bool:
    return bool_env("MAPPING_GAP_LEDGER", default=True)


def build_outcomes(
    inventory: list[RfqGapItem],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    *,
    walked_keys: set[tuple[str, str]] | None = None,
    league_for: Any | None = None,
) -> list[GapOutcome]:
    """Classify each inventoried key after one harvest tick."""
    pinned = _pinned_keys(pins)
    skip_by = _skip_index(skipped)
    walked = walked_keys or set()
    return [
        _outcome_for(item, pinned, skip_by, walked, league_for)
        for item in inventory
    ]


def _outcome_for(
    item: RfqGapItem,
    pinned: set[tuple[str, str]],
    skip_by: dict[tuple[str, str], str],
    walked: set[tuple[str, str]],
    league_for: Any | None,
) -> GapOutcome:
    ident = (item.book, item.key)
    league_token = str(league_for(item)).strip() if league_for is not None else ""
    if ident in pinned:
        return GapOutcome(item.book, item.key, item.demand, "pinned", league_token=league_token)
    reason = skip_by.get(ident, "")
    if reason in {"already_mapped", "maker_lag"}:
        return GapOutcome(item.book, item.key, item.demand, "maker_lag", reason, league_token)
    if reason in {"league_not_wired", "needs_league", "league_miss", "no_source_league"}:
        return GapOutcome(item.book, item.key, item.demand, "needs_league", reason, league_token)
    if reason == "needs_probe":
        return GapOutcome(item.book, item.key, item.demand, "needs_probe", reason, league_token)
    if reason == "needs_code":
        return GapOutcome(item.book, item.key, item.demand, "needs_code", reason, league_token)
    if reason in _HORIZON_REASONS:
        return GapOutcome(item.book, item.key, item.demand, HORIZON_OUTCOME, reason, league_token)
    if reason:
        tier = "expected_residual" if _residual(reason) else "skipped"
        return GapOutcome(item.book, item.key, item.demand, tier, reason, league_token)
    if ident not in walked:
        return GapOutcome(item.book, item.key, item.demand, "not_walked", league_token=league_token)
    logger.warning(
        "gap ledger walked key without skip reason book=%s key=%s",
        item.book,
        item.key[:80],
    )
    return GapOutcome(item.book, item.key, item.demand, "skipped", WALK_WITHOUT_OUTCOME, league_token)


def write_ledger(
    outcomes: list[GapOutcome],
    *,
    tip_rule_set_id: str | None,
    proposal_id: str | None = None,
    project: str | None = None,
) -> None:
    """Insert rows; no-op when disabled or table missing."""
    if not gap_ledger_enabled() or not outcomes:
        return
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    now = datetime.now(tz=UTC)
    rows = [
        {
            "run_at": now.isoformat(),
            "tip_rule_set_id": tip_rule_set_id,
            "book": o.book,
            "key": o.key,
            "demand": o.demand,
            "outcome": o.outcome,
            "reason": o.reason or None,
            "league_token": o.league_token or None,
            "proposal_id": proposal_id,
        }
        for o in outcomes
    ]
    try:
        client = bigquery.Client(project=proj)
    except Exception:  # noqa: BLE001 — offline pytest / missing ADC
        logger.info("gap ledger client unavailable; skipping write")
        return
    table = f"{proj}.{LEDGER_TABLE}"
    try:
        errors = client.insert_rows_json(table, rows)
        if errors:
            logger.warning("gap ledger insert errors: %s", errors[:3])
    except Exception as exc:  # noqa: BLE001
        if is_missing_bq_table(exc, LEDGER_TABLE):
            logger.info("gap ledger table missing; skipping write (%s)", LEDGER_TABLE)
            return
        logger.warning("gap ledger write failed: %s", exc)


def write_league_reopen(
    tip_rule_set_id: str | None,
    leagues: set[str],
    *,
    project: str | None = None,
) -> None:
    """Mark leagues reopened on a new tip so prior terminal rows stop blocking harvest."""
    cleaned = {str(league).strip() for league in leagues if str(league).strip()}
    if not cleaned or not tip_rule_set_id or not gap_ledger_enabled():
        return
    outcomes = [
        GapOutcome(_REOPEN_BOOK, _REOPEN_KEY, 0, LEAGUE_REOPEN_OUTCOME, league_token=league)
        for league in sorted(cleaned)
    ]
    write_ledger(outcomes, tip_rule_set_id=tip_rule_set_id, project=project)


def summarize_outcomes(outcomes: list[GapOutcome]) -> str:
    """One-line Slack summary."""
    if not outcomes:
        return "gap ledger: no inventory keys"
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.outcome] = counts.get(o.outcome, 0) + 1
    parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    unexplained = [o for o in outcomes if o.outcome in {"skipped", "not_walked"} and not o.reason]
    head = ", ".join(parts)
    if unexplained:
        top = sorted(unexplained, key=lambda x: -x.demand)[:3]
        keys = "; ".join(f"{o.book}:{o.key[:40]}({o.demand})" for o in top)
        return f"{head} | unexplained: {keys}"
    return head


def _pinned_keys(pins: list[dict[str, Any]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for pin in pins:
        out.update(pin_harvest_pairs(pin))
    return out


def _skip_index(skipped: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for row in skipped:
        book = str(row.get("book") or "").strip()
        key = str(row.get("key") or row.get("event_ticker") or row.get("symbol") or "")
        reason = str(row.get("reason") or row.get("kind") or "")
        if book and key:
            out[(book, key)] = reason
    return out


def _residual(reason: str) -> bool:
    return reason in {
        "missing_optic",
        "prop_supply",
        "title_miss",
        "out_of_scope",
        "stamp_residual",
        "prefix_satisfied",
        "tournament_future",
        "catalogue_miss",
        "completed_stale",
        "expected_residual",
    }


TERMINAL_OUTCOMES = frozenset({
    "pinned",
    "maker_lag",
    "expected_residual",
    "needs_code",
    "needs_league",
    "needs_probe",
    "skipped",
})


_LEDGER_LATEST_CTE = """
ledger_latest as (
  select book, key, outcome, league_token, run_at
  from `{project}.{table}`
  qualify row_number() over (
    partition by book, key order by run_at desc
  ) = 1
),
ledger_reopen as (
  select league_token, max(run_at) as reopened_at
  from `{project}.{table}`
  where outcome = '{reopen_outcome}'
    and league_token is not null
    and league_token != ''
  group by league_token
),
-- A reopen lifts only rows written before it; the next walk of that key is ignored again.
ledger_exclude as (
  select l.book, l.key
  from ledger_latest l
  left join ledger_reopen r
    on r.league_token = l.league_token
   and r.reopened_at > l.run_at
  where (
      l.outcome in ({outcomes})
      or (
        l.outcome = '{horizon_outcome}'
        and l.run_at > timestamp_sub(current_timestamp(), interval {horizon_hours} hour)
      )
    )
    and r.league_token is null
)
"""

_LEDGER_TERMINAL_SQL = """
with {latest_cte}
select book, key
from ledger_exclude
where book not in ('{_reopen_book}')
  and key not in ('{_reopen_key}')
"""


def _latest_cte(project: str) -> str:
    """ledger_exclude: terminal keys, plus horizon waits younger than the wait window."""
    return _LEDGER_LATEST_CTE.format(
        project=project,
        table=LEDGER_TABLE,
        outcomes=", ".join(f"'{o}'" for o in sorted(TERMINAL_OUTCOMES)),
        reopen_outcome=LEAGUE_REOPEN_OUTCOME,
        horizon_outcome=HORIZON_OUTCOME,
        horizon_hours=HORIZON_WAIT_HOURS,
    )


def ledger_inventory_sql_suffix(
    *,
    project: str,
    enabled: bool,
) -> tuple[str, str]:
    """Extra CTE + WHERE suffix for RFQ inventory anti-join against the ledger."""
    if not enabled:
        return "", ""
    cte = ",\n" + _latest_cte(project)
    predicate = (
        "and not exists ("
        "select 1 from ledger_exclude le "
        "where le.book = inventory_rows.book and le.key = inventory_rows.key)"
    )
    return cte, predicate


def load_terminal_keys(
    tip_rule_set_id: str | None,
    *,
    project: str | None = None,
    query_fn: Any | None = None,
    fail_closed: bool = False,
) -> set[tuple[str, str]]:
    """Latest ledger row per key when outcome is terminal (respects league reopen)."""
    if not tip_rule_set_id or not gap_ledger_enabled():
        return set()
    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = _LEDGER_TERMINAL_SQL.format(
        latest_cte=_latest_cte(proj),
        _reopen_book=_REOPEN_BOOK,
        _reopen_key=_REOPEN_KEY,
    )
    try:
        runner = query_fn or (lambda text: bigquery.Client(project=proj).query(text).result())
        rows = list(runner(sql))
    except Exception as exc:  # noqa: BLE001
        if is_missing_bq_table(exc, LEDGER_TABLE):
            logger.info("gap ledger table missing; no terminal keys (%s)", LEDGER_TABLE)
            return set()
        logger.warning("gap ledger terminal keys query failed: %s", exc)
        if fail_closed:
            raise GapLedgerQueryError(str(exc)) from exc
        return set()
    out: set[tuple[str, str]] = set()
    for row in rows:
        book = str(getattr(row, "book", "") or "").strip()
        key = str(getattr(row, "key", "") or "").strip()
        if book and key:
            out.add((book, key))
    return out

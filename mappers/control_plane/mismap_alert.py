"""Hourly alert for high-risk mappings that are being served (mmmapper#23).

    python -m mappers.control_plane.mismap_alert

Scores live mappings with the Mapping risk scorer, keeps rows that are ``high`` tier,
currently served (``is_rfq_winner``) and carry no operator flag (open or resolved: a
flagged mapping is already being handled), drops any alerted in the last
``REALERT_HOURS``, and raises the rest:

* Slack via the shared ``application-alerts`` relay (``BigQuery/alerts.py``; route with
  ``ALERT_SLACK_CHANNEL``, e.g. ``#marketmaking-mapping-alerts``) as ONE rollup message;
* the central alert engine (``mismap_alert_engine``), one alert per mapping, when
  ``MAPPING_ALERT_ENGINE_URL`` is set.

Dedupe lives in the console work-item inbox (``markets_us.mapping_work_items``): one row
per run, ``source = "mismap_alert"``, listing the fingerprints it alerted. One append per
run, however many mappings. Off unless ``MAPPING_MISMAP_ALERT=1``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from BigQuery.alerts import AlertPublisher, build_gap_propose_publisher
from BigQuery.client import ro_client
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.console_mismap import MismapQueryFn, flags_by_fingerprint, score_live_mappings
from mappers.control_plane.mismap_alert_engine import EngineAlertSink, build_engine_sink
from mappers.control_plane.settings import get_settings
from mappers.control_plane.store import WorkItemRow, new_id

logger = logging.getLogger(__name__)

ALERT_ENV = "MAPPING_MISMAP_ALERT"
ALERT_SOURCE = "mismap_alert"
REALERT_HOURS = 24
TOP_ROWS = 15
_PROD_CONSOLE = "https://mapping.mm.whiteswandata.com"
_TEST_CONSOLE = "https://mapping.mm-test.whiteswandata.com"


def alert_enabled() -> bool:
    """True when ``MAPPING_MISMAP_ALERT`` is 1/true/yes/on."""
    return os.getenv(ALERT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def risk_url(environment: str) -> str:
    """Mapping risk page filtered to the high tier (test vs prod host)."""
    default = _TEST_CONSOLE if environment == "test" else _PROD_CONSOLE
    root = (os.environ.get("MAPPING_CONSOLE_URL") or default).rstrip("/")
    return f"{root}/mapping-risk?tier=high"


def recently_alerted(store: Any, now: datetime, hours: int = REALERT_HOURS) -> set[str]:
    """Fingerprints any alert run recorded inside the re-alert window."""
    cutoff = (now - timedelta(hours=hours)).isoformat()
    out: set[str] = set()
    for item in store.list_work_items():
        if item.source == ALERT_SOURCE and (item.updated_at or "") >= cutoff:
            out.update((item.request_extraction or {}).get("fingerprints") or [])
    return out


def select_new(scored: list[dict[str, Any]], flags: dict[str, Any], alerted: set[str]) -> list[dict[str, Any]]:
    """High tier, served, unflagged, not alerted in the window; soonest kickoff first."""
    rows = [
        r
        for r in scored
        if r.get("tier") == "high"
        and r.get("is_rfq_winner")
        and r["fingerprint"] not in flags
        and r["fingerprint"] not in alerted
    ]
    return sorted(rows, key=lambda r: r.get("start_date") or "9999")


def _row_line(row: dict[str, Any]) -> str:
    """One Slack line: venue, fixture/market/selection, reasons."""
    reasons = ", ".join(s.get("code") or "" for s in row.get("signals") or [])
    venue = row.get("book") or row.get("sb")
    what = f"{row.get('league') or '?'} {row.get('market_id')} / {row.get('selection')}"
    return f"- {venue}: {what} (venue {row.get('src_key')}) - {reasons}"


def slack_text(rows: list[dict[str, Any]], *, link: str) -> str:
    """Rollup: count by venue, the first ``TOP_ROWS`` rows, and the page link."""
    by_venue = Counter(r.get("book") or r.get("sb") for r in rows)
    counts = ", ".join(f"{venue} {n}" for venue, n in by_venue.most_common())
    lines = [f"Mapping risk: {len(rows)} new high-risk mapping(s) being quoted ({counts})."]
    lines += [_row_line(r) for r in rows[:TOP_ROWS]]
    if len(rows) > TOP_ROWS:
        lines.append(f"... and {len(rows) - TOP_ROWS} more.")
    lines.append(f"Review and flag: {link}")
    return "\n".join(lines)


def record_alerted(store: Any, rows: list[dict[str, Any]], now: datetime) -> None:
    """One work item for this run listing what it alerted (the dedupe memory)."""
    stamp = now.isoformat()
    store.put_work_item(
        WorkItemRow(
            work_item_id=new_id("mismapalert"),
            fingerprint=f"{ALERT_SOURCE}|{stamp}",
            source=ALERT_SOURCE,
            status="sent",
            severity="high",
            request_extraction={"fingerprints": [r["fingerprint"] for r in rows]},
            occurrence_count=len(rows),
            summary=f"{len(rows)} high-risk served mapping(s) alerted",
            created_at=stamp,
            updated_at=stamp,
        )
    )


def run_alert(
    *,
    store: Any,
    publisher: AlertPublisher,
    engine: EngineAlertSink,
    environment: str,
    query_fn: MismapQueryFn | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One pass: score, select, post Slack for NEW rows, reinforce every current row in the engine."""
    at = now or datetime.now(UTC)
    scored = score_live_mappings(query_fn, at)
    flags = flags_by_fingerprint(store)
    current = select_new(scored, flags, set())
    alerted = recently_alerted(store, at)
    fresh = [r for r in current if r["fingerprint"] not in alerted]
    link = risk_url(environment)
    # The engine drops alerts not reinforced for 6h, so every current row is posted each run.
    accepted = engine.raise_alerts(current, link=link)
    if not fresh:
        return {"new": 0, "slack": None, "engine": accepted}
    message_id = publisher.publish("warning", slack_text(fresh, link=link))
    record_alerted(store, fresh, at)
    return {"new": len(fresh), "slack": message_id, "engine": accepted}


def build_store() -> tuple[BigQueryStore, str]:
    """BigQuery-backed store for the work-item inbox (no activate)."""
    settings = get_settings()
    store = BigQueryStore(
        ro_client(),
        environment=settings.environment,
        allow_activate=False,
        cow_enabled=settings.cow_enabled,
        tip_ttl_sec=0.0,
    )
    return store, settings.environment


def main(argv: list[str] | None = None) -> int:
    """0 when disabled or done; 1 when the pass crashed."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argparse.ArgumentParser(prog="mismap_alert", description="Hourly alert for high-risk served mappings.").parse_args(
        argv
    )
    if not alert_enabled():
        logger.info("mismap alert disabled (%s unset)", ALERT_ENV)
        return 0
    publisher = build_gap_propose_publisher()
    try:
        store, environment = build_store()
        result = run_alert(store=store, publisher=publisher, engine=build_engine_sink(), environment=environment)
        logger.info("mismap alert done %s", result)
        return 0
    except Exception:
        logger.exception("mismap alert failed")
        return 1
    finally:
        publisher.close()


if __name__ == "__main__":
    sys.exit(main())

"""Slack alert for new Optic passthrough cross-check disagreements."""

from __future__ import annotations

import json
import os
from pathlib import Path

from BigQuery.alerts import AlertPublisher, build_publisher
from BigQuery.exchange_fetch_snapshot import fetch_time_from_dir
from mappers.exchanges.optic_passthrough_crosscheck import TWO_WAY_NO, CrosscheckLedger

_STATE_FILE = "optic_crosscheck_alert_state.json"


def enrich_ledger_blocks(ledger: CrosscheckLedger) -> list[dict[str, str]]:
    """Disagreements that already carry the fold ``rfq_key``."""
    return [row for row in ledger.disagreements if row.get("rfq_key")]


def _state_path(data_dir: Path) -> Path:
    """Beside the run dirs when ``data_dir`` is a cron run (``<root>/<date>/<HH_MM>``).

    Inside the per-run dir the next run never read it, so every run alerted
    every disagreement as new.
    """
    try:
        fetch_time_from_dir(data_dir)
    except ValueError:
        return data_dir / _STATE_FILE
    return data_dir.parent.parent / _STATE_FILE


def _load_seen(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("seen_disagree") or [])


def _save_seen(path: Path, seen: set[str]) -> None:
    path.write_text(
        json.dumps({"seen_disagree": sorted(seen)}, indent=2),
        encoding="utf-8",
    )


def _alert_text(fresh: list[dict[str, str]]) -> str:
    """One line per disagreement (first 25), with the strip reason when known."""
    lines = [
        f"Optic passthrough cross-check: {len(fresh)} new disagreement(s)",
        "",
    ]
    for row in fresh[:25]:
        why = f" [{row['detail']}]" if row.get("detail") else ""
        lines.append(
            f"• {row['sportsbook']} [{row['league']}] token {row['token']}{why} "
            f"ours {row['our_row_key'] or '(none)'} vs optic {row['optic_row_key']}",
        )
    if len(fresh) > 25:
        lines.append(f"… and {len(fresh) - 25} more")
    unverified = int(os.getenv("OPTIC_CROSSCHECK_UNVERIFIED_BOOKS", "0") or 0)
    if unverified:
        lines.append("")
        lines.append(
            f"SX Bet / DraftKings passthrough: {unverified} id(s) unverified (no matcher — kept, not cross-checked)",
        )
    return "\n".join(lines)


def publish_new_disagreements(
    ledger: CrosscheckLedger,
    *,
    data_dir: Path | None,
    publisher: AlertPublisher | None = None,
) -> None:
    """Alert disagreements the prior mapper run did not already report.

    ``TWO_WAY_NO`` strips are left out: the complement pass stamps that NO
    side back from our own YES row. The state is rewritten on every routable
    run, so a disagreement that clears and comes back alerts again.
    """
    pub = publisher or build_publisher()
    if not pub.routable:
        return
    alertable = {
        f"{d['sportsbook']}|{d['token']}": d
        for d in ledger.disagreements
        if d.get("token") and d.get("detail") != TWO_WAY_NO
    }
    state_file = _state_path(data_dir) if data_dir else None
    prior = _load_seen(state_file) if state_file else set()
    fresh = [d for fp, d in alertable.items() if fp not in prior]
    if fresh:
        pub.publish("warning", _alert_text(fresh))
    if state_file is not None:
        _save_seen(state_file, set(alertable))

"""Coverage gap alerts must stay off the mapper VM.

Kalshi and Polymarket checks used to run in post_load on every */15 tick.
The crypto.com check used to bill ~50 TiB/day there, then ~0.23 TiB/day on
its own 2-hour cron. gap-propose drafts those repairs. Putting any of the
three scans back into run_pipeline.sh, run_single_league.sh, or crontab
restores the bill with no change in mapping output.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CRONTAB = _REPO / "infra" / "crontab"
_RUN_PIPELINE = _REPO / "infra" / "run_pipeline.sh"
_RUN_SINGLE = _REPO / "infra" / "run_single_league.sh"

_FORBIDDEN = (
    "BigQuery.kalshi_gap_check",
    "BigQuery.polymarket_gap_check",
    "BigQuery.crypto_gap_check",
    "cron_crypto_gap_check.sh",
    "run_crypto_gap_check.sh",
)


def _command_lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_mapper_vm_does_not_run_coverage_gap_checks():
    bodies = (
        _command_lines(_RUN_PIPELINE)
        + _command_lines(_RUN_SINGLE)
        + _command_lines(_CRONTAB)
    )
    hits = [
        line
        for line in bodies
        if any(token in line for token in _FORBIDDEN)
    ]
    assert hits == [], hits

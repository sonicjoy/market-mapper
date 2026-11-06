"""Live vs pre fixture phases for Coverage and Unmapped explorers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

IN_PLAY_LOOKBACK_HOURS = 36
_COMPLETE_STATUSES = frozenset({"completed", "cancelled", "canceled"})
_LIVE_OPTIC_STATUSES = frozenset({"live"})
_PRE_OPTIC_STATUSES = frozenset({"unplayed", "delayed"})


def normalize_fixture_phase(raw: str | None) -> str:
    """API phase param: live (default) or pre."""
    return "pre" if str(raw or "").strip().lower() == "pre" else "live"


def is_complete_status(status: str | None) -> bool:
    """True when Optic (or equivalent) status means the fixture is finished."""
    return str(status or "").strip().lower() in _COMPLETE_STATUSES


def optic_status_phase(status: str | None) -> str | None:
    """Map Optic status to live/pre, or None when complete or missing."""
    st = str(status or "").strip().lower()
    if not st or st in _COMPLETE_STATUSES:
        return None
    if st in _LIVE_OPTIC_STATUSES:
        return "live"
    if st in _PRE_OPTIC_STATUSES:
        return "pre"
    return None


def row_phase_from_ttko(
    ttko_hours: float | None,
    *,
    kickoff_day: date | None = None,
    date_only: bool = False,
) -> str:
    """Kickoff-relative phase when Optic status is missing."""
    if date_only and kickoff_day is not None:
        return "live" if kickoff_day <= datetime.now(UTC).date() else "pre"
    if ttko_hours is None:
        return "pre"
    return "live" if float(ttko_hours) < 0 else "pre"


def row_phase_from_optic(
    status: str | None,
    *,
    ttko_hours: float | None,
    kickoff_day: date | None = None,
    date_only: bool = False,
) -> str | None:
    """Prefer Optic status; delayed counts as pre; missing status uses start time."""
    if is_complete_status(status):
        return None
    by_status = optic_status_phase(status)
    if by_status:
        return by_status
    return row_phase_from_ttko(
        ttko_hours,
        kickoff_day=kickoff_day,
        date_only=date_only,
    )


def row_is_open(ttko_hours: float | None) -> bool:
    """Drop legs/fixtures whose kickoff is older than the in-play lookback."""
    if ttko_hours is None:
        return True
    return float(ttko_hours) >= -IN_PLAY_LOOKBACK_HOURS


def coverage_matches_phase(row: dict[str, Any], phase: str) -> bool:
    """Coverage tab match: Optic status first, kickoff time when status is missing."""
    if is_complete_status(str(row.get("optic_status") or "")):
        return False
    if not row_is_open(row.get("ttko_hours")):
        return False
    actual = row_phase_from_optic(
        str(row.get("optic_status") or "") or None,
        ttko_hours=row.get("ttko_hours"),
    )
    if actual is None:
        return False
    return actual == normalize_fixture_phase(phase)


def row_matches_phase(row: dict[str, Any], phase: str) -> bool:
    """Unmapped tab match: status when present, else kickoff / ticker date."""
    if is_complete_status(str(row.get("optic_status") or "")):
        return False
    if not row_is_open(row.get("ttko_hours")):
        return False
    want = normalize_fixture_phase(phase)
    kickoff_day = _kickoff_day(row.get("kickoff_day"))
    actual = row_phase_from_optic(
        str(row.get("optic_status") or "") or None,
        ttko_hours=row.get("ttko_hours"),
        kickoff_day=kickoff_day,
        date_only=bool(row.get("kickoff_date_only")),
    )
    if actual is None:
        return False
    return actual == want


def _kickoff_day(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None

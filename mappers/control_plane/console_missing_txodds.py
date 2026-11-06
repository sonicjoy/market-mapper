"""Explore → Missing for TxODDS: NBA fixtures the TxODDS→Optic fixture map could not join 1:1.

Source: ``tx_scores_us.txodds_optic_fixture_map`` (mm-infrastructure !1576), which joins TxODDS
fixtures to Optic ones through the ``txodds`` team pins approved in this console. A row here means a
team is not pinned yet (``teams_unpinned``), no Optic game has those teams within 6 h
(``unmatched``), or more than one does (``ambiguous``). The fix for ``teams_unpinned`` is a pin
(Editor, book TxODDS); the other two are data to look at, not to pin.

Row contract (console/src/types.ts ``MissingSymbolRow``): ``symbol`` = TxODDS fixture id,
``fixture_name`` = "HOME v AWAY" (canonical keys, or TxODDS team ids where unpinned),
``contract_type`` = match status (so the Markets picker filters by status), ``scope`` = ``untouched``
when nothing could be joined (unpinned / unmatched) and ``extra`` for ambiguous.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

TXODDS_PLATFORM = "txodds"
TXODDS_NOTE = (
    "TxODDS NBA fixtures with no single Optic match (tx_scores_us.txodds_optic_fixture_map). "
    "teams_unpinned: pin the TxODDS team id in the Editor (book TxODDS)."
)


class CatalogueUnavailableError(RuntimeError):
    """The catalogue source is not readable here (view missing, or no IAM grant)."""


_TXODDS_MISSING_SQL = """
select
  txodds_fixture_id, txodds_start, home_canonical, away_canonical,
  home_txodds_team_id, away_txodds_team_id, coverage_status, match_status
from `{project}.{view}`
where match_status != 'matched'
  and coalesce(entity_status, 'active') != 'deleted'
  and txodds_start >= timestamp_sub(current_timestamp(), interval 24 hour)
order by txodds_start
"""


def txodds_missing_sql(project: str) -> str:
    """Unmatched TxODDS fixtures from 24 h ago onward, soonest first (project from the console env)."""
    from BigQuery.client import TXODDS_FIXTURE_MAP_VIEW

    return _TXODDS_MISSING_SQL.replace("{project}", project).replace("{view}", TXODDS_FIXTURE_MAP_VIEW)


def fetch_txodds_missing(project: str) -> list[dict[str, Any]]:
    """Rows from the fixture map; CatalogueUnavailableError when this console cannot read it."""
    from google.api_core.exceptions import Forbidden, NotFound

    from BigQuery.client import ro_client, ro_query

    if not project:
        raise CatalogueUnavailableError("GCP_PROJECT is not set")
    try:
        return [dict(r) for r in ro_query(ro_client(), txodds_missing_sql(project))]
    except (NotFound, Forbidden) as exc:
        raise CatalogueUnavailableError(f"{type(exc).__name__}: {str(exc)[:160]}") from exc


def normalize_txodds_row(raw: dict[str, Any]) -> dict[str, Any]:
    """One fixture-map row in the Missing row shape."""
    kickoff = _as_utc(raw.get("txodds_start"))
    status = str(raw.get("match_status") or "")
    home = str(raw.get("home_canonical") or raw.get("home_txodds_team_id") or "?")
    away = str(raw.get("away_canonical") or raw.get("away_txodds_team_id") or "?")
    return {
        "platform": TXODDS_PLATFORM,
        "symbol": str(raw.get("txodds_fixture_id") or ""),
        "symbol_base": "",
        "fixture_prefix": "",
        "crypto_prefix": "",
        "market_group": "fixture",
        "contract_type": status,
        "period_type": "",
        "fixture_name": f"{home} v {away}",
        "meta_league": "NBA",
        "scope": "extra" if status == "ambiguous" else "untouched",
        "kickoff": kickoff.isoformat() if kickoff else None,
        "ttko_hours": (kickoff - datetime.now(UTC)).total_seconds() / 3600.0 if kickoff else None,
        "league": "nba",
        "sport": "basketball",
    }


def _as_utc(value: Any) -> datetime | None:
    """BigQuery TIMESTAMP or ISO text as an aware UTC datetime."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

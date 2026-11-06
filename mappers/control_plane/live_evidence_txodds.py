"""Cart Verify evidence for TxODDS team pins (sportsbook ``txodds``, alias_kind ``external_id``).

TxODDS is a scores feed, not a trading venue: its Fusion ``TeamId`` is pinned on a canonical team
so ``tx_scores_us.txodds_optic_fixture_map`` can join TxODDS fixtures to Optic ones. classify never
reads these pins (``mappers/seed/sot.py`` ``_EXCHANGE_KEY``).

The team list comes from ``tx_scores_us.txodds_reference_raw`` (``/teams`` rows written by the
mm-external-feeds TxODDS direct listener). A read failure (no IAM grant, table absent in this environment)
fails OPEN with a ``txodds:unverified:`` ref, so a missing grant never blocks a cart.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from mappers.control_plane.live_evidence_names import name_ok
from mappers.control_plane.live_evidence_types import EvidenceFetchers, EvidenceHit

TXODDS_BOOK = "txodds"
TXODDS_ID_KINDS = frozenset({"external_id"})

_TTL_SEC = 15 * 60
_cache: dict[str, Any] = {}
_lock = threading.Lock()

_TEAMS_SQL = """
select
  json_value(data, '$.TeamId') as team_id,
  json_value(data, '$.PreferredName') as name
from `{table}`
where message_type = 'team'
  and received_at >= timestamp_sub(current_timestamp(), interval 30 day)
  and json_value(data, '$.TeamId') is not null
qualify row_number() over (partition by json_value(data, '$.TeamId') order by received_at desc) = 1
"""


def txodds_team_pin(
    store: Any,
    league: str,
    team_id: str,
    name: str,
    fx: EvidenceFetchers,
) -> EvidenceHit:
    """The pinned TeamId exists in the TxODDS team list and its name is this canonical's."""
    if not team_id.isdigit():
        return EvidenceHit(blocker=f"TxODDS team ids are numbers; {team_id!r} is not one.")
    try:
        teams = (fx.txodds_teams or cached_txodds_teams)()
    except Exception as exc:  # noqa: BLE001 — no grant / table missing: fail open, say so
        return EvidenceHit(refs=(f"txodds:unverified:{type(exc).__name__}",))
    label = teams.get(team_id)
    if label is None:
        return EvidenceHit(blocker=f"TxODDS team {team_id} is not in the TxODDS team list.")
    want = _tip_display_name(store, league, name)
    refs = (f"txodds:team:{team_id}:{label}",)
    if not want:
        return EvidenceHit(refs=(*refs, "txodds:name-unchecked"))
    if not any(name_ok(want, variant, league) for variant in _label_variants(label)):
        return EvidenceHit(blocker=f"TxODDS {team_id} is {label!r}, not {want!r}.")
    return EvidenceHit(refs=refs)


def _label_variants(label: str) -> list[str]:
    """TxODDS writes "LA Clippers"; the tip and Optic write "Los Angeles Clippers"."""
    out = [label]
    if label.startswith("LA "):
        out.append("Los Angeles " + label[3:])
    return out


def _tip_display_name(store: Any, league: str, name: str) -> str:
    """A human name for the check: the name given, or the tip's name when only a canonical key came in."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return name
    for ent in store.entities_for(rid):
        if str(ent.league) == league and str(ent.canonical_key) == name:
            return str(ent.canonical_name or "")
    return name


def cached_txodds_teams() -> dict[str, str]:
    """TeamId -> PreferredName, one BigQuery read per process every 15 minutes."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get("teams")
        if hit is not None and now - hit[0] < _TTL_SEC:
            return hit[1]
    teams = _query_txodds_teams()
    with _lock:
        _cache["teams"] = (now, teams)
    return teams


def _query_txodds_teams() -> dict[str, str]:
    """Latest PreferredName per TeamId from the last 30 days of /teams rows."""
    from BigQuery.client import TXODDS_REFERENCE_TABLE, ro_client, ro_query

    rows = ro_query(ro_client(), _TEAMS_SQL.replace("{table}", TXODDS_REFERENCE_TABLE))
    return {str(r.team_id): str(r.name or "") for r in rows}

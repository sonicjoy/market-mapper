"""Complementary catalogue source from processed_upstream_us.crypto_security_def.

Supplements ``crypto_underlying_securities`` with SecurityDef rows that
have full attribute-99 metadata.  Converts rows into the same flat
catalogue dicts the mapper consumes.  On merge, a newer ``publish_time``
for an existing SecurityID refreshes the catalogue entry (e.g. after an
EVENT_DATE reschedule).
"""

from __future__ import annotations

import json
from typing import Any

from BigQuery.client import CRYPTO_SECURITY_DEF_TABLE, is_missing_bq_table, ro_query
from fetch.crypto_com_underlying import (
    CATALOGUE_EVENT_STALE_HOURS,
    EVENT_DATE_TS,
)
from fetch.crypto_com_underlying_flat import (
    infer_player_prop_line_side,
    team_id_from_participant,
)

SECURITY_DEF_QUERY = rf"""
SELECT
  publish_time,
  security_id,
  symbol,
  security_desc,
  security_type,
  security_sub_type,
  currency,
  strike_price,
  min_price_increment,
  maturity_date,
  product,
  security_req_id,
  event_code,
  event_name,
  meta_league,
  meta_name,
  meta_sports_grouping,
  meta_event_date,
  meta_home_participant,
  meta_away_participant,
  meta_external_home_id,
  meta_external_away_id,
  meta_external_game_id,
  meta_external_tournament_id,
  meta_participant,
  meta_player_id,
  meta_predict_market_type,
  meta_predict_contract_type,
  meta_predict_period_type,
  meta_predict_event_type,
  meta_predict_category,
  meta_predict_market_id,
  meta_predict_outcome_id,
  meta_predict_outcome_type,
  meta_predict_value,
  meta_team_id,
  meta_venue,
  meta_feed_type,
  meta_alpha_strike,
  meta_version,
  attributes
FROM `{CRYPTO_SECURITY_DEF_TABLE}`
WHERE publish_time > timestamp_sub(current_timestamp(), INTERVAL {{minutes}} MINUTE)
  AND NOT STARTS_WITH(symbol, 'NX.F.OPT.COMBOS')
  AND ({EVENT_DATE_TS} IS NULL
    OR {EVENT_DATE_TS} > timestamp_sub(
         current_timestamp(), INTERVAL {CATALOGUE_EVENT_STALE_HOURS} HOUR))
QUALIFY row_number() OVER (
  PARTITION BY security_id ORDER BY publish_time DESC) = 1
"""

# Flattened meta_* columns published by upstream.  Each maps to an
# ``eventMeta<UPPER>`` key by dropping the ``meta_`` prefix and upper-casing
# (e.g. ``meta_external_home_id`` -> ``eventMetaEXTERNAL_HOME_ID``), matching
# the attribute-99 codes the mapper already consumes.
_META_COLUMNS: tuple[str, ...] = (
    "meta_league",
    "meta_name",
    "meta_sports_grouping",
    "meta_event_date",
    "meta_home_participant",
    "meta_away_participant",
    "meta_external_home_id",
    "meta_external_away_id",
    "meta_external_game_id",
    "meta_external_tournament_id",
    "meta_participant",
    "meta_player_id",
    "meta_predict_market_type",
    "meta_predict_contract_type",
    "meta_predict_period_type",
    "meta_predict_event_type",
    "meta_predict_category",
    "meta_predict_market_id",
    "meta_predict_outcome_id",
    "meta_predict_outcome_type",
    "meta_predict_value",
    "meta_team_id",
    "meta_venue",
    "meta_feed_type",
    "meta_alpha_strike",
    "meta_version",
)

_SCALAR_FIELDS: tuple[tuple[str, str], ...] = (
    ("security_id", "SecurityID"),
    ("symbol", "Symbol"),
    ("security_desc", "SecurityDesc"),
    ("security_type", "SecurityType"),
    ("security_sub_type", "SecuritySubType"),
    ("currency", "Currency"),
    ("strike_price", "StrikePrice"),
    ("min_price_increment", "MinPriceIncrement"),
    ("maturity_date", "MaturityDate"),
    ("product", "Product"),
    ("security_req_id", "SecurityReqID"),
)


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return str(value)
    return str(value)


def _event_metadata_from_columns(row) -> dict[str, str | None]:
    """Build eventMeta* keys directly from the flattened meta_* columns."""
    out: dict[str, str | None] = {}
    for col in _META_COLUMNS:
        val = _scalar(getattr(row, col, None))
        if val is not None:
            out["eventMeta" + col.removeprefix("meta_").upper()] = val
    return out


def _event_metadata_from_attributes(raw: str | None) -> dict[str, str | None]:
    """Parse attribute-99 JSON into eventMeta* keys."""
    if not raw:
        return {}
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict[str, str | None] = {}
    if isinstance(blob, list):
        for item in blob:
            if not isinstance(item, dict):
                continue
            code = item.get("eventPropertyTypeCode")
            if code:
                out["eventMeta" + code] = item.get("eventPropertyValue")
        return out
    if not isinstance(blob, dict):
        return {}
    for meta in blob.get("eventMetadata", []):
        if not isinstance(meta, dict):
            continue
        code = meta.get("eventPropertyTypeCode")
        if code:
            out["eventMeta" + code] = meta.get("eventPropertyValue")
    return out


def _has_event_metadata(meta: dict[str, str | None]) -> bool:
    """A row is mappable once it carries a league or predict-market type."""
    return bool(meta.get("eventMetaPREDICT_MARKET_TYPE") or meta.get("eventMetaLEAGUE"))


def _recover_missing_predict_value(flat: dict[str, str | None]) -> None:
    """Fill a missing prop PREDICT_VALUE (and blank outcome) from security_desc.

    Game lines are never recovered from text: their line and side come only
    from the typed meta_predict_value / meta_predict_outcome_type columns.
    """
    market = flat.get("eventMetaPREDICT_MARKET_TYPE")
    if market == "Team Prop" and not flat.get("eventMetaTEAM_ID"):
        team_id = team_id_from_participant(
            flat.get("eventMetaPARTICIPANT"),
            flat.get("eventMetaHOME_PARTICIPANT"),
            flat.get("eventMetaAWAY_PARTICIPANT"),
            flat.get("eventMetaEXTERNAL_HOME_ID"),
            flat.get("eventMetaEXTERNAL_AWAY_ID"),
        )
        if team_id:
            flat["eventMetaTEAM_ID"] = team_id
    if flat.get("eventMetaPREDICT_VALUE") not in (None, ""):
        return
    if market == "Player Prop" or market == "Team Prop":
        value, side = infer_player_prop_line_side(
            flat.get("SecurityDesc"),
            flat.get("eventName"),
        )
        if value is not None:
            flat["eventMetaPREDICT_VALUE"] = str(value)
        if side is not None and flat.get("eventMetaPREDICT_OUTCOME_TYPE") in (None, ""):
            flat["eventMetaPREDICT_OUTCOME_TYPE"] = side
        return


def security_def_row_to_flat(row) -> dict | None:
    """Convert one crypto_security_def row to a flat catalogue dict.

    Prefers the flattened ``meta_*`` columns; falls back to parsing the
    ``attributes`` JSON blob for legacy rows where those columns are null.
    """
    meta = _event_metadata_from_columns(row)
    if not _has_event_metadata(meta):
        meta = _event_metadata_from_attributes(getattr(row, "attributes", None))
    event_code = getattr(row, "event_code", None)
    event_name = getattr(row, "event_name", None)
    if event_code:
        meta.setdefault("eventCode", event_code)
    if event_name:
        meta.setdefault("eventName", event_name)
    if not _has_event_metadata(meta):
        return None

    flat: dict[str, str | None] = {}
    for src, dst in _SCALAR_FIELDS:
        val = _scalar(getattr(row, src, None))
        if val is not None:
            flat[dst] = val
    flat.update(meta)
    _recover_missing_predict_value(flat)
    return flat


def build_security_def_contracts(
    rows: list,
) -> tuple[list[dict], int, object | None]:
    """Flatten security_def rows to latest-per-SecurityID contracts.

    Returns (contracts, skipped_no_metadata, newest_publish_time).
    """
    latest: dict[str, tuple[object, dict]] = {}
    skipped = 0
    newest = None
    for row in rows:
        if newest is None or row.publish_time > newest:
            newest = row.publish_time
        flat = security_def_row_to_flat(row)
        if flat is None:
            skipped += 1
            continue
        sid = flat.get("SecurityID")
        if not sid:
            continue
        flat["fix_type"] = "SecurityDef"
        flat["publish_time"] = row.publish_time.isoformat()
        prev = latest.get(sid)
        if prev is None or row.publish_time > prev[0]:
            latest[sid] = (row.publish_time, flat)
    return [flat for _, flat in latest.values()], skipped, newest


def fetch_security_def_contracts(
    client,
    minutes: int,
) -> tuple[list[dict], int, object | None, int]:
    """Fetch and flatten security_def contracts.

    Returns (contracts, skipped_no_metadata, newest_publish_time, row_count);
    empty when the table is not provisioned.
    """
    rows = fetch_security_def_rows(client, minutes)
    if rows is None:
        return [], 0, None, 0
    contracts, skipped, newest = build_security_def_contracts(rows)
    return contracts, skipped, newest, len(rows)


def _publish_time_key(contract: dict) -> str:
    """Comparable publish_time string; missing sorts as oldest."""
    raw = contract.get("publish_time")
    return "" if raw is None else str(raw)


def merge_security_def_contracts(
    contracts: list[dict],
    sd_contracts: list[dict],
) -> tuple[list[dict], int]:
    """Merge security_def into underlying; newer publish_time wins per SecurityID.

    Underlying is a daily SecurityList snapshot and can pin a stale
    EVENT_DATE after a reschedule.  SecurityDef keeps issuing updates on
    the same SecurityID — previously those were dropped because the id
    was already present, leaving crypto MatchKeys on the wrong date.
    """
    by_sid: dict[str, dict] = {}
    for contract in contracts:
        sid = str(contract.get("SecurityID") or "")
        if sid:
            by_sid[sid] = contract
    changed = 0
    for sd in sd_contracts:
        sid = str(sd.get("SecurityID") or "")
        if not sid:
            continue
        prev = by_sid.get(sid)
        if prev is None or _publish_time_key(sd) > _publish_time_key(prev):
            by_sid[sid] = sd
            changed += 1
    no_sid = [c for c in contracts if not c.get("SecurityID")]
    return no_sid + list(by_sid.values()), changed


def fetch_security_def_rows(client, minutes: int) -> list | None:
    """Query crypto_security_def; return [] when the table is not provisioned."""
    try:
        return list(ro_query(client, SECURITY_DEF_QUERY.format(minutes=minutes)))
    except Exception as exc:
        if is_missing_bq_table(exc, CRYPTO_SECURITY_DEF_TABLE):
            return None
        raise
